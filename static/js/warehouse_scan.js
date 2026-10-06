(() => {
  "use strict";

  const node = id => document.getElementById(id);
  const translations = JSON.parse(node("page-translations").textContent);
  const text = key => translations[key] || key;
  const cabinets = JSON.parse(node("warehouse-cabinet-config").textContent);
  const targets = new Map(cabinets.flatMap(cabinet => cabinet.drawerGroups.flatMap(group =>
    group.drawers.map(drawer => [drawer.qrPayload, {cabinet_id: cabinet.id, drawer_code: drawer.code}]))));
  const modalNode = node("warehouse-scan-modal");
  const modal = bootstrap.Modal.getOrCreateInstance(modalNode);
  const video = node("warehouse-scan-video");
  const camera = node("warehouse-scan-camera");
  const imageInput = node("warehouse-scan-image");
  let active = false;
  let starting = false;
  let busy = false;
  let generation = 0;
  let stream = null;
  let timer = null;
  let pendingTarget = null;

  function message(key, error = false) {
    node("warehouse-scan-message").textContent = text(key);
    node("warehouse-scan-message").className = "mt-3 mb-0 " + (error ? "text-danger" : "text-secondary");
  }

  function updateControls() {
    node("warehouse-scan-start").disabled = !active || starting || busy || !!stream;
    node("warehouse-scan-stop").disabled = !stream && !starting;
    camera.disabled = starting || busy || !camera.options.length;
    imageInput.disabled = busy;
  }

  function stopCamera() {
    ++generation;
    starting = false;
    clearTimeout(timer);
    timer = null;
    if (stream) for (const track of stream.getTracks()) track.stop();
    stream = null;
    video.srcObject = null;
    video.hidden = true;
    updateControls();
  }

  async function processImage(blob, fromCamera, version) {
    if (!active || busy || version !== generation) return;
    busy = true;
    updateControls();
    try {
      if (blob.size > 10 * 1024 * 1024) { message("scan_too_large", true); return; }
      if (!fromCamera) message("scan_decoding");
      const results = await ScanDecoder.decode(blob);
      if (!active || version !== generation) return;
      const matches = new Map();
      for (const result of results) {
        const payload = String(result.text || "").trim();
        if (targets.has(payload)) matches.set(payload, targets.get(payload));
      }
      if (matches.size !== 1) {
        if (matches.size > 1) message("scan_multiple", true);
        else if (results.length) message("scan_invalid", true);
        else if (!fromCamera) message("scan_no_code", true);
        return;
      }
      pendingTarget = matches.values().next().value;
      stopCamera();
      modal.hide();
    } catch (_error) {
      if (active && version === generation) {
        stopCamera();
        message("scan_error", true);
      }
    } finally {
      busy = false;
      updateControls();
    }
  }

  async function cameraFrame(version) {
    if (!active || !stream || version !== generation) return;
    try {
      if (!busy && video.readyState >= 2 && video.videoWidth && video.videoHeight) {
        const canvas = document.createElement("canvas");
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        canvas.getContext("2d").drawImage(video, 0, 0);
        const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/jpeg", 0.95));
        if (blob) await processImage(blob, true, version);
      }
    } catch (_error) {
      if (active && version === generation) {
        stopCamera();
        message("scan_error", true);
      }
    }
    if (active && stream && version === generation) timer = setTimeout(() => cameraFrame(version), 450);
  }

  async function startCamera() {
    if (!active || starting || busy || stream) return;
    starting = true;
    const version = ++generation;
    updateControls();
    message("scan_loading");
    try {
      if (!navigator.mediaDevices?.getUserMedia || !window.isSecureContext) {
        throw new Error("Secure camera access is unavailable");
      }
      await ScanDecoder.prepare();
      if (!active || version !== generation) return;
      const opened = await navigator.mediaDevices.getUserMedia({audio: false, video: {
        ...(camera.value ? {deviceId: {exact: camera.value}} : {facingMode: {ideal: "environment"}}),
        width: {ideal: 1920}, height: {ideal: 1080},
      }});
      if (!active || version !== generation) {
        for (const track of opened.getTracks()) track.stop();
        return;
      }
      stream = opened;
      video.srcObject = opened;
      video.hidden = false;
      await video.play();
      if (!active || version !== generation) return;
      const selected = opened.getVideoTracks()[0].getSettings().deviceId;
      try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        if (!active || version !== generation) return;
        camera.replaceChildren();
        for (const [index, device] of devices.filter(item => item.kind === "videoinput").entries()) {
          camera.add(new Option(device.label || `${text("scan_camera")} ${index + 1}`, device.deviceId));
        }
        camera.value = selected || "";
      } catch (_error) { /* The default camera remains usable without a device list. */ }
      if (!active || version !== generation) return;
      message("scan_ready");
      cameraFrame(version);
    } catch (_error) {
      if (active && version === generation) {
        stopCamera();
        message("scan_camera_error", true);
      }
    } finally {
      if (version === generation) starting = false;
      updateControls();
    }
  }

  modalNode.addEventListener("shown.bs.modal", () => {
    active = true;
    pendingTarget = null;
    startCamera();
  });
  modalNode.addEventListener("hide.bs.modal", () => {
    active = false;
    stopCamera();
  });
  modalNode.addEventListener("hidden.bs.modal", () => {
    const target = pendingTarget;
    pendingTarget = null;
    if (target) document.dispatchEvent(new CustomEvent("warehouse:show-drawer", {
      detail: {...target, scroll_to_drawer: true},
    }));
  });
  node("warehouse-scan-start").addEventListener("click", startCamera);
  node("warehouse-scan-stop").addEventListener("click", () => {
    stopCamera();
    message("scan_stopped");
  });
  camera.addEventListener("change", () => {
    stopCamera();
    startCamera();
  });
  imageInput.addEventListener("change", async () => {
    const file = imageInput.files[0];
    stopCamera();
    if (file) await processImage(file, false, generation);
    imageInput.value = "";
  });
  document.addEventListener("visibilitychange", () => { if (document.hidden) stopCamera(); });
  window.addEventListener("pagehide", () => { active = false; stopCamera(); });
  updateControls();
})();
