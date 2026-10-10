"""Fasteners and Mechanical Standards database service module."""

import math
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from app.i18n.fastener_aliases import (
    aliases_for_standard,
    expand_fastener_query,
    localized_standard_name,
)
from app.services import search_alias_service
from . import common



FASTENER_DOMAINS = [
    {"domain": "fasteners", "name_zh": "紧固件", "name_en": "Fasteners"},
    {"domain": "power_transmission", "name_zh": "动力传动", "name_en": "Power Transmission"},
    {"domain": "structural_materials", "name_zh": "结构材料/型材", "name_en": "Structural Materials & Profiles"},
]


class FastenersLibrary:
    """Encapsulates querying, standard details, and custom specs for fasteners.db."""

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path

    @property
    def db_path(self) -> Path:
        if self._db_path is not None:
            return self._db_path
        return common.get_db_path("FASTENERS_DB_PATH", common.FASTENERS_DB_PATH)

    def get_domains(self) -> List[Dict[str, Any]]:
        """Returns domain groups (Fasteners, Power Transmission, Structural Materials) with counts."""
        conn = common.get_connection(self.db_path)
        if not conn:
            return []
        try:
            cur = conn.cursor()
            cur.execute("SELECT domain, count(*) as count FROM fastener_standards GROUP BY domain")
            counts = {row["domain"]: row["count"] for row in cur.fetchall()}
            res = []
            for d in FASTENER_DOMAINS:
                res.append({
                    "domain": d["domain"],
                    "name_zh": d["name_zh"],
                    "name_en": d["name_en"],
                    "count": counts.get(d["domain"], 0)
                })
            return res
        finally:
            conn.close()


    def get_categories(self, domain: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns all category groups with counts from fasteners.db, optionally filtered by domain."""
        conn = common.get_connection(self.db_path)
        if not conn:
            return []
        try:
            cur = conn.cursor()
            if domain and domain != "all":
                cur.execute("""
                    SELECT domain, category_group, category_group_zh, count(*) as count
                    FROM fastener_standards
                    WHERE domain = ?
                    GROUP BY domain, category_group, category_group_zh
                    ORDER BY count DESC
                """, (domain,))
            else:
                cur.execute("""
                    SELECT domain, category_group, category_group_zh, count(*) as count
                    FROM fastener_standards
                    GROUP BY domain, category_group, category_group_zh
                    ORDER BY domain ASC, count DESC
                """)
            return [
                {
                    "domain": row["domain"],
                    "group": row["category_group"],
                    "group_zh": row["category_group_zh"],
                    "count": row["count"]
                }
                for row in cur.fetchall()
            ]
        finally:
            conn.close()


    def get_authorities(self) -> List[Dict[str, Any]]:
        """Returns all standard authorities (ISO, DIN, ASME, JIS, KS, etc.) with counts."""
        conn = common.get_connection(self.db_path)
        if not conn:
            return []
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT authority, count(*) as count
                FROM fastener_standards
                GROUP BY authority
                ORDER BY count DESC
            """)
            return [
                {
                    "authority": row["authority"],
                    "count": row["count"]
                }
                for row in cur.fetchall()
            ]
        finally:
            conn.close()


    def query(
        self,
        page: int = 1,
        page_size: int = 25,
        query: Optional[str] = None,
        category: Optional[str] = None,
        authority: Optional[str] = None,
        domain: Optional[str] = None,
        lang: str = "zh"
    ) -> Dict[str, Any]:
        """
        Search and page fastener / mechanical standards from fasteners.db.
        Supports filtering by domain (fasteners, power_transmission, structural_materials).
        """
        conn = common.get_connection(self.db_path)
        if not conn:
            return {"items": [], "total": 0, "page": page, "page_size": page_size, "total_pages": 0}

        try:
            cur = conn.cursor()
            where_clauses = []
            params = []
            fastener_search_fields = search_alias_service.searchable_fields("fasteners")

            if domain and domain != "all":
                where_clauses.append("domain = ?")
                params.append(domain)

            if query:
                q_clean = query.strip()
                query_terms = search_alias_service.expand_query(q_clean, "fasteners")
                q_clean = query_terms[0] if query_terms else q_clean
                alias_codes = expand_fastener_query(q_clean)
                term_matches = []
                for term in query_terms:
                    term_param = f"%{term}%"
                    text_match = " OR ".join(f"{field} LIKE ?" for field in fastener_search_fields)
                    term_matches.append(
                        f"({text_match} OR param_table_name IN ("
                        "SELECT DISTINCT table_name FROM fastener_tables WHERE row_key = ? OR row_key LIKE ?))"
                    )
                    params.extend([term_param] * len(fastener_search_fields) + [term, term_param])
                if alias_codes:
                    term_matches.append("standard_code IN (" + ", ".join("?" for _ in alias_codes) + ")")
                    params.extend(alias_codes)
                where_clauses.append("(" + " OR ".join(term_matches) + ")")

            if category and category != "all":
                where_clauses.append("(category_group = ? OR category_group_zh = ?)")
                params.extend([category, category])

            if authority and authority != "all":
                where_clauses.append("authority = ?")
                params.append(authority)

            where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

            # Total count
            cur.execute(f"SELECT count(*) FROM fastener_standards{where_sql}", params)
            total = cur.fetchone()[0]

            total_pages = math.ceil(total / page_size) if total > 0 else 1
            page = max(1, min(page, total_pages)) if total > 0 else 1
            offset = (page - 1) * page_size

            if query:
                original_fields = " OR ".join(f"{field} LIKE ?" for field in fastener_search_fields)
                original_match = (
                    f"({original_fields} OR param_table_name IN ("
                    "SELECT DISTINCT table_name FROM fastener_tables WHERE row_key = ? OR row_key LIKE ?))"
                )
                original_rank_params = [f"%{query.strip()}%"] * len(fastener_search_fields)
                original_rank_params.extend([query.strip(), f"%{query.strip()}%"])
                relevance_order = f"CASE WHEN {original_match} THEN 0 ELSE 1 END, domain ASC, authority ASC, standard_code ASC"
            else:
                original_rank_params = []
                relevance_order = "domain ASC, authority ASC, standard_code ASC"

            cur.execute(f"""
                SELECT id, standard_code, standard_name, authority, domain, category_group, category_group_zh,
                       description, param_table_name, length_table_name, has_length, source_file
                FROM fastener_standards
                {where_sql}
                ORDER BY {relevance_order}
                LIMIT ? OFFSET ?
            """, params + original_rank_params + [page_size, offset])

            items = []
            for row in cur.fetchall():
                item = dict(row)
                item["standard_name_localized"] = localized_standard_name(
                    item.get("standard_code"), item.get("standard_name"), lang
                )
                item["search_aliases"] = aliases_for_standard(item.get("standard_code"))
                items.append(item)

            return {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages
            }
        finally:
            conn.close()


    def get_detail(self, standard_code: str, lang: str = "zh") -> Optional[Dict[str, Any]]:
        """
        Returns complete metadata, dimensional parameter matrix, valid length matrix,
        hole drill references, and torque/wrench assembly guidelines for a standard.
        """
        conn = common.get_connection(self.db_path)
        if not conn:
            return None

        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM fastener_standards
                WHERE standard_code = ? OR lower(standard_code) = lower(?)
                LIMIT 1
            """, (standard_code, standard_code))
            std_row = cur.fetchone()
            if not std_row:
                return None

            standard = dict(std_row)
            standard["standard_name_localized"] = localized_standard_name(
                standard.get("standard_code"), standard.get("standard_name"), lang
            )
            standard["search_aliases"] = aliases_for_standard(standard.get("standard_code"))
            param_table = standard.get("param_table_name")
            length_table = standard.get("length_table_name")

            # 1. Fetch param table titles and data
            param_titles = []
            param_rows = []
            if param_table:
                cur.execute("SELECT titles_json FROM fastener_table_titles WHERE table_name = ?", (param_table,))
                t_row = cur.fetchone()
                if t_row:
                    try:
                        param_titles = json.loads(t_row[0])
                    except Exception:
                        param_titles = []

                cur.execute("SELECT row_key, data_json, source_file FROM fastener_tables WHERE table_name = ? ORDER BY id ASC", (param_table,))
                for r in cur.fetchall():
                    try:
                        vals = json.loads(r["data_json"])
                    except Exception:
                        vals = []
                    row_key = r["row_key"]
                    param_rows.append({
                        "nominal": common._custom_nominal_from_row_key(row_key),
                        "row_key": row_key,
                        "source_file": r["source_file"],
                        "is_custom": r["source_file"] == "user",
                        "custom_length": common._custom_length_from_row_key(row_key),
                        "values": vals
                    })

            # 2. Fetch length table titles and data
            length_titles = []
            length_rows = []
            if length_table:
                cur.execute("SELECT titles_json FROM fastener_table_titles WHERE table_name = ?", (length_table,))
                lt_row = cur.fetchone()
                if lt_row:
                    try:
                        length_titles = json.loads(lt_row[0])
                    except Exception:
                        length_titles = []

                cur.execute("SELECT row_key, data_json, source_file FROM fastener_tables WHERE table_name = ? ORDER BY id ASC", (length_table,))
                for r in cur.fetchall():
                    try:
                        vals = json.loads(r["data_json"])
                    except Exception:
                        vals = []
                    length_rows.append({
                        "key": r["row_key"],
                        "row_key": r["row_key"],
                        "source_file": r["source_file"],
                        "is_custom": r["source_file"] == "user",
                        "nominal": common._custom_nominal_from_row_key(r["row_key"]),
                        "custom_length": common._custom_length_from_row_key(r["row_key"]),
                        "lengths": [str(x) for x in vals if str(x).strip()]
                    })
            standard["length_unit"] = "in" if any(
                str(row.get("key", "")).casefold().endswith("in") for row in length_rows
            ) else "mm"

            # 3. Fetch hole chart matching standard if metric
            cur.execute("SELECT nominal_dia, hole_diameter FROM fastener_hole_charts WHERE chart_type = 'metric_tap_hole'")
            tap_holes = {r[0]: r[1] for r in cur.fetchall()}

            # 4. Fetch assembly guides (torque and wrench specifications)
            current_nominals = {r["nominal"].upper().replace(" ", "") for r in param_rows}
            cur.execute("""
                SELECT nominal, stress_area, hex_key, hex_wrench_af, socket_size,
                       preload_8_8, dry_torque_8_8, lube_torque_8_8,
                       preload_10_9, dry_torque_10_9, lube_torque_10_9,
                       preload_12_9, dry_torque_12_9, lube_torque_12_9
                FROM fastener_assembly_guides
                ORDER BY id ASC
            """)
            guide_rows = cur.fetchall()
            assembly_guides = []
            for gr in guide_rows:
                g_dict = dict(gr)
                g_dict["is_current"] = (g_dict["nominal"].upper() in current_nominals)
                assembly_guides.append(g_dict)

            return {
                "standard": standard,
                "param_titles": param_titles,
                "param_rows": param_rows,
                "length_titles": length_titles,
                "length_rows": length_rows,
                "tap_holes": tap_holes,
                "assembly_guides": assembly_guides
            }
        finally:
            conn.close()


    def _parse_positive_number(self, value: Any, field_name: str, *, allow_fraction: bool = False) -> float:
        raw = str(value).strip()
        try:
            if allow_fraction and re.fullmatch(r"\d+\s*/\s*\d+", raw):
                numerator, denominator = (int(part.strip()) for part in raw.split("/", 1))
                if denominator == 0:
                    raise ValueError
                number = numerator / denominator
            else:
                number = float(raw)
        except (TypeError, ValueError, ZeroDivisionError):
            raise ValueError(f"{field_name} must be a finite positive number")
        if not math.isfinite(number) or number <= 0:
            raise ValueError(f"{field_name} must be a finite positive number")
        return number


    def _parse_custom_length(self, value: Any, default_unit: str) -> tuple[str, float]:
        raw = str(value or "").strip().lower().replace("\u00a0", " ")
        explicit_mm = bool(re.search(r"mm$", raw))
        explicit_in = bool(re.search(r"(?:in|inch|\")$", raw))
        cleaned = re.sub(r"(?:mm|inch|in|\")$", "", raw).strip()
        mixed = re.fullmatch(r"(\d+)\s+(\d+)\s*/\s*(\d+)", cleaned)
        fraction = re.fullmatch(r"(\d+)\s*/\s*(\d+)", cleaned)
        try:
            if mixed:
                whole, numerator, denominator = (int(part) for part in mixed.groups())
                if denominator == 0:
                    raise ValueError
                number = whole + numerator / denominator
            elif fraction:
                numerator, denominator = (int(part) for part in fraction.groups())
                if denominator == 0:
                    raise ValueError
                number = numerator / denominator
            else:
                number = float(cleaned)
        except (TypeError, ValueError, ZeroDivisionError):
            raise ValueError("length must be a finite positive number")
        if not math.isfinite(number) or number <= 0:
            raise ValueError("length must be a finite positive number")

        is_inch = explicit_in or (not explicit_mm and default_unit == "in")
        if is_inch:
            if fraction and not mixed:
                length_key = f"{fraction.group(1)}/{fraction.group(2)}in"
            else:
                length_key = f"{format(number, '.12g')}in"
            return length_key, number * 25.4
        return format(number, ".12g"), number


    def append_spec(
        self,
        standard_code: str,
        nominal: str,
        dimensions: Dict[str, Any],
        length: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Append a validated user specification to the selected standard's existing tables."""
        if not isinstance(dimensions, dict):
            raise ValueError("dimensions must be an object")
        nominal = str(nominal or "").strip()
        if not nominal or nominal.startswith("user:"):
            raise ValueError("nominal is required")
        nominal = common._normalize_custom_nominal(nominal)

        conn = common.get_connection(self.db_path)
        if not conn:
            raise ValueError("fasteners database is unavailable")
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT standard_code, param_table_name, length_table_name FROM fastener_standards "
                "WHERE standard_code = ? OR lower(standard_code) = lower(?) LIMIT 1",
                (standard_code, standard_code),
            )
            standard = cur.fetchone()
            if not standard:
                raise ValueError("unknown fastener standard")
            if (str(standard["standard_code"]).casefold() == "iutheatinsert"
                    and not re.fullmatch(r"M\d+(?:\.\d+)?", nominal, re.IGNORECASE)):
                raise ValueError("heat-set insert nominal must be a metric thread size such as M3")
            param_table = standard["param_table_name"]
            if not param_table:
                raise ValueError("standard has no parameter table")
            length_table = standard["length_table_name"]

            cur.execute("SELECT titles_json FROM fastener_table_titles WHERE table_name = ?", (param_table,))
            title_row = cur.fetchone()
            if not title_row:
                raise ValueError("parameter table schema is unavailable")
            titles = json.loads(title_row["titles_json"])
            if not isinstance(titles, list) or not titles:
                raise ValueError("parameter table schema is invalid")

            title_lookup = {str(title).strip().casefold(): str(title) for title in titles}
            supplied = {}
            for key, value in dimensions.items():
                canonical = title_lookup.get(str(key).strip().casefold())
                if canonical is None:
                    raise ValueError(f"unknown dimension field: {key}")
                supplied[canonical] = value

            critical_by_standard = {
                "iutheatinsert": ("Length", "ExtDia"),
            }
            critical = critical_by_standard.get(str(standard["standard_code"]).casefold(), ())
            for title in critical:
                if title not in title_lookup.values() or title not in supplied:
                    raise ValueError(f"required dimension is missing: {title}")

            values = []
            for title in titles:
                value = supplied.get(str(title))
                if value is None or (isinstance(value, str) and not value.strip()):
                    values.append(None)
                    continue
                number = self._parse_positive_number(value, str(title))
                values.append(number)

            for title in critical:
                critical_value = values[titles.index(title)]
                if critical_value is None or critical_value <= 0:
                    raise ValueError(f"{title} must be positive")
            if not any(value is not None for value in values):
                raise ValueError("at least one dimension is required")

            parsed_length = None
            length_key = None
            if length is not None and str(length).strip():
                if not length_table:
                    raise ValueError("standard has no separate length table")
                cur.execute("SELECT row_key FROM fastener_tables WHERE table_name = ?", (length_table,))
                known_lengths = [str(row["row_key"]).casefold() for row in cur.fetchall()]
                default_length_unit = "in" if any(key.endswith("in") for key in known_lengths) else "mm"
                length_key, parsed_length = self._parse_custom_length(length, default_length_unit)
            custom_nominal_key = nominal
            if parsed_length is not None:
                custom_nominal_key = f"{nominal}@{length_key}"
            payload = {
                "standard_code": standard["standard_code"],
                "nominal": custom_nominal_key,
                "values": values,
                "length": parsed_length,
                "length_key": length_key,
            }
            row_key = common._custom_row_key(custom_nominal_key, payload)
            data_json = json.dumps(values, separators=(",", ":"), ensure_ascii=False, allow_nan=False)

            conn.execute("BEGIN IMMEDIATE")
            cur.execute(
                "SELECT data_json, source_file FROM fastener_tables WHERE table_name = ? AND row_key = ?",
                (param_table, row_key),
            )
            existing = cur.fetchone()
            if existing:
                if existing["source_file"] != "user" or json.loads(existing["data_json"]) != values:
                    raise ValueError("custom row key conflicts with existing dimensions")
            else:
                cur.execute(
                    "INSERT INTO fastener_tables (table_name, row_key, data_json, source_file) VALUES (?, ?, ?, 'user')",
                    (param_table, row_key, data_json),
                )

            length_row_key = None
            length_added = False
            if parsed_length is not None:
                cur.execute("SELECT titles_json FROM fastener_table_titles WHERE table_name = ?", (length_table,))
                length_title_row = cur.fetchone()
                if not length_title_row:
                    raise ValueError("length table schema is unavailable")
                length_titles = json.loads(length_title_row["titles_json"])
                simple_key = length_key
                cur.execute(
                    "SELECT row_key, data_json FROM fastener_tables WHERE table_name = ? AND row_key = ?",
                    (length_table, simple_key),
                )
                existing_length = cur.fetchone()
                if existing_length:
                    old_values = json.loads(existing_length["data_json"])
                    low = float(old_values[0]) if old_values else parsed_length
                    high = float(old_values[1]) if len(old_values) > 1 else low
                    if min(low, high) <= parsed_length <= max(low, high):
                        length_row_key = existing_length["row_key"]
                    else:
                        length_row_key = row_key
                else:
                    length_row_key = row_key

                if not existing_length or length_row_key != existing_length["row_key"]:
                    length_values = []
                    for title in length_titles:
                        title_lower = str(title).casefold()
                        if "min" in title_lower:
                            length_values.append(parsed_length)
                        elif "max" in title_lower:
                            length_values.append(parsed_length)
                        else:
                            length_values.append(parsed_length)
                    length_json = json.dumps(length_values, separators=(",", ":"), allow_nan=False)
                    cur.execute(
                        "SELECT data_json, source_file FROM fastener_tables WHERE table_name = ? AND row_key = ?",
                        (length_table, length_row_key),
                    )
                    custom_length_row = cur.fetchone()
                    if custom_length_row:
                        if custom_length_row["source_file"] != "user" or json.loads(custom_length_row["data_json"]) != length_values:
                            raise ValueError("custom length row key conflicts with existing length")
                    else:
                        cur.execute(
                            "INSERT INTO fastener_tables (table_name, row_key, data_json, source_file) VALUES (?, ?, ?, 'user')",
                            (length_table, length_row_key, length_json),
                        )
                        length_added = True

            conn.commit()
            return {
                "standard_code": standard["standard_code"],
                "nominal": nominal,
                "row_key": row_key,
                "source_file": "user",
                "is_custom": True,
                "values": values,
                "length": length_key,
                "length_row_key": length_row_key,
                "length_added": length_added,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


    def get_hole_charts(self, chart_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns drill hole reference chart rows."""
        conn = common.get_connection(self.db_path)
        if not conn:
            return []
        try:
            cur = conn.cursor()
            if chart_type:
                cur.execute(
                    "SELECT chart_type, nominal_dia, hole_diameter FROM fastener_hole_charts WHERE chart_type = ? ORDER BY hole_diameter ASC",
                    (chart_type,)
                )
            else:
                cur.execute(
                    "SELECT chart_type, nominal_dia, hole_diameter FROM fastener_hole_charts ORDER BY chart_type ASC, hole_diameter ASC"
                )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()


    def get_assembly_guides(self, nominal: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns torque specs and tool sizing assembly guidelines."""
        conn = common.get_connection(self.db_path)
        if not conn:
            return []
        try:
            cur = conn.cursor()
            if nominal:
                cur.execute("SELECT * FROM fastener_assembly_guides WHERE nominal = ? OR lower(nominal) = lower(?)", (nominal, nominal))
            else:
                cur.execute("SELECT * FROM fastener_assembly_guides ORDER BY id ASC")
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()


fasteners_library = FastenersLibrary()
