import os
import sqlite3
from pathlib import Path
from typing import Dict, Optional, Tuple, Set

# Base directory for PartShelf
PARTSHELF_DIR = Path(__file__).resolve().parent.parent
DEFAULT_TARGET_DB = PARTSHELF_DIR / "partshelf.db"

# Database source paths
BACKEND_ROOT = PARTSHELF_DIR.parent
DATABASE_DIR = BACKEND_ROOT / "database"

JLCPARTS_DB_PRIMARY = DATABASE_DIR / "jlcparts" / "cache.sqlite3"
JLCPARTS_DB_FALLBACK = DATABASE_DIR / "jlcpcb-parts-database" / "jlcpcb-components.sqlite3"
KICAD_SYMBOLS_DIR = DATABASE_DIR / "kicad-symbols"
ALTIUM_DIR = DATABASE_DIR / "altium_jlcpcb_libraries"


class PartShelfImporter:
    """High-performance SQLite batch importer for PartShelf."""

    def __init__(self, target_db_path: Optional[str or Path] = None):
        self.target_db_path = Path(target_db_path or DEFAULT_TARGET_DB)
        self.conn = sqlite3.connect(str(self.target_db_path))
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.conn.execute("PRAGMA journal_mode = WAL;")
        self.conn.execute("PRAGMA synchronous = NORMAL;")
        self.cursor = self.conn.cursor()

        # In-memory caches to avoid N+1 SELECT queries
        self.manufacturers: Dict[str, int] = {}
        self.packages: Dict[str, int] = {}
        self.types: Dict[str, int] = {}
        self.existing_part_names: Set[str] = set()

        self.added_count = 0
        self.skipped_count = 0
        self.updated_count = 0

        self._load_caches()

    def _load_caches(self):
        """Preload lookup tables and existing part names into memory."""
        self.cursor.execute("SELECT id, name FROM manufacturers")
        for m_id, name in self.cursor.fetchall():
            if name:
                self.manufacturers[name.strip().lower()] = m_id

        self.cursor.execute("SELECT id, package_type FROM packages")
        for p_id, pkg in self.cursor.fetchall():
            if pkg:
                self.packages[pkg.strip().lower()] = p_id

        self.cursor.execute("SELECT id, part_type FROM types")
        for t_id, p_type in self.cursor.fetchall():
            if p_type:
                self.types[p_type.strip().lower()] = t_id

        self.cursor.execute("SELECT name FROM parts")
        for (name,) in self.cursor.fetchall():
            if name:
                self.existing_part_names.add(name.strip().lower())

    def get_or_create_manufacturer(self, name: Optional[str]) -> int:
        clean = (name or "").strip()
        if not clean:
            clean = "Generic"
        key = clean.lower()
        if key in self.manufacturers:
            return self.manufacturers[key]

        self.cursor.execute("INSERT INTO manufacturers (name) VALUES (?)", (clean[:255],))
        m_id = self.cursor.lastrowid
        self.manufacturers[key] = m_id
        return m_id

    def get_or_create_package(self, package_type: Optional[str]) -> int:
        clean = (package_type or "").strip()
        if not clean:
            clean = "Other"
        key = clean.lower()
        if key in self.packages:
            return self.packages[key]

        self.cursor.execute("INSERT INTO packages (package_type) VALUES (?)", (clean[:255],))
        p_id = self.cursor.lastrowid
        self.packages[key] = p_id
        return p_id

    def get_or_create_type(self, part_type: Optional[str]) -> int:
        clean = (part_type or "").strip()
        if not clean:
            clean = "Miscellaneous"
        key = clean.lower()
        if key in self.types:
            return self.types[key]

        self.cursor.execute("INSERT INTO types (part_type) VALUES (?)", (clean[:255],))
        t_id = self.cursor.lastrowid
        self.types[key] = t_id
        return t_id

    def add_part(
        self,
        name: str,
        description: Optional[str],
        manufacturer: Optional[str],
        package: Optional[str],
        part_type: Optional[str],
        quantity: int = 0,
        disambiguate_suffix: Optional[str] = None
    ) -> bool:
        """
        Add a part and its inventory record into SQLite.
        If the part name already exists and a disambiguate_suffix is provided, appends the suffix.
        Returns True if inserted, False if skipped as duplicate.
        """
        clean_name = (name or "").strip()
        if not clean_name:
            self.skipped_count += 1
            return False

        key = clean_name.lower()
        if key in self.existing_part_names:
            if disambiguate_suffix:
                clean_name = f"{clean_name} ({disambiguate_suffix})"
                key = clean_name.lower()
                if key in self.existing_part_names:
                    self.skipped_count += 1
                    return False
            else:
                self.skipped_count += 1
                return False

        m_id = self.get_or_create_manufacturer(manufacturer)
        pkg_id = self.get_or_create_package(package)
        type_id = self.get_or_create_type(part_type)

        clean_desc = (description or "")[:255].strip()
        qty = max(0, int(quantity or 0))

        # Insert part
        self.cursor.execute(
            """
            INSERT INTO parts (name, description, manufacturer_id, package_id, type_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (clean_name[:255], clean_desc, m_id, pkg_id, type_id)
        )
        part_id = self.cursor.lastrowid

        # Insert inventory
        self.cursor.execute(
            """
            INSERT INTO inventories (part_id, quantity_available)
            VALUES (?, ?)
            """,
            (part_id, qty)
        )

        self.existing_part_names.add(key)
        self.added_count += 1
        return True

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.commit()
        self.conn.close()
