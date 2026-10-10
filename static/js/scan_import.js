(() => {
  "use strict";
  const translations = JSON.parse(document.getElementById("page-translations").textContent);
  const text = key => translations[key] || key;
  const node = id => document.getElementById(id);
  const project = node("scan-project");
  const imageInput = node("scan-image");
  const video = node("scan-video");
  const camera = node("scan-camera");
  const projectKey = "partshelf.scanProjectId";
  let projectOptions = [];
  let stream = null;
  let running = false;
  let starting = false;
  let cameraVersion = 0;
  let busy = false;
  let projectsReady = false;
  let decoderReady = false;
  let timer = null;
  let review = null;
  let selectedIdentity = null;
  let history = [];
  const seen = new Set();
  const labelKey = label => JSON.stringify([label.pc, label.pm, label.qty, label.on || "", label.pdi || "", label.cc || ""]);

  function message(key, error = false) {
    node("scan-message").textContent = text(key);
    node("scan-message").className = "mt-3 mb-0 " + (error ? "text-danger" : "text-secondary");
  }
  function updateControls() {
    project.disabled = busy || !projectsReady;
    imageInput.disabled = busy || !projectsReady || !decoderReady;
    node("scan-start").disabled = running || starting || busy || !projectsReady || !decoderReady;
    node("scan-stop").disabled = !running && !starting;
    node("scan-capture").disabled = !running || busy;
    camera.disabled = busy;
    node("scan-review-confirm").disabled = busy;
    node("scan-review-retry").disabled = busy;
    node("scan-repeat").disabled = busy;
    for (const button of document.querySelectorAll("[data-scan-review]")) button.disabled = busy;
  }
  async function request(url, options) {
    const response = await fetch(url, options);
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : text("error"));
    return result;
  }
  function saveProject() {
    const token = (projectOptions.find(item => String(item.id) === project.value) || {}).identity_token || "";
    try {
      localStorage.setItem(projectKey, project.value);
      localStorage.setItem(projectKey + ".identity", token);
    } catch (_error) { /* Selection still persists in this tab. */ }
  }
  async function loadProjects() {
    const projects = await request("/api/scan/projects");
    projectOptions = projects;
    let saved = "";
    let token = null;
    try { saved = localStorage.getItem(projectKey) || ""; token = localStorage.getItem(projectKey + ".identity"); } catch (_error) { /* Optional storage. */ }
    const linked = node("scan-import-page").dataset.projectId;
    if (linked) { saved = linked; token = null; }
    project.replaceChildren(new Option(text("inventory_only"), ""));
    for (const item of projects.filter(item => !item.is_system)) project.add(new Option(item.name, String(item.id)));
    project.value = ScanLabel.projectChoice(projects, saved, token);
    projectsReady = true;
    saveProject();
    updateControls();
  }
  project.addEventListener("change", saveProject);

  function element(tag, content, className = "") {
    const result = document.createElement(tag);
    result.textContent = content;
    result.className = className;
    return result;
  }
  function link(container, title, url) {
    const anchor = element("a", text(title), "btn btn-outline-primary btn-sm");
    anchor.href = url;
    container.append(anchor);
  }
  function showReview(scan) {
    review = scan;
    node("scan-review").hidden = false;
    node("scan-review-project").textContent = `${text("project")}: ${scan.project_name || text("inventory_only")}`;
    node("scan-review-photo").src = scan.image_url;
    const evidence = node("scan-evidence");
    evidence.replaceChildren();
    const component = scan.component || {};
    selectedIdentity = component.library_source && component.external_part_id ? component : null;
    const catalogCode = component.library_source === "jlcparts" ? `C${component.external_part_id}` : component.external_part_id || "?";
    evidence.append(element("p", `${text("catalog")}: ${catalogCode} · ${component.mfr_part_number || component.mfr || component.name || "?"} · ${component.package || "?"}`, "fw-bold"));
    for (const [key, result] of Object.entries(scan.verification.fields || {})) {
      const status = text(result.matched ? "matched" : "unmatched");
      const value = `${text(key)}: ${status} · ${result.expected ?? ""} · ${result.text || ""}`;
      evidence.append(element("p", value, "scan-evidence-line " + (result.matched ? "text-success" : "text-danger")));
    }
    for (const reason of scan.verification.reasons || []) evidence.append(element("p", text(`reason_${reason}`), "text-danger"));
    const details = document.createElement("details");
    details.append(element("summary", text("ocr")));
    for (const line of (scan.ocr || {}).lines || []) details.append(element("p", line.text, "small"));
    evidence.append(details);
    const aiNote = node("scan-ai-note");
    if (aiNote) {
      if (scan.verification && scan.verification.ai_reasoning) {
        aiNote.hidden = false;
        aiNote.textContent = `${text("label_ai_reasoning")}: ${scan.verification.ai_reasoning}`;
      } else {
        aiNote.hidden = true;
      }
    }
    const candSection = node("scan-candidates-section");
    const candList = node("scan-candidates-list");
    if (candSection && candList) {
      const candidates = (scan.verification && scan.verification.candidates) || [];
      candSection.hidden = candidates.length === 0;
      candList.replaceChildren();
      for (const cand of candidates) {
        const card = document.createElement("div");
        card.className = "card p-2 border scan-candidate-card";
        const title = cand.mfr_part_number || cand.name || cand.external_part_id || "";
        const sub = `${cand.package || ""} · ${cand.manufacturer || ""} · ${text("stock_label") || "Stock"}: ${cand.stock ?? 0}`;
        const row = document.createElement("div");
        row.className = "d-flex justify-content-between align-items-center";
        const info = document.createElement("div");
        const titleEl = document.createElement("div");
        titleEl.className = "fw-bold small";
        titleEl.textContent = title;
        const subEl = document.createElement("div");
        subEl.className = "text-muted small";
        subEl.textContent = sub;
        info.append(titleEl, subEl);
        const selBtn = document.createElement("button");
        selBtn.type = "button";
        selBtn.className = "btn btn-outline-primary btn-sm";
        selBtn.textContent = text("btn_select_candidate") || "Select";
        selBtn.addEventListener("click", () => {
          const codeVal = cand.external_part_id ? (cand.library_source === "jlcparts" ? "C" + cand.external_part_id : cand.external_part_id) : (cand.lcsc ? "C" + cand.lcsc : title);
          node("scan-review-code").value = codeVal;
          selectedIdentity = cand;
        });
        row.append(info, selBtn);
        card.append(row);
        candList.append(card);
      }
    }
    node("scan-review-form").hidden = scan.status === "imported";
    const resolvedCode = (scan.component && (scan.component.lcsc ? "C" + scan.component.lcsc : scan.component.external_part_id))
      || (scan.label && scan.label.pc)
      || "";
    node("scan-review-code").value = resolvedCode;
    node("scan-review-quantity").value = scan.quantity || (scan.label && scan.label.qty) || "";
    node("scan-review-note").value = scan.note || "";
    node("scan-new-package").checked = false;
    node("scan-new-package-wrap").hidden = scan.status !== "duplicate";
  }
  function renderHistory() {
    const container = node("scan-history");
    container.replaceChildren();
    if (!history.length) container.append(element("p", text("empty"), "text-muted"));
    for (const scan of history) {
      const card = document.createElement("article");
      const component = scan.component || {};
      const cardCode = (component.lcsc ? "C" + component.lcsc : component.external_part_id) || (scan.label && scan.label.pc) || "Part";
      card.append(element("p", `${cardCode} · ${component.mfr_part_number || component.mfr || (scan.label && scan.label.pm) || ""} · ${component.package || ""}`, "fw-bold"));
      card.append(element("p", `${text("quantity")}: ${scan.quantity || (scan.label && scan.label.qty) || "?"} · ${scan.project_name || text("inventory_only")}`));
      card.append(element("p", `${text(`status_${scan.status}`)} · ${new Date(scan.created_at).toLocaleString()} · ${scan.imported_by || scan.username || ""}`, scan.status === "imported" ? "text-success small" : "text-warning-emphasis small"));
      const actions = element("div", "", "scan-history-actions");
      const button = element("button", text("inspect"), "btn btn-outline-secondary btn-sm");
      button.dataset.scanReview = scan.id;
      button.addEventListener("click", () => { stopCamera(); showReview(scan); });
      actions.append(button);
      if (scan.part_id) {
        link(actions, "inventory_link", `/component_details?part_id=${scan.part_id}`);
        link(actions, "warehouse_link", `/warehouse?part_id=${scan.part_id}&drawer_type=S`);
        if (scan.project_id) link(actions, "project_link", `/project_details?project_id=${scan.project_id}`);
      }
      card.append(actions);
      container.append(card);
    }
    updateControls();
  }
  async function loadHistory() {
    const result = await request("/api/scan/history");
    history = result.items;
    for (const scan of history.filter(item => item.status === "imported")) {
      if (scan.label && scan.label.pc) seen.add(labelKey(scan.label));
    }
    renderHistory();
  }
  function receive(scan) {
    history = [scan, ...history.filter(item => item.id !== scan.id)].slice(0, 50);
    renderHistory();
    if (scan.status === "needs_review" || scan.status === "duplicate") {
      stopCamera();
      showReview(scan);
    } else if (scan.status === "imported") {
      node("scan-review").hidden = true;
    }
    message(scan.status === "processing" ? "status_processing" : scan.status, scan.status === "needs_review");
  }
  async function processImage(blob, fromCamera = false) {
    if (busy) return;
    if (blob.size > 10 * 1024 * 1024) { message("too_large", true); return; }
    busy = true;
    updateControls();
    message("decoding");
    try {
      const results = await ScanDecoder.decode(blob);
      const choice = ScanLabel.decodeChoice(results);
      if (choice.kind === "jlc") {
        const key = labelKey(choice.label);
        if (fromCamera && seen.has(key)) { message("duplicate"); return; }
      } else if (fromCamera && choice.kind === "ordinary") {
        // Continuous camera mode only imports QR codes; photos need an explicit capture.
        return;
      }
      const requestId = ScanLabel.requestId();
      const body = new FormData();
      body.append("image", blob, "label.jpg");
      body.append("qr_text", choice.qr_text || "");
      if (choice.qr_texts) body.append("qr_texts", JSON.stringify(choice.qr_texts));
      body.append("request_id", requestId);
      if (project.value) body.append("project_id", project.value);
      message("processing");
      const result = await request("/api/scan/recognize", {method: "POST", body});
      if (choice.kind === "jlc") seen.add(labelKey(choice.label));
      receive(result);
    } catch (error) {
      stopCamera();
      message("error", true);
      node("scan-message").append(document.createTextNode(` ${error.message}`));
    } finally {
      busy = false;
      updateControls();
    }
  }
  async function cameraFrame() {
    if (!running) return;
    if (!busy && video.readyState >= 2) {
      const canvas = document.createElement("canvas");
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      canvas.getContext("2d").drawImage(video, 0, 0);
      const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/jpeg", 0.95));
      if (blob && running) await processImage(blob, true);
    }
    if (running) timer = setTimeout(cameraFrame, 650);
  }
  async function startCamera() {
    if (starting || running || busy) return;
    starting = true;
    const version = ++cameraVersion;
    updateControls();
    try {
      if (!window.isSecureContext) {
        throw new Error("insecure_context");
      }
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error("no_media_devices");
      }
      const opened = await navigator.mediaDevices.getUserMedia({video: camera.value ? {deviceId: {exact: camera.value}, width: {ideal: 1920}, height: {ideal: 1080}}
        : {facingMode: {ideal: "environment"}, width: {ideal: 1920}, height: {ideal: 1080}}, audio: false});
      if (version !== cameraVersion) { for (const track of opened.getTracks()) track.stop(); return; }
      stream = opened;
      video.srcObject = stream;
      video.hidden = false;
      await video.play();
      const selected = stream.getVideoTracks()[0].getSettings().deviceId;
      const devices = await navigator.mediaDevices.enumerateDevices();
      camera.replaceChildren();
      for (const [index, device] of devices.filter(item => item.kind === "videoinput").entries()) camera.add(new Option(device.label || `${text("camera")} ${index + 1}`, device.deviceId));
      camera.value = selected;
      running = true;
      updateControls();
      message("ready");
      cameraFrame();
    } catch (err) {
      stopCamera();
      if (!window.isSecureContext || (err && err.message === "insecure_context")) {
        message("camera_insecure_context", true);
      } else if (err && (err.name === "NotAllowedError" || err.name === "PermissionDeniedError")) {
        message("camera_permission_denied", true);
      } else {
        const detail = err && err.message ? ` (${err.message})` : "";
        node("scan-message").textContent = `${text("camera_error")}${detail}`;
        node("scan-message").className = "mt-3 mb-0 text-danger";
      }
    }
    finally { starting = false; updateControls(); }
  }
  function stopCamera() {
    ++cameraVersion;
    running = false;
    if (timer) clearTimeout(timer);
    if (stream) for (const track of stream.getTracks()) track.stop();
    stream = null;
    video.srcObject = null;
    video.hidden = true;
    updateControls();
  }
  node("scan-start").addEventListener("click", startCamera);
  node("scan-repeat").addEventListener("click", () => {
    ScanLabel.repeatCameraScan(seen);
    message("repeat_ready");
  });
  node("scan-stop").addEventListener("click", stopCamera);
  node("scan-capture").addEventListener("click", async () => {
    if (busy || !running || video.readyState < 2) return;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d").drawImage(video, 0, 0);
    const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/jpeg", 0.95));
    stopCamera();
    if (blob) await processImage(blob);
  });
  camera.addEventListener("change", () => { if (running) { stopCamera(); startCamera(); } });
  window.addEventListener("pagehide", stopCamera);
  imageInput.addEventListener("change", async () => {
    const file = imageInput.files[0];
    stopCamera();
    if (file) await processImage(file);
    imageInput.value = "";
  });
  node("scan-refresh").addEventListener("click", () => loadHistory().catch(() => message("error", true)));
  node("scan-review-code").addEventListener("input", () => { selectedIdentity = null; });
  node("scan-review-form").addEventListener("submit", async event => {
    event.preventDefault();
    if (busy || !review || !event.target.reportValidity()) return;
    if (review.status === "duplicate" && !node("scan-new-package").checked) { message("confirm_duplicate", true); return; }
    busy = true;
    updateControls();
    try {
      const result = await request(`/api/scan/${review.id}/confirm`, {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({...ScanLabel.confirmationIdentity(node("scan-review-code").value.trim(), selectedIdentity), quantity: Number(node("scan-review-quantity").value),
          note: node("scan-review-note").value, new_package: node("scan-new-package").checked})});
      receive(result);
    } catch (error) { message("error", true); node("scan-message").append(document.createTextNode(` ${error.message}`)); }
    finally { busy = false; updateControls(); }
  });
  node("scan-review-retry").addEventListener("click", async () => {
    if (busy || !review) return;
    busy = true;
    updateControls();
    message("processing");
    try { receive(await request(`/api/scan/${review.id}/retry`, {method: "POST"})); }
    catch (error) { message("error", true); node("scan-message").append(document.createTextNode(` ${error.message}`)); }
    finally { busy = false; updateControls(); }
  });
  (async () => {
    try {
      await Promise.all([loadProjects(), loadHistory(), ScanDecoder.prepare()]);
      decoderReady = true;
      updateControls();
      message("ready");
    } catch (error) { message("error", true); node("scan-message").append(document.createTextNode(` ${error.message}`)); }
  })();
})();
