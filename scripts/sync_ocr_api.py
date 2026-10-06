"""Publish the version-controlled standalone service to ElectronicQwen."""

import argparse
from pathlib import Path
import shutil


def sync(destination):
    source = Path(__file__).resolve().parents[1] / "services" / "paddleocr_api"
    target = Path(destination) / "ocr_api"
    target.mkdir(parents=True, exist_ok=True)
    for path in source.iterdir():
        if path.is_file() and path.suffix in {".py", ".md", ".txt"}:
            shutil.copyfile(path, target / path.name)
    print(f"Standalone OCR API published to {target}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=Path(__file__).resolve().parents[2] / "ElectronicQwen")
    sync(parser.parse_args().destination)
