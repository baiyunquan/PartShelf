"""Shared query expansion and record-alias access for all searchable sources."""

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


ALIAS_CONFIG_PATH = Path(__file__).resolve().parents[1] / "data" / "search_aliases.json"
SEARCH_SOURCES = ("inventory", "jlcparts", "altium", "kicad", "fasteners")
SOURCE_ALIAS_FIELDS = {
    "inventory": (
        "name", "manufacturer", "package", "part_type", "storage_location",
        "note", "external_part_id", "external_details",
    ),
    "jlcparts": (
        "lcsc", "mfr", "manufacturer", "package", "category", "subcategory",
        "description", "attributes", "attributes_dict",
    ),
    "altium": (
        "lib_reference", "lcsc_part", "mfr_part_number", "manufacturer",
        "package", "description", "parameters_json", "parameters",
    ),
    "kicad": (
        "library", "name", "value", "footprint", "datasheet", "keywords",
        "fp_filters", "description", "properties_json", "properties",
    ),
    "fasteners": (
        "standard_code", "standard_name", "category_group", "category_group_zh",
        "description",
    ),
}
SOURCE_DB_SEARCH_FIELDS = {
    "jlcparts": ("mfr", "manufacturer", "package", "category", "subcategory", "description", "attributes"),
    "altium": (
        "lib_reference", "lcsc_part", "mfr_part_number", "manufacturer",
        "package", "description", "parameters_json",
    ),
    "kicad": (
        "library", "name", "value", "footprint", "datasheet", "keywords",
        "description", "fp_filters", "properties_json",
    ),
    "fasteners": ("standard_code", "standard_name", "description", "category_group", "category_group_zh"),
}


def normalize_alias_text(value: Any) -> str:
    """Normalize case, Unicode width, and whitespace for alias comparisons."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(text.casefold().split())


def _flatten_values(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, nested in value.items():
            yield str(key)
            yield from _flatten_values(nested)
    elif isinstance(value, (list, tuple, set)):
        for nested in value:
            yield from _flatten_values(nested)
    elif value is not None:
        text = str(value).strip()
        if text and text.casefold() not in {"none", "null", "n/a"}:
            yield text


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return value
    return value


class SearchAliasRegistry:
    """Loads centrally curated aliases and combines them with source-native fields."""

    def __init__(self, config: Dict[str, Any]):
        self.max_query_variants = max(1, min(16, int(config.get("max_query_variants", 8))))
        self.synonym_groups = []
        for group in config.get("synonym_groups", []):
            terms = tuple(dict.fromkeys(
                str(term).strip() for term in group.get("terms", []) if str(term).strip()
            ))
            if len(terms) > 1:
                self.synonym_groups.append({
                    "terms": terms,
                    "normalized_terms": tuple(normalize_alias_text(term) for term in terms),
                    "sources": frozenset(group.get("sources") or SEARCH_SOURCES),
                })
        self.record_aliases = {}
        self._record_key_names = {}
        for source, records in config.get("record_aliases", {}).items():
            self.record_aliases[source] = {}
            self._record_key_names[source] = {}
            for key, aliases in records.items():
                normalized_key = normalize_alias_text(key)
                self.record_aliases[source][normalized_key] = tuple(
                    str(alias).strip()
                    for alias in aliases
                    if str(alias).strip()
                )
                self._record_key_names[source][normalized_key] = str(key)

    @classmethod
    def from_file(cls, path: Path = ALIAS_CONFIG_PATH) -> "SearchAliasRegistry":
        with open(path, "r", encoding="utf-8") as file:
            return cls(json.load(file))

    def expand_query(self, query: str, source: Optional[str] = None) -> Tuple[str, ...]:
        """Return the original query and bounded one-hop synonym substitutions."""
        original = " ".join(unicodedata.normalize("NFKC", str(query or "")).strip().split())
        if not original:
            return ()

        variants = [original]
        seen = {normalize_alias_text(original)}
        if len(variants) >= self.max_query_variants:
            return tuple(variants)
        normalized = normalize_alias_text(original)
        for group in self.synonym_groups:
            if source and source not in group["sources"]:
                continue
            for term, normalized_term in zip(group["terms"], group["normalized_terms"]):
                if normalized_term not in normalized:
                    continue
                for replacement in group["terms"]:
                    if normalize_alias_text(replacement) == normalized_term:
                        continue
                    candidate = re.sub(re.escape(term), replacement, original, flags=re.IGNORECASE)
                    normalized_candidate = normalize_alias_text(candidate)
                    if normalized_candidate in seen:
                        continue
                    if len(variants) >= self.max_query_variants:
                        return tuple(variants)
                    seen.add(normalized_candidate)
                    variants.append(candidate)
        return tuple(variants)

    def _record_keys(self, source: str, record: Dict[str, Any]) -> Tuple[str, ...]:
        def first(*keys: str) -> str:
            for key in keys:
                value = record.get(key)
                if value is not None and str(value).strip():
                    return str(value).strip()
            return ""

        if source == "jlcparts":
            lcsc = first("lcsc", "lcsc_part", "external_part_id")
            normalized = re.sub(r"^c", "", lcsc, flags=re.IGNORECASE)
            return (normalized,) if normalized else ()
        if source == "altium":
            reference = first("lib_reference")
            source_file = first("source_file")
            return (f"{source_file}|{reference}",) if reference and source_file else ()
        if source == "kicad":
            library, name = first("library"), first("name")
            return (f"{library}|{name}",) if library and name else ()
        if source == "fasteners":
            code = first("standard_code")
            return (code,) if code else ()
        if source == "inventory":
            keys = []
            library_source = first("library_source")
            external_id = first("external_part_id")
            part_id = first("id", "part_id")
            if library_source and external_id:
                keys.append(f"{library_source.casefold()}:{external_id}")
            if part_id:
                keys.append(f"part:{part_id}")
            return tuple(keys)
        return ()

    def record_keys_for_query(self, source: str, query: str) -> Tuple[str, ...]:
        """Find stable source record keys whose curated alias occurs in query."""
        normalized_query = normalize_alias_text(query)
        if not normalized_query:
            return ()
        matched = []
        for key, aliases in self.record_aliases.get(source, {}).items():
            if any(normalize_alias_text(alias) in normalized_query for alias in aliases):
                matched.append(self._record_key_names[source][key])
        return tuple(matched[:100])

    def record_keys_matching_text(self, source: str, text: str) -> Tuple[str, ...]:
        """Find curated aliases containing one keyword of a compound search."""
        normalized = normalize_alias_text(text)
        if not normalized:
            return ()
        return tuple(
            self._record_key_names[source][key]
            for key, values in self.record_aliases.get(source, {}).items()
            if any(normalized in normalize_alias_text(value) for value in values)
        )

    def aliases_for_record(self, source: str, record: Dict[str, Any]) -> Tuple[str, ...]:
        """Return deduplicated native and curated alias text for one source record."""
        values = list(self.native_aliases_for_record(source, record))
        values.extend(self.record_curated_aliases(source, record))
        return self._unique_values(values)

    def native_aliases_for_record(self, source: str, record: Dict[str, Any]) -> Tuple[str, ...]:
        """Return searchable text extracted from the source record itself."""
        values: List[str] = []
        for field in SOURCE_ALIAS_FIELDS.get(source, ()):
            if field not in record:
                continue
            values.extend(_flatten_values(_json_value(record[field])))
        return self._unique_values(values)

    def record_curated_aliases(self, source: str, record: Dict[str, Any]) -> Tuple[str, ...]:
        """Return centrally configured aliases attached to a source record."""
        values = []
        for key in self._record_keys(source, record):
            values.extend(self.record_aliases.get(source, {}).get(normalize_alias_text(key), ()))
        return self._unique_values(values)

    @staticmethod
    def _unique_values(values: Iterable[str]) -> Tuple[str, ...]:
        unique: Dict[str, str] = {}
        for value in values:
            normalized = normalize_alias_text(value)
            if normalized and normalized not in unique:
                unique[normalized] = value
        return tuple(unique.values())

    @staticmethod
    def searchable_fields(source: str) -> Tuple[str, ...]:
        """Return database text columns used by source query adapters."""
        return SOURCE_DB_SEARCH_FIELDS.get(source, ())


search_aliases = SearchAliasRegistry.from_file()


def expand_query(query: str, source: Optional[str] = None) -> Tuple[str, ...]:
    return search_aliases.expand_query(query, source)


def record_keys_for_query(source: str, query: str) -> Tuple[str, ...]:
    return search_aliases.record_keys_for_query(source, query)


def record_keys_matching_text(source: str, text: str) -> Tuple[str, ...]:
    return search_aliases.record_keys_matching_text(source, text)


def aliases_for_record(source: str, record: Dict[str, Any]) -> Tuple[str, ...]:
    return search_aliases.aliases_for_record(source, record)


def native_aliases_for_record(source: str, record: Dict[str, Any]) -> Tuple[str, ...]:
    return search_aliases.native_aliases_for_record(source, record)


def record_curated_aliases(source: str, record: Dict[str, Any]) -> Tuple[str, ...]:
    return search_aliases.record_curated_aliases(source, record)


def searchable_fields(source: str) -> Tuple[str, ...]:
    return search_aliases.searchable_fields(source)


def record_keys(source: str, record: Dict[str, Any]) -> Tuple[str, ...]:
    return search_aliases._record_keys(source, record)


def curated_aliases_for_record(source: str, key: str) -> Tuple[str, ...]:
    return search_aliases.record_aliases.get(source, {}).get(normalize_alias_text(key), ())
