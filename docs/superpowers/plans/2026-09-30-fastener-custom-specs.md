# Fastener Aliases and Custom Specifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Chinese search aliases and let users append custom dimensions to an existing mechanical parameter table, then use those rows in inventory and BOM matching without losing them during reimport.

**Architecture:** Keep user rows in the existing `fastener_tables` table, mark them with `source_file='user'` and deterministic `user:<nominal>:<digest>` row keys. Add search aliases, a validated write API and detail-page form; teach variant hydration and BOM matching to distinguish repeated nominals; make imports stage to a temporary database and migrate user rows before atomic replacement.

**Tech Stack:** Python 3, FastAPI, SQLite, SQLAlchemy, Jinja2, static JavaScript, pytest.

**Spec:** `docs/superpowers/specs/2026-09-29-fastener-custom-specs-design.md`

## Global Constraints

- Append custom rows to the selected standard's existing parameter or length table; do not create a separate custom-spec table.
- Keep `database/FreeCAD_FastenersWB/FsData` read-only.
- Preserve existing standards and `fastener:v1` inventory references.
- Preserve user rows during mechanical-library reimport.
- Do not auto-bind incomplete or conflicting mechanical dimensions.
- Keep templates light; put page behavior in `static/js` and pass translations through JSON data islands.
- Add no emoji to UI or translations; write any commit messages in English.

## Review Focus

- Repeated nominal sizes must not collapse into or overwrite the source row; test two M3 insert geometries as separate variants.
- Repeating an identical custom-spec POST must be idempotent; test stable row keys and one stored row.
- Client-controlled table/column names must never reach SQL; test unknown fields and unknown standards are rejected.
- A failed reimport must leave the old database usable; test injected failure before replacement.
- A user row whose standard/table schema changed upstream must not be silently discarded; test migration aborts and retains the original database.

---

### Task 1: Search aliases and localized fastener names

**Files:**
- Create: `app/i18n/fastener_aliases.py`
- Modify: `app/services/external_library_service.py`
- Modify: `app/api/library_api_routes.py`
- Modify: `app/api/search_api_routes.py`
- Modify: `static/js/libraries_fasteners.js`
- Modify: `static/js/libraries_fasteners_details.js`
- Modify: `static/js/search.js`
- Test: `tests/test_fasteners_library.py`

**Interfaces:**
- Produce `aliases_for_standard(standard_code: str) -> list[str]` and `expand_fastener_query(query: str) -> tuple[str, ...]`.
- Alias terms map `热熔螺母`, `热熔铜螺母`, `热熔嵌件`, and `热压嵌件` to `IUTHeatInsert`; `平头螺丝` and `沉头螺钉` expand to countersunk-standard English descriptors/codes.
- Search responses add `standard_name_localized` and `search_aliases`; preserve existing response fields.
- List, detail and global-search views prefer `standard_name_localized` while keeping the source description visible.

- [x] **Step 1: Write failing tests**
  - Assert `query_fasteners('热熔螺母')` returns `IUTHeatInsert`.
  - Assert `query_fasteners('平头螺丝')` returns countersunk standards and excludes hex nuts.
  - Assert the Chinese display name is present while the English source description remains unchanged.
- [x] **Step 2: Run focused tests and confirm expected failures**
- [x] **Step 3: Implement the alias map and query expansion**
- [x] **Step 4: Run focused tests and confirm they pass**

### Task 2: Append and validate custom rows

**Files:**
- Modify: `app/api/library_api_routes.py`
- Create: `app/schemas/fastener.py`
- Modify: `app/services/external_library_service.py`
- Test: `tests/test_fasteners_library.py`

**Interfaces:**
- `POST /api/libraries/fasteners/{standard_code}/specs` accepts a nominal string, dimension mapping and optional custom length.
- Add `append_fastener_spec(standard_code: str, nominal: str, dimensions: dict[str, object], length: str | None = None) -> dict[str, object]`.
- Deterministic row keys use `user:<encoded-nominal>:<sha256-prefix>`; values follow the table title order; `source_file='user'`.

- [x] **Step 1: Write failing tests** for M3 / `Length=4` / `ExtDia=5.5`, unchanged source M3 row, optional null columns, duplicate POST, invalid/unknown dimension names, non-finite values and unknown standard.
- [x] **Step 2: Run focused tests and confirm expected failures**
- [x] **Step 3: Implement server-side schema discovery, validation, transactional append and idempotency**
- [x] **Step 4: Run focused tests and confirm they pass**

### Task 3: Versioned custom variants and inventory hydration

**Files:**
- Modify: `app/services/fastener_variant_service.py`
- Modify: `static/js/fastener_variant.js`
- Modify: `app/services/external_library_service.py`
- Test: `tests/test_fastener_inventory_bom.py`

**Interfaces:**
- Preserve `fastener:v1/<standard>/<nominal>/<length>` parsing.
- Add `fastener:v2/<standard>/<row-key>` builder/parser for a specific parameter-table row, including user rows with repeated nominal values.
- Detail rows expose `row_key`, base `nominal`, `is_custom`, and values; variant hydration resolves the exact row key.

- [x] **Step 1: Write failing tests** for two custom M3 rows resolving independently, custom stock detail and existing v1 hydration.
- [x] **Step 2: Run focused tests and confirm expected failures**
- [x] **Step 3: Implement v2 identity and row-key hydration**
- [x] **Step 4: Run focused tests and confirm they pass**

### Task 4: Mechanical BOM matching for custom dimensions

**Files:**
- Modify: `app/services/bom_matcher.py`
- Modify: `app/services/bom_service.py`
- Test: `tests/test_fastener_inventory_bom.py`

**Interfaces:**
- Load user rows alongside source rows; parse the nominal base from `user:` keys.
- Heat-set inserts match thread nominal, external diameter and length; flat-head screws match the selected head family, nominal and exact listed/custom length.
- Candidate external IDs use v2 for custom rows. Import validation reruns the same matcher.

- [x] **Step 1: Write failing tests** for M3×5.5×4 matching only its custom insert row, mismatch rejection, incomplete dimensions remaining unbound and flat-head length matching.
- [x] **Step 2: Run focused tests and confirm expected failures**
- [x] **Step 3: Implement dimension extraction, critical-dimension comparison and custom candidate generation**
- [x] **Step 4: Run focused tests and confirm they pass**

### Task 5: Detail-page custom-spec entry flow

**Files:**
- Modify: `templates/libraries_fasteners_details.html`
- Modify: `static/js/libraries_fasteners_details.js`
- Modify: `app/i18n/locales/zh.json`
- Modify: `app/i18n/locales/en.json`
- Test: `tests/test_fasteners_library.py`

- [x] **Step 1: Write failing API/template tests** for translated labels, JSON translation data island, add-spec form and successful POST response.
- [x] **Step 2: Run focused tests and confirm expected failures**
- [x] **Step 3: Add a dynamic dimension form generated from `param_titles`, submit through the API, and refresh the selected table row; support adding a custom length to standards with length tables**
- [x] **Step 4: Run focused tests and confirm they pass**

### Task 6: Preserve user rows on reimport

**Files:**
- Modify: `scripts/import_fasteners.py`
- Test: `tests/test_fasteners_import.py`

**Interfaces:**
- Rebuild into a temporary SQLite file in the output directory.
- Copy `source_file='user'` parameter and length rows only after validating target table titles and value counts; abort replacement on migration error.
- Close connections and atomically replace the output with `os.replace` only after import and migration succeed.

- [x] **Step 1: Write failing tests** for successful migration, injected import failure preserving the old DB, and incompatible table schema preserving the old DB.
- [x] **Step 2: Run focused tests and confirm expected failures**
- [x] **Step 3: Implement staged import, user-row migration and atomic replacement**
- [x] **Step 4: Run focused tests and confirm they pass**

### Task 7: Full regression

**Files:**
- Test: `tests/test_fasteners_library.py`
- Test: `tests/test_fastener_inventory_bom.py`
- Test: full repository pytest suite

- [x] **Step 1: Run focused fastener and BOM tests**
- [x] **Step 2: Run the full pytest suite: 177 passed, 1 skipped**
- [x] **Step 3: Review `git diff`; the implementation worktree contained no unrelated tracked changes at start**
