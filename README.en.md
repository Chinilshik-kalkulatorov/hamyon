<div align="center">

# 💳 Hamyon

**A ledger-based wallet backend — balance is never stored, always derived from an immutable log.**

![Python](https://img.shields.io/badge/Python-3.10-3776AB?logo=python&logoColor=white)
![Django](https://img.shields.io/badge/Django-5.2-092E20?logo=django&logoColor=white)
![DRF](https://img.shields.io/badge/DRF-3.16-A30000)
![Postgres](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-7-DC382D?logo=redis&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-5.5-37814A?logo=celery&logoColor=white)
![Tests](https://img.shields.io/badge/tests-46%20passing-2ee6a8)

[🇺🇿 O‘zbekcha](README.md) · **🇬🇧 English**

</div>

---

## The core idea

A wallet has **no `balance` field**. Every money event is an immutable row in an append-only ledger; the balance is computed from those rows on every read.

```python
# ❌ Wrong — a mutable counter. One crash mid-write = lost money, no audit trail.
wallet.balance += amount; wallet.save()

# ✅ Right — append an event. Balance = SUM(credits) − SUM(debits).
LedgerEntry.objects.create(wallet=w, type="credit", amount=50_000)
```

**Three rules, enforced in code:**
1. Every balance change is a `LedgerEntry` — no silent writes.
2. Entries are append-only — `save()`/`delete()` on an existing row raise; bulk `update()`/`delete()` are blocked at the manager.
3. Balance is always derived on read, never stored.

---

## Quickstart

```bash
docker compose up -d            # PostgreSQL :5544, Redis :6380
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
make migrate && make seed       # demo users: alice / bob  (password: demo123)
make run                        # API at http://localhost:8000
make worker                     # Celery: push notifications, CSV export
make beat                       # Celery beat: expire stale requests
make test                       # 46 tests — sqlite + fakeredis, no docker needed
```

Telegram runs in **console-imitation mode** by default (OTP codes and push messages are printed to the server log). Set `TELEGRAM_*_BOT_TOKEN` in `.env` to switch to the real Bot API — the OTP bot and the push bot are deliberately separate modules with separate tokens.

---

## Features

| Module | What it does |
|---|---|
| **Ledger / Balance** | `Wallet`, `LedgerEntry`, `Transfer`; `balance / available / held` in one aggregated query, cached 5 s. |
| **Payments** | Top-up & withdraw with OTP; `PaymentRequest` state machine; holds released by reversal entries. |
| **P2P + QR** | Atomic two-leg transfers; static QR (wallet id) + dynamic QR (signed single-use JWT). |
| **OTP** | 6-digit code over Telegram; only `sha256(code+pepper)` in Redis; TTL 90 s, 3 attempts → 10-min lock; single-use. |
| **KYC** | `unverified / basic / full` levels with configurable 30-day spend limits; approve/reject state machine. |
| **Blacklist** | Block by user / phone / wallet; middleware gate before every transaction; full audit trail. |
| **History** | Cursor pagination only (offset banned); type/date/status filters; CSV export via Celery. |
| **Notifications** | `post_save` on `LedgerEntry` → Celery → Telegram push, with a delivery log. |

---

## Architecture highlights

- **Money is integer tiyin** (1 UZS = 100), with a DB `CHECK (amount > 0)` — never floats.
- **Balance in one round-trip** — four filtered `SUM`s in a single `aggregate()`; financial decisions bypass the cache and run under `select_for_update()`.
- **Idempotency** — `idempotency_key` is unique at the DB level; a retry returns the existing result, no duplicates even under a concurrent race.
- **Atomic transfers** — debit + credit + `Transfer` row in one transaction; both wallets locked in stable id order to avoid deadlocks.
- **Three guards, in order** — blacklist → KYC → balance/limit; blocked actors get an **empty 403** (no detail leaked).
- **Cursor pagination** — `base64(created_at:id)` seek on an index, constant-time at any depth; a test pins the endpoint to **exactly 2 SQL queries** so offset pagination can't sneak back in.
- **Explicit state machines** — `PaymentRequest` / `TransferRequest` / `KYCApplication` transitions are methods; illegal transitions raise, never pass silently.

---

## API

Auth: `Authorization: Token <key>` (obtain via `POST /api/auth/token/`). All amounts in tiyin.

| Method | Endpoint | |
|---|---|---|
| `GET` | `/api/wallet/{id}/balance/` | derived balance (read-only) |
| `GET` | `/api/wallet/{id}/history/` | cursor-paginated ledger (`?cursor=&type=&status=&from=&to=`) |
| `POST` | `/api/wallet/{id}/history/export/` | CSV export → Telegram link (Celery) |
| `GET` | `/api/wallet/{id}/qr/static/` | reusable receive QR (PNG) |
| `POST` | `/api/payments/initiate/` · `/{id}/confirm/` · `/{id}/cancel/` | top-up / withdraw with OTP |
| `POST` | `/api/p2p/transfer/` · `/transfers/{id}/confirm/` | wallet-to-wallet with OTP |
| `POST` | `/api/p2p/qr/dynamic/` · `/scan/` | issue / verify single-use payment QR |
| `POST` | `/api/kyc/submit/` · `/admin/{id}/approve/` · `/reject/` | KYC flow |
| `POST` | `/api/admin/blacklist/block/` · `/{id}/unblock/` | block / unblock (admin) |

---

## Deployment (production)

One command on a server with a domain:

```bash
cp .env.prod.example .env.prod      # set secrets and your domain
make deploy                          # web + db + redis + worker + beat + nginx
```

Behind `make deploy`: `docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build`.
The `web` container runs `migrate` and `collectstatic` itself; if `SEED_DEMO=1` is set in `.env.prod`, demo users (alice / bob / admin) are created too. **nginx** sits on port 80, serves `static/` and `media/`, and proxies the rest to `gunicorn`.

Point your domain's A record at the server IP and add it to `DJANGO_ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` in `.env.prod`. For HTTPS, put `certbot` in front of nginx (next step). Logs: `make deploy-logs`, stop: `make deploy-down`.

**Just to review it (local, only Docker needed — no Python/Postgres/Redis install):**

```bash
git clone https://github.com/Chinilshik-kalkulatorov/hamyon && cd hamyon
cp .env.prod.example .env.prod        # ready for local, no edits needed
make deploy                            # brings up the whole stack
```

Then open `http://localhost` (API + `/admin/`, admin / admin123). Stop: `make deploy-down`.

---

## Tests

`make test` — 46 tests on sqlite + fakeredis + eager Celery (no docker required): derived balance & holds, append-only enforcement, idempotent retries, full state machines, OTP single-use / lock / hash-only storage, blacklist empty-403, KYC limits & rejection, cursor walk with timestamp ties, the 2-query pin, QR single-use / expiry / tamper, CSV export, notification log.

---

## Tech & layout

`Django 5.2 · DRF · PostgreSQL 16 · Redis 7 · Celery · PyJWT · qrcode · pytest`

```
config/    settings, urls, celery
apps/
  users  core  kyc  blacklist  otp  payments  p2p  history  notifications
tests/     46 tests across all modules
```

## Production notes (out of scope, by design)

DB-level immutability triggers · ledger partitioning + balance snapshots · transactional outbox for pushes · nightly balance reconciliation · OTP send rate-limiting.
