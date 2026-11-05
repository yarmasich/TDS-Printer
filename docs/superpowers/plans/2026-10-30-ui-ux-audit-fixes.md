# TDS Printer UI/UX Audit Fixes Implementation Plan

> For agentic workers: execute the approved audit in independent file ownership groups; root reviews integration and runs the combined checks.

**Goal:** Resolve the 17 findings from the approved Figma audit without changing printing protocols, authorization policy or production data.

**Architecture:** Keep Vue/PrimeVue and existing stores. Protect draft lifecycle, make async actions single-flight and stale-response safe, and adapt existing forms to touch use. Figma audit: https://www.figma.com/design/ph88BJK8wEDcXtyfilBRks?node-id=2-207 . The user authorized agents after reviewing the audit; no additional approval gate or deployment is needed.

**Tech Stack:** Vue 3, TypeScript, PrimeVue, node:test; FastAPI regression suite.

## Ownership and acceptance

- [x] Templates agent: TemplatesSection, PrintWorkspace, TypographyPanel, CalibrationPanel. Dirty-close and navigation protection; calibration state controls every print/save/switch action; Auto Fit bounds; named fields; touch targets; transport retry; in-app preview. Expose `canLeave(): Promise<boolean>` to Admin. Add meaningful state/validation regression tests.
- [x] Admin forms agent: ImportsSection, ProjectsTree, ListsSection, ApiKeysSection, PrintersSection. Clear/disable stale discipline selection and reject outdated responses; busy guards; caught errors/retry; correct empty slots; accessible names; explicit destructive impact; 44px touch targets; distinguish connection test from physical print.
- [x] Operator agent: PrintPanel, KioskPanel, StationLogin, AdminLogin, stores/auth, StickyCart. Kiosk bundle selector and hall context; full cart text; named selects; distinguish network failure from unconfigured authentication; one guarded login submit; no login-loop link.
- [x] Root: Admin, HistorySection, StationsSection. Tablet section selector with named content/focus management and child dirty guard; history puts when/operator/result first and secondary metadata in details; validate dates; station edit scroll/focus, loading/error/empty feedback and printer prerequisite.

## Validation sequence

1. Write/run focused failing tests for state/race/validation defects, then implement and rerun. Do not create tests merely to mirror simple CSS edits.
2. Each worker runs relevant node tests and type checking; root inspects diffs and resolves integration issues.
3. `npm --prefix frontend test` and `npm --prefix frontend run build` must pass.
4. `PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest server/tests -q` checks printing/auth regressions.
5. Inspect local browser at 768x1024 and 1024x768, using isolated local test data if needed. Verify draft cancel/keep paths, tablet navigation, history details, labels and touch targets. Never send real print jobs or mutate production.
6. `git diff --check`; report implemented changes and remaining physical iPad/RFID/printer verification limits. No commit/deploy unless requested.

## Verification results

- Frontend: 52 tests passed; production build and TypeScript checks passed.
- Backend: 408 tests passed; no backend or database schema changes.
- Browser: isolated temporary database, loopback-only server, printer connections disabled. Checked 768×1024 and 1024×768 layouts; admin selector, history details/no page overflow, station empty state and named printer fields.
- Repeated template Cancel → Keep editing → Cancel → Discard exposed a pre-existing global z-index override. Removed it so PrimeVue orders nested overlays; repeated browser flow passed afterward.
- Widened datetime filters after visual inspection showed clipped values.
- Physical iPad/Safari, VoiceOver, RFID and real printer output were not tested; production data was untouched.
