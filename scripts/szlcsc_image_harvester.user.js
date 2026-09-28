// ==UserScript==
// @name         SZLCSC Part Image Harvester for PartShelf
// @namespace    https://partshelf.local/
// @version      2.0.0
// @description  Multi-tab concurrent image harvester for LCSC components on szlcsc.com. Atomically claims tasks directly from PartShelf server without client-side cursor management.
// @author       PartShelf
// @match        https://*.szlcsc.com/*
// @grant        GM_xmlhttpRequest
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_registerMenuCommand
// @connect      127.0.0.1
// @connect      localhost
// @connect      alimg.szlcsc.com
// @connect      assets.lcsc.com
// @connect      item.szlcsc.com
// @connect      szlcsc.com
// @run-at       document-idle
// ==/UserScript==

(function () {
    "use strict";

    // ----------------------------------------------------
    // Configuration & Persistent State
    // ----------------------------------------------------
    const DEFAULT_API_URL = "http://127.0.0.1:8000";
    const DEFAULT_DELAY_MS = 1000;

    let apiUrl = GM_getValue("partshelf_api_url", DEFAULT_API_URL);
    let delayMs = GM_getValue("crawler_delay_ms", DEFAULT_DELAY_MS);
    let isCrawlerActive = GM_getValue("crawler_active", false);

    // Tab-specific ID (persists within this specific browser tab across page navigations)
    let tabId = sessionStorage.getItem("ps_tab_id");
    if (!tabId) {
        tabId = "T" + Math.floor(100 + Math.random() * 900);
        sessionStorage.setItem("ps_tab_id", tabId);
    }

    // Task claimed by this specific tab
    let claimedTask = null;
    const rawClaimed = sessionStorage.getItem("ps_claimed_task");
    if (rawClaimed) {
        try {
            claimedTask = JSON.parse(rawClaimed);
        } catch (e) {
            claimedTask = null;
        }
    }

    let jumpTimeoutId = null;

    // ----------------------------------------------------
    // Helper Functions
    // ----------------------------------------------------
    function sleep(ms) {
        return new Promise((resolve) => setTimeout(resolve, ms));
    }

    function logMessage(msg, type = "info") {
        const now = new Date().toTimeString().split(" ")[0];
        const lineText = `[${now}] [${tabId}] ${msg}`;
        console.log(`[PartShelf Harvester] ${lineText}`);

        let activityLogs = GM_getValue("crawler_log", []);
        activityLogs.push({ text: lineText, type: type });
        if (activityLogs.length > 50) {
            activityLogs.shift();
        }
        GM_setValue("crawler_log", activityLogs);

        renderLogs();
    }

    function renderLogs() {
        const logBox = document.getElementById("ps-crawler-log");
        if (!logBox) return;

        const activityLogs = GM_getValue("crawler_log", []);
        logBox.innerHTML = "";
        for (const item of activityLogs) {
            const line = document.createElement("div");
            line.className = `ps-log-line ps-log-${item.type || "info"}`;
            line.textContent = item.text;
            logBox.appendChild(line);
        }
        logBox.scrollTop = logBox.scrollHeight;
    }

    function gmRequest(options) {
        return new Promise((resolve, reject) => {
            GM_xmlhttpRequest({
                timeout: 30000,
                ...options,
                onload: (res) => resolve(res),
                onerror: (err) => reject(err),
                ontimeout: () => reject(new Error("Request timed out")),
            });
        });
    }

    function blobToBase64(blob) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onloadend = () => resolve(reader.result);
            reader.onerror = reject;
            reader.readAsDataURL(blob);
        });
    }

    // ----------------------------------------------------
    // Server API Calls
    // ----------------------------------------------------
    async function checkBackendConnection() {
        try {
            const res = await gmRequest({
                method: "GET",
                url: `${apiUrl}/api/libraries/jlcparts/crawler/stats`,
                headers: { "Accept": "application/json" },
            });
            if (res.status === 200) {
                const data = JSON.parse(res.responseText);
                updateBackendStatus(true);
                updateGlobalStats(data);
                return true;
            } else {
                updateBackendStatus(false, `HTTP ${res.status}`);
                return false;
            }
        } catch (e) {
            updateBackendStatus(false, e.message || "Network Error");
            return false;
        }
    }

    async function claimTaskFromServer() {
        const url = `${apiUrl}/api/libraries/jlcparts/crawler/claim-task`;
        const res = await gmRequest({
            method: "GET",
            url: url,
            headers: { "Accept": "application/json" },
        });
        if (res.status !== 200) {
            throw new Error(`Failed to claim task: HTTP ${res.status}`);
        }
        const data = JSON.parse(res.responseText);
        return data.task || null;
    }

    async function releaseTaskOnServer(lcsc) {
        if (!lcsc) return;
        try {
            await gmRequest({
                method: "POST",
                url: `${apiUrl}/api/libraries/jlcparts/crawler/release-task?lcsc=${lcsc}`,
                headers: { "Accept": "application/json" },
            });
        } catch (e) {
            console.warn("Error releasing task:", e);
        }
    }

    async function uploadCrawledImage(payload) {
        const res = await gmRequest({
            method: "POST",
            url: `${apiUrl}/api/libraries/jlcparts/crawler/upload`,
            headers: {
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            data: JSON.stringify(payload),
        });
        if (res.status !== 200) {
            throw new Error(`Upload failed: HTTP ${res.status}`);
        }
        return JSON.parse(res.responseText);
    }

    // ----------------------------------------------------
    // In-Page Data Extraction
    // ----------------------------------------------------
    function extractPageProductData() {
        let imgUrl = null;
        let productModel = "";
        let productCode = "";

        // 1. Check __NEXT_DATA__ script tag in DOM
        const nextDataEl = document.getElementById("__NEXT_DATA__");
        if (nextDataEl && nextDataEl.textContent) {
            try {
                const nextData = JSON.parse(nextDataEl.textContent);
                const webData = nextData?.props?.pageProps?.webData;
                const prod = webData?.productRecord;

                if (prod) {
                    productCode = prod.productCode || "";
                    productModel = prod.productModel || prod.productName || "";
                    if (prod.breviaryImageUrl) {
                        imgUrl = prod.breviaryImageUrl;
                    } else if (prod.luceneBreviaryImageUrls) {
                        const urls = prod.luceneBreviaryImageUrls.split("<$>").filter((u) => u.trim());
                        if (urls.length > 0) {
                            imgUrl = urls[0];
                        }
                    }
                }
            } catch (e) {
                console.warn("[PartShelf Harvester] Error parsing __NEXT_DATA__:", e);
            }
        }

        // 2. Fallback: Search DOM for preview images
        if (!imgUrl) {
            const previewImg = document.querySelector('img[title*="点击查看大图"], img[alt*="实物图"], img[alt*="商品缩略图"]');
            if (previewImg && previewImg.src && !previewImg.src.startsWith("data:")) {
                imgUrl = previewImg.src;
            }
        }

        // 3. Fallback: Meta OpenGraph image tag
        if (!imgUrl) {
            const ogMeta = document.querySelector('meta[property="og:image"]');
            if (ogMeta && ogMeta.content) {
                imgUrl = ogMeta.content;
            }
        }

        return { imgUrl, productModel, productCode };
    }

    // ----------------------------------------------------
    // Tab Worker Lifecycle
    // ----------------------------------------------------
    async function runTabWorker() {
        isCrawlerActive = GM_getValue("crawler_active", false);
        if (!isCrawlerActive) {
            updateHarvesterStatus("Idle");
            return;
        }

        updateHarvesterStatus("Running");

        // 1. If this tab has a pending claimed task, process it now
        if (claimedTask) {
            const lcsc = claimedTask.lcsc;
            const wid = claimedTask.website_component_id || lcsc;
            updateCurrentTaskDisplay(`C${lcsc} (${wid})`);

            const is404 = document.title.includes("404") || document.title.includes("不存在") || document.title.includes("已下架");
            if (is404) {
                logMessage(`[404] C${lcsc}: Product page not found or item discontinued`, "warn");
                try {
                    await uploadCrawledImage({ lcsc: lcsc, has_image: false });
                } catch (e) {
                    console.error(e);
                }
            } else {
                const { imgUrl, productModel, productCode } = extractPageProductData();

                if (!imgUrl) {
                    logMessage(`[NO_IMG] C${lcsc}: No image on page (Model: ${productModel || "N/A"})`, "info");
                    try {
                        await uploadCrawledImage({
                            lcsc: lcsc,
                            product_model: productModel,
                            has_image: false,
                        });
                    } catch (e) {
                        console.error(e);
                    }
                } else {
                    let fullImgUrl = imgUrl;
                    if (fullImgUrl.startsWith("//")) {
                        fullImgUrl = "https:" + fullImgUrl;
                    }

                    try {
                        const imgRes = await gmRequest({
                            method: "GET",
                            url: fullImgUrl,
                            responseType: "blob",
                            headers: {
                                "Referer": window.location.href,
                            },
                        });

                        if (imgRes.status === 200 && imgRes.response) {
                            const base64Data = await blobToBase64(imgRes.response);
                            await uploadCrawledImage({
                                lcsc: lcsc,
                                image_base64: base64Data,
                                image_url: fullImgUrl,
                                product_model: productModel,
                                has_image: true,
                            });
                            const sizeKb = Math.round((imgRes.response.size || 0) / 1024);
                            logMessage(`[OK] C${lcsc}: Synced (${sizeKb} KB) - ${productModel}`, "success");
                        } else {
                            throw new Error(`HTTP ${imgRes.status}`);
                        }
                    } catch (e) {
                        logMessage(`[IMG_FAIL] C${lcsc}: ${e.message}`, "error");
                        await releaseTaskOnServer(lcsc);
                    }
                }
            }

            // Task completed for this tab
            claimedTask = null;
            sessionStorage.removeItem("ps_claimed_task");

            // Refresh global progress stats
            await checkBackendConnection();
        }

        // 2. Check if crawler is still globally active
        isCrawlerActive = GM_getValue("crawler_active", false);
        if (!isCrawlerActive) {
            updateHarvesterStatus("Paused");
            return;
        }

        // 3. Atomically claim the NEXT task directly from PartShelf server
        logMessage("Claiming next task from PartShelf server...", "info");
        let nextTask = null;
        try {
            nextTask = await claimTaskFromServer();
        } catch (e) {
            logMessage(`[CLAIM_ERR] ${e.message}. Retrying in 5s...`, "error");
            jumpTimeoutId = setTimeout(runTabWorker, 5000);
            return;
        }

        if (!nextTask) {
            logMessage("Queue complete! No more pending items found on server.", "success");
            stopHarvester();
            return;
        }

        // 4. Save claimed task to sessionStorage and navigate
        claimedTask = nextTask;
        sessionStorage.setItem("ps_claimed_task", JSON.stringify(claimedTask));

        const targetId = nextTask.website_component_id || nextTask.lcsc;
        const targetUrl = `https://item.szlcsc.com/${targetId}.html`;

        logMessage(`[NEXT] Claimed C${nextTask.lcsc} (${targetId}). Jumping in ${delayMs}ms...`, "info");
        updateCurrentTaskDisplay(`C${nextTask.lcsc} (${targetId})`);
        updateCountdownDisplay(delayMs);

        jumpTimeoutId = setTimeout(() => {
            isCrawlerActive = GM_getValue("crawler_active", false);
            if (!isCrawlerActive) return;
            window.location.href = targetUrl;
        }, Math.max(500, delayMs));
    }

    function startHarvester() {
        isCrawlerActive = true;
        GM_setValue("crawler_active", true);
        updateHarvesterStatus("Running");

        document.getElementById("ps-btn-start").disabled = true;
        const pauseBtn = document.getElementById("ps-btn-pause");
        pauseBtn.disabled = false;
        pauseBtn.textContent = "Pause";

        logMessage("Crawler activated. Starting multi-tab worker...", "info");
        runTabWorker();
    }

    function pauseHarvester() {
        isCrawlerActive = false;
        GM_setValue("crawler_active", false);

        if (jumpTimeoutId) {
            clearTimeout(jumpTimeoutId);
            jumpTimeoutId = null;
        }

        // If currently holding an uncompleted task, release it on server
        if (claimedTask && claimedTask.lcsc) {
            releaseTaskOnServer(claimedTask.lcsc);
            claimedTask = null;
            sessionStorage.removeItem("ps_claimed_task");
        }

        updateHarvesterStatus("Paused");
        document.getElementById("ps-btn-start").disabled = false;
        const pauseBtn = document.getElementById("ps-btn-pause");
        pauseBtn.textContent = "Resume";

        logMessage("Crawler paused. Released pending task.", "warn");
    }

    function stopHarvester() {
        isCrawlerActive = false;
        GM_setValue("crawler_active", false);

        if (jumpTimeoutId) {
            clearTimeout(jumpTimeoutId);
            jumpTimeoutId = null;
        }

        updateHarvesterStatus("Idle");
        document.getElementById("ps-btn-start").disabled = false;
        const pauseBtn = document.getElementById("ps-btn-pause");
        pauseBtn.disabled = true;
        pauseBtn.textContent = "Pause";
    }

    // ----------------------------------------------------
    // User Interface (Strictly No Emojis, Industrial Style)
    // ----------------------------------------------------
    function createUI() {
        const container = document.createElement("div");
        container.id = "ps-harvester-panel";
        container.innerHTML = `
            <div id="ps-panel-header">
                <div class="ps-header-title">
                    <span class="ps-brand">PartShelf</span>
                    <span class="ps-subtitle">Multi-Tab Harvester [${tabId}]</span>
                </div>
                <div class="ps-header-actions">
                    <button id="ps-btn-minimize" class="ps-btn-icon" title="Minimize/Maximize">_</button>
                </div>
            </div>
            <div id="ps-panel-body">
                <!-- Status Row -->
                <div class="ps-section">
                    <div class="ps-status-row">
                        <span class="ps-label">Backend:</span>
                        <span id="ps-backend-status" class="ps-badge ps-badge-gray">Checking...</span>
                        <span class="ps-label" style="margin-left: 10px;">Status:</span>
                        <span id="ps-crawler-status" class="ps-badge ps-badge-blue">Idle</span>
                    </div>
                    <div class="ps-status-row" style="margin-top: 6px;">
                        <span class="ps-label">Assigned Target:</span>
                        <span id="ps-current-task" class="ps-mono ps-text-cyan">None</span>
                    </div>
                </div>

                <!-- Global Progress Bar Section -->
                <div class="ps-section">
                    <div class="ps-progress-header">
                        <span class="ps-label">Server Progress:</span>
                        <span id="ps-progress-text" class="ps-mono ps-text-cyan">-- / -- (--%)</span>
                    </div>
                    <div class="ps-progress-track">
                        <div id="ps-progress-fill" class="ps-progress-fill" style="width: 0%;"></div>
                    </div>
                    <div id="ps-countdown-row" class="ps-countdown-text">Ready</div>
                </div>

                <!-- Settings -->
                <div class="ps-section">
                    <div class="ps-field">
                        <label class="ps-label">PartShelf API URL:</label>
                        <input id="ps-input-api" class="ps-input ps-mono" type="text" value="${apiUrl}" />
                    </div>
                    <div class="ps-field" style="margin-top: 6px;">
                        <label class="ps-label">Jump Delay (ms):</label>
                        <input id="ps-input-delay" class="ps-input ps-mono" type="number" min="300" max="10000" step="100" value="${delayMs}" />
                    </div>
                </div>

                <!-- Summary Counters -->
                <div class="ps-section">
                    <div class="ps-stats-grid">
                        <div class="ps-stat-box">
                            <div class="ps-stat-val ps-text-green" id="ps-stat-with-img">--</div>
                            <div class="ps-stat-lbl">With Image</div>
                        </div>
                        <div class="ps-stat-box">
                            <div class="ps-stat-val ps-text-yellow" id="ps-stat-no-img">--</div>
                            <div class="ps-stat-lbl">No Image</div>
                        </div>
                        <div class="ps-stat-box">
                            <div class="ps-stat-val ps-text-cyan" id="ps-stat-local-files">--</div>
                            <div class="ps-stat-lbl">Local Files</div>
                        </div>
                        <div class="ps-stat-box">
                            <div class="ps-stat-val ps-text-blue" id="ps-stat-remaining">--</div>
                            <div class="ps-stat-lbl">Remaining</div>
                        </div>
                    </div>
                    <div class="ps-global-summary" id="ps-global-summary">
                        Total Components: 1,037,000
                    </div>
                </div>

                <!-- Controls -->
                <div class="ps-btn-group">
                    <button id="ps-btn-start" class="ps-btn ps-btn-primary">Start</button>
                    <button id="ps-btn-pause" class="ps-btn ps-btn-secondary" disabled>Pause</button>
                    <button id="ps-btn-test" class="ps-btn ps-btn-outline">Test API</button>
                </div>

                <!-- Activity Log -->
                <div class="ps-section" style="margin-bottom: 0;">
                    <div class="ps-log-header">
                        <span>Cluster Activity Log</span>
                        <span id="ps-btn-clear-log" class="ps-link-btn">Clear</span>
                    </div>
                    <div id="ps-crawler-log" class="ps-log-box ps-mono"></div>
                </div>
            </div>
        `;

        const style = document.createElement("style");
        style.textContent = `
            #ps-harvester-panel {
                position: fixed;
                bottom: 20px;
                right: 20px;
                width: 360px;
                background-color: #0f172a;
                color: #f1f5f9;
                border: 1px solid #334155;
                border-radius: 8px;
                box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.6), 0 8px 10px -6px rgba(0, 0, 0, 0.5);
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                font-size: 12px;
                z-index: 9999999;
                overflow: hidden;
                line-height: 1.4;
            }
            #ps-panel-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                padding: 10px 14px;
                background-color: #1e293b;
                border-bottom: 1px solid #334155;
                user-select: none;
                cursor: move;
            }
            .ps-header-title {
                display: flex;
                align-items: baseline;
                gap: 8px;
            }
            .ps-brand {
                font-weight: 700;
                font-size: 14px;
                color: #38bdf8;
                letter-spacing: 0.5px;
            }
            .ps-subtitle {
                font-size: 11px;
                color: #94a3b8;
            }
            .ps-btn-icon {
                background: none;
                border: 1px solid #475569;
                color: #94a3b8;
                border-radius: 4px;
                width: 22px;
                height: 22px;
                line-height: 18px;
                text-align: center;
                cursor: pointer;
                font-size: 11px;
                font-weight: 700;
            }
            .ps-btn-icon:hover {
                color: #f8fafc;
                background: #334155;
            }
            #ps-panel-body {
                padding: 12px;
                display: flex;
                flex-direction: column;
                gap: 10px;
                max-height: 580px;
                overflow-y: auto;
            }
            .ps-section {
                background: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 8px 10px;
            }
            .ps-status-row {
                display: flex;
                align-items: center;
            }
            .ps-label {
                color: #94a3b8;
                font-size: 11px;
            }
            .ps-mono {
                font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
            }
            .ps-badge {
                display: inline-block;
                padding: 2px 6px;
                border-radius: 4px;
                font-size: 10px;
                font-weight: 600;
                margin-left: 6px;
                text-transform: uppercase;
            }
            .ps-badge-gray { background: #334155; color: #cbd5e1; }
            .ps-badge-green { background: #065f46; color: #34d399; }
            .ps-badge-red { background: #7f1d1d; color: #f87171; }
            .ps-badge-blue { background: #1e40af; color: #93c5fd; }
            .ps-badge-yellow { background: #78350f; color: #fde047; }
            .ps-text-green { color: #34d399; }
            .ps-text-yellow { color: #facc15; }
            .ps-text-red { color: #f87171; }
            .ps-text-blue { color: #60a5fa; }
            .ps-text-cyan { color: #38bdf8; font-weight: 600; margin-left: 6px; }

            .ps-progress-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 5px;
            }
            .ps-progress-track {
                width: 100%;
                height: 8px;
                background: #0f172a;
                border: 1px solid #334155;
                border-radius: 4px;
                overflow: hidden;
            }
            .ps-progress-fill {
                height: 100%;
                background: linear-gradient(90deg, #2563eb, #38bdf8);
                border-radius: 3px;
                transition: width 0.3s ease;
            }
            .ps-countdown-text {
                font-size: 10px;
                color: #94a3b8;
                margin-top: 4px;
                text-align: right;
                font-family: ui-monospace, SFMono-Regular, monospace;
            }

            .ps-field {
                display: flex;
                flex-direction: column;
                gap: 4px;
            }
            .ps-input {
                background: #0f172a;
                border: 1px solid #475569;
                border-radius: 4px;
                color: #f8fafc;
                padding: 5px 8px;
                font-size: 11px;
                outline: none;
                width: 100%;
                box-sizing: border-box;
            }
            .ps-input:focus {
                border-color: #38bdf8;
            }
            .ps-stats-grid {
                display: grid;
                grid-template-columns: repeat(4, 1fr);
                gap: 6px;
                text-align: center;
            }
            .ps-stat-box {
                background: #0f172a;
                border: 1px solid #334155;
                border-radius: 4px;
                padding: 6px 4px;
            }
            .ps-stat-val {
                font-size: 13px;
                font-weight: 700;
                font-family: ui-monospace, SFMono-Regular, monospace;
            }
            .ps-stat-lbl {
                font-size: 9px;
                color: #94a3b8;
                margin-top: 2px;
                text-transform: uppercase;
            }
            .ps-global-summary {
                margin-top: 8px;
                font-size: 10px;
                color: #94a3b8;
                text-align: center;
                border-top: 1px solid #334155;
                padding-top: 6px;
                font-family: ui-monospace, SFMono-Regular, monospace;
            }
            .ps-btn-group {
                display: flex;
                gap: 6px;
            }
            .ps-btn {
                flex: 1;
                padding: 7px 0;
                border-radius: 4px;
                font-size: 11px;
                font-weight: 600;
                cursor: pointer;
                border: none;
                transition: background 0.15s ease;
                text-align: center;
            }
            .ps-btn:disabled {
                opacity: 0.5;
                cursor: not-allowed;
            }
            .ps-btn-primary {
                background: #2563eb;
                color: #ffffff;
            }
            .ps-btn-primary:hover:not(:disabled) {
                background: #1d4ed8;
            }
            .ps-btn-secondary {
                background: #d97706;
                color: #ffffff;
            }
            .ps-btn-secondary:hover:not(:disabled) {
                background: #b45309;
            }
            .ps-btn-outline {
                background: transparent;
                border: 1px solid #475569;
                color: #cbd5e1;
            }
            .ps-btn-outline:hover:not(:disabled) {
                background: #334155;
                color: #ffffff;
            }
            .ps-log-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                color: #94a3b8;
                font-size: 10px;
                margin-bottom: 4px;
                text-transform: uppercase;
            }
            .ps-link-btn {
                cursor: pointer;
                color: #38bdf8;
            }
            .ps-link-btn:hover {
                text-decoration: underline;
            }

            .ps-log-box {
                background: #0f172a;
                border: 1px solid #334155;
                border-radius: 4px;
                height: 110px;
                overflow-y: scroll;
                overflow-x: hidden;
                padding: 6px 8px;
                font-size: 11px;
                display: block;
                box-sizing: border-box;
                scrollbar-width: thin;
                scrollbar-color: #475569 #1e293b;
            }
            .ps-log-box::-webkit-scrollbar {
                width: 6px;
            }
            .ps-log-box::-webkit-scrollbar-track {
                background: #1e293b;
                border-radius: 3px;
            }
            .ps-log-box::-webkit-scrollbar-thumb {
                background: #475569;
                border-radius: 3px;
            }
            .ps-log-box::-webkit-scrollbar-thumb:hover {
                background: #64748b;
            }
            .ps-log-line {
                display: block;
                line-height: 18px;
                min-height: 18px;
                height: 18px;
                margin-bottom: 2px;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
                box-sizing: border-box;
            }
            .ps-log-info { color: #94a3b8; }
            .ps-log-success { color: #34d399; font-weight: 600; }
            .ps-log-warn { color: #facc15; }
            .ps-log-error { color: #f87171; font-weight: 600; }
        `;

        document.head.appendChild(style);
        document.body.appendChild(container);

        bindUIEvents();
    }

    function bindUIEvents() {
        const btnStart = document.getElementById("ps-btn-start");
        const btnPause = document.getElementById("ps-btn-pause");
        const btnTest = document.getElementById("ps-btn-test");
        const btnClearLog = document.getElementById("ps-btn-clear-log");
        const btnMinimize = document.getElementById("ps-btn-minimize");
        const panelBody = document.getElementById("ps-panel-body");

        const inputApi = document.getElementById("ps-input-api");
        const inputDelay = document.getElementById("ps-input-delay");

        inputApi.addEventListener("change", () => {
            apiUrl = inputApi.value.trim().replace(/\/+$/, "");
            GM_setValue("partshelf_api_url", apiUrl);
            logMessage(`API URL updated: ${apiUrl}`, "info");
            checkBackendConnection();
        });

        inputDelay.addEventListener("change", () => {
            delayMs = Math.max(300, parseInt(inputDelay.value, 10) || DEFAULT_DELAY_MS);
            inputDelay.value = delayMs;
            GM_setValue("crawler_delay_ms", delayMs);
            logMessage(`Delay set to ${delayMs}ms`, "info");
        });

        btnStart.addEventListener("click", () => {
            startHarvester();
        });

        btnPause.addEventListener("click", () => {
            pauseHarvester();
        });

        btnTest.addEventListener("click", async () => {
            logMessage("Testing connection to PartShelf API...", "info");
            const ok = await checkBackendConnection();
            if (ok) {
                logMessage("PartShelf API connected successfully", "success");
            } else {
                logMessage("Failed to reach PartShelf API. Check URL and CORS.", "error");
            }
        });

        btnClearLog.addEventListener("click", () => {
            GM_setValue("crawler_log", []);
            renderLogs();
        });

        let isMinimized = false;
        btnMinimize.addEventListener("click", () => {
            isMinimized = !isMinimized;
            panelBody.style.display = isMinimized ? "none" : "flex";
            btnMinimize.textContent = isMinimized ? "+" : "_";
        });

        // Draggable panel
        const header = document.getElementById("ps-panel-header");
        const panel = document.getElementById("ps-harvester-panel");
        let isDragging = false;
        let startX, startY, origX, origY;

        header.addEventListener("mousedown", (e) => {
            if (e.target.tagName === "BUTTON") return;
            isDragging = true;
            startX = e.clientX;
            startY = e.clientY;
            const rect = panel.getBoundingClientRect();
            origX = rect.left;
            origY = rect.top;
            e.preventDefault();
        });

        document.addEventListener("mousemove", (e) => {
            if (!isDragging) return;
            const dx = e.clientX - startX;
            const dy = e.clientY - startY;
            panel.style.left = `${origX + dx}px`;
            panel.style.top = `${origY + dy}px`;
            panel.style.right = "auto";
            panel.style.bottom = "auto";
        });

        document.addEventListener("mouseup", () => {
            isDragging = false;
        });
    }

    function updateBackendStatus(connected, detail = "") {
        const el = document.getElementById("ps-backend-status");
        if (!el) return;
        if (connected) {
            el.className = "ps-badge ps-badge-green";
            el.textContent = "Online";
        } else {
            el.className = "ps-badge ps-badge-red";
            el.textContent = detail ? `Offline (${detail})` : "Offline";
        }
    }

    function updateHarvesterStatus(status) {
        const el = document.getElementById("ps-crawler-status");
        if (!el) return;
        el.textContent = status;
        if (status === "Running") {
            el.className = "ps-badge ps-badge-green";
        } else if (status === "Paused") {
            el.className = "ps-badge ps-badge-yellow";
        } else {
            el.className = "ps-badge ps-badge-blue";
        }
    }

    function updateCurrentTaskDisplay(taskStr) {
        const el = document.getElementById("ps-current-task");
        if (el) el.textContent = taskStr;
    }

    function updateGlobalStats(stats) {
        const total = stats.total_components || 0;
        const withImg = stats.with_image || 0;
        const noImg = stats.no_image || 0;
        const rem = stats.remaining || 0;
        const local = stats.local_image_files || 0;

        const elWith = document.getElementById("ps-stat-with-img");
        const elNo = document.getElementById("ps-stat-no-img");
        const elLocal = document.getElementById("ps-stat-local-files");
        const elRem = document.getElementById("ps-stat-remaining");
        const elSum = document.getElementById("ps-global-summary");

        if (elWith) elWith.textContent = withImg.toLocaleString();
        if (elNo) elNo.textContent = noImg.toLocaleString();
        if (elLocal) elLocal.textContent = local.toLocaleString();
        if (elRem) elRem.textContent = rem.toLocaleString();
        if (elSum) elSum.textContent = `Total Components: ${total.toLocaleString()}`;

        // Update progress bar
        const progText = document.getElementById("ps-progress-text");
        const progFill = document.getElementById("ps-progress-fill");
        if (progText && progFill && total > 0) {
            const completed = withImg + noImg;
            const pct = Math.min(100, Math.round((completed / total) * 100));
            progText.textContent = `${completed.toLocaleString()} / ${total.toLocaleString()} (${pct}%)`;
            progFill.style.width = `${pct}%`;
        }
    }

    function updateCountdownDisplay(ms) {
        const el = document.getElementById("ps-countdown-row");
        if (!el) return;
        const sec = (ms / 1000).toFixed(1);
        el.textContent = `Redirecting in ${sec}s...`;
    }

    // ----------------------------------------------------
    // Initialization & Lifecycle
    // ----------------------------------------------------
    function init() {
        createUI();
        renderLogs();
        checkBackendConnection();

        if (typeof GM_registerMenuCommand !== "undefined") {
            GM_registerMenuCommand("Start Harvester", startHarvester);
            GM_registerMenuCommand("Pause Harvester", pauseHarvester);
        }

        isCrawlerActive = GM_getValue("crawler_active", false);
        if (isCrawlerActive) {
            updateHarvesterStatus("Running");
            document.getElementById("ps-btn-start").disabled = true;
            const pauseBtn = document.getElementById("ps-btn-pause");
            pauseBtn.disabled = false;
            pauseBtn.textContent = "Pause";

            setTimeout(() => {
                runTabWorker();
            }, 600);
        } else {
            updateHarvesterStatus("Idle");
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
