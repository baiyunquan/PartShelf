# Verified JLC label scan import

Accepted in conversation on 2026-10-06. Execute inline in the main worktree.

## Goal

Decode JLC QR labels in the browser, verify number/model/package against OCR and the existing local-or-remote catalog resolver, automatically create one inventory row per package and associate the selected project without another confirmation.

## Tasks

1. Add a decoupled ElectronicQwen OCR API compatible with PaddleOCR 2.9.1 / PaddlePaddle 2.6.2, with independent requirements, health endpoint, bounded upload validation, orientation handling, API and deployment documentation.
2. Add a safe QR parser, OCR evidence matcher, persistent scan sessions, transactional inventory/project import, duplicate prevention and manual-review APIs. Record usernames using the existing cookie and project history hooks. Use temporary databases for all write tests.
3. Add the locally hosted zxing-wasm reader through a pinned Git submodule and a repeatable, integrity-checked release-asset installer.
4. Add a bilingual camera/image scan page with a persistent project selector, review list, receipts and small-drawer continuation. Successful verification imports immediately; reviews retain the project captured when scanned.
5. Exercise the real sample photos and OCR service, focused regression tests, document deployment and usage, request a final review, fix important findings and commit PartShelf changes.

## Decisions

- One package creates a new Part, Inventory and optional ProjectPart. Both quantities use the package quantity.
- A blank project means inventory only (Loose Parts is derived). System projects cannot be selected.
- The project selection is stored in localStorage, validated against current projects on load, and captured in each scan request. Selection is disabled during an active request.
- C-number and package require complete normalized matches. Model permits at most one character edit with similarity >= 0.90; evidence confidence >= 0.90. Explicit conflicting fields block automatic import.
- QR quantity must be positive. A confidently read conflicting QTY blocks automatic import.
- OCR API only returns text evidence and does not access PartShelf or its databases. PartShelf proxies image uploads.
- Use QR content fingerprints plus unique request IDs and transactional claims to prevent repeats. A separate physical bag with the same QR requires explicit manual new-package confirmation.
- Images and evidence persist for review; managed image files live in data/scan_uploads.
- Existing source libraries must be available; remote missing components use the current LCSC resolver and persistent cache.
- ElectronicQwen is not a Git repository. Deliver its API source there, and include a reproducible service-source copy in the PartShelf commit so a checkout contains the API needed for deployment.

## Implementation notes

- Reproducible OCR source is committed under `services/paddleocr_api/` and synced to ElectronicQwen. The separate Python 3.11 environment preserves the existing Windows and Qwen environments; the tradeoff is maintaining the source copy through the sync helper.
- Linux CPU Paddle 2.6.2 crashed in its optional `self_attention_fuse_pass`. Disable only that pass during predictor construction and restore the factory; preload pyclipper to avoid its reproduced bundled-zlib import conflict. Keep the original library versions and PP-OCRv4 models. This compatibility path is isolated to the independent service and covered by a regression test.
- Preserve OCR evidence from all four document rotations. The first sample's upside-down numeric package line otherwise read as `8090`; rotation alternatives recovered `0603` without lowering the confidence threshold. The cost is four OCR passes per image.
- Persist a stable UUID project identity with each review and saved browser selection. A deleted project's reused numeric ID cannot redirect imports. This adds a compatible project column and a scan snapshot column.

## Verification record

- Full Python suite against a temporary business database: **347 passed, 1 skipped**.
- JavaScript suite: **24 passed**.
- All three supplied photographs passed real browser QR decoding, the independent PaddleOCR API, and automatic import into a temporary project: three independent inventory/project rows, quantities 200, 100, 100, total 400. Username history was recorded; project selection survived imports and refresh. Repeating a photograph did not increase stock. Desktop and mobile screenshots were inspected.
- Navigation/translation migration and pinned ZXing asset generation were rerun: eight output files remained byte-identical.
- Final independent review: fixed verification/manual-confirm races, partial-model acceptance, reused project IDs, and camera repeat suppression. Race, model and identity regressions were observed failing before their fixes and passing afterwards; the complete suites remained green. Explicit camera repetition has a frontend regression test and still requires backend confirmation of an extra physical bag.
- Deferred minor: the browser parser supports the supplied unquoted JLC key/value format, while the backend also accepts quoted JSON. The current browser format is documented in USAGE.md; quoted JSON browser support is deferred.
