# External Print API (v1)

Machine-to-machine API for printing labels from an external application.
Authentication is by **API key** in the `X-API-Key` header (not the admin JWT).
Printing is done **by cable number**: the server finds the label in the given
discipline, uses its bound template, renders it and sends it to the printer.
Every print is recorded in the shared history (`/api/history`) with the
operator set to `api:<key name>`.

Base URL is the same server that serves the UI, e.g. `http://10.0.0.5:8000`.
Interactive spec: `GET /docs` (Swagger) and `GET /openapi.json`.

---

## 1. Get a key

Keys are issued by an administrator in the web admin → **API keys** section:

1. Enter the app name (e.g. `FloorHub`) → **Create key**.
2. Copy the key that is shown. **It is shown only once** — the server stores
   only its SHA-256 hash and cannot recover the plaintext.
3. A key can be temporarily **disabled** or **revoked** — revocation takes
   effect immediately.

Key format: `tdsk_<8-hex>_<secret>`, e.g.
`tdsk_c0d04177_X9f...`. Send it in full.

> Treat the key as a secret (env / vault). Do not commit it to a repository.

---

## 2. Print a label

```
POST /api/v1/print
X-API-Key: <key>
Content-Type: application/json
```

### Request body

| Field           | Type   | Required | Description |
|-----------------|--------|----------|-------------|
| `cable`         | string | yes      | Cable number / text, e.g. `"1.1"`. Same search syntax as the UI. |
| `discipline_id` | int    | —        | Direct discipline reference (takes precedence over names). |
| `discipline`    | string | —        | Discipline name (if `discipline_id` is not given). |
| `project`       | string | —        | Project name — to disambiguate a discipline by name. |
| `data_hall`     | string | —        | Data hall name — an extra disambiguator. |
| `reason`        | string | —        | Print reason for the history (defaults to `"API"`). |
| `copies`        | int    | —        | Number of copies, 1–50 (defaults to 1). |
| `printer_id`    | string | —        | Logical printer **code** = printer name, e.g. `"WS1"` (see [§7 Printer routing](#7-printer-routing-per-workstation)). Overrides the template's printer. Omit → template default. Unknown code → `404`. |

**Scope**: provide either `discipline_id`, or `discipline` (plus `project` /
`data_hall` if needed so the name is unambiguous).

### Example (curl)

```bash
curl -X POST http://10.0.0.5:8000/api/v1/print \
  -H "X-API-Key: tdsk_c0d04177_..." \
  -H "Content-Type: application/json" \
  -d '{"cable": "1.1", "project": "Nscale", "discipline": "8K-IBLFSP"}'
```

### Success — `200 OK`

```json
{
  "ok": true,
  "log_ids": [310],
  "label_id": 1,
  "left_text": "WH1D9-U18-P37/1\n...\n144S SMF | CBL#1.1 | 78m",
  "right_text": "CH1C1-U18-P1/1\n...\n144S SMF | CBL#1.1 | 78m",
  "template_name": "R150x150",
  "printer": "192.168.0.178:9100",
  "copies": 1
}
```

`log_ids` — the history entries (one per copy).

---

## 3. Error codes

| Code  | When | Body |
|-------|------|------|
| `401` | Missing / invalid / revoked / disabled key | `{"detail": "Invalid or revoked API key"}` |
| `400` | No scope given (neither `discipline_id` nor `discipline`) or malformed `cable` | `{"detail": "..."}` |
| `404` | Discipline / cable not found, or unknown `printer_id` code | `{"detail": "No label matching '1.1' in discipline '...'"}` · `{"detail": "Unknown printer 'WS9'"}` |
| `409` | Ambiguous match | see below |
| `502` | Printer unreachable / send error | `{"detail": {"message": "...", "log_ids": [...], "printed": N}}` |

### `409` — multiple labels for one cable

```json
{
  "detail": {
    "message": "'1.1' matches 3 labels in '8K-IBLFSP' — narrow the query or print by label_id.",
    "candidates": [
      {"label_id": 1, "left_text": "...", "right_text": "...", "sheet_name": "...", "row_idx": 4}
    ]
  }
}
```

`409` is also returned when the discipline name is ambiguous — in that case add
`project` and/or `data_hall`.

### `502` — partial print

With `copies > 1`, if the printer drops mid-way, `detail.printed` holds the
number of copies already printed and `detail.log_ids` their history entries.
Retry is the caller's decision — there is no server-side idempotency, so a
repeated request prints again.

---

## 4. Print many labels at once (batch)

To print many *different* cable numbers of **one discipline** in a single call
(e.g. 50 labels), use the batch endpoint. (`copies` on `/api/v1/print` prints
the *same* label N times — that's not what you want here.)

```
POST /api/v1/print-batch
X-API-Key: <key>
Content-Type: application/json
```

### Request body

| Field           | Type     | Required | Description |
|-----------------|----------|----------|-------------|
| `cables`        | string[] | —        | List of cables; each entry may be a single number, a range, or a list. |
| `cable`         | string   | —        | A single range/list string, e.g. `"1.1-50"`. |
| `discipline_id` | int      | —        | Discipline (or use `discipline` + `project`). |
| `discipline` / `project` / `data_hall` | string | — | Name-based scope (same as single print). |
| `reason`        | string   | —        | History reason (defaults to `"API batch"`). |
| `printer_id`    | string   | —        | Logical printer **code** = printer name, e.g. `"WS1"` (see [§7 Printer routing](#7-printer-routing-per-workstation)). Whole batch prints to it. Omit → template default. Unknown → `404`. |
| `stop_on_error` | bool     | —        | Stop on the first **printer/send** error (default `false` = keep going). |

Provide `cables` and/or `cable` (at least one), or an explicit `bundle` for a
bundle-mode discipline. Up to **500 distinct labels** per call, including group
and bundle matches. Oversized ranges and batches are rejected before any send.

**Range / list syntax** (same as the operator search box):

- `"1.1-50"` → `1.1, 1.2, … 1.50` (50 cables — note the end is the minor part,
  not `"1.1-1.50"`).
- `"1.1,1.2,1.5"` → those three.
- `"20.*"` (or `"20."`) → the **whole group 20**: the trunk `#20` *and* every
  breakout `#20.1` … `#20.18`. (A bare `"20"` matches only the single `#20`.)
- `["1.1", "1.5-1.8", "2.3"]` → each entry expanded, then de-duplicated.

Overlapping selectors such as `["1.*", "1.1"]` print each matching label once.
In bundle mode only a complete `N`, `N.` or `N.*` selector chooses a bundle;
an individual `1.1` still selects that cable. Missing bundles are reported as
`not_found` and make `ok` false even when other bundles were printed.

### Example — 50 labels

```bash
curl -X POST http://10.0.0.5:8000/api/v1/print-batch \
  -H "X-API-Key: tdsk_c0d04177_..." \
  -H "Content-Type: application/json" \
  -d '{"cable": "1.1-50", "project": "Nscale", "discipline": "8K-IBLFSP"}'
```

Or an explicit list:

```bash
curl -X POST http://10.0.0.5:8000/api/v1/print-batch \
  -H "X-API-Key: tdsk_c0d04177_..." \
  -H "Content-Type: application/json" \
  -d '{"cables": ["1.1","1.2","1.7","2.3-2.10"], "discipline_id": 1}'
```

### Response — `200 OK`

```json
{
  "ok": true,
  "requested": 50,
  "printed": 50,
  "discipline": "8K-IBLFSP",
  "printer": "192.168.0.178:9100",
  "results": [
    { "cable": "1.1", "status": "printed", "label_id": 1, "log_id": 311 },
    { "cable": "1.7", "status": "not_found" },
    { "cable": "1.9", "status": "ambiguous", "candidates": [ ... ] }
  ]
}
```

- `ok` is `true` only if **every** requested cable printed.
- Per-cable `status`: `printed` · `not_found` · `ambiguous` · `invalid` ·
  `error` (printer/send failed) · `skipped` (only when `stop_on_error` aborted
  the rest).
- The endpoint returns `200` even with partial failures — inspect `results`.
  Empty/malformed selectors and a batch over 500 are rejected with `400`;
  invalid request field types or constraints return `422`.
- `requested` counts resolved distinct labels plus unresolved selectors, rather
  than the number of input expressions. Stopping during a group reports every
  remaining selected label as `skipped`.

> Prints are sent **serially** to one printer, so a 50-label batch is one long
> request — set a generous client timeout.

---

## 5. Printer status (online / offline)

```
GET /api/v1/printers
X-API-Key: <key>
```

Returns the printer roster with a live online flag — useful for an external
dashboard. Each printer is TCP-connect probed (~2 s timeout each, checked
serially), so keep polling reasonable when there are many printers.

### Query params

| Param  | Default | Description |
|--------|---------|-------------|
| `ping` | `true`  | Probe each printer. `false` = config only, fast (no `online`/`ms`). |
| `name` | —       | Filter to a single printer by exact name. |

### Example

```bash
curl http://10.0.0.5:8000/api/v1/printers \
  -H "X-API-Key: tdsk_c0d04177_..."
```

```json
[
  {
    "name": "DP4300H",
    "ip": "192.168.0.178",
    "port": 9100,
    "protocol": "jscript",
    "online": true,
    "ms": 12.3,
    "error": ""
  }
]
```

When `ping=false`, `online` and `ms` are `null` and `error` is empty. When a
printer is offline, `online` is `false` and `error` carries the reason
(e.g. connection refused / timeout).

> Use each printer's `name` as the logical `printer_id` code when routing a print
> to a specific workstation — see [§7 Printer routing](#7-printer-routing-per-workstation).

---

## 6. Examples in other languages

### Python

```python
import requests

resp = requests.post(
    "http://10.0.0.5:8000/api/v1/print",
    headers={"X-API-Key": "tdsk_c0d04177_..."},
    json={"cable": "1.1", "project": "Nscale", "discipline": "8K-IBLFSP", "copies": 2},
    timeout=15,
)
resp.raise_for_status()
print(resp.json()["log_ids"])
```

### JavaScript (fetch)

```js
const res = await fetch("http://10.0.0.5:8000/api/v1/print", {
  method: "POST",
  headers: {
    "X-API-Key": "tdsk_c0d04177_...",
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ cable: "1.1", discipline_id: 1 }),
});
if (!res.ok) throw new Error((await res.json()).detail);
const data = await res.json();
```

---

## 7. Printer routing (per workstation)

The print API works **by discipline**, and a discipline is *printer-agnostic* —
its template only decides *how* to render (geometry / font), not *where* to
print. That lets the **same discipline** print to different physical printers
depending on which workstation prints it.

**How it works.** Each request may carry a `printer_id` field — a **logical
code** equal to the target printer's `name`. The server maps that code to the
physical device (ip / port / protocol) and routes there. The caller never sends
an IP or USB path — just the code. (The bare name `printer` is also accepted for
backwards compatibility; `printer_id` is canonical.)

```
printer_id sent    →  server finds the Printer whose name == code  →  prints there
printer_id omitted →  template default (its main printer)
printer_id unknown →  404 "Unknown printer '<code>'"  (a typo never prints elsewhere)
```

**Recommended FloorHub pattern.** Each workstation picks its printer **once**
and stores the code in that browser's `localStorage` (per-machine, not per
user — a labeler can move desks, the printer stays with the desk). Every print
then sends that code. To populate the picker, call `GET /api/v1/printers`
([§5](#5-printer-status-online--offline)) and use each printer's `name` as the
code; if you prefer, hard-code a fixed list (`WS1` / `WS2` / `WS3`) in FloorHub
settings that matches the printer names configured in the admin.

```jsonc
// three workstations, one discipline, three destinations:
{ "cable": "30.*", "project": "X-AI", "discipline": "18K-EW-LFSP", "printer_id": "WS1" }
{ "cable": "30.*", "project": "X-AI", "discipline": "18K-EW-LFSP", "printer_id": "WS2" }
{ "cable": "30.*", "project": "X-AI", "discipline": "18K-EW-LFSP", "printer_id": "WS3" }
```

> Protocol is per-printer: routing a job to a `jscript` printer frames it as
> JScript even if the template's default printer is `epl2`. The rendered
> geometry still comes from the template, so keep the routed printers on the
> same label stock.

---

## 8. Notes

- **A discipline needs a template.** If the discipline has no template assigned,
  you get `400`. Assign one in the admin (Projects · Halls · Disciplines).
- **Printer.** If a request carries a `printer_id` code it prints there
  ([§7](#7-printer-routing-per-workstation)). Otherwise API jobs print to the
  template's printer (the same one the web/operator flow uses).
- **Text comes from the label.** The API prints the matched label's
  `left_text` / `right_text` as-is — you cannot override the text through this
  endpoint (use the internal `POST /api/print` for arbitrary text).
- **History.** All API prints appear in the admin → History as
  `api:<key name>`, with status `ok` / `error`.
- **CORS.** The server currently allows all origins (LAN deployment). CORS does
  not matter when printing from an external backend; keep it in mind if you
  print from a browser and later tighten the settings.

## Safe HTTP retries with `Idempotency-Key`

For both `POST /api/v1/print` and `POST /api/v1/print-batch`, send an optional
`Idempotency-Key` header containing a unique logical job identifier (for example
a UUID; 1–200 visible ASCII characters without spaces). Persist this identifier
in the caller **before the first request**, and reuse it with the same API
credential, endpoint, and body when retrying after a timeout or lost response.
A new intended print job needs a new identifier.

The server commits a durable reservation before processing the job. Concurrent
requests using that key cannot send again. Completed requests replay their
original HTTP status and response body, including print errors and partial
batch results. A changed payload or endpoint with the same key returns `409`.
Hashing uses validated fields and defaults, so JSON property ordering and the
`printer` / `printer_id` aliases do not change identity.

An interrupted job whose final response was not saved returns `409` on retry:
its outcome may be unknown. Inspect the printer and print history before
creating any new job. Reservations never expire or automatically release;
this favors preventing duplicates over automatic recovery. Even a failure
before any labels printed may require a fresh identifier after investigation.
Do not blindly retry a partial batch under a new key.

This prevents repeated server send attempts for a retained key; it cannot prove
physical printing completed or make printer transport transactional. Requests
without the header retain their existing behavior and can print again on retry.
Changing API credentials starts a different key scope. Deleting reservations,
restoring an older database backup, or downgrading the reservation migration
removes protection for affected jobs. Reservations consume database storage and
must be retained for as long as callers could retry. Install database migration
`a6d9b2e71c40` before using this header; a missing reservation table fails closed
before sending a keyed job.

## RFID identity

Both integration print requests accept an optional `rfid_code` string (maximum
256 characters before normalization, 64 after). It is required when any selected label belongs to a project
with `require_rfid=true`. The server resolves it through the configured RFID
service before sending labels; the returned `full_name` becomes the audited
operator; the stable `employee_id` is retained in the audit record. Only one
active directory match with the same normalized RFID is accepted. An API key or manual operator name does not bypass this policy.
An unconfigured/unavailable lookup returns 503; an unknown card returns 403.
RFID codes are not stored in print history. The idempotency request digest
includes the supplied code, so changing it requires a new idempotency key.
A completed replay returns the saved response without another lookup or print.
See the server README for the lookup service contract and configuration.
