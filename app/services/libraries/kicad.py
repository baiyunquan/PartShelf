"""KiCad Symbol Libraries database service module."""

import math
import json
from pathlib import Path
from typing import Optional, Dict, Any, List

from app.services import search_alias_service
from app.services.numeric_alias_query import build_numeric_sql
from . import common

class KiCadLibrary:
    """Encapsulates querying and introspection for kicad_symbols.db."""

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path

    @property
    def db_path(self) -> Path:
        if self._db_path is not None:
            return self._db_path
        return common.get_db_path("KICAD_DB_PATH", common.KICAD_DB_PATH)

    def get_libraries(self) -> List[str]:
        conn = common.get_connection(self.db_path)
        if not conn:
            return []
        try:
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT library FROM kicad_symbols ORDER BY library")
            return [r[0] for r in cur.fetchall()]
        finally:
            conn.close()


    def search(
        self,
        query: str = "",
        library: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        conn = common.get_connection(self.db_path)
        if not conn:
            return {"items": [], "total": 0, "page": page, "page_size": page_size, "total_pages": 0}

        if limit is not None:
            page_size = limit

        page = max(1, page)
        page_size = max(1, min(200, page_size))
        offset = (page - 1) * page_size

        cur = conn.cursor()
        conditions = []
        params = []

        q = (query or "").strip()
        query_terms = search_alias_service.expand_query(q, "kicad")
        q = query_terms[0] if query_terms else q
        alias_keys = search_alias_service.record_keys_for_query("kicad", q)
        text_fields = search_alias_service.searchable_fields("kicad")
        numeric = build_numeric_sql(conn, "kicad", q, text_fields, "id")
        original_match = "(" + " OR ".join(f"{field} LIKE ?" for field in text_fields) + ")"
        original_params = [f"%{q}%"] * len(text_fields) if q else []
        if q:
            term_matches = []
            for term in query_terms:
                term_matches.append("(" + " OR ".join(f"{field} LIKE ?" for field in text_fields) + ")")
                params.extend([f"%{term}%"] * len(text_fields))
            for key in alias_keys:
                alias_library, separator, name = key.partition("|")
                if separator:
                    term_matches.append("(lower(library) = lower(?) AND lower(name) = lower(?))")
                    params.extend([alias_library, name])
            if numeric:
                numeric_condition, numeric_params = numeric.positional(numeric.condition)
                conditions.append(numeric_condition)
                params = numeric_params
            else:
                conditions.append("(" + " OR ".join(term_matches) + ")")

        if library:
            conditions.append("library = ?")
            params.append(library)

        where_sql = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        # Count
        cur.execute(f"SELECT count(*) FROM kicad_symbols{where_sql}", params)
        total = cur.fetchone()[0]

        # Data (omitting heavy raw_sexpr in list view for performance)
        relevance_order = f"CASE WHEN {original_match} THEN 0 ELSE 1 END, library, name" if q else "library, name"
        if numeric:
            numeric_exact, exact_params = numeric.positional(numeric.exact)
            relevance_order = (
                "CASE WHEN lower(name)=lower(?) THEN 0 "
                f"WHEN {numeric_exact} THEN 1 WHEN {original_match} THEN 2 ELSE 3 END, library, name"
            )
            original_params = [q] + exact_params + original_params
        sql = f"""
        SELECT id, library, name, extends, reference, value, footprint,
               datasheet, description, keywords, fp_filters, in_bom, on_board,
               properties_json, source_file
        FROM kicad_symbols
        {where_sql}
        ORDER BY {relevance_order}
        LIMIT ? OFFSET ?
        """
        cur.execute(sql, params + original_params + [page_size, offset])
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        for r in rows:
            if r.get("properties_json"):
                try:
                    r["properties"] = json.loads(r["properties_json"])
                except Exception:
                    r["properties"] = {}
            else:
                r["properties"] = {}

        total_pages = math.ceil(total / page_size) if total > 0 else 1
        return {
            "items": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages
        }


    def get_symbol(self, symbol_id: int) -> Optional[Dict[str, Any]]:
        conn = common.get_connection(self.db_path)
        if not conn:
            return None
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM kicad_symbols WHERE id = ?", (symbol_id,))
            row = cur.fetchone()
            if not row:
                return None
            item = dict(row)
            if item.get("properties_json"):
                try:
                    item["properties"] = json.loads(item["properties_json"])
                except Exception:
                    item["properties"] = {}
            else:
                item["properties"] = {}
            return item
        finally:
            conn.close()




kicad_library = KiCadLibrary()
