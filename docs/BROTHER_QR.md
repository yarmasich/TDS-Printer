# Brother QR labels

TDS-Printer supports a dedicated QR workflow for the **Brother QL-1110NWBc**, alongside existing Panduit cable printing. It renders QR and optional captions, provides an identical PNG preview, and sends one label per request over TCP (default port 9100). It does not depend on P-touch Editor or a Windows printer driver.

## Before enabling

**TDS must be the sole owner of the Brother endpoint.** Stop/remove this printer from the old FloorHub print relay's PRINTERS configuration and disable FloorHub delivery/status routing to that relay before using it from TDS. The old `/health` implementation sends initialization commands and can interrupt another service's print. TDS file locks coordinate only TDS workers on the same host, not unrelated services, Windows drivers or other hosts. Use a consistent IP and shared `TDS_PRINTER_LOCK_DIR` on a local filesystem for all workers. DNS aliases of the same device are not deduplicated.

Install updated server dependencies and migrate a backed-up database as part of your normal deployment:

```sh
cd server
python -m pip install -e '.[test]'
alembic upgrade head
```

The migration adds audit fields to print history, backfills existing entries as `cable`, and preserves existing printers, templates and history. This change does not run migration against the installed database automatically.

In Admin → Printers, add a printer using the **QL-1110NWBc** model profile and its IP. The profile sets Brother raster protocol and 300 dpi. Go to **Admin → QR labels**, choose the physical roll and label length, enter the QR contents and optional caption/description, then preview and send. Cable templates and station accounts cannot bind a Brother printer. Reassign existing templates/stations before changing a printer to/from Brother.

Supported continuous rolls:

| Roll | Nominal width | Printable dots | Firmware width byte |
| --- | --- | --- | --- |
| DK-2246 | 103 mm | 1200 | 104 |
| DK-2205 | 62 mm | 696 | 62 |

Length is 30–200 mm of raster content at 300 dpi; printer feed/cut margins are additional. One request makes one label, cut at the end. The selected roll must match the physically loaded roll. TDS declares the selected type/width in the raster command; rejection of mismatched media is expected printer behavior, **not hardware verified**. Loaded media can be observed through the supported Brother SNMP status probe; an unavailable observation remains unknown and does not substitute the configured roll. Additional rolls require explicit profiles and tests; no width/model fallback is used.

## Machine API

Create an API key in Admin → API keys. Keep it on the caller's backend. Use stable integer printer IDs (GET `/api/printers` with admin auth lists them); the existing machine roster `/api/v1/printers` remains compatible with cable clients and lists printer names/protocols, not IDs. Never expose the key in an Inventory browser client.

POST `/api/v1/qr-labels/preview` returns `image/png` and never connects to a printer. POST `/api/v1/qr-labels` sends exactly one label. Both require `X-API-Key`. Printing additionally requires `Idempotency-Key` (1–200 visible ASCII characters, no spaces). Use a fresh random key for each intentional physical label, and **reuse the identical key and body when retrying a lost HTTP response**.

Example (environment variables supplied by the operator):

```sh
curl "$TDS_URL/api/v1/qr-labels/preview" \
  -H "X-API-Key: $TDS_API_KEY" -H 'Content-Type: application/json' \
  --data '{"printer_id":1,"media":"DK-2205","length_mm":60,"scan":"PALLET-001","code":"PALLET-001","description":"Inbound stock","reference":"inventory:spot:17"}' \
  --output label-preview.png

curl "$TDS_URL/api/v1/qr-labels" \
  -H "X-API-Key: $TDS_API_KEY" -H "Idempotency-Key: $LABEL_REQUEST_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"printer_id":1,"media":"DK-2205","length_mm":60,"scan":"PALLET-001","code":"PALLET-001","description":"Inbound stock","reference":"inventory:spot:17"}'
```

The admin equivalents are `/api/qr-labels/preview` and `/api/qr-labels`, using an admin bearer token. Admin keys are scoped by username in a namespace separate from API credentials. The admin and machine endpoint names are also distinct in the request hash. Do not switch authentication or endpoint while retrying a request.

`scan` is encoded exactly as UTF-8 byte data (maximum 512 bytes), including leading/trailing spaces. No trimming, case folding or normalization occurs. Control characters and invalid Unicode are rejected. QR error correction is M, quiet zone four modules, minimum module size four dots. Dense payloads and captions that do not fit are rejected, never silently truncated or resized. `code` (≤80 characters) and `description` (≤240) are optional visible fields; empty fields take no space. Captions use the bundled Carlito font (Latin/Cyrillic); other scripts may show missing-glyph boxes and are not guaranteed. The QR payload itself remains UTF-8. `reference` (≤200) is history metadata only. Preview and printer use the same one-bit bitmap; the adapter adds only the printer's full-head padding and protocol framing.

Success is HTTP 200 with `code: "sent"`, `message`, `log_id`, `printer_id`, and the exact `scan`. It means the bytes were handed to the operating system and the socket was half-closed; peer receipt and physical output are **not confirmed**. The server does not parse status or completion replies. Automatic notifications are disabled (ESC i ! 01) and no status request is included in the raster. Acceptance of these commands on this exact hardware remains unverified.

Delivery failures are HTTP 502 with a `detail` object:

- `error_not_sent`: no raster bytes were attempted (for example lock/connect failure). Fix the problem and explicitly create a new intent/key to retry. Reusing the old key replays its saved failure.
- `uncertain`: sending started, or shutdown/reset failed. Inspect the physical labels before explicitly creating a new intent/key. Never automatically resend.

Invalid geometry/configuration returns 400 with `error_not_sent`. FastAPI validation/auth errors may use the standard 422/401 format. Missing idempotency header is 428 (`key_required`); invalid header is 400 (`invalid_key`). QR-specific 409 codes are `key_conflict` (same key, changed body/endpoint) and `in_progress_or_unknown` (reservation exists but has no completed response). Both require investigation, not a fresh automatic retry. Existing cable API error bodies are unchanged.

Attempts are permanently reserved before delivery; saved responses, including failures, replay without another send. Interrupted/unexpected failures leave the reservation intact. A `sending` history entry means in-progress or interrupted with unknown outcome, not success. Check the printer/history and, if intentionally reissuing, use the workspace's physical-check confirmation to start a new request. Never delete reservations as a recovery mechanism. Unexpected failures can leave the HTTP caller with 500 even if the device received data.

Do not blindly loop a list of labels: send sequentially and stop on an uncertain result. This first release has no batch or automatic replay worker. Maximum 200 mm labels can take several seconds; endpoint lock wait is 30 s, socket send timeout 10 s, drain deadline 2 s. Configure the caller's HTTP timeout accordingly (admin UI uses 60 s). A disconnect or HTTP timeout can happen after output; repeat the same key/body to inspect the stored result.

Existing status pings now acquire the same endpoint lock with zero wait and report busy if printing holds it. The pre-existing single-printer ping route is unauthenticated; deploy behind normal trusted-network/access controls. No ping initializes the Brother.

## Verification and limitations

Tests reconstruct the outgoing uncompressed raster, compare it pixel-for-pixel to the PNG, decode its QR with zxing-cpp, verify media/cut commands and exercise idempotent replay, protocol isolation, migration rollback and transport failure classification. No automated test contacts physical printers. Hardware print/scan, roll mismatch behavior, network notification handling and physical margins still need acceptance on the actual QL-1110NWBc. A nonprinting status probe to 172.16.10.50 timed out during development; no real label was sent.

The supplied `pew6_13_0.exe` was identified as an InstallShield bundle containing `ptedit6.msi` (Brother P-touch Editor). Its embedded cabinet was extracted for static inspection only; no installer or extracted program was run. These are application binaries, not the TDS source or a prerequisite for this network adapter.


## Per-printer status and label settings

In **Admin → Printers → Edit**, configure the printer connection, Brother status monitoring, and QR label defaults. Save before using **Check status**. This check reads the saved connection and SNMP configuration without sending a label.

- Monitoring supports **SNMP v1 read-only** for the supported Brother profile. Configure the UDP port (normally 161) and enable/disable polling per printer. Enable read-only SNMP on the device separately.
- A blank unchanged community field preserves the existing setting. Choose **Replace** to enter a new value, or reset to the service default to inherit `BROTHER_SNMP_COMMUNITY` (default `public`; an empty environment value disables polling). The API never returns the community. The override is stored in the printer service database; protect database backups accordingly.
- Configured label defaults and detected media are separate. QR defaults are DK-2246 / 103 mm and 60 mm length for compatibility with the existing admin workspace. Select DK-2205 for a 62 mm roll. Defaults initialize a clean QR workspace; explicit job settings and previewed/pending print intents remain authoritative.
- ACT Preparation continues to request DK-2205 / 62 mm explicitly. Configuring another default does not change these requests or prove that the matching paper is installed.

Deploy the printer-service migration with `cd server && alembic upgrade head` before starting updated workers. It preserves printer records, calibration and print history. Tests use disposable databases; the installed database is not migrated automatically by this change.

Authenticated admin `GET /api/printers/{id}/status` reports the saved printer's reachability and device observation. Scoped integration catalogs expose optional `qr_defaults` per supported QR printer, alongside the existing normalized `device_status` when requested. They do not expose SNMP connection credentials. Readiness is a device observation, not confirmation that a particular label printed. Status reads keep the existing bounded timeout and cache; no status check retries a print.
