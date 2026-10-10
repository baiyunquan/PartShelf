"""Altium JLCPCB Libraries database service module."""

import math
import json
from pathlib import Path
from typing import Optional, Dict, Any, List

from app.i18n.category_i18n import category_i18n
from app.services import search_alias_service
from app.services.numeric_alias_query import build_numeric_sql
from . import common

class AltiumLibrary:
    """Encapsulates querying and introspection for altium_library.db."""

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path

    @property
    def db_path(self) -> Path:
        if self._db_path is not None:
            return self._db_path
        return common.get_db_path("ALTIUM_DB_PATH", common.ALTIUM_DB_PATH)

    def get_categories(self, lang: str = "zh") -> List[Dict[str, str]]:
        conn = common.get_connection(self.db_path)
        if not conn:
            return []
        try:
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT category FROM altium_components WHERE category != '' ORDER BY category")
            return [
                {"category": r[0], "category_localized": category_i18n.translate_altium(r[0], lang)}
                for r in cur.fetchall()
            ]
        finally:
            conn.close()


    def get_packages(self) -> List[str]:
        conn = common.get_connection(self.db_path)
        if not conn:
            return []
        try:
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT package FROM altium_components WHERE package != '' ORDER BY package LIMIT 200")
            return [r[0] for r in cur.fetchall()]
        finally:
            conn.close()


    def search(
        self,
        query: str = "",
        category: Optional[str] = None,
        package: Optional[str] = None,
        basic_only: Optional[bool] = None,
        page: int = 1,
        page_size: int = 50,
        limit: Optional[int] = None,
        lang: str = "zh"
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
        query_terms = search_alias_service.expand_query(q, "altium")
        q = query_terms[0] if query_terms else q
        alias_keys = search_alias_service.record_keys_for_query("altium", q)
        text_fields = search_alias_service.searchable_fields("altium")
        numeric = build_numeric_sql(conn, "altium", q, (*text_fields, "category"), "id")
        original_match = "(" + " OR ".join(f"{field} LIKE ?" for field in text_fields) + ")"
        original_params = [f"%{q}%"] * len(text_fields) if q else []
        if q:
            term_matches = []
            for term in query_terms:
                term_matches.append("(" + " OR ".join(f"{field} LIKE ?" for field in text_fields) + ")")
                params.extend([f"%{term}%"] * len(text_fields))
            for key in alias_keys:
                source_file, separator, lib_reference = key.partition("|")
                if separator:
                    term_matches.append("(lower(source_file) = lower(?) AND lower(lib_reference) = lower(?))")
                    params.extend([source_file, lib_reference])
            if numeric:
                numeric_condition, numeric_params = numeric.positional(numeric.condition)
                conditions.append(numeric_condition)
                params = numeric_params
            else:
                conditions.append("(" + " OR ".join(term_matches) + ")")

        if category:
            conditions.append("category = ?")
            params.append(category)

        if package:
            conditions.append("package = ?")
            params.append(package)

        if basic_only is True:
            conditions.append("basic_part = 1")
        elif basic_only is False:
            conditions.append("basic_part = 0")

        where_sql = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        # Count
        cur.execute(f"SELECT count(*) FROM altium_components{where_sql}", params)
        total = cur.fetchone()[0]

        # Data
        relevance_order = f"CASE WHEN {original_match} THEN 0 ELSE 1 END, id" if q else "id"
        if numeric:
            numeric_exact, exact_params = numeric.positional(numeric.exact)
            relevance_order = (
                "CASE WHEN lower(lib_reference)=lower(?) OR lower(mfr_part_number)=lower(?) THEN 0 "
                f"WHEN {numeric_exact} THEN 1 WHEN {original_match} THEN 2 ELSE 3 END, id"
            )
            original_params = [q, q] + exact_params + original_params
        sql = f"""
        SELECT id, lib_reference, lcsc_part, category, package, manufacturer,
               mfr_part_number, basic_part, description, resistance, capacitance,
               inductance, tolerance, voltage_rating, power_rating, datasheet_url,
               jlcpcb_url, lcsc_url, parameters_json, source_file
        FROM altium_components
        {where_sql}
        ORDER BY {relevance_order}
        LIMIT ? OFFSET ?
        """
        cur.execute(sql, params + original_params + [page_size, offset])
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        for r in rows:
            r["category_localized"] = category_i18n.translate_altium(r.get("category") or "", lang)
            if r.get("parameters_json"):
                try:
                    r["parameters"] = json.loads(r["parameters_json"])
                except Exception:
                    r["parameters"] = {}
            else:
                r["parameters"] = {}

        total_pages = math.ceil(total / page_size) if total > 0 else 1
        return {
            "items": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages
        }


    def get_component(self, comp_id: int, lang: str = "zh") -> Optional[Dict[str, Any]]:
        conn = common.get_connection(self.db_path)
        if not conn:
            return None
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM altium_components WHERE id = ?", (comp_id,))
            row = cur.fetchone()
            if not row:
                return None
            item = dict(row)
            item["category_localized"] = category_i18n.translate_altium(item.get("category") or "", lang)
            if item.get("parameters_json"):
                try:
                    item["parameters"] = json.loads(item["parameters_json"])
                except Exception:
                    item["parameters"] = {}
            else:
                item["parameters"] = {}

            if item.get("raw_data_json"):
                try:
                    item["raw_data"] = json.loads(item["raw_data_json"])
                except Exception:
                    item["raw_data"] = {}
            else:
                item["raw_data"] = None

            return item
        finally:
            conn.close()




altium_library = AltiumLibrary()
