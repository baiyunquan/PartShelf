"""Build or refresh derived C/R/L aliases in installed reference catalogs."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.services.numeric_alias_index import CATALOGS, ensure_numeric_aliases


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-dir", type=Path, default=BASE_DIR / "data" / "libraries")
    parser.add_argument("--source", choices=("all", *CATALOGS), default="all")
    parser.add_argument("--batch-size", type=int, default=2000)
    parser.add_argument("--incremental", action="store_true", help="Refresh only dirty records when the index is current")
    args = parser.parse_args(argv)
    sources = CATALOGS if args.source == "all" else (args.source,)
    failed = False
    for source in sources:
        path = args.library_dir / CATALOGS[source][2]
        if not path.exists():
            print(json.dumps({"source": source, "status": "missing", "path": str(path)}))
            failed = True
            continue
        conn = sqlite3.connect(path, timeout=30)
        try:
            report = ensure_numeric_aliases(conn, source, force=not args.incremental, batch_size=args.batch_size)
            print(json.dumps({"path": str(path), **report}, ensure_ascii=False), flush=True)
        except (sqlite3.Error, ValueError, RuntimeError) as exc:
            print(json.dumps({"source": source, "status": "error", "error": str(exc)}), flush=True)
            failed = True
        finally:
            conn.close()
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
