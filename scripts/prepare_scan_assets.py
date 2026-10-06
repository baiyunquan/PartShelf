"""Install version-matched, integrity-checked local ZXing reader assets."""

import argparse
import base64
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tarfile
from urllib.request import urlopen


BASE = Path(__file__).resolve().parents[1]
VERSION = "3.1.4"
INTEGRITY = "1+v8p7sauddySVNG+ye7GD/0TS95BG2ycdkrC+EnBrFBFkHeIghzUt2yVjtx3NucJeNrQnhT8yGAIz60Vx9o0w=="


def prepare(destination=None):
    source = BASE / "vendor" / "zxing-wasm"
    manifest = source / "package.json"
    if not manifest.is_file() or json.loads(manifest.read_text())["version"] != VERSION:
        raise RuntimeError(f"Initialize the zxing-wasm submodule at v{VERSION} first")
    destination = Path(destination or BASE / "static" / "js" / "vendor" / "zxing-wasm")
    destination.mkdir(parents=True, exist_ok=True)
    with urlopen(f"https://registry.npmjs.org/zxing-wasm/-/zxing-wasm-{VERSION}.tgz", timeout=60) as response:
        data = response.read(8 * 1024 * 1024)
    digest = base64.b64encode(hashlib.sha512(data).digest()).decode()
    if digest != INTEGRITY:
        raise RuntimeError("ZXing release integrity check failed")
    files = {"package/dist/iife/reader/index.js": "reader.js", "package/dist/reader/zxing_reader.wasm": "zxing_reader.wasm"}
    with tarfile.open(fileobj=BytesIO(data), mode="r:gz") as archive:
        for name, output in files.items():
            member = archive.extractfile(name)
            if member is None:
                raise RuntimeError(f"Missing release asset: {name}")
            (destination / output).write_bytes(member.read())
    (destination / "LICENSE").write_bytes((source / "LICENSE").read_bytes())
    (destination / "version.json").write_text(json.dumps({"version": VERSION, "package_integrity": "sha512-" + INTEGRITY,
        "files": {name: hashlib.sha256((destination / name).read_bytes()).hexdigest()
                  for name in ("reader.js", "zxing_reader.wasm")}}, indent=2) + "\n")
    print(f"Prepared local ZXing reader {VERSION}: {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path)
    prepare(parser.parse_args().destination)
