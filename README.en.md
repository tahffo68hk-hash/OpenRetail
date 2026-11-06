# OpenRetail V2 · Self-hosted small-store transaction and device platform

[中文](README.md)

> **Status: deployable staged pilot source / NOT CLEARED FOR UNATTENDED PRODUCTION.**
> Suitable for local demos, integration tests, and a **staffed checkout pilot** after merchant, payment, network, and operator review.
> **Not a finished unattended store.** There is no verified phone or identity check, no live electric lock, no complete remote attendant, no item-level loss prevention, and no production refund, reconciliation, or on-site fire-egress acceptance.

Designed for a 20–50 m² daily-goods shop. It integrates the boundaries of **OSPOS CSV / ERPNext Frappe REST / Home Assistant REST / ESPHome read-only door contact / Frigate MQTT**. It does not copy or mix those upstream codebases.

## 1. What is implemented

- **Catalog:** barcode, name, price, active flag, and sellable stock. Chinese responsive web UI, USB scanner input, and `BarcodeDetector` where the browser supports it.
- **Orders:** server-side pricing, idempotent `request_id`, single-database `BEGIN IMMEDIATE`, stock reserved at order creation, released on cancel or expiry, and both on-hand and reserved stock reduced at settlement. Stock movements and order audit are recorded.
- **Payments:** demo mode uses `MOCK_NOT_REAL_MONEY`. A WeChat Pay APIv3 **Native QR adapter** signs requests with RSA-SHA256, verifies platform responses and notifications, decrypts AES-256-GCM payloads, checks amount, merchant, and currency, and treats repeat notifications as idempotent. An operator can query an order or close a timed-out order and release the reservation. **No live merchant credentials have been used, and automatic refunds are not implemented.**
- **Admin:** PBKDF2 password hash, HttpOnly/SameSite cookie, CSRF protection, login lockout, audit, and stock, order, and event management. The legacy `X-Admin-Key` works only in demo mode and is disabled for staging and production.
- **Staffed entry to checkout:** while the store is staffed, an employee issues a **120-second one-time checkout QR**. The customer redeems a one-hour shopping session. This is not identity verification, does not authorize a lock, and cannot be used for unattended operation.
- **Door:** Home Assistant connectivity and event adapter. Physical unlock stays **prohibited**. Demo mode can simulate a door action. Power loss, network loss, and emergency exit are on-site hardware acceptance items.
- **Monitoring:** Frigate `frigate/events` MQTT bridge can show person detections. It does not decide theft. The ESPHome sample is a read-only door-contact example.
- **Inventory bridge:** one-time OSPOS-style CSV import. After the first order, stock overwrite is refused. ERPNext `Item` is a read-only REST preview. OSPOS, ERPNext, and OpenRetail must not all be treated as the inventory authority at once.
- **Self-hosting:** single-instance SQLite WAL, schema upgrade, offline tests, Docker Compose single instance as non-root on loopback, online SQLite backup, health check, and deployment preflight.

## 2. Profiles

`APP_MODE` has three profiles. `pilot` remains a legacy alias of `staging`.

| Profile | Use | Mock payment | Physical unlock |
|---|---|---|---|
| `demo` | Local demonstration | Allowed, recorded as `MOCK_NOT_REAL_MONEY` | Rejected at startup |
| `staging` | Staffed pre-production | Rejected; it is not a real sale | Rejected at startup |
| `production` | Production | Rejected | Rejected at startup; Compose also forces `LIVE_DOOR_ENABLED=false` |

Examples: `.env.demo.example`, `.env.staging.example`, `.env.production.example`. Real secrets belong only in an uncommitted `.env`.

## 3. Windows start, stop, backup, and restore

Requires Python 3.11+. Run these commands in the project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts\init_env.py
.\.venv\Scripts\python.exe scripts\doctor.py --init-demo
.\.venv\Scripts\python.exe -m uvicorn openretail.main:app --host 127.0.0.1 --port 8000
```

`--init-demo` creates a database only in demo mode when no business database exists. Staging, production, and an existing business database are not created or overwritten. Routine checks omit that flag:

```powershell
.\.venv\Scripts\python.exe scripts\doctor.py
```

Open http://127.0.0.1:8000. The demo flow is: create a guest session, add an item, create an order, and confirm a mock payment. Demo admin login uses `ADMIN_KEY` from `.env`. The key is not written into the page. Staging and production use an admin password:

```powershell
.\.venv\Scripts\python.exe scripts\set_admin_password.py
```

Stop the server with Ctrl+C in the uvicorn window. If that window is already closed, stop only the process listening on port 8000:

```powershell
$procId = (Get-NetTCPConnection -LocalPort 8000 -State Listen).OwningProcess
Stop-Process -Id $procId
```

Backup uses the SQLite online backup API. Do not copy a WAL file by itself:

```powershell
.\.venv\Scripts\python.exe scripts\backup.py
```

Restore must write a different file. The script refuses to replace the live database named by `DB_PATH`:

```powershell
.\.venv\Scripts\python.exe scripts\restore.py --backup .\backups\openretail-TIMESTAMP.sqlite3 --dest .\restore-drill\restored.sqlite3
```

After the restored file reports PASS, a person decides whether to replace the live database during a maintenance window. The restore command does not do that replacement.

Regression:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## 4. Docker

The published port is only `127.0.0.1:8000`. The container runs one worker, and data lives in named volumes. A successful config check is not a successful start when Docker Engine is absent.

```powershell
docker compose config
docker compose up --build -d
docker compose ps
docker compose exec openretail python scripts/backup.py
docker compose down
```

The image uses single-node SQLite transactions. Do not put the data volume on NFS, and do not run multiple writers.

## 5. Staffed pilot (only after configuration is complete)

1. Back up the current data. Create an admin password. Set `APP_MODE=staging` or `production`, `MOCK_PAYMENTS_ENABLED=false`, `TRUSTED_PROXY_TLS=true`, and `PUBLIC_BASE_URL=https://your-configured-domain`. The HTTPS reverse proxy must actually be configured. Setting the variable alone is not enough. `production` also rejects mock payments and physical unlock.
2. Apply for a WeChat merchant account and Native Pay permission. Set `PAYMENT_PROVIDER=wechat_native` and the merchant id, certificate private key, platform public key, APIv3 key, and notify URL required by `.env.example`. **Never commit private keys, certificates, or `.env`.**
3. Complete official payment tests: order id, amount, repeated callbacks, disconnects, query, close, timeout, refund, and end-of-day reconciliation. **Refunds are not coded yet.** Do not take live money until a refund implementation or a separate manual refund procedure exists.
4. In the admin UI, create products and stock. An employee issues a 120-second one-time checkout QR. The customer scans it to get a self-checkout session. Show the WeChat Native payment QR on **another screen or device**. In-WeChat H5/JSAPI payment on the same device is not implemented.
5. For orders that started payment but received no callback, an operator can call `POST /api/admin/orders/{order_id}/reconcile-wechat`. A reservation is released only after WeChat confirms `CLOSED`. A successful payment is the verified callback or the verified merchant query.

`staging` and `production` cannot create an anonymous guest session, cannot switch to unattended operation, and cannot control a physical lock. That is an intentional safety boundary. `pilot` is the legacy alias of `staging`.

## 6. Upstream projects and limits

| Project | Implemented here | Still requires a separate deployment |
|---|---|---|
| [OSPOS](https://github.com/opensourcepos/opensourcepos) | CSV catalog import and preview | OSPOS itself; no live order dual-write; keep its special footer attribution |
| [Home Assistant](https://developers.home-assistant.io/docs/api/rest/) | Connectivity check and event publish | A separate install; physical door control stays prohibited |
| [ESPHome](https://esphome.io/) | Read-only door-contact sample | Firmware, sensors, and safe electrical work; a homemade relay is not the only commercial door control |
| [Frigate](https://docs.frigate.video/integrations/mqtt/) | MQTT event bridge | Broker, cameras, NVR, and retention; not item-level theft detection |
| [ERPNext](https://docs.frappe.io/framework/user/en/api/rest) | Read-only Frappe `Item` API | ERP, stock, and order mapping, ownership, and conflict policy are undecided |

Check OSPOS's special LICENSE attribution, ERPNext's GPLv3, and the other upstream licenses before redistribution. This repository does not copy their source.

## 7. Safety boundary and acceptance

- **No live charge is sent by default.** No merchant secret is included, and no physical lock is connected.
- **Payment must not be a condition for leaving.** The door needs an independent emergency release and a power-failure behavior that meets local fire and building rules.
- **A Frigate person detection is not theft detection.** Remote staff, stock counts, customer privacy notice, and exception handling are still required.
- Live mobile WeChat or Alipay, refunds and settlement reconciliation, remote customer service, phone or identity verification, a controllable door, item-level loss prevention, bidirectional ERP consistency, and production database HA are not done.
- Door safety, payment qualification, video privacy, network deployment, and financial reconciliation must be accepted against the real address, door, merchant, and devices.

See `docs/ARCHITECTURE.md` and `docs/AGENT_HANDOFF.md`.

Long-term management notes from the 2026-11-06 source check are in Chinese and separate what was re-run from what was only claimed:

- [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md)
- [`docs/DECISIONS.md`](docs/DECISIONS.md)
- [`docs/API_INVENTORY.md`](docs/API_INVENTORY.md)
- [`docs/HARDWARE_PLAN.md`](docs/HARDWARE_PLAN.md)
- [`docs/PRODUCTION_GATE.md`](docs/PRODUCTION_GATE.md)
- [`docs/TECH_ROADMAP.md`](docs/TECH_ROADMAP.md)

## 8. Optional isolated browser check

```bash
pip install -r requirements-ui.txt
# Requires Chromium (system chromium/google-chrome or a Playwright browser)
python scripts/ui_bridge_smoke.py
```

The script renders the real HTML, CSS, and JavaScript in Chromium and bridges HTTP calls to the FastAPI TestClient. It is for offline UI regression. It does not replace a real domain, HTTPS, a phone browser, or a payment-terminal acceptance test.
