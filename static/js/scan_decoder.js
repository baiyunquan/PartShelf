(function (root) {
  "use strict";
  let ready;
  function prepare() {
    if (!ready) ready = root.ZXingWASM.prepareZXingModule({fireImmediately: true, overrides: {
      locateFile: path => path.endsWith(".wasm") ? "/static/js/vendor/zxing-wasm/zxing_reader.wasm" : path,
    }});
    return ready;
  }
  async function read(imageData) {
    await prepare();
    for (const binarizer of ["LocalAverage", "GlobalHistogram"]) {
      const results = await root.ZXingWASM.readBarcodes(imageData, {formats: ["QRCode"], tryHarder: true,
        tryRotate: true, tryInvert: true, tryDownscale: true, tryDenoise: true, binarizer, maxNumberOfSymbols: 8});
      if (results.length) return results;
    }
    return [];
  }
  async function decode(blob) {
    const bitmap = await createImageBitmap(blob, {imageOrientation: "from-image"});
    try {
      const canvas = document.createElement("canvas");
      const context = canvas.getContext("2d", {willReadFrequently: true});
      for (const scale of [1, 0.75, 1.08]) {
        const factor = Math.min(1, 4000 / Math.max(bitmap.width, bitmap.height)) * scale;
        canvas.width = Math.round(bitmap.width * factor);
        canvas.height = Math.round(bitmap.height * factor);
        context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
        const results = await read(context.getImageData(0, 0, canvas.width, canvas.height));
        if (results.length) return results;
      }
      return [];
    } finally { bitmap.close(); }
  }
  root.ScanDecoder = {prepare, read, decode};
})(globalThis);
