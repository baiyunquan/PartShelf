"""JLCParts Database service module."""

import math
import json
import re
from pathlib import Path
from typing import Optional, Dict, Any, List

from app.i18n.category_i18n import category_i18n
from app.services import component_search_service, search_alias_service
from app.services.numeric_alias_index import prepare_numeric_aliases
from app.services.numeric_alias_query import build_numeric_sql, parse_numeric_query
from . import common
from .common import STATIC_PARTS_DIR

class JLCPartsLibrary:
    """Encapsulates querying and introspection for jlcparts.db."""

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path

    @property
    def db_path(self) -> Path:
        if self._db_path is not None:
            return self._db_path
        return common.get_db_path("JLCPARTS_DB_PATH", common.JLCPARTS_DB_PATH)

    def get_categories(self, lang: str = "zh") -> List[Dict[str, Any]]:
        conn = common.get_connection(self.db_path)
        if not conn:
            return []
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT category, subcategory, count(*) as cnt
                FROM jlc_components
                WHERE category != ''
                GROUP BY category, subcategory
                ORDER BY category, subcategory
            """)
            rows = cur.fetchall()
            result = {}
            for r in rows:
                cat = r["category"]
                subcat = r["subcategory"]
                cnt = r["cnt"]
                if cat not in result:
                    result[cat] = {
                        "category": cat,
                        "category_localized": category_i18n.translate_primary(cat, lang),
                        "subcategories": []
                    }
                if subcat:
                    result[cat]["subcategories"].append({
                        "subcategory": subcat,
                        "subcategory_localized": category_i18n.translate_secondary(subcat, lang),
                        "count": cnt
                    })
            return list(result.values())
        finally:
            conn.close()


    def parse_prices(self, price_str: Optional[str]) -> List[Dict[str, Any]]:
        if not price_str:
            return []
        breaks = []
        # format: "1-9:1.5179,10-11:1.5179,12-199:1.5179,200-499:0.6069,500-999:0.5857,1000-:0.576"
        for part in price_str.split(","):
            part = part.strip()
            if ":" in part:
                qty_range, unit_price = part.split(":", 1)
                breaks.append({"range": qty_range.strip(), "price": unit_price.strip()})
        return breaks


    def extract_specs(self, category: str, subcategory: str, attrs_dict: Dict[str, Any], description: Optional[str] = "") -> str:
        """
        Extracts up to 3 most important technical parameters (e.g. Capacitance, Tolerance, Voltage)
        for JLCPCB/LCSC components based on component category.
        """
        if not attrs_dict and not description:
            return "-"

        cat_lower = f"{category or ''} {subcategory or ''}".lower()
        specs = []

        # 1. Targeted priority attributes by category
        if "capacitor" in cat_lower:
            for k in ["Capacitance", "Tolerance", "Voltage Rating"]:
                if attrs_dict.get(k):
                    specs.append(str(attrs_dict[k]))
        elif "resistor" in cat_lower:
            for k in ["Resistance", "Tolerance", "Power(Watts)"]:
                if attrs_dict.get(k):
                    specs.append(str(attrs_dict[k]))
        elif "inductor" in cat_lower or "choke" in cat_lower:
            for k in ["Inductance", "Tolerance", "Current Rating", "DC Resistance(DCR)"]:
                if attrs_dict.get(k) and len(specs) < 3:
                    specs.append(str(attrs_dict[k]))
        elif "diode" in cat_lower:
            for k in ["Zener Voltage(Range)", "Forward Voltage (Vf)", "Current - Average Rectified (Io)", "Pd - Power Dissipation"]:
                if attrs_dict.get(k) and len(specs) < 3:
                    specs.append(str(attrs_dict[k]))
        elif "mosfet" in cat_lower or "transistor" in cat_lower or "bjt" in cat_lower:
            for k in ["Drain to Source Voltage", "Collector - Emitter Voltage VCEO", "Current - Continuous Drain(Id)", "Current - Collector(Ic)", "RDS(on)", "type"]:
                if attrs_dict.get(k) and len(specs) < 3:
                    specs.append(str(attrs_dict[k]))
        elif "crystal" in cat_lower or "oscillator" in cat_lower:
            for k in ["Frequency", "Frequency Tolerance", "Load Capacitance"]:
                if attrs_dict.get(k) and len(specs) < 3:
                    specs.append(str(attrs_dict[k]))
        elif "fuse" in cat_lower:
            for k in ["Current Rating", "Voltage Rating", "Response Time"]:
                if attrs_dict.get(k) and len(specs) < 3:
                    specs.append(str(attrs_dict[k]))
        elif "led" in cat_lower:
            for k in ["Emitted Color", "Dominant Wavelength", "Forward Voltage (Vf)"]:
                if attrs_dict.get(k) and len(specs) < 3:
                    specs.append(str(attrs_dict[k]))
        elif "linear" in cat_lower or "ldo" in cat_lower or "pmic" in cat_lower:
            for k in ["Output Voltage", "Output Current", "Input Voltage"]:
                if attrs_dict.get(k) and len(specs) < 3:
                    specs.append(str(attrs_dict[k]))

        # 2. If priority mappings didn't get 3, check generic important keys
        if len(specs) < 3:
            generic_keys = [
                "Capacitance", "Resistance", "Inductance", "Voltage Rating", "Tolerance", 
                "Power(Watts)", "Current Rating", "Frequency", "Operating Temperature", "Type"
            ]
            for k in generic_keys:
                if k in attrs_dict and str(attrs_dict[k]) not in specs:
                    specs.append(str(attrs_dict[k]))
                    if len(specs) >= 3:
                        break

        # 3. Fallback to remaining non-boilerplate attributes
        if len(specs) < 3:
            for k, v in attrs_dict.items():
                val_str = str(v)
                if k not in ["RoHS", "Package", "Lifecycle Status"] and val_str not in specs and len(val_str) < 30:
                    specs.append(val_str)
                    if len(specs) >= 3:
                        break

        if specs:
            return ", ".join(specs[:3])
        return (description[:35] + "...") if description and len(description) > 35 else (description or "-")


    def _numeric_component_priority_sql(self, parsed_query) -> str:
        """Prefer primary passive categories and then non-chip records for C/R/L values."""
        if not parsed_query:
            return "0"
        category_terms = {
            "capacitance": ("capacitor", "capacitors"),
            "resistance": ("resistor", "resistors"),
            "inductance": ("inductor", "inductors"),
        }
        passive_matches = []
        for kind in {quantity.kind for quantity in parsed_query.quantities}:
            for term in category_terms.get(kind, ()):
                passive_matches.extend((
                    f"lower(coalesce(j.category, '')) LIKE '%{term}%'",
                    f"lower(coalesce(j.subcategory, '')) LIKE '%{term}%'",
                ))
        if not passive_matches:
            return "0"
        chip_terms = (
            "integrated circuit", "power management", "pmic", "interface", "memory",
            "logic", "processor", "controller", "motor driver", "amplifier",
            "comparator", "rf and wireless", "data acquisition", "clock/timing",
            "signal isolation", "optoisolator",
        )
        chip_matches = []
        for term in chip_terms:
            chip_matches.extend((
                f"lower(coalesce(j.category, '')) LIKE '%{term}%'",
                f"lower(coalesce(j.subcategory, '')) LIKE '%{term}%'",
            ))
        return "CASE WHEN " + " OR ".join(passive_matches) + " THEN 0 " \
               "WHEN " + " OR ".join(chip_matches) + " THEN 2 ELSE 1 END"


    def search(
        self,
        query: str = "",
        category: Optional[str] = None,
        subcategory: Optional[str] = None,
        package: Optional[str] = None,
        library_type: Optional[str] = None,
        in_stock_only: bool = False,
        page: int = 1,
        page_size: int = 50,
        limit: Optional[int] = None,
        lang: str = "zh"
    ) -> Dict[str, Any]:
        if limit is not None:
            page_size = limit

        page = max(1, page)
        page_size = max(1, min(200, page_size))
        offset = (page - 1) * page_size
        q = (query or "").strip()
        query_terms = search_alias_service.expand_query(q, "jlcparts") if q else ()
        q = query_terms[0] if query_terms else q

        conn = common.get_connection(self.db_path)
        if not conn:
            return self._search_dynamic_lcsc_only(
                q, category, subcategory, package, library_type, in_stock_only,
                page, page_size, lang
            )

        cur = conn.cursor()
        conditions = []
        params = {}
        code_query = False

        capacitance = None
        alias_keys = search_alias_service.record_keys_for_query("jlcparts", q) if q else ()
        jlc_search_fields = tuple(
            f"j.{field}" for field in search_alias_service.searchable_fields("jlcparts")
        ) + ("('C' || j.lcsc)",)
        parsed_numeric_query = parse_numeric_query(q)
        numeric = build_numeric_sql(conn, "jlcparts", q, jlc_search_fields, "j.lcsc")
        component_priority_sql = self._numeric_component_priority_sql(parsed_numeric_query)
        if numeric:
            params.update(numeric.params)
        alias_lcsc_codes = []
        for key in alias_keys:
            normalized_code = re.sub(r"^c", "", str(key).strip(), flags=re.IGNORECASE)
            if normalized_code.isdigit():
                alias_lcsc_codes.append(int(normalized_code))
        alias_lcsc_codes = list(dict.fromkeys(alias_lcsc_codes))
        for index, lcsc in enumerate(alias_lcsc_codes):
            params[f"alias_lcsc_{index}"] = lcsc

        capacitance_sql = (
            "CASE WHEN j.attributes LIKE :capacitance_hint AND json_valid(j.attributes) THEN "
            "lower(replace(replace(replace(json_extract(j.attributes, '$.Capacitance'), "
            "' ', ''), 'µ', 'u'), 'μ', 'u')) END"
        )
        if q:
            params.update(query_lower=q.lower(), like=f"%{q}%", prefix=f"{q}%", code=None)
            capacitance_match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([pnumµμ]?)f", q, re.IGNORECASE)
            if capacitance_match:
                unit = capacitance_match.group(2).lower().replace("µ", "u").replace("μ", "u")
                capacitance = f"{capacitance_match.group(1)}{unit}f"
                params.update(
                    capacitance=capacitance,
                    query_lower=capacitance,
                    like=f"%{capacitance}%",
                    prefix=f"{capacitance}%",
                )
                unit_hint = "" if unit == "u" else unit
                params["capacitance_hint"] = f"%{capacitance_match.group(1)}%{unit_hint}f%"

            # Check if user entered LCSC code e.g. "C12345" or "12345"
            if q.upper().startswith("C") and q[1:].isdigit():
                params["code"] = int(q[1:])
                code_query = True
            elif q.isdigit():
                params["code"] = int(q)
                code_query = True
            else:
                matches = [f"{field} LIKE :like" for field in jlc_search_fields]
                if capacitance is not None:
                    matches.append(f"{capacitance_sql} = :capacitance")
                for index, term in enumerate(query_terms[1:], start=1):
                    parameter_name = f"alias_like_{index}"
                    params[parameter_name] = f"%{term}%"
                    matches.extend(f"{field} LIKE :{parameter_name}" for field in jlc_search_fields)
                if alias_lcsc_codes:
                    target_names = [f":alias_lcsc_{index}" for index in range(len(alias_lcsc_codes))]
                    matches.append("j.lcsc IN (" + ", ".join(target_names) + ")")
                conditions.append(numeric.condition if numeric else "(" + " OR ".join(matches) + ")")

        if category:
            conditions.append("j.category = :category")
            params["category"] = category

        if subcategory:
            conditions.append("j.subcategory = :subcategory")
            params["subcategory"] = subcategory

        if package:
            conditions.append("j.package = :package")
            params["package"] = package

        if library_type:
            if library_type == "no_fee":
                conditions.append("(j.library_type = 'base' OR j.preferred = 1)")
            elif library_type == "expand":
                conditions.append("(j.library_type = 'expand' AND j.preferred = 0)")
            else:
                conditions.append("j.library_type = :library_type")
                params["library_type"] = library_type

        if in_stock_only:
            conditions.append("j.stock > 0")

        where_sql = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        if code_query:
            # The model index covers the broad code search; fetch full rows only
            # for matching IDs instead of scanning every large component record.
            hit_queries = [
                "SELECT lcsc FROM jlc_components WHERE mfr LIKE :like",
                "SELECT lcsc FROM jlc_components WHERE lcsc = :code",
            ]
            if alias_lcsc_codes:
                target_names = [f":alias_lcsc_{index}" for index in range(len(alias_lcsc_codes))]
                hit_queries.append(
                    "SELECT lcsc FROM jlc_components WHERE lcsc IN (" + ", ".join(target_names) + ")"
                )
            hits_sql = "hits AS (" + " UNION ".join(hit_queries) + ")"
            candidate_from = "FROM hits h JOIN jlc_components j ON j.lcsc = h.lcsc"
        else:
            hits_sql = ""
            candidate_from = "FROM jlc_components j"

        if q:
            rank = ["WHEN j.lcsc = :code OR lower(j.mfr) = :query_lower THEN 0"]
            if numeric:
                rank.append(f"WHEN {numeric.exact} THEN 1")
            elif capacitance is not None:
                rank.append(f"WHEN {capacitance_sql} = :capacitance THEN 1")
            rank.extend([
                "WHEN lower(j.mfr) LIKE lower(:prefix) THEN 2",
                "WHEN lower(j.mfr) LIKE lower(:like) THEN 3",
            ])
            original_field_matches = " OR ".join(f"{field} LIKE :like" for field in jlc_search_fields)
            rank.append("WHEN (" + original_field_matches + ") THEN 4")
            alias_rank_matches = []
            for index in range(1, len(query_terms)):
                parameter_name = f"alias_like_{index}"
                alias_rank_matches.extend(f"{field} LIKE :{parameter_name}" for field in jlc_search_fields)
            if alias_lcsc_codes:
                alias_rank_matches.extend(
                    f"j.lcsc = :alias_lcsc_{index}"
                    for index in range(len(alias_lcsc_codes))
                )
            if alias_rank_matches:
                rank.append("WHEN (" + " OR ".join(alias_rank_matches) + ") THEN 5")
            rank_sql = "CASE " + " ".join(rank) + " ELSE 6 END"
        else:
            # Preserve the stock-first listing when there is no search term.
            cur.execute(f"SELECT count(*) FROM jlc_components j{where_sql}", params)
            total = cur.fetchone()[0]

        row_columns = """
            j.lcsc, j.category, j.subcategory, j.mfr, j.package, j.joints,
            j.manufacturer, j.library_type, j.preferred, j.stock, j.price,
            j.description, j.datasheet, j.attributes, j.rohs, l.image, l.url_slug
        """
        if q:
            # Rank and paginate narrow rows before loading attributes and joined data.
            ranked_prefix = f"{hits_sql}, " if code_query else ""
            sql = f"""
            WITH {ranked_prefix} ranked AS (
                SELECT j.lcsc, j.stock, j.preferred, {rank_sql} AS relevance,
                       {component_priority_sql} AS component_priority,
                       count(*) OVER() AS search_total
                {candidate_from}
                {where_sql}
                ORDER BY relevance, component_priority, j.stock DESC, j.preferred DESC, j.lcsc ASC
                LIMIT :page_size OFFSET :offset
            )
            SELECT {row_columns}, ranked.search_total
            FROM ranked
            JOIN jlc_components j ON j.lcsc = ranked.lcsc
            LEFT JOIN lcsc_components l ON j.lcsc = l.lcsc
            ORDER BY ranked.relevance, ranked.component_priority, ranked.stock DESC,
                     ranked.preferred DESC, ranked.lcsc ASC
            """
        else:
            sql = f"""
            SELECT {row_columns}
            FROM jlc_components j
            LEFT JOIN lcsc_components l ON j.lcsc = l.lcsc
            {where_sql}
            ORDER BY j.stock DESC, j.preferred DESC, j.lcsc ASC
            LIMIT :page_size OFFSET :offset
            """
        cur.execute(sql, {**params, "page_size": page_size, "offset": offset})
        rows = [dict(r) for r in cur.fetchall()]
        if q:
            if rows:
                total = rows[0]["search_total"]
                for row in rows:
                    row.pop("search_total")
            else:
                # A page beyond the last match still reports the full match count.
                count_prefix = f"WITH {hits_sql}" if code_query else ""
                cur.execute(f"{count_prefix} SELECT count(*) {candidate_from}{where_sql}", params)
                total = cur.fetchone()[0]
        conn.close()

        dynamic_item = component_search_service.resolve_search_lcsc_query(q)
        if dynamic_item:
            if self._dynamic_component_matches_filters(
                dynamic_item, category, subcategory, package, library_type, in_stock_only
            ):
                total = 1
                rows = [dynamic_item] if page == 1 else []
            else:
                total = 0
                rows = []

        for r in rows:
            if r.get("library_type") == "lcsc_dynamic":
                r["source"] = "lcsc_dynamic"
            r["category_localized"] = category_i18n.translate_primary(r.get("category") or "", lang)
            r["subcategory_localized"] = category_i18n.translate_secondary(r.get("subcategory") or "", lang)
            # Build image URLs
            if r.get("image"):
                img_file = r["image"]
                if (STATIC_PARTS_DIR / img_file).exists():
                    r["image_url_small"] = f"/static/images/parts/{img_file}"
                    r["image_url_medium"] = f"/static/images/parts/{img_file}"
                else:
                    r["image_url_small"] = f"https://assets.lcsc.com/images/lcsc/96x96/{img_file}"
                    r["image_url_medium"] = f"https://assets.lcsc.com/images/lcsc/224x224/{img_file}"
                r["image_url_large"] = f"https://assets.lcsc.com/images/lcsc/900x900/{img_file}"
            else:
                r["image_url_small"] = None
                r["image_url_medium"] = None
                r["image_url_large"] = None

            if r.get("attributes"):
                try:
                    r["attributes_dict"] = json.loads(r["attributes"])
                except Exception:
                    r["attributes_dict"] = {}
            else:
                r["attributes_dict"] = {}

            r["specs"] = self.extract_specs(
                r.get("category") or "",
                r.get("subcategory") or "",
                r.get("attributes_dict") or {},
                r.get("description")
            )

            r["price_breaks"] = self.parse_prices(r.get("price"))

        total_pages = math.ceil(total / page_size) if total > 0 else 1
        return {
            "items": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages
        }


    def _dynamic_component_matches_filters(
        self,
        item: Dict[str, Any],
        category: Optional[str],
        subcategory: Optional[str],
        package: Optional[str],
        library_type: Optional[str],
        in_stock_only: bool,
    ) -> bool:
        if category and item.get("category") != category:
            return False
        if subcategory and item.get("subcategory") != subcategory:
            return False
        if package and item.get("package") != package:
            return False
        if in_stock_only and item.get("stock", -1) <= 0:
            return False
        if library_type:
            if library_type == "no_fee":
                return False
            if library_type not in ("lcsc_dynamic",):
                return False
        return True


    def _search_dynamic_lcsc_only(
        self,
        query: str,
        category: Optional[str],
        subcategory: Optional[str],
        package: Optional[str],
        library_type: Optional[str],
        in_stock_only: bool,
        page: int,
        page_size: int,
        lang: str,
    ) -> Dict[str, Any]:
        item = component_search_service.resolve_search_lcsc_query(query)
        if item and self._dynamic_component_matches_filters(
            item, category, subcategory, package, library_type, in_stock_only
        ):
            item["category_localized"] = category_i18n.translate_primary(
                item.get("category") or "", lang
            )
            item["subcategory_localized"] = category_i18n.translate_secondary(
                item.get("subcategory") or "", lang
            )
            image = item.get("image")
            if image:
                item["image_url_small"] = f"https://assets.lcsc.com/images/lcsc/96x96/{image}"
                item["image_url_medium"] = f"https://assets.lcsc.com/images/lcsc/224x224/{image}"
                item["image_url_large"] = f"https://assets.lcsc.com/images/lcsc/900x900/{image}"
            else:
                item["image_url_small"] = None
                item["image_url_medium"] = None
                item["image_url_large"] = None
            try:
                item["attributes_dict"] = json.loads(item.get("attributes") or "{}")
            except (TypeError, json.JSONDecodeError):
                item["attributes_dict"] = {}
            item["specs"] = self.extract_specs(
                item.get("category") or "",
                item.get("subcategory") or "",
                item["attributes_dict"],
                item.get("description"),
            )
            item["price_breaks"] = self.parse_prices(item.get("price"))
            items = [item] if page == 1 else []
            total = 1
        else:
            items = []
            total = 0
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": math.ceil(total / page_size) if total > 0 else 0,
        }


    def get_component(self, lcsc: int, lang: str = "zh") -> Optional[Dict[str, Any]]:
        item = component_search_service.resolve_exact_lcsc_component(lcsc)
        if item is None:
            return None
        if item.get("library_type") == "lcsc_dynamic":
            item["source"] = "lcsc_dynamic"

        item["category_localized"] = category_i18n.translate_primary(item.get("category") or "", lang)
        item["subcategory_localized"] = category_i18n.translate_secondary(item.get("subcategory") or "", lang)

        if item.get("image"):
            img_file = item["image"]
            if (STATIC_PARTS_DIR / img_file).exists():
                item["image_url_small"] = f"/static/images/parts/{img_file}"
                item["image_url_medium"] = f"/static/images/parts/{img_file}"
            else:
                item["image_url_small"] = f"https://assets.lcsc.com/images/lcsc/96x96/{img_file}"
                item["image_url_medium"] = f"https://assets.lcsc.com/images/lcsc/224x224/{img_file}"
            item["image_url_large"] = f"https://assets.lcsc.com/images/lcsc/900x900/{img_file}"
        else:
            item["image_url_small"] = None
            item["image_url_medium"] = None
            item["image_url_large"] = None

        if item.get("attributes"):
            try:
                item["attributes_dict"] = json.loads(item["attributes"])
            except Exception:
                item["attributes_dict"] = {}
        else:
            item["attributes_dict"] = {}

        if item.get("attrition"):
            try:
                item["attrition_dict"] = json.loads(item["attrition"])
            except Exception:
                item["attrition_dict"] = {}
        else:
            item["attrition_dict"] = {}

        item["specs"] = self.extract_specs(
            item.get("category") or "",
            item.get("subcategory") or "",
            item.get("attributes_dict") or {},
            item.get("description")
        )

        item["price_breaks"] = self.parse_prices(item.get("price"))
        if not item.get("lcsc_url"):
            if item.get("url_slug"):
                item["lcsc_url"] = f"https://www.lcsc.com/product-detail/{item['url_slug']}_C{item['lcsc']}.html"
            else:
                item["lcsc_url"] = f"https://www.lcsc.com/search?q=C{item['lcsc']}"

        return item




jlcparts_library = JLCPartsLibrary()
