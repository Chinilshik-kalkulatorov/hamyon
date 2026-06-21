# Hamyon — деплой на сервер 24/7 + доступ к Claude через браузер

Это пошаговый runbook. Цель: сервис работает круглосуточно (независимо от твоего
компьютера), а ты управляешь Claude через браузер прямо на сервере.

**Архитектура:**
```
[твой браузер] --SSH-в-браузере (Google-логин)--> VM: tmux + claude   ← даёшь команды
[мир / бот] --HTTPS--> Cloudflare edge --туннель--> cloudflared -> nginx -> gunicorn

VM (Ubuntu 24.04, e2-small): db · redis · web · worker · beat · nginx · cloudflared
Порты наружу: только SSH (22). HTTP/HTTPS наружу НЕ открываем — туннель исходящий.
```

---

## Часть A. Что делаешь ТЫ (по шагам)

### Шаг 1 — Google Cloud
1. Открой https://console.cloud.google.com, войди Google-аккаунтом.
2. Включи billing (привяжи карту; новым аккаунтам обычно дают стартовый кредит).
3. Создай проект, например `hamyon-prod`.

### Шаг 2 — Создай виртуальную машину
Compute Engine → **Create instance**:
- **Name:** `hamyon-1`
- **Region:** ближе к пользователям — `asia-south1` (Мумбаи) или `europe-west3` (Франкфурт)
- **Machine type:** `e2-small` (2 ГБ RAM — нужно для 6 контейнеров; 1 ГБ из free-tier мало)
- **Boot disk:** Ubuntu **24.04 LTS**, размер **30 ГБ**
- **Firewall:** галки «Allow HTTP/HTTPS traffic» **НЕ ставить** (туннель исходящий, порты не нужны)
- (для будущего — чтобы Claude мог сам создавать новые серверы) в разделе
  *Identity and API access* поставь **Allow full access to all Cloud APIs**.
  Роли `Compute Admin` + `Service Account User` сервис-аккаунту можно выдать сейчас или позже.

Нажми **Create**.

### Шаг 3 — Cloudflare (для бесплатного HTTPS)
1. Зарегистрируйся на https://dash.cloudflare.com (бесплатно).
2. Для **постоянного адреса** (его будет использовать бот и клиенты) нужен домен в Cloudflare:
   - заведи самый дешёвый домен (~$1–10/год) и добавь его в Cloudflare, **либо**
   - временно стартуй на quick-туннеле (адрес `*.trycloudflare.com` меняется при перезапуске — годится только для проверки).
3. Если есть домен: Zero Trust → Networks → **Tunnels** → Create tunnel → дай имя →
   на странице туннеля скопируй **токен** (длинная строка `eyJ...`) — он понадобится Claude.
   Public hostname настроим на сервис `http://nginx:80` (это сделаю я).

> Если решишь пойти по quick-туннелю без домена — просто скажи мне, я переключу
> `cloudflared` на временный режим. Но для бота позже лучше домен.

### Шаг 4 — (можно отложить) Telegram-боты
Через @BotFather в Telegram создай бота и получи токен `TELEGRAM_OTP_BOT_TOKEN`
(для реальной отправки OTP). Для демо это не нужно — работает echo-режим.

### Шаг 5 — Запушь ветку с UI в GitHub
Сейчас в GitHub есть только `main`, а демо-UI лежит в ветке `deploy-with-ui`.
**На своём ноутбуке** выполни один раз:
```bash
git push -u origin deploy-with-ui
```
(Эта команда отправит и production-доводки, которые я уже внёс: фикс nginx,
сервис cloudflared, bootstrap-скрипт, эту инструкцию.)

### Шаг 6 — Зайди на сервер и запусти bootstrap
1. GCP Console → Compute Engine → VM `hamyon-1` → кнопка **SSH** (терминал в браузере).
2. Вставь одну команду:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/Chinilshik-kalkulatorov/hamyon/deploy-with-ui/deploy/bootstrap.sh | bash
   ```
   Она поставит Docker, Node, Claude Code, gcloud, GitHub CLI, tmux.
3. **Переподключись по SSH** (закрой и снова открой кнопку SSH) — чтобы docker заработал без sudo.
4. Дальше по подсказке из скрипта:
   ```bash
   gh auth login                                  # доступ к репозиторию (вход в браузере)
   gh repo clone Chinilshik-kalkulatorov/hamyon
   cd hamyon && git checkout deploy-with-ui
   tmux new -s claude
   claude                                         # войди в аккаунт Anthropic
   ```
5. Напиши мне в этой сессии:
   > «Заверши деплой hamyon: собери `.env.prod` со свежими секретами, подними
   > стек и настрой Cloudflare Tunnel (токен: …)».

**С этого момента команды мне даёшь ты — а делаю всё я.**

---

## Часть B. Что сделаю Я (Claude) на сервере

1. Сгенерирую свежие секреты (`DJANGO_SECRET_KEY`, `DB_PASSWORD`, `OTP_PEPPER`, `QR_JWT_SECRET`).
2. Соберу `.env.prod` из `.env.prod.example` (туннель-хост, `CF_TUNNEL_TOKEN`, режимы).
3. Подниму стек: `make deploy` (миграции и `collectstatic` пройдут сами).
4. Настрою Cloudflare Tunnel и проверю публичный HTTPS-адрес.
5. Проверю авто-старт после перезагрузки VM (всё с `restart: unless-stopped`).
6. Прогоню end-to-end демо-сценарий (логин → платёж → OTP → подтверждение → баланс).
7. Дальше — по твоим командам (новые серверы через `gcloud`, Telegram-бот и т.д.).

---

## Как потом давать мне команды через браузер

1. GCP Console → Compute Engine → VM `hamyon-1` → **SSH**.
2. `tmux attach -t claude` → пиши команды.
   (Сессия `claude` живёт в tmux на сервере 24/7 — я «всегда на связи».)

Опционально могу поднять красивый веб-терминал (ttyd / VS Code в браузере) под своим
адресом через тот же туннель + Cloudflare Access (вход по email-коду) — скажи, сделаю.

---

## Справка

- **Стоимость:** e2-small ≈ $13–15/мес, Cloudflare free → итого ~$15/мес.
- **Безопасность:** наружу открыт только SSH (за Google-логином). Приложение доступно
  лишь через конкретный hostname туннеля. Кто имеет SSH к VM — может командовать мной.
- **Реальная эксплуатация (когда выйдем из демо):** в `.env.prod` поставить
  `SEED_DEMO=0` и `OTP_DEMO_ECHO=0`, заполнить `TELEGRAM_OTP_BOT_TOKEN`.
- **Стабильный адрес:** quick-туннель меняет URL при перезапуске; для постоянного —
  домен в Cloudflare + named-туннель (токен в `CF_TUNNEL_TOKEN`).
- **Фаза 4 — Telegram-бот:** будет жить на этой же VM отдельным compose-сервисом и
  ходить в API кошелька (`/api/auth/token/`, `/api/payments/…`, `/api/p2p/…`).
