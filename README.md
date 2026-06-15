<div align="center">

# 💳 Hamyon

**Ledger asosidagi hamyon backend — balans hech qachon saqlanmaydi, har doim o‘zgarmas jurnaldan hisoblab chiqiladi.**

![Python](https://img.shields.io/badge/Python-3.10-3776AB?logo=python&logoColor=white)
![Django](https://img.shields.io/badge/Django-5.2-092E20?logo=django&logoColor=white)
![DRF](https://img.shields.io/badge/DRF-3.16-A30000)
![Postgres](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-7-DC382D?logo=redis&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-5.5-37814A?logo=celery&logoColor=white)
![Tests](https://img.shields.io/badge/testlar-46%20passing-2ee6a8)

**🇺🇿 O‘zbekcha** · [🇬🇧 English](README.en.md)

</div>

---

## Asosiy g‘oya

Hamyonda **`balance` maydoni yo‘q**. Har bir pul harakati append-only jurnalga o‘zgarmas yozuv sifatida qo‘shiladi; balans esa har o‘qishda shu yozuvlardan hisoblanadi.

```python
# ❌ Noto‘g‘ri — o‘zgaruvchan hisoblagich. Yozuv o‘rtasida crash = pul yo‘qoladi, audit yo‘q.
wallet.balance += amount; wallet.save()

# ✅ To‘g‘ri — hodisani qo‘shamiz. Balans = SUM(credit) − SUM(debit).
LedgerEntry.objects.create(wallet=w, type="credit", amount=50_000)
```

**Kodda ta’minlangan uchta qoida:**
1. Har qanday balans o‘zgarishi — bu `LedgerEntry`. Yashirin yozuvlar yo‘q.
2. Yozuvlar faqat qo‘shiladi — mavjud yozuvda `save()`/`delete()` xato beradi; ommaviy `update()`/`delete()` manager darajasida bloklangan.
3. Balans har doim o‘qishda hisoblanadi, hech qachon saqlanmaydi.

---

## Tezkor ishga tushirish

```bash
docker compose up -d            # PostgreSQL :5544, Redis :6380
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
make migrate && make seed       # demo foydalanuvchilar: alice / bob  (parol: demo123)
make run                        # API: http://localhost:8000
make worker                     # Celery: push bildirishnomalar, CSV eksport
make beat                       # Celery beat: eskirgan so‘rovlarni bekor qilish
make test                       # 46 ta test — sqlite + fakeredis, docker shart emas
```

Telegram standart holatda **konsol-imitatsiya rejimida** ishlaydi (OTP kodlar va push xabarlar server logiga chiqariladi). Haqiqiy Bot API’ga o‘tish uchun `.env` ga `TELEGRAM_*_BOT_TOKEN` qo‘ying — OTP bot va push bot ataylab alohida modullar, alohida tokenlar bilan.

---

## Imkoniyatlar

| Modul | Vazifasi |
|---|---|
| **Ledger / Balance** | `Wallet`, `LedgerEntry`, `Transfer`; `balance / available / held` bitta aggregat so‘rovda, 5 s kesh. |
| **Payments** | OTP bilan to‘ldirish va yechib olish; `PaymentRequest` holatlar mashinasi; hold’lar reversal yozuv bilan ochiladi. |
| **P2P + QR** | Atomar ikki tomonlama o‘tkazmalar; static QR (wallet id) + dynamic QR (imzolangan, bir martalik JWT). |
| **OTP** | Telegram orqali 6 xonali kod; Redis’da faqat `sha256(code+pepper)`; TTL 90 s, 3 urinish → 10 daqiqa blok; bir martalik. |
| **KYC** | `unverified / basic / full` darajalar, sozlanadigan 30 kunlik limitlar; approve/reject holatlar mashinasi. |
| **Blacklist** | Foydalanuvchi / telefon / hamyon bo‘yicha bloklash; har tranzaksiyadan oldin middleware; to‘liq audit jurnali. |
| **History** | Faqat cursor paginatsiya (offset taqiqlangan); tur/sana/holat filtrlari; Celery orqali CSV eksport. |
| **Notifications** | `LedgerEntry`da `post_save` → Celery → Telegram push, yetkazib berish jurnali bilan. |

---

## Arxitektura yechimlari

- **Pul — butun son tiyin** (1 so‘m = 100), DB `CHECK (amount > 0)` bilan — hech qachon float emas.
- **Balans bitta so‘rovda** — bitta `aggregate()` ichida to‘rtta filtrlangan `SUM`; moliyaviy qarorlar keshni chetlab o‘tib, `select_for_update()` ostida bajariladi.
- **Idempotentlik** — `idempotency_key` DB darajasida unique; takroriy so‘rov mavjud natijani qaytaradi, parallel poyga vaqtida ham dublikat yo‘q.
- **Atomar o‘tkazmalar** — debit + credit + `Transfer` bitta tranzaksiyada; deadlock’ning oldini olish uchun ikkala hamyon barqaror id tartibida lock qilinadi.
- **Uchta guard, tartib bilan** — blacklist → KYC → balans/limit; bloklangan foydalanuvchi **bo‘sh 403** oladi (hech qanday ma’lumot oshkor qilinmaydi).
- **Cursor paginatsiya** — `base64(created_at:id)` indeks bo‘yicha seek, istalgan chuqurlikda doimiy vaqt; test endpointni **aniq 2 ta SQL so‘rovga** bog‘laydi, shunda offset paginatsiya qaytib kira olmaydi.
- **Aniq holatlar mashinalari** — `PaymentRequest` / `TransferRequest` / `KYCApplication` o‘tishlari metodlar; noto‘g‘ri o‘tish xato beradi, hech qachon jim o‘tmaydi.

---

## API

Avtorizatsiya: `Authorization: Token <key>` (`POST /api/auth/token/` orqali olinadi). Barcha summalar tiyinda.

| Method | Endpoint | |
|---|---|---|
| `GET` | `/api/wallet/{id}/balance/` | hisoblangan balans (faqat o‘qish) |
| `GET` | `/api/wallet/{id}/history/` | cursor paginatsiyali jurnal (`?cursor=&type=&status=&from=&to=`) |
| `POST` | `/api/wallet/{id}/history/export/` | CSV eksport → Telegram havola (Celery) |
| `GET` | `/api/wallet/{id}/qr/static/` | qayta ishlatiladigan qabul QR (PNG) |
| `POST` | `/api/payments/initiate/` · `/{id}/confirm/` · `/{id}/cancel/` | OTP bilan to‘ldirish / yechib olish |
| `POST` | `/api/p2p/transfer/` · `/transfers/{id}/confirm/` | OTP bilan hamyondan hamyonga |
| `POST` | `/api/p2p/qr/dynamic/` · `/scan/` | bir martalik to‘lov QR yaratish / tekshirish |
| `POST` | `/api/kyc/submit/` · `/admin/{id}/approve/` · `/reject/` | KYC jarayoni |
| `POST` | `/api/admin/blacklist/block/` · `/{id}/unblock/` | bloklash / blokdan chiqarish (admin) |

---

## Deploy (production)

Domenli serverda bitta buyruq bilan ko‘tariladi:

```bash
cp .env.prod.example .env.prod      # sirlar va domeningizni yozing
make deploy                          # web + db + redis + worker + beat + nginx
```

`make deploy` ortida: `docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build`.
`web` konteyneri o‘zi `migrate` va `collectstatic` ni bajaradi; `.env.prod` da `SEED_DEMO=1` bo‘lsa demo foydalanuvchilar (alice / bob / admin) ham yaratiladi. **nginx** 80-portda turadi: `static/` va `media/` ni o‘zi uzatadi, qolganini `gunicorn` ga proxy qiladi.

Domenni ulash: A-yozuvni server IP’siga yo‘naltiring, `.env.prod` da `DJANGO_ALLOWED_HOSTS` va `CSRF_TRUSTED_ORIGINS` ga domeningizni qo‘shing. HTTPS uchun nginx oldiga `certbot` qo‘shiladi (keyingi qadam). Loglar: `make deploy-logs`, to‘xtatish: `make deploy-down`.

**Faqat ko‘rib chiqish uchun (lokal, faqat Docker kerak — Python/Postgres/Redis o‘rnatish shart emas):**

```bash
git clone https://github.com/Chinilshik-kalkulatorov/hamyon && cd hamyon
cp .env.prod.example .env.prod        # lokal uchun tayyor, o‘zgartirish shart emas
make deploy                            # butun stack ko‘tariladi
```

Tayyor bo‘lgach: `http://localhost` (API + `/admin/`, admin / admin123). To‘xtatish: `make deploy-down`.

---

## Testlar

`make test` — sqlite + fakeredis + eager Celery’da **46 ta test** (docker shart emas): hisoblangan balans va hold’lar, append-only ta’minlash, idempotent takrorlar, to‘liq holatlar mashinalari, OTP bir martalik / blok / faqat-hash saqlash, blacklist bo‘sh-403, KYC limitlari va rad etish, bir xil vaqtli yozuvlar bilan cursor yurish, 2-so‘rov bog‘lash, QR bir martalik / muddati / buzilishi, CSV eksport, bildirishnoma jurnali.

---

## Texnologiyalar va tuzilma

`Django 5.2 · DRF · PostgreSQL 16 · Redis 7 · Celery · PyJWT · qrcode · pytest`

```
config/    settings, urls, celery
apps/
  users  core  kyc  blacklist  otp  payments  p2p  history  notifications
tests/     barcha modullar bo‘yicha 46 ta test
```

## Production tavsiyalar (ataylab qamrov tashqarisida)

DB darajasidagi immutability triggerlari · ledger partitsiyalash + balans snapshotlari · push’lar uchun transactional outbox · har kechagi balans reconciliation · OTP yuborishni rate-limiting.
