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


## Panduit model profiles (2026-10-25)

Migration `a92e6b371d04` adds `printer.model` (default `custom`) and template
`media_height_mm` (0 = legacy automatic height) / `media_gap_mm` (default 3).
Run `alembic upgrade head` before restarting the updated backend; back up the
SQLite database first. Rebuild the frontend. Existing printer DPI, protocol,
text coordinates and feed behaviour are retained until an operator selects a profile.

Admin → Printers offers DP4300M, DP4300H, DP4600H and DP4300HD. Profile selection
sets JScript and native DPI (600 for DP4600H; 300 for the other three). API and
print-time validation apply the same settings. Custom preserves manual settings.
Named profiles reject ink outside the single-head width before opening a socket;
only empty padding is trimmed, with byte alignment preserved.

Admin → Templates → Material feed accepts a measured label height and gap in mm.
A positive explicit height rejects vertically clipped ink. Zero height retains
the previous automatic calculation, including 54 mm for existing Turn-Tell layouts.
Gap sensing remains `l1`; continuous stock and duplex layout are not added here.

DP4300HD is **single-sided only** with these templates. Follow the manufacturer's
single-sided setup (including Disable lower head). The driver's 2497 dots at
300 DPI represent the combined two-head page, not a 211.4 mm wide single head.
Do not treat the current left/right label columns as front/back surfaces.

Evidence: local Panduit driver 1.3.0.25 GPDs (1249 dots at 300 DPI, 2497 at 600 DPI),
[Panduit HD instructions, section 5.2](https://www.panduit.com/content/dam/panduit/en/products/media/0/10/010/3010/111653010.pdf),
and [cab JScript manual, S command](https://www.cab.de/media/pushfile.cfm?file=3047).
Wire generation and migration are tested offline. Physical alignment and firmware
acceptance must still be checked on each device with the actual material.


## EasyMark material catalog (2026-10-25)

The user-supplied EasyMark 2.0.0.229 installer contains `database/easymark.xml`.
`app/data/materials.json` records only SKU, stock category and numeric dimensions
from that file (1715 records), with a source SHA-256. No executable, vendor image,
font or binary serialization is embedded in this application. The separate
`formats.pemex` is not used; this is a reference to the bundled XML, not a claim
that every newer EasyMark format or device capability is supported.

Reproduce extraction with `python scripts/import_easymark_catalog.py /path/easymark.xml`.
The catalog is packaged with the backend and searchable in Admin → Templates →
Material catalog. The full SKU distinguishes thermal stock from similarly named
laser/inkjet stock. Admin authentication is required for `/api/materials`.

43 formats pass the current two-column, one-row, die-cut, canvas and pitch checks.
Other formats remain visible as reference-only. Continuous media, duplex layouts,
and arbitrary row/column counts are not silently approximated by two columns.
Applying a supported format requires a named Panduit model profile. Material
width and layout compatibility still need review on the installed hardware.

“Use sizes, keep text positions” changes raster dimensions, physical height/gap
and material association. “Use catalog layout” additionally replaces rectangles
and padding from the catalog. Both preserve typography and text and modify only
the open draft until Save. Catalog-backed preview displays the full raster.
Material feed fields show three decimal places (e.g. 3.175 mm, not 3.18 mm).

Migration `b16d4a0c87e2` adds `template.material_sku` defaulting to empty. Existing
calibrated templates are not converted. Run `alembic upgrade head` before serving
the new backend and rebuild frontend assets. For an existing template, duplicate
it before a physical calibration trial if both layouts need to remain available.

The catalog is a geometry reference, not a physical alignment certification.
Validate loaded stock, sensor/feed and printer model with a sample before using
new geometry for production. No physical prints were sent during automated tests.


## Text fit preflight (2026-10-25)

Preview and print share a check of measured glyph bounds before rendering can
clip text. The check covers long unbroken identifiers, wrapped/multiline text,
character-width stretching, vertical offsets and each half of a repeated,
180-degree legend. Errors identify the operator-facing Left or Right label and
suggest reducing font size/character width, shortening text, or adjusting
insets/offsets. Font metrics and the existing 203-DPI point-size conversion are
unchanged. Actual glyph heights are checked rather than rejecting unused font
line-box space; one device pixel accommodates fractional-coordinate rounding.

Intentional compatibility change: nonempty text in an unconfigured, zero-area
side now fails preflight instead of being silently drawn/clipped at the page
origin. For a one-sided template, clear that side's default text; otherwise
configure its print rectangle. Existing valid layouts, including 6 pt mirrored
Turn-Tell text at 110% width with a small negative offset, remain supported.

Regression tests cover both 300- and 600-DPI rendering, left/right diagnostics,
preview/test-print errors and valid ink containment. Automatic font-size fitting
is not implemented. This validation checks configured print areas; actual roll
alignment still requires physical calibration.

## Per-printer transport serialization (2026-10-25)

All print paths (cart, direct, draft test, printer test and integration) now
acquire the same OS advisory lock around their TCP connection and send. The
key is the normalized host/IP plus port, so two database printer records with
the same endpoint share a slot. Different endpoints can send concurrently.
A caller waits at most 30 seconds; a busy timeout occurs before any socket
activity and can be retried. Existing cart claims remain unchanged.

This is bounded transport serialization, **not** a persisted FIFO spooler.
It does not guarantee ordering between waiting requests, keep an entire batch
together, confirm physical printing, or coordinate separate application hosts.
No payload is automatically replayed. A paused worker retains its lock; a
crashed worker releases it through the OS. Existing cart recovery still marks
interrupted claims uncertain. Partial socket sends and failures releasing the
slot after sending have an uncertain outcome. Direct, test and integration
history now preserve `uncertain` rather than recording these as ordinary
errors. Check the physical labels before repeating an uncertain job.

Deployment requirements:

- Run on Linux/macOS with a local filesystem supporting `flock`. Unsupported
  lock handling fails closed before connecting to a printer.
- Every API worker must share the same writable `TDS_PRINTER_LOCK_DIR`.
  By default it is `printer-locks` beside the configured SQLite database;
  with another database backend the fallback is `server/data/printer-locks`.
  For releases with separate deployment directories, explicitly configure a
  stable shared directory, such as `/var/lib/tds-printer/printer-locks`, owned
  by the service user. No database migration is needed for serialization.
- Use one consistent IP/address for each physical printer. DNS aliases and
  different ports pointing to the same device are different lock keys.
- Never delete or rotate lock files while any workers are running: replacing
  their inodes can allow concurrent senders. Empty lock files are normal and
  do not indicate stuck jobs.

Regression checks use mocked sockets and a separate process to verify mutual
exclusion, independent endpoints, bounded waiting, process-death release,
uncertain cleanup failures and uncertainty retention in non-cart history.


### Printer/material calibration (2026-10-25)

Migration `c37a5e9d1048` adds `printer.material_calibrations`, an empty JSON map for existing printers. Back up the database and run `alembic upgrade head` before starting this version. No existing template coordinates are changed.

The template editor has a separate **Printer & material calibration** section for named Panduit models and exact supported catalog SKUs. An operator sends one sample label, measures its displacement against the carrier view, and enters the opposite X/Y correction (or uses the measured-displacement calculator). Corrections are limited to ±5 mm and saved immediately to the printer/material pair, independently of the template draft. Positive X moves right and positive Y moves down in the carrier view. Save first, then send another sample to verify; the preview displays the saved correction. The test action uses the current template text, so use a short representative sample. This is a manual workflow, not automated sensor calibration or a certified physical ruler target.

Every JScript job looks up the actual destination printer's exact SKU correction, including integration printer overrides, and translates the oriented raster at native DPI. The preview uses the same correction at the 300-DPI design scale. The carrier outline and guides stay nominal. A correction that clips ink at a raster edge, printhead width, or configured material height is rejected before sending. 600-DPI rounding may differ from the 300-DPI preview by one native dot. Check the full **Carrier raster** view, because the illustrative label view crops to the white strip.

`PUT /api/printers/{id}/calibration/{sku}` requires admin access and uses compare-and-swap to reject concurrent changes instead of overwriting another profile. A stale general printer form cannot replace saved calibrations. Changing printer model, IP, or port clears its corrections; recalibrate after hardware changes. No physical print was sent during implementation. Physical accuracy, feed direction on installed equipment, and repeatability still need operator verification on each model and roll.
