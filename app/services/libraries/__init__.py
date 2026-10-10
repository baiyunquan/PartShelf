"""Domain library database services for PartShelf."""

from .common import (
    ALTIUM_DB_PATH,
    BASE_DIR,
    DATA_DIR,
    FASTENERS_DB_PATH,
    JLCPARTS_DB_PATH,
    KICAD_DB_PATH,
    SCRIPTS_DIR,
    STATIC_PARTS_DIR,
    ensure_libraries_on_startup,
    get_connection,
    get_db_path,
    get_libraries_status,
)
from .altium import AltiumLibrary, altium_library
from .kicad import KiCadLibrary, kicad_library
from .jlcparts import JLCPartsLibrary, jlcparts_library
from .fasteners import FASTENER_DOMAINS, FastenersLibrary, fasteners_library

__all__ = [
    "BASE_DIR",
    "DATA_DIR",
    "SCRIPTS_DIR",
    "JLCPARTS_DB_PATH",
    "ALTIUM_DB_PATH",
    "KICAD_DB_PATH",
    "FASTENERS_DB_PATH",
    "STATIC_PARTS_DIR",
    "ensure_libraries_on_startup",
    "get_connection",
    "get_db_path",
    "get_libraries_status",
    "AltiumLibrary",
    "altium_library",
    "KiCadLibrary",
    "kicad_library",
    "JLCPartsLibrary",
    "jlcparts_library",
    "FastenersLibrary",
    "fasteners_library",
    "FASTENER_DOMAINS",
]
