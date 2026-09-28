// ==UserScript==
// @name         SZLCSC Part Image Harvester for PartShelf
// @namespace    https://partshelf.local/
// @version      1.1.0
// @description  Automated in-page image harvester for LCSC components running on szlcsc.com by directly navigating to product pages and extracting images into local PartShelf database.
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
    const DEFAULT_DELAY_MS = 1500;

    let apiUrl = GM_getValue("partshelf_api_url", DEFAULT_API_URL);
    let delayMs = GM_getValue("crawler_delay_ms", DEFAULT_DELAY_MS);
    let cursor = GM_getValue("crawler_cursor", 0);
    let isCrawlerActive = GM_getValue("crawler_active", false);

    let taskQueue = GM_getValue("crawler_task_queue", []);
    let currentTask = GM_getValue("crawler_current_task", null);
    let batchTotal = GM_getValue("crawler_batch_total", 50);
    let batchIndex = GM_getValue("crawler_batch_index", 0);

    let sessionStats = GM_getValue("crawler_stats", {
        processed: 0,
        downloaded: 0,
        noImage: 0,
        failed: 0,
    });

    let activityLogs = GM_getValue("crawler_log", []);

    let jumpTimeoutId = null;

    // ----------------------------------------------------
    // Helper Functions
    // ----------------------------------------------------
    function sleep(ms) {
        return new Promise((resolve) => setTimeout(resolve, ms));
    }

    function logMessage(msg, type = "info") {
        const now = new Date().toTimeString().split(" ")[0];
        const lineText = `[${now}] ${msg}`;
        console.log(`[PartShelf Harvester] ${msg}`);

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
    // Backend API Calls
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

    async function fetchTasks(limit = 50) {
        const url = `${apiUrl}/api/libraries/jlcparts/crawler/tasks?limit=${limit}&cursor=${cursor}`;
        const res = await gmRequest({
            method: "GET",
            url: url,
            headers: { "Accept": "application/json" },
        });
        if (res.status !== 200) {
            throw new Error(`Failed to fetch tasks: HTTP ${res.status}`);
        }
        return JSON.parse(res.responseText);
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

        // 2. Fallback: Search DOM for product preview images
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
    // Harvester Flow: Process Loaded Page & Plan Next Jump
    // ----------------------------------------------------
    async function processCurrentPage() {
        if (!isCrawlerActive) return;

        // Verify if we have an active task
        if (!currentTask) {
            logMessage("No current task found. Fetching next task queue...", "info");
            await advanceToNextTask();
            return;
        }

        const lcsc = currentTask.lcsc;
        const wid = currentTask.website_component_id || lcsc;
        const currentPath = window.location.pathname;

        updateCurrentTaskDisplay(`C${lcsc} (${wid})`);

        // Check if we are on an error or 404 page
        const is404 = document.title.includes("404") || document.title.includes("不存在") || document.title.includes("已下架");
        if (is404) {
            logMessage(`[404] C${lcsc}: Product page not found or item discontinued`, "warn");
            try {
                await uploadCrawledImage({ lcsc: lcsc, has_image: false });
            } catch (e) {
                console.error(e);
            }
            sessionStats.noImage++;
            sessionStats.processed++;
            saveStats();
            updateStatsDisplay();
            await scheduleNextJump();
            return;
        }

        // Extract product data from the loaded webpage
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
            sessionStats.noImage++;
            sessionStats.processed++;
            saveStats();
            updateStatsDisplay();
            await scheduleNextJump();
            return;
        }

        // Normalize URL if protocol-relative
        let fullImgUrl = imgUrl;
        if (fullImgUrl.startsWith("//")) {
            fullImgUrl = "https:" + fullImgUrl;
        }

        // Download image binary directly with browser credentials
        try {
            logMessage(`[DOWNLOADING] C${lcsc}: Fetching image binary...`, "info");
            const imgRes = await gmRequest({
                method: "GET",
                url: fullImgUrl,
                responseType: "blob",
                headers: {
                    "Referer": window.location.href,
                },
            });

            if (imgRes.status !== 200 || !imgRes.response) {
                throw new Error(`Image download HTTP ${imgRes.status}`);
            }

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
            sessionStats.downloaded++;
            sessionStats.processed++;
            saveStats();
            updateStatsDisplay();
        } catch (e) {
            logMessage(`[IMG_FAIL] C${lcsc}: ${e.message}`, "error");
            sessionStats.failed++;
            updateStatsDisplay();
        }

        await scheduleNextJump();
    }

    async function advanceToNextTask() {
        // Refill queue if needed
        if (!taskQueue || taskQueue.length === 0) {
            logMessage(`Queue empty. Fetching batch of 50 tasks (cursor: ${cursor})...`, "info");
            try {
                const batch = await fetchTasks(50);
                taskQueue = batch.tasks || [];
                batchTotal = taskQueue.length;
                batchIndex = 0;
                GM_setValue("crawler_task_queue", taskQueue);
                GM_setValue("crawler_batch_total", batchTotal);
                GM_setValue("crawler_batch_index", batchIndex);

                if (taskQueue.length === 0) {
                    logMessage("Queue complete! No more pending items found in PartShelf database.", "success");
                    stopHarvester();
                    return null;
                }
            } catch (e) {
                logMessage(`[FETCH_ERR] ${e.message}. Retrying in 5s...`, "error");
                await sleep(5000);
                if (isCrawlerActive) {
                    return advanceToNextTask();
                }
                return null;
            }
        }

        // Pop next task
        const nextTask = taskQueue.shift();
        batchIndex++;
        GM_setValue("crawler_task_queue", taskQueue);
        GM_setValue("crawler_batch_index", batchIndex);

        currentTask = nextTask;
        GM_setValue("crawler_current_task", currentTask);

        cursor = nextTask.lcsc;
        GM_setValue("crawler_cursor", cursor);
        updateCursorDisplay(cursor);

        updateProgressBar();
        return nextTask;
    }

    async function scheduleNextJump() {
        if (!isCrawlerActive) return;

        const nextTask = await advanceToNextTask();
        if (!nextTask || !isCrawlerActive) return;

        const targetId = nextTask.website_component_id || nextTask.lcsc;
        const targetUrl = `https://item.szlcsc.com/${targetId}.html`;

        logMessage(`[NEXT] C${nextTask.lcsc} (ID: ${targetId}). Navigating in ${delayMs}ms...`, "info");

        // Countdown visual display
        updateCountdownDisplay(delayMs);

        jumpTimeoutId = setTimeout(() => {
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

        logMessage("Harvester activated", "info");

        // If on item page matching currentTask, process it now; otherwise advance and navigate
        const currentPath = window.location.pathname;
        const currentWid = currentTask?.website_component_id || currentTask?.lcsc;

        if (currentTask && currentWid && currentPath.includes(String(currentWid))) {
            processCurrentPage();
        } else {
            scheduleNextJump();
        }
    }

    function pauseHarvester() {
        isCrawlerActive = false;
        GM_setValue("crawler_active", false);

        if (jumpTimeoutId) {
            clearTimeout(jumpTimeoutId);
            jumpTimeoutId = null;
        }

        updateHarvesterStatus("Paused");
        document.getElementById("ps-btn-start").disabled = false;
        const pauseBtn = document.getElementById("ps-btn-pause");
        pauseBtn.textContent = "Resume";

        logMessage("Harvester paused by user", "warn");
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

    function saveStats() {
        GM_setValue("crawler_stats", sessionStats);
    }

    function resetStats() {
        sessionStats = {
            processed: 0,
            downloaded: 0,
            noImage: 0,
            failed: 0,
        };
        saveStats();
        updateStatsDisplay();
        logMessage("Session statistics reset to 0", "warn");
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
                    <span class="ps-subtitle">Direct Page Harvester</span>
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
                        <span class="ps-label" style="margin-left: 10px;">Harvester:</span>
                        <span id="ps-crawler-status" class="ps-badge ps-badge-blue">Idle</span>
                    </div>
                    <div class="ps-status-row" style="margin-top: 6px;">
                        <span class="ps-label">Current Target:</span>
                        <span id="ps-current-task" class="ps-mono ps-text-cyan">None</span>
                    </div>
                </div>

                <!-- Progress Bar Section -->
                <div class="ps-section">
                    <div class="ps-progress-header">
                        <span class="ps-label">Batch Progress:</span>
                        <span id="ps-progress-text" class="ps-mono ps-text-cyan">0 / 0 (0%)</span>
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
                    <div class="ps-field-row" style="margin-top: 6px;">
                        <div class="ps-field-col">
                            <label class="ps-label">Jump Delay (ms):</label>
                            <input id="ps-input-delay" class="ps-input ps-mono" type="number" min="500" max="10000" step="100" value="${delayMs}" />
                        </div>
                        <div class="ps-field-col" style="margin-left: 8px;">
                            <label class="ps-label">Start Cursor (LCSC):</label>
                            <input id="ps-input-cursor" class="ps-input ps-mono" type="number" min="0" value="${cursor}" />
                        </div>
                    </div>
                </div>

                <!-- Session Stats -->
                <div class="ps-section">
                    <div class="ps-stats-grid">
                        <div class="ps-stat-box">
                            <div class="ps-stat-val ps-text-green" id="ps-stat-downloaded">0</div>
                            <div class="ps-stat-lbl">Downloaded</div>
                        </div>
                        <div class="ps-stat-box">
                            <div class="ps-stat-val ps-text-yellow" id="ps-stat-noimg">0</div>
                            <div class="ps-stat-lbl">No Image</div>
                        </div>
                        <div class="ps-stat-box">
                            <div class="ps-stat-val ps-text-red" id="ps-stat-failed">0</div>
                            <div class="ps-stat-lbl">Failed</div>
                        </div>
                        <div class="ps-stat-box">
                            <div class="ps-stat-val ps-text-blue" id="ps-stat-processed">0</div>
                            <div class="ps-stat-lbl">Processed</div>
                        </div>
                    </div>
                    <div class="ps-global-summary" id="ps-global-summary">
                        Total: -- | With Image: -- | Remaining: --
                    </div>
                </div>

                <!-- Controls -->
                <div class="ps-btn-group">
                    <button id="ps-btn-start" class="ps-btn ps-btn-primary">Start</button>
                    <button id="ps-btn-pause" class="ps-btn ps-btn-secondary" disabled>Pause</button>
                    <button id="ps-btn-test" class="ps-btn ps-btn-outline">Test API</button>
                    <button id="ps-btn-reset-stats" class="ps-btn ps-btn-outline" title="Reset session stats">Reset</button>
                </div>

                <!-- Activity Log -->
                <div class="ps-section" style="margin-bottom: 0;">
                    <div class="ps-log-header">
                        <span>Activity Log</span>
                        <span id="ps-btn-clear-log" class="ps-link-btn">Clear</span>
                    </div>
                    <div id="ps-crawler-log" class="ps-log-box ps-mono"></div>
                </div>
            </div>
        `;

        // Inject Styles (Strictly no flex child line collapse, clean scrollbar and progress bar)
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

            /* Progress Bar */
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
            .ps-field-row {
                display: flex;
                align-items: center;
            }
            .ps-field-col {
                flex: 1;
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
                font-size: 14px;
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

            /* Log Box (Clear display with scrollbar, no line overlap) */
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
        const btnResetStats = document.getElementById("ps-btn-reset-stats");
        const btnClearLog = document.getElementById("ps-btn-clear-log");
        const btnMinimize = document.getElementById("ps-btn-minimize");
        const panelBody = document.getElementById("ps-panel-body");

        const inputApi = document.getElementById("ps-input-api");
        const inputDelay = document.getElementById("ps-input-delay");
        const inputCursor = document.getElementById("ps-input-cursor");

        inputApi.addEventListener("change", () => {
            apiUrl = inputApi.value.trim().replace(/\/+$/, "");
            GM_setValue("partshelf_api_url", apiUrl);
            logMessage(`API URL updated: ${apiUrl}`, "info");
            checkBackendConnection();
        });

        inputDelay.addEventListener("change", () => {
            delayMs = Math.max(500, parseInt(inputDelay.value, 10) || DEFAULT_DELAY_MS);
            inputDelay.value = delayMs;
            GM_setValue("crawler_delay_ms", delayMs);
            logMessage(`Delay set to ${delayMs}ms`, "info");
        });

        inputCursor.addEventListener("change", () => {
            cursor = Math.max(0, parseInt(inputCursor.value, 10) || 0);
            inputCursor.value = cursor;
            GM_setValue("crawler_cursor", cursor);
            // Clear current task queue so next fetch starts from new cursor
            taskQueue = [];
            GM_setValue("crawler_task_queue", []);
            logMessage(`Cursor set to ${cursor}. Queue cleared.`, "warn");
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

        btnResetStats.addEventListener("click", () => {
            resetStats();
        });

        btnClearLog.addEventListener("click", () => {
            activityLogs = [];
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

    function updateCursorDisplay(c) {
        const el = document.getElementById("ps-input-cursor");
        if (el && document.activeElement !== el) {
            el.value = c;
        }
    }

    function updateStatsDisplay() {
        const elDown = document.getElementById("ps-stat-downloaded");
        const elNoImg = document.getElementById("ps-stat-noimg");
        const elFail = document.getElementById("ps-stat-failed");
        const elProc = document.getElementById("ps-stat-processed");

        if (elDown) elDown.textContent = sessionStats.downloaded;
        if (elNoImg) elNoImg.textContent = sessionStats.noImage;
        if (elFail) elFail.textContent = sessionStats.failed;
        if (elProc) elProc.textContent = sessionStats.processed;
    }

    function updateGlobalStats(stats) {
        const el = document.getElementById("ps-global-summary");
        if (!el) return;
        const total = (stats.total_components || 0).toLocaleString();
        const withImg = (stats.with_image || 0).toLocaleString();
        const remaining = (stats.remaining || 0).toLocaleString();
        el.textContent = `Total: ${total} | With Image: ${withImg} | Remaining: ${remaining}`;
    }

    function updateProgressBar() {
        const textEl = document.getElementById("ps-progress-text");
        const fillEl = document.getElementById("ps-progress-fill");
        if (!textEl || !fillEl) return;

        const total = Math.max(1, batchTotal);
        const idx = Math.min(total, batchIndex);
        const pct = Math.round((idx / total) * 100);

        textEl.textContent = `${idx} / ${total} (${pct}%)`;
        fillEl.style.width = `${pct}%`;
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
        updateStatsDisplay();
        updateProgressBar();
        checkBackendConnection();

        if (typeof GM_registerMenuCommand !== "undefined") {
            GM_registerMenuCommand("Start Harvester", startHarvester);
            GM_registerMenuCommand("Pause Harvester", pauseHarvester);
        }

        // Restore active state
        if (isCrawlerActive) {
            updateHarvesterStatus("Running");
            document.getElementById("ps-btn-start").disabled = true;
            const pauseBtn = document.getElementById("ps-btn-pause");
            pauseBtn.disabled = false;
            pauseBtn.textContent = "Pause";

            // Process current page after a short stabilization delay
            setTimeout(() => {
                processCurrentPage();
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
