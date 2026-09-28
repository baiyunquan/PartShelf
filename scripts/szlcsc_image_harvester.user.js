// ==UserScript==
// @name         SZLCSC Part Image Harvester for PartShelf
// @namespace    https://partshelf.local/
// @version      1.0.0
// @description  Automated background image harvester for LCSC components running on szlcsc.com to sync with local PartShelf database.
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

    let isRunning = false;
    let isPaused = false;
    let currentTask = null;

    const sessionStats = {
        processed: 0,
        downloaded: 0,
        noImage: 0,
        failed: 0,
    };

    // ----------------------------------------------------
    // Helper Functions
    // ----------------------------------------------------
    function sleep(ms) {
        return new Promise((resolve) => setTimeout(resolve, ms));
    }

    function logMessage(msg, type = "info") {
        const now = new Date().toTimeString().split(" ")[0];
        const logBox = document.getElementById("ps-crawler-log");
        if (logBox) {
            const line = document.createElement("div");
            line.className = `ps-log-line ps-log-${type}`;
            line.textContent = `[${now}] ${msg}`;
            logBox.appendChild(line);
            logBox.scrollTop = logBox.scrollHeight;

            while (logBox.children.length > 50) {
                logBox.removeChild(logBox.firstChild);
            }
        }
        console.log(`[PartShelf Harvester] ${msg}`);
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
    // Harvester Processing Logic
    // ----------------------------------------------------
    async function processSingleLcsc(lcsc) {
        currentTask = lcsc;
        updateCurrentTaskDisplay(`C${lcsc}`);

        const itemUrl = `https://item.szlcsc.com/${lcsc}.html`;
        let htmlRes;

        try {
            htmlRes = await gmRequest({
                method: "GET",
                url: itemUrl,
                headers: {
                    "User-Agent": navigator.userAgent,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
            });
        } catch (e) {
            logMessage(`[NET_ERR] C${lcsc}: ${e.message}`, "error");
            sessionStats.failed++;
            updateStatsDisplay();
            return;
        }

        // Product not found or discontinued
        if (htmlRes.status === 404 || htmlRes.status === 301 || htmlRes.status === 302) {
            logMessage(`[404] C${lcsc}: Page not found or redirected`, "warn");
            await uploadCrawledImage({ lcsc: lcsc, has_image: false });
            sessionStats.noImage++;
            sessionStats.processed++;
            updateStatsDisplay();
            return;
        }

        if (htmlRes.status !== 200) {
            logMessage(`[HTTP ${htmlRes.status}] C${lcsc}: Request failed`, "warn");
            sessionStats.failed++;
            updateStatsDisplay();
            return;
        }

        const html = htmlRes.responseText || "";
        const nextDataMatch = html.match(/<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/);

        let imgUrl = null;
        let productModel = "";

        if (nextDataMatch) {
            try {
                const nextData = JSON.parse(nextDataMatch[1]);
                const webData = nextData?.props?.pageProps?.webData;
                const prod = webData?.productRecord;

                if (prod) {
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
                logMessage(`[PARSE_ERR] C${lcsc}: JSON parse error: ${e.message}`, "warn");
            }
        }

        // Fallback: check OpenGraph or meta image tags
        if (!imgUrl) {
            const ogMatch = html.match(/<meta property="og:image" content="([^"]+)"/i);
            if (ogMatch) {
                imgUrl = ogMatch[1];
            }
        }

        if (!imgUrl) {
            logMessage(`[NO_IMG] C${lcsc}: No image found on item page`, "info");
            await uploadCrawledImage({
                lcsc: lcsc,
                product_model: productModel,
                has_image: false,
            });
            sessionStats.noImage++;
            sessionStats.processed++;
            updateStatsDisplay();
            return;
        }

        // Normalize image URL
        if (imgUrl.startsWith("//")) {
            imgUrl = "https:" + imgUrl;
        }

        // Download image binary
        try {
            const imgRes = await gmRequest({
                method: "GET",
                url: imgUrl,
                responseType: "blob",
                headers: {
                    "Referer": "https://item.szlcsc.com/",
                },
            });

            if (imgRes.status !== 200 || !imgRes.response) {
                throw new Error(`Image download HTTP ${imgRes.status}`);
            }

            const base64Data = await blobToBase64(imgRes.response);
            await uploadCrawledImage({
                lcsc: lcsc,
                image_base64: base64Data,
                image_url: imgUrl,
                product_model: productModel,
                has_image: true,
            });

            const sizeKb = Math.round((imgRes.response.size || 0) / 1024);
            logMessage(`[OK] C${lcsc}: Synced (${sizeKb} KB) - ${productModel}`, "success");
            sessionStats.downloaded++;
            sessionStats.processed++;
            updateStatsDisplay();
        } catch (e) {
            logMessage(`[IMG_FAIL] C${lcsc}: ${e.message}`, "error");
            sessionStats.failed++;
            updateStatsDisplay();
        }
    }

    async function harvesterLoop() {
        logMessage("Harvester loop started", "info");

        while (isRunning) {
            if (isPaused) {
                await sleep(500);
                continue;
            }

            let taskBatch;
            try {
                taskBatch = await fetchTasks(50);
            } catch (e) {
                logMessage(`[FETCH_ERR] ${e.message}. Retrying in 5s...`, "error");
                await sleep(5000);
                continue;
            }

            const tasks = taskBatch.tasks || [];
            if (tasks.length === 0) {
                logMessage("No more pending tasks in queue. All components crawled.", "success");
                stopHarvester();
                break;
            }

            logMessage(`Fetched batch of ${tasks.length} tasks (cursor: ${cursor})`, "info");

            for (const lcsc of tasks) {
                if (!isRunning) break;
                while (isPaused && isRunning) {
                    await sleep(500);
                }
                if (!isRunning) break;

                await processSingleLcsc(lcsc);

                cursor = lcsc;
                GM_setValue("crawler_cursor", cursor);
                updateCursorDisplay(cursor);

                await sleep(delayMs);
            }

            // Refresh global stats after each batch
            await checkBackendConnection();
        }

        logMessage("Harvester loop stopped", "info");
        updateHarvesterStatus("Idle");
    }

    function startHarvester() {
        if (isRunning) return;
        isRunning = true;
        isPaused = false;
        updateHarvesterStatus("Running");
        document.getElementById("ps-btn-start").disabled = true;
        document.getElementById("ps-btn-pause").disabled = false;
        document.getElementById("ps-btn-pause").textContent = "Pause";
        harvesterLoop();
    }

    function pauseHarvester() {
        if (!isRunning) return;
        isPaused = !isPaused;
        const pauseBtn = document.getElementById("ps-btn-pause");
        if (isPaused) {
            updateHarvesterStatus("Paused");
            pauseBtn.textContent = "Resume";
            logMessage("Harvester paused", "warn");
        } else {
            updateHarvesterStatus("Running");
            pauseBtn.textContent = "Pause";
            logMessage("Harvester resumed", "info");
        }
    }

    function stopHarvester() {
        isRunning = false;
        isPaused = false;
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
                    <span class="ps-subtitle">LCSC Image Harvester</span>
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
                        <span class="ps-label">Current Part:</span>
                        <span id="ps-current-task" class="ps-mono ps-text-cyan">None</span>
                    </div>
                </div>

                <!-- Settings -->
                <div class="ps-section">
                    <div class="ps-field">
                        <label class="ps-label">PartShelf API URL:</label>
                        <input id="ps-input-api" class="ps-input ps-mono" type="text" value="${apiUrl}" />
                    </div>
                    <div class="ps-field-row" style="margin-top: 6px;">
                        <div class="ps-field-col">
                            <label class="ps-label">Delay (ms):</label>
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
                    <button id="ps-btn-reset-cursor" class="ps-btn ps-btn-outline" title="Reset cursor to 0">Reset Csr</button>
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

        // Inject Styles
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
                box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5), 0 8px 10px -6px rgba(0, 0, 0, 0.4);
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
                max-height: 540px;
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
            .ps-log-box {
                background: #0f172a;
                border: 1px solid #334155;
                border-radius: 4px;
                height: 100px;
                overflow-y: auto;
                padding: 6px 8px;
                font-size: 10px;
                display: flex;
                flex-direction: column;
                gap: 2px;
            }
            .ps-log-line {
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            .ps-log-info { color: #94a3b8; }
            .ps-log-success { color: #34d399; }
            .ps-log-warn { color: #facc15; }
            .ps-log-error { color: #f87171; }
        `;

        document.head.appendChild(style);
        document.body.appendChild(container);

        // Bind Events
        bindUIEvents();
    }

    function bindUIEvents() {
        const btnStart = document.getElementById("ps-btn-start");
        const btnPause = document.getElementById("ps-btn-pause");
        const btnTest = document.getElementById("ps-btn-test");
        const btnResetCursor = document.getElementById("ps-btn-reset-cursor");
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
            logMessage(`Cursor manually set to ${cursor}`, "warn");
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

        btnResetCursor.addEventListener("click", () => {
            cursor = 0;
            inputCursor.value = 0;
            GM_setValue("crawler_cursor", 0);
            logMessage("Cursor reset to 0", "warn");
        });

        btnClearLog.addEventListener("click", () => {
            const logBox = document.getElementById("ps-crawler-log");
            if (logBox) logBox.innerHTML = "";
        });

        let isMinimized = false;
        btnMinimize.addEventListener("click", () => {
            isMinimized = !isMinimized;
            panelBody.style.display = isMinimized ? "none" : "flex";
            btnMinimize.textContent = isMinimized ? "+" : "_";
        });

        // Draggable panel header
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

    // ----------------------------------------------------
    // Initialization
    // ----------------------------------------------------
    function init() {
        createUI();
        logMessage("Harvester initialized. Ready to sync with PartShelf.", "info");
        checkBackendConnection();

        if (typeof GM_registerMenuCommand !== "undefined") {
            GM_registerMenuCommand("Start Harvester", startHarvester);
            GM_registerMenuCommand("Pause Harvester", pauseHarvester);
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
