"""Transactional, rebuildable C/R/L aliases stored beside each source catalog."""

import hashlib
import json
import logging
import sqlite3
from typing import Any, Dict, Iterable, Optional

from app.services import search_alias_service
from app.services.electrical_value_service import PARSER_VERSION, measurements_for_record


LOGGER = logging.getLogger(__name__)
TRIGGER_VERSION = "2"
CATALOGS = {
    "jlcparts": ("jlc_components", "lcsc", "jlcparts.db"),
    "altium": ("altium_components", "id", "altium_library.db"),
    "kicad": ("kicad_symbols", "id", "kicad_symbols.db"),
}
_FIELDS = {
    "jlcparts": ("lcsc", "attributes", "description", "mfr"),
    "altium": ("id", "source_file", "lib_reference", "mfr_part_number", "capacitance",
               "resistance", "inductance", "parameters_json", "description"),
    "kicad": ("id", "library", "name", "value", "properties_json", "description"),
}


def _alias_digest(source: str) -> str:
    payload = search_alias_service.search_aliases.record_aliases.get(source, {})
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _schema(conn: sqlite3.Connection, source: str) -> None:
    table, identity, _ = CATALOGS[source]
    conn.execute("CREATE TABLE IF NOT EXISTS numeric_search_aliases ("
                 "record_id INTEGER NOT NULL, kind TEXT NOT NULL, value TEXT NOT NULL, "
                 "PRIMARY KEY(record_id,kind,value))")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_numeric_search_lookup "
                 "ON numeric_search_aliases(kind,value,record_id)")
    conn.execute("CREATE TABLE IF NOT EXISTS numeric_search_dirty (record_id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE IF NOT EXISTS numeric_search_meta (key TEXT PRIMARY KEY,value TEXT NOT NULL)")
    meta = dict(conn.execute("SELECT key,value FROM numeric_search_meta"))
    if meta.get("trigger_version") == TRIGGER_VERSION:
        return
    for event, reference in (("INSERT", "NEW"), ("UPDATE", "NEW"), ("DELETE", "OLD")):
        conn.execute(f"DROP TRIGGER IF EXISTS numeric_search_{event.lower()}")
        conn.execute(
            f"CREATE TRIGGER numeric_search_{event.lower()} AFTER {event} ON {table} "
            f"BEGIN INSERT INTO numeric_search_dirty(record_id) VALUES({reference}.{identity}) ON CONFLICT(record_id) DO NOTHING; "
            + (f"INSERT INTO numeric_search_dirty(record_id) VALUES(OLD.{identity}) ON CONFLICT(record_id) DO NOTHING; "
               if event == "UPDATE" else "") + "END"
        )
    conn.execute("INSERT INTO numeric_search_meta VALUES('trigger_version',?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (TRIGGER_VERSION,))


def ensure_numeric_triggers(conn: sqlite3.Connection, source: str) -> None:
    """Migrate only dirty-record triggers before a catalog UPSERT; do not rebuild aliases."""
    if conn.in_transaction:
        raise RuntimeError("Commit catalog changes before migrating numeric triggers")
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='numeric_search_meta'").fetchone()
    if exists:
        version = conn.execute("SELECT value FROM numeric_search_meta WHERE key='trigger_version'").fetchone()
        if version and version[0] == TRIGGER_VERSION:
            return
    try:
        conn.execute("BEGIN IMMEDIATE")
        _schema(conn, source)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _insert_records(conn, source, records, columns) -> Dict[str, int]:
    _, identity, _ = CATALOGS[source]
    scanned = aliases = unparsed = 0
    pending = []
    for raw in records:
        record = dict(zip(columns, raw))
        quantities = measurements_for_record(
            source, record, search_alias_service.record_curated_aliases(source, record)
        )
        scanned += 1
        if not quantities:
            unparsed += 1
        aliases += len(quantities)
        pending.extend((record[identity], kind, value) for kind, value in quantities)
    conn.executemany("INSERT OR IGNORE INTO numeric_search_aliases VALUES(?,?,?)", pending)
    return {"scanned": scanned, "aliases": aliases, "without_values": unparsed}


def ensure_numeric_aliases(
    conn: sqlite3.Connection, source: str, *, force: bool = False, batch_size: int = 2000,
) -> Dict[str, Any]:
    """Build once, then refresh dirty IDs before any parameter lookup.

    This owns its transaction; callers must commit catalog writes first.
    SQLite serializes builders across application workers and CLI processes.
    """
    table, identity, _ = CATALOGS[source]
    batch_size = max(1, min(10000, int(batch_size)))
    if conn.in_transaction:
        raise RuntimeError("Commit catalog changes before refreshing numeric aliases")
    digest = _alias_digest(source)
    report = {"source": source, "scanned": 0, "aliases": 0, "without_values": 0,
              "rebuilt": False}
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                          "AND name='numeric_search_meta'").fetchone()
    if exists and not force:
        meta = dict(conn.execute("SELECT key,value FROM numeric_search_meta"))
        if (meta.get("version") == PARSER_VERSION and meta.get("aliases") == digest
                and meta.get("trigger_version") == TRIGGER_VERSION):
            if not conn.execute("SELECT 1 FROM numeric_search_dirty LIMIT 1").fetchone():
                return report
    try:
        conn.execute("BEGIN IMMEDIATE")
        _schema(conn, source)
        meta = dict(conn.execute("SELECT key,value FROM numeric_search_meta"))
        rebuild = force or meta.get("version") != PARSER_VERSION or meta.get("aliases") != digest
        available = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        columns = [field for field in _FIELDS[source] if field in available]
        if identity not in columns:
            raise ValueError(f"Missing catalog identity column: {identity}")
        fields = ",".join(columns)
        report["rebuilt"] = rebuild
        if rebuild:
            conn.execute("DELETE FROM numeric_search_aliases")
            cursor = conn.execute(f"SELECT {fields} FROM {table} ORDER BY {identity}")
            while True:
                rows = cursor.fetchmany(batch_size)
                if not rows:
                    break
                counts = _insert_records(conn, source, rows, columns)
                for key, count in counts.items():
                    report[key] += count
            conn.execute("DELETE FROM numeric_search_dirty")
            conn.executemany("INSERT OR REPLACE INTO numeric_search_meta VALUES(?,?)",
                             (("version", PARSER_VERSION), ("aliases", digest)))
        else:
            while True:
                ids = [row[0] for row in conn.execute(
                    "SELECT record_id FROM numeric_search_dirty LIMIT ?", (min(batch_size, 500),)
                )]
                if not ids:
                    break
                placeholders = ",".join("?" for _ in ids)
                conn.execute(f"DELETE FROM numeric_search_aliases WHERE record_id IN ({placeholders})", ids)
                rows = conn.execute(f"SELECT {fields} FROM {table} WHERE {identity} IN ({placeholders})", ids)
                counts = _insert_records(conn, source, rows, columns)
                for key, count in counts.items():
                    report[key] += count
                conn.execute(f"DELETE FROM numeric_search_dirty WHERE record_id IN ({placeholders})", ids)
        conn.commit()
        return report
    except Exception:
        conn.rollback()
        raise


def prepare_numeric_aliases(conn: sqlite3.Connection, source: str) -> bool:
    """Keep legacy text search available when a derived index cannot be prepared."""
    try:
        ensure_numeric_aliases(conn, source)
        return True
    except (sqlite3.Error, OSError, ValueError, RuntimeError):
        LOGGER.exception("Numeric equivalence search is unavailable for %s; retaining text search", source)
        return False


def aliases_for_ids(conn: sqlite3.Connection, identities: Iterable[int]) -> Dict[int, set]:
    ids = sorted(set(identities))
    result = {}
    for start in range(0, len(ids), 500):
        batch = ids[start:start + 500]
        placeholders = ",".join("?" for _ in batch)
        for record_id, kind, value in conn.execute(
            f"SELECT record_id,kind,value FROM numeric_search_aliases WHERE record_id IN ({placeholders})", batch
        ):
            result.setdefault(record_id, set()).add((kind, value))
    return result
