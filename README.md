# Hamyon — ledger-based wallet

A wallet backend where **balance is never stored** — every money event is an
immutable row in an append-only ledger, and the balance is always *derived*
from those rows. Built for the "Ledger Wallet System" brief.

**Stack:** Python 3.10 · Django 5.2 + DRF · PostgreSQL 16 · Redis 7 · Celery ·
PyJWT · qrcode · pytest

```
apps/
  users/          custom User (phone, telegram_chat_id, kyc_level)
  core/           Wallet, LedgerEntry, Transfer · balance service · 3 guards
  kyc/            KYCApplication, approve/reject, get_spending_limit()
  blacklist/      BlacklistEntry, middleware gate, block/unblock + audit
  otp/            OTP over Redis (hash+pepper) · its own Telegram channel
  payments/       PaymentRequest state machine, hold/reversal, idempotency
  p2p/            transfers · static/dynamic QR (signed JWT) · scan
  history/        cursor pagination · filters · CSV export via Celery
  notifications/  post_save signal -> Celery -> Telegram push + log
```

## Quickstart

```bash
docker compose up -d            # postgres :5544, redis :6380
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
make migrate && make seed       # demo users: alice, bob (password demo123)
make run                        # API on :8000
make worker                     # celery worker (pushes, CSV export)
make beat                       # celery beat (expires stale requests)
make test                       # 46 tests, sqlite+fakeredis, no docker needed
```

No `TELEGRAM_*_BOT_TOKEN` in `.env` → Telegram runs in **console-imitation
mode**: every OTP and push is printed to stdout instead of sent. Put real bot
tokens into `.env` and the same code talks to the real Bot API.

## The core idea: why a ledger

```
WRONG                                   RIGHT
wallet.balance += amount                LedgerEntry(wallet, type=credit, amount)
wallet.save()                           balance = SUM(credits) - SUM(debits)
```

A mutable balance column loses money on a crash between "check" and "save",
allows silent corrections nobody can audit, and turns concurrent requests into
lost updates. An append-only ledger gives:

* **Crash safety** — an entry either committed or it didn't; there is no
  half-written balance.
* **A free audit trail** — the history *is* the source of truth, not a
  best-effort log next to it.
* **Reproducibility** — the balance at any moment in history can be recomputed.

The three rules enforced in code:

1. Every balance change is a `LedgerEntry` (`core/services/ledger.py` is the
   only writer).
2. Entries are append-only: `LedgerEntry.save()` raises on UPDATE, `delete()`
   always raises, and the custom queryset blocks bulk `update()`/`delete()`.
   Even Django admin is read-only for ledger rows.
3. Balance is derived on read (`core/services/balance.py`), never stored.

### Balance in one query

```
balance   = SUM(credit) - SUM(debit)
held      = SUM(hold)   - SUM(reversal)     -- a reversal releases its hold
available = balance - held
```

One `aggregate()` with four filtered `Sum`s = **one DB round-trip**, cached in
Redis for max 5 seconds. Financial decisions (withdraw/transfer checks) always
bypass the cache and run under `select_for_update()`.

### Money is integers

All amounts are `BigIntegerField` in **tiyin** (1 UZS = 100 tiyin) with a DB
`CHECK (amount > 0)`. Floats accumulate rounding errors; Decimal round-trips
through serialization ambiguously. Integer minor units are exact, compact and
comparison-safe. (Same model as Stripe.)

### Holds without mutation

A hold is released by appending a `reversal` entry pointing at the hold via
`related_entry` — the hold row itself is never touched. So "release" is itself
an auditable event, and `held` stays a pure aggregate.

## Cross-cutting guards

Every transaction endpoint runs three guards **in order**
(`core/services/guards.py`):

1. **Blacklist** — user / phone / wallet checked independently; blocked →
   **403 with an empty body** (no detail leaked). Also enforced earlier as
   Django middleware (`blacklist/middleware.py`) on every POST to
   `/api/payments/*` and `/api/p2p/*`, including wallet ids found in the
   request body.
2. **KYC** — a rejected application blocks all transactions; spending is
   capped per rolling 30-day window by level (`unverified / basic / full`),
   limits configurable in `settings.KYC_SPEND_LIMITS`, not hardcoded.
3. **Balance** — `available >= amount`, computed cache-bypassing, under row
   locks.

## OTP (Telegram)

* 6-digit code from `secrets`; only
  `sha256(code + PEPPER)` is stored, only in Redis:
  `otp:{user_id}:{purpose}` (`payment` / `p2p` / `withdraw`), TTL **90 s**.
* 3 wrong attempts → key destroyed and locked for **10 minutes**
  (`...:lock`). Constant-time compare (`hmac.compare_digest`).
* Single-use: deleted on first successful verify.
* The raw code never appears in logs, error messages, or the database. In
  imitation mode it is printed *as the Telegram message itself*.
* `otp/telegram.py` and `notifications/telegram.py` are deliberately two
  independent modules with separate bot tokens — an outage or rate-limit on
  the push bot can never delay OTP delivery (brief: "share no code path").

## Payments (top-up / withdraw)

State machine, explicit transitions only, invalid ones raise:

```
initiated -> otp_pending -> confirmed | cancelled | expired
```

* **Withdraw**: `initiate()` places a *hold* (reserves `available`), OTP
  confirm writes the real `debit` + releases the hold by `reversal` — one
  atomic transaction.
* **Top-up**: no hold on initiate — the money isn't in the wallet yet, so
  there is nothing to reserve; confirm writes the `credit`. (Deliberate
  interpretation of the brief, worth mentioning at review.)
* **Idempotency**: `idempotency_key` is required and unique; a retry returns
  the existing request (HTTP 200 instead of 201) — no duplicates even under a
  concurrent race (DB constraint, not application logic).
* Stale requests are expired by a Celery beat task every minute; expiry
  releases holds the same reversal way.

## P2P + QR

* Transfer = sender OTP → **one atomic transaction**: `debit` sender,
  `credit` recipient, `Transfer` row linking both entries. Either everything
  commits or nothing does.
* Both wallets are locked with `select_for_update()` **in stable pk order** —
  two opposite simultaneous transfers can't deadlock.
* Blocked if either party is blacklisted or sender's KYC is insufficient.
* **Static QR** — wallet_id only, reusable forever, rendered server-side
  (`qrcode`) as PNG.
* **Dynamic QR** — JWT (HS256, secret in settings) carrying
  `wallet_id + amount + ref_id + exp(15 min)`. `scan()` verifies the
  signature and returns a pre-filled TransferIntent; the client can't tamper
  with the amount. **Single-use**: the QR's `ref_id` becomes the transfer's
  idempotency key, so the DB unique constraint burns it on first use.

## History

* **Cursor pagination only** — the cursor is `base64(created_at:id)`; each
  page is a `WHERE (created_at, id) < (...)` index seek on
  `(wallet, created_at DESC, id DESC)`.
* Why not offset: `OFFSET 50000` scans and throws away 50 000 rows and needs
  a `COUNT(*)` per page; the cursor is O(page) at any depth and stable under
  concurrent inserts (no row shifting). A test pins the endpoint to **exactly
  2 SQL queries** — adding a COUNT would fail the suite.
* Filters: type, date range, status (derived: `pending`/`released` holds,
  `posted` otherwise). Users only ever see their own wallets' entries.
* `export()` → Celery task writes CSV and sends a download link via the push
  Telegram channel.

## Push notifications (imitated)

`post_save(LedgerEntry, created=True)` → `transaction.on_commit` →
Celery task → Telegram message to the owner's confirmed `chat_id`
("You received 50,000 UZS from @alice"), then a `NotificationLog` row
(channel, status sent/failed, timestamp). The HTTP response never waits for
the push; a rolled-back transaction never notifies.

## Security notes

* OTP: hash-only storage, pepper from settings, constant-time compare,
  attempt lock, single-use.
* Blacklisted actors get `403` with an **empty body** — middleware and guard
  return no hint of why.
* KYC stores passport/selfie **references** only, never files.
* Dynamic QR is signed server-side; amount/recipient come from the verified
  token, never from the scanning client.
* Wallet existence is not leaked: foreign wallets answer `404`, not `403`.
* `select_for_update` + stable lock ordering + DB-level unique constraints —
  correctness does not depend on application-level goodwill.

## Production recommendations (out of scope here, said out loud)

* Enforce immutability in the DB too: a trigger / revoked UPDATE,DELETE
  grants on the ledger table — defense in depth beyond the ORM.
* Partition the ledger by month + periodic balance **snapshots** so reads
  stay O(recent) at tens of millions of rows.
* Transactional **outbox** instead of post_save→Celery for pushes (survives
  broker outages without losing events).
* Rate-limit OTP sends per user/phone; alert on lock events.
* A nightly **reconciliation job**: recompute every balance from scratch and
  compare against the cached values; alert on drift.
* Idempotency keys with TTL'd storage for *all* mutating endpoints, not only
  money ones.

## API

| Method | Path | What |
|---|---|---|
| POST | `/api/auth/token/` | obtain DRF token (`username`, `password`) |
| GET/POST | `/api/wallet/` | list / create my wallets |
| GET | `/api/wallet/{id}/balance/` | derived balance (read-only) |
| GET | `/api/wallet/{id}/history/` | cursor-paginated ledger (`?cursor=&type=&status=&from=&to=&page_size=`) |
| POST | `/api/wallet/{id}/history/export/` | CSV via Celery + Telegram link |
| GET | `/api/wallet/{id}/qr/static/` | PNG, reusable receive QR |
| POST | `/api/kyc/submit/` | submit refs (`requested_level`, `passport_ref`, `selfie_ref`) |
| GET | `/api/kyc/status/` | my level, 30-day limit, latest application |
| POST | `/api/kyc/admin/{id}/approve/` · `/reject/` | admin review (reject needs `reason`) |
| POST | `/api/admin/blacklist/block/` | block by `user_id` / `phone` / `wallet_id` |
| POST | `/api/admin/blacklist/{id}/unblock/` | unblock (requires `reason`) |
| GET | `/api/admin/blacklist/history/` | full audit trail |
| POST | `/api/payments/initiate/` | `wallet_id, direction(topup/withdraw), amount, idempotency_key` |
| POST | `/api/payments/{id}/confirm/` | `{code}` — OTP confirm |
| POST | `/api/payments/{id}/cancel/` | cancel, releases hold |
| GET | `/api/payments/{id}/` | status |
| POST | `/api/p2p/transfer/` | explicit fields **or** `{sender_wallet, qr_token}` |
| POST | `/api/p2p/transfers/{id}/confirm/` | sender OTP confirm |
| POST | `/api/p2p/qr/dynamic/` | issue signed single-use QR (`wallet_id, amount`) |
| POST | `/api/p2p/scan/` | verify token → TransferIntent |

Amounts everywhere are **tiyin** (integer). Auth:
`Authorization: Token <key>`.

## Demo walkthrough

```bash
make seed    # prints tokens + wallet ids for alice and bob

T_ALICE=...  W_ALICE=...  W_BOB=...

# top-up 50,000 UZS
curl -s -X POST :8000/api/payments/initiate/ \
  -H "Authorization: Token $T_ALICE" -H 'Content-Type: application/json' \
  -d "{\"wallet_id\":\"$W_ALICE\",\"direction\":\"topup\",\"amount\":5000000,
       \"idempotency_key\":\"$(uuidgen)\"}"
# server console prints: [TELEGRAM-IMITATION otp-bot -> ...] Hamyon code: 123456 ...
curl -s -X POST :8000/api/payments/<id>/confirm/ \
  -H "Authorization: Token $T_ALICE" -H 'Content-Type: application/json' \
  -d '{"code":"123456"}'

# P2P with OTP
curl -s -X POST :8000/api/p2p/transfer/ ... # then /confirm/ with the code

# history, first page of 5
curl -s ":8000/api/wallet/$W_ALICE/history/?page_size=5" \
  -H "Authorization: Token $T_ALICE"
```

## Tests

`make test` — 46 tests on sqlite + fakeredis + eager Celery (no docker
needed): derived balance & holds, append-only enforcement, idempotent
initiate/retry, full state machine, OTP single-use & 3-attempt lock & hash-only
storage, blacklist empty-403 (middleware and guard), KYC limits & rejection,
cursor walk with timestamp ties, the 2-query pin on history, QR single-use /
expiry / tamper, CSV export, notification log.
