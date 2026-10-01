"""Combine indexed electrical equivalence with the existing text alias search."""

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Tuple

from app.services import search_alias_service as aliases
from app.services.electrical_value_service import (
    Measurement, measurements_for_record, normalize_value_text, parse_measurements,
)
from app.services.numeric_alias_index import aliases_for_ids, prepare_numeric_aliases


@dataclass(frozen=True)
class NumericQuery:
    quantities: Tuple[Measurement, ...]
    keywords: Tuple[str, ...]
    text: str = ""


@dataclass
class NumericSql:
    condition: str
    exact: str
    params: Dict[str, Any]

    def positional(self, expression: str) -> Tuple[str, list]:
        values = []

        def replace(match):
            values.append(self.params[match.group(1)])
            return "?"

        return re.sub(r":(numeric_\w+)", replace, expression), values


def parse_numeric_query(query: str) -> Optional[NumericQuery]:
    text = normalize_value_text(query)
    quantities = parse_measurements(text)
    if not quantities:
        return None
    parts = []
    start = 0
    for quantity in quantities:
        parts.append(text[start:quantity.start])
        start = quantity.end
    parts.append(text[start:])
    return NumericQuery(quantities, tuple(" ".join(parts).split()), query)


def text_forms(quantity: Measurement) -> Tuple[str, ...]:
    compact = re.sub(r"\s+", "", quantity.text)
    return tuple(dict.fromkeys((quantity.text, compact,
                               compact.replace("u", "µ"), compact.replace("u", "μ"))))


def build_numeric_sql(conn, source: str, query: str, fields: Iterable[str], identity: str) -> Optional[NumericSql]:
    parsed = parse_numeric_query(query)
    if parsed is None:
        return None
    indexed = prepare_numeric_aliases(conn, source)
    params = {}
    fields = tuple(fields)

    def bind(value):
        name = f"numeric_{len(params)}"
        params[name] = value
        return f":{name}"

    def text_condition(terms):
        expressions = []
        for term in terms:
            placeholder = bind(f"%{term}%")
            expressions.extend(f"{field} LIKE {placeholder}" for field in fields)
        return "(" + " OR ".join(expressions) + ")" if expressions else "0"

    conditions, exact_matches = [], []
    for quantity in parsed.quantities:
        if indexed:
            kind, value = bind(quantity.kind), bind(quantity.value)
            exact = (f"{identity} IN (SELECT record_id FROM numeric_search_aliases "
                     f"WHERE kind={kind} AND value={value})")
        else:
            exact = "0"
        exact_matches.append(exact)
        conditions.append(f"({exact} OR {text_condition(text_forms(quantity))})")
    for keyword in parsed.keywords:
        text = text_condition(aliases.expand_query(keyword, source))
        curated = []
        for key in aliases.record_keys_matching_text(source, keyword):
            if source == "jlcparts" and str(key).isdigit():
                curated.append(f"{identity}={bind(int(key))}")
            elif source == "altium":
                source_file, separator, reference = key.partition("|")
                if separator:
                    curated.append(f"(lower(source_file)=lower({bind(source_file)}) AND "
                                   f"lower(lib_reference)=lower({bind(reference)}))")
            elif source == "kicad":
                library, separator, name = key.partition("|")
                if separator:
                    curated.append(f"(lower(library)=lower({bind(library)}) AND "
                                   f"lower(name)=lower({bind(name)}))")
        conditions.append("(" + " OR ".join([text, *curated]) + ")")
    return NumericSql("(" + " AND ".join(conditions) + ")",
                      "(" + " AND ".join(exact_matches) + ")", params)


def inventory_measurements(records: Iterable[Dict[str, Any]], paths: Dict[str, Any]) -> Dict[int, set]:
    """Batch linked-library lookups instead of hydrating every external record."""
    import sqlite3

    records = list(records)
    result = {}
    for record in records:
        result[record.get("id")] = set(measurements_for_record(
            "inventory", record, aliases.record_curated_aliases("inventory", record)
        ))
    for source, path in paths.items():
        if not path.exists():
            continue
        linked = []
        for record in records:
            if record.get("library_source") != source:
                continue
            external_id = str(record.get("external_part_id", "")).strip()
            if source == "jlcparts":
                external_id = re.sub(r"^[Cc]", "", external_id)
            if external_id.isdigit():
                linked.append((record, int(external_id)))
        if not linked:
            continue
        conn = sqlite3.connect(path, timeout=30)
        try:
            if not prepare_numeric_aliases(conn, source):
                continue
            found = aliases_for_ids(conn, (identity for _, identity in linked))
            for record, identity in linked:
                result[record.get("id")].update(found.get(identity, ()))
        finally:
            conn.close()
    return result


def inventory_match_rank(parsed: NumericQuery, record: Dict[str, Any], quantities: set) -> Optional[int]:
    native = aliases.native_aliases_for_record("inventory", record)
    curated = aliases.record_curated_aliases("inventory", record)
    texts = [aliases.normalize_alias_text(text) for text in (*native, *curated)]
    all_exact = True
    for quantity in parsed.quantities:
        exact = (quantity.kind, quantity.value) in quantities
        all_exact = all_exact and exact
        fuzzy = any(aliases.normalize_alias_text(form) in text
                    for form in text_forms(quantity) for text in texts)
        if not exact and not fuzzy:
            return None
    for keyword in parsed.keywords:
        if not any(aliases.normalize_alias_text(term) in text
                   for term in aliases.expand_query(keyword, "inventory") for text in texts):
            return None
    if record.get("name") and aliases.normalize_alias_text(record["name"]) == aliases.normalize_alias_text(parsed.text):
        return 0
    return 1 if all_exact else 2
