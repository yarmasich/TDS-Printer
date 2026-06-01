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
| `404` | Discipline or cable not found | `{"detail": "No label matching '1.1' in discipline '...'"}` |
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
| `stop_on_error` | bool     | —        | Stop on the first **printer/send** error (default `false` = keep going). |

Provide `cables` and/or `cable` (at least one). Up to **500** cables per call.

**Range / list syntax** (same as the operator search box):

- `"1.1-50"` → `1.1, 1.2, … 1.50` (50 cables — note the end is the minor part,
  not `"1.1-1.50"`).
- `"1.1,1.2,1.5"` → those three.
- `["1.1", "1.5-1.8", "2.3"]` → each entry expanded, then de-duplicated.

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
  (A `400` is returned only for an empty request or a batch over 500.)

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

> The print API works by discipline, not by printer. To know which printer a
> given discipline prints to, match by printer `name` (each discipline's
> template is bound to one printer).

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

## 7. Notes

- **A discipline needs a template.** If the discipline has no template assigned,
  you get `400`. Assign one in the admin (Projects · Halls · Disciplines).
- **Text comes from the label.** The API prints the matched label's
  `left_text` / `right_text` as-is — you cannot override the text through this
  endpoint (use the internal `POST /api/print` for arbitrary text).
- **History.** All API prints appear in the admin → History as
  `api:<key name>`, with status `ok` / `error`.
- **CORS.** The server currently allows all origins (LAN deployment). CORS does
  not matter when printing from an external backend; keep it in mind if you
  print from a browser and later tighten the settings.
