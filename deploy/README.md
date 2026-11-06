# deploy/

Production deployment files. Nothing here is applied automatically — copy,
edit the paths/hostnames marked `EDIT`, and reload.

```
deploy/
├── nginx/
│   ├── tds-printer.conf            MODE A — trusted LAN, :80, IP-gated
│   ├── tds-printer-tls.conf        MODE B — public domain, :443 + HSTS
│   └── snippets/
│       ├── tds-printer-app.conf        root, body limit, all locations, gzip
│       ├── tds-printer-proxy.conf      uvicorn proxy plumbing + 300s timeouts
│       ├── tds-printer-headers.conf    security headers (HSTS via $tds_hsts)
│       └── tds-printer-csp.conf        the app's Content-Security-Policy
├── systemd/
│   └── tds-printer.service         uvicorn unit, /opt/tds-printer layout
└── tds-printer.service             uvicorn unit, /opt/TDS-Printer layout,
                                    with pip-install-on-start + sandboxing
```

**Two systemd units, not one.** They assume different install trees and are not
interchangeable; install one and ignore the other. `systemctl cat tds-printer`
on the host says which is live. Neither may gain `--workers`: the login
throttle in `server/app/login_limits.py` is process-local by design, so extra
workers quietly multiply the brute-force allowance on
`POST /api/auth/login` and `POST /api/station-auth/login`. Both files carry the
full reasoning.

## Pick a mode

Install **exactly one** of the two site files. Both are complete and valid on
their own, and both `include snippets/tds-printer-app.conf`, so neither can
lose the 50M body limit, the 300s print timeouts, the tighter `/docs`
allowlist, the SPA history-mode fallback, the `/assets/` immutable caching,
`no-cache` on `index.html`, or the security headers. Enabling both fails
`nginx -t` on a duplicate `upstream tds_api`, on purpose.

| | MODE A `tds-printer.conf` | MODE B `tds-printer-tls.conf` |
|---|---|---|
| Listener | `:80` plain HTTP | `:443` TLS, `:80` → 301 |
| Site-wide IP allowlist | yes (`10/8`, `192.168/16`, …) | **no** — inappropriate on a public domain |
| HSTS | never emitted (`$tds_hsts` is empty without TLS) | `max-age=31536000; includeSubDomains` |
| What protects the app | the edge allowlist, even with zero stations | TLS + app-level auth, **only if stations exist** |

Install (either mode — the snippets are required by both):

```bash
sudo mkdir -p /etc/nginx/snippets
sudo cp deploy/nginx/snippets/*.conf /etc/nginx/snippets/
sudo cp deploy/nginx/<chosen file> /etc/nginx/sites-available/tds-printer
sudo ln -s /etc/nginx/sites-available/tds-printer /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## Before you trust the live host

The live deployment is **https://print.hload.dev**, i.e. MODE B. Nothing in
this repository can inspect it. The **OPERATOR CHECKLIST** at the top of
[`nginx/tds-printer-tls.conf`](nginx/tds-printer-tls.conf) is the authoritative
list of what to verify there, with the exact commands. The two findings that
decide whether the host is safe at all:

1. **Is the IP allowlist still in place?** The config originally shipped for a
   LAN gated the whole site with `deny all`. Whether that survived the move to
   a public domain is unknown from here, and it changes what else you need.
2. **With no provisioned `Station` rows the app has no authentication of its
   own.** `require_reader` in `server/app/auth_station.py` enforces a token
   only while `stations_required(db)` is true, which needs at least one
   `Station` row. Until then the catalogue reads and the operator print path
   answer anyone who can reach the host — by design, so a fresh LAN install
   stays passwordless.
