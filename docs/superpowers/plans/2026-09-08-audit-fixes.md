# Audit fixes implementation plan

> Execute the accepted recommendations from both audits with regression tests, independent file ownership, and a final code review.

**Goal:** Fix all reported frontend/backend defects without touching the working database or sending real print jobs.

**Architecture:** Keep FastAPI/SQLModel/SQLite and Vue/Pinia. Validate HTTP input with non-table schemas; make import operations atomic; resolve batches to unique label IDs before printing. Persist cart item print state and atomically claim the whole session before sending; never automatically resend an item with an uncertain outcome. Keep UI results tied to their request/context and cart scope.

**Tech stack:** Python, pytest, FastAPI TestClient, SQLite, Pillow, Vue 3, TypeScript, Vite.

- [x] Validation/rendering: add regression tests for invalid enum/geometry/protocol; implement request DTOs, bounded geometry, render error conversion, alignment-preserving stretch, and useful conflict responses on template/printer deletion. Preserve response shapes and editor fields.
- [x] Import/deletion/migrations: test corrupt-file rollback and empty directories; move commits to the operation boundary, clear related cart items/import metadata in FK order, use a server-owned upload filename, and repair the SQLite migration rebuild. Test clean/populated upgrades with temporary DBs.
- [x] Search/batch: test bounded ranges, both documented list forms, text spaces, total/truncation, overlapping groups, missing bundles, actual 500-label cap and complete skipped reporting. Resolve each batch first, deduplicate label IDs, then send and report.
- [x] Cart: test concurrent claims and mid-job failure. Add persistent per-item state/claim token plus migration, claim queued items atomically, block overlapping session prints, commit progress per item, and expose uncertain outcomes for explicit removal instead of automatic resend. Block mutation of active items. No lease-based automatic retry of potentially sent labels.
- [x] Frontend: scope stores by Print/Kiosk, ignore old async results and clear them on context changes, show truncation and cart processing/uncertain status; improve search help, filter wrapping and chip accessibility. Verify scoped cart/race logic with executable frontend tests and build; check screens in browser.
- [x] Deployment/docs: bind both systemd units to loopback, document limits, atomic imports and recovery from uncertain print outcomes; expose an isolated DB URL for tests without changing the production default.
- [x] Final verification: run all backend tests (network blocked), frontend tests/type-check/build, isolated Alembic upgrade/check and a separate code review. Check the full finding list against the diff and resolve remaining issues.

**Checks:** `PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest server/tests`; `npm test`, `npm run build` in frontend. New defect tests must fail before the corresponding implementation. Browser uses a temporary backend database and mock printer sending. No production migration, deployment, push, or physical printing is part of this work.

**Verified outcome:** 96 backend tests, 12 frontend tests, type-check and production build pass. Clean and populated temporary SQLite upgrades, Alembic metadata check and foreign_key_check pass. Browser QA verified 390px layout, scoped Print/Kiosk carts, three mocked sends, template editor save and 500/502 truncation. Independent review closed the dotenv/Alembic configuration mismatch. No live database migration or physical print occurred.
