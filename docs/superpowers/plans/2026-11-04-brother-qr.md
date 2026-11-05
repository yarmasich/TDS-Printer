# Brother QR Labels Implementation Plan

> **For agentic workers:** Execute inline with executing-plans and test-driven-development. Independent Claude plan agreement is recorded in the task's temporary review artifacts (round 6).

**Goal:** Add QL-1110NWBc QR labels to TDS-Printer, with DK-2246 / DK-2205 media, preview and authenticated API. FloorHub Inventory integration is a separate stage.

**Architecture:** TDS owns QR layout and the physical Brother endpoint. A dedicated adapter uses the existing process-safe endpoint lock and durable idempotency reservation. Cable templates and station printing remain isolated from Brother. Success means SENT, never confirmed physical output.

**Tech Stack:** FastAPI, SQLModel/Alembic, Pillow, qrcode 8, brother_ql-inventree 1.3, Vue 3 / TypeScript, pytest and zxing-cpp.

- [x] Inspect existing TDS source, FloorHub renderer and supplied P-touch Editor installer without executing it.
- [x] Agree scope with user and independent Claude Code; evaluate and resolve routing, retry, audit and TCP shutdown findings.
- [x] Test-first QR layout and decode exact scan payload for both media, including UTF-8 and spaces. Reject overflow; preserve a four-module quiet zone and minimum four dots per module.
- [x] Test-first Brother raster: exact model, media declarations, no resampling, no status requests, notifications disabled, auto cut. Reconstruct bitmap from wire data and compare to preview.
- [x] Test-first exclusive TCP sender: connect, sendall, SHUT_WR, bounded drain, close under the endpoint file lock; distinguish pre-send failure from uncertain outcome.
- [x] Add authenticated admin and machine preview/send endpoints. Require idempotency keys; persist 'sending' audit row before network I/O; preserve interrupted reservations.
- [x] Add printer profile and block cable/template/station cross-routing and protocol reassignment of bound printers. Existing ping calls share endpoint locks.
- [x] Add audit migration, history rendering and interrupted-attempt summary. Validate upgrade/downgrade against a disposable database.
- [x] Add admin QR workspace and immutable client intent/retry state. Preserve existing frontend changes.
- [x] Finish full checks and independent post-change review of the exact task diff.
- [x] Apply only reviewed task changes to the original working files after checking baseline bytes.

Validation commands (from server / frontend respectively):

```sh
ADMIN_USERNAME=qr-test ADMIN_PASSWORD=qr-test-only ADMIN_JWT_SECRET=qr-tests-only-secret-32-characters python -m pytest -q
npm test
npm run build
```

In the isolated copy, linked node_modules is read-only, so build uses `npm run build -- --configLoader runner` to avoid Vite writing its bundled config beside the original dependencies.

No production migration, service restart, deploy or physical print is part of this change. Before real use, remove this Brother from the old FloorHub relay and its health polling. A nonprinting status probe to the user-supplied 172.16.10.50 timed out; hardware compatibility remains unverified.
