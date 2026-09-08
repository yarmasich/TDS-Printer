# Audit fixes and rollout

Run `alembic upgrade head` before serving the updated backend. Revision
`f8a2d6e901bc` adds cart claim/status columns; existing items become `queued`.
Both shipped systemd units bind to loopback so nginx remains the access gate.
Neither unit should expose port 8000 directly to clients.

Imports are atomic: one upload or directory scan either commits its hierarchy,
labels and import metadata together, or restores the previous data. Wipe and
hierarchy/import deletion remove dependent inactive carts in FK order. They
return 409 when affected labels belong to active or uncertain print jobs.

Cart states are `queued`, `printing`, `uncertain`, and transient `printed`.
One atomic database claim reserves the session's queued rows before sending.
Successful rows are removed durably one at a time (or preserved when an API
caller explicitly sets `clear_after=false`). A connection failure before any
send can be retried. A failed partial send or unknown failure becomes uncertain.
Claims without progress for five minutes also become uncertain on the next
cart read/print request; they never automatically return to the print queue.

For an uncertain item, check the physical printer/labels before removing its
record. Re-add the label only when another physical copy is needed. Raw TCP
has no transactional acknowledgement of physical printing: software cannot
guarantee exactly-once output after a network/process failure. The UI exposes
that uncertainty instead of silently resending. The passwordless LAN cart
API still treats the opaque session ID as its capability.

Search now supports complete and abbreviated numeric lists/ranges, preserves
spaces in text, bounds expansion to 5000 queries and reports actual `total`,
`truncated` and `offset`. `GET /api/labels/search` accepts `offset` for subsequent
pages. The UI labels capped results as displayed results, not the whole group.
Batch printing resolves and deduplicates all label IDs before enforcing its
500-label limit or sending any bytes.

Template/printer writes and draft rendering use validated request schemas.
Bad enum values, nonfinite/negative/oversized geometry and unknown protocols
are rejected before persistence. Existing invalid settings are not silently
rewritten; correct them before printing. Check a restored backup separately
if it contains enum values that were already invalid before this update.

Regression checks use temporary databases and block printer sockets:

```sh
python3 -m pip install -e 'server[test]'
python3 -m pytest server/tests
cd frontend
npm test
npm run build
```

`TDS_DATABASE_URL=sqlite:////absolute/temporary/tds.db` selects an isolated
SQLite database for QA and migrations. When unset, the existing
`server/data/tds.db` path is used. Do not point tests at a live database.
