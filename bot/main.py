"""Hamyon Telegram bot — интерактивный интерфейс к API кошелька.

Долгий поллинг (getUpdates) — только исходящие соединения, портов наружу не нужно.
Бот живёт рядом с кошельком в той же docker-сети и ходит в API по http://web:8000.

Тот же токен (TELEGRAM_OTP_BOT_TOKEN) кошелёк использует для ОТПРАВКИ OTP, а бот —
для ПРИЁМА команд. Это не конфликтует: poll (бот) и sendMessage (кошелёк) независимы.

Двуязычный (ru/uz): язык хранится per-chat в сессии, переключается /lang или кнопкой.

Команды:
  /start /help /menu       — меню и список команд
  /info                    — что это за проект (ссылка на /about)
  /login <user> <pass>     — войти (получить API-токен и привязать чат)
  /logout /whoami          — выйти / статус
  /balance /history        — баланс / последние операции
  /stats                   — аналитика за 30 дней
  /limit                   — остаток KYC-лимита
  /qr                      — мой QR для приёма переводов
  /send <кому> <сумма>     — перевод; /confirm <код>; /cancel
  /lang                    — сменить язык (ru/uz)
"""

import json
import logging
import os
import time
import uuid

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("hamyon.bot")

TOKEN = os.environ.get("TELEGRAM_OTP_BOT_TOKEN", "").strip()
API_BASE = os.environ.get("API_BASE", "http://web:8000").rstrip("/")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://hamyon.duckdns.org").rstrip("/")
ABOUT_URL = f"{PUBLIC_BASE_URL}/about/"
TG = f"https://api.telegram.org/bot{TOKEN}"
SESSIONS_PATH = os.environ.get("BOT_SESSIONS_PATH", "/data/sessions.json")

# chat_id (str) -> {"lang": str, "token": str, "username": str, "pending": {...}}
sessions: dict[str, dict] = {}

# ---------------------------------------------------------------- i18n ---

STR = {
    "ru": {
        "welcome": (
            "👋 <b>Hamyon</b> — кошелёк прямо в Telegram.\n\n"
            "Команды:\n"
            "• /login <i>логин пароль</i> — войти\n"
            "• /balance — баланс · /history — операции\n"
            "• /stats — аналитика · /limit — KYC-лимит\n"
            "• /qr — мой QR · /info — о проекте\n"
            "• /send <i>кому сумма</i> — перевод (ник/телефон, UZS)\n"
            "• /confirm <i>код</i> · /cancel — подтвердить/отменить\n"
            "• /lang — язык · /whoami — статус · /logout — выйти\n\n"
            "Демо-вход: <code>/login alice demo123</code>"
        ),
        "menu_title": "Меню — выбери действие:",
        "m_balance": "💰 Баланс", "m_history": "🧾 История", "m_stats": "📊 Аналитика",
        "m_limit": "🎚 Лимит", "m_qr": "📲 Мой QR", "m_info": "ℹ️ О проекте", "m_lang": "🌐 Til/Язык",
        "need_login": "Сначала войди: <code>/login логин пароль</code>",
        "login_format": "Формат: <code>/login логин пароль</code>",
        "login_bad": "❌ Неверный логин или пароль.",
        "service_down": "⚠️ Сервис недоступен, попробуй позже.",
        "login_ok": "✅ Вход выполнен как <b>{username}</b>. {tail}\nЖми /menu или /balance.",
        "tail_bound": "OTP-коды теперь будут приходить в этот чат.",
        "tail_unbound": "(OTP-привязку включить не удалось — коды придут другим способом.)",
        "logout_ok": "Вышел. /login — чтобы войти снова.",
        "logout_none": "Ты и так не в системе.",
        "no_wallet": "Кошелёк не найден.",
        "balance": "💰 Баланс: <b>{bal}</b>\nДоступно: {avail}",
        "balance_held": "\nВ холде: {held}",
        "history_title": "🧾 <b>Последние операции:</b>",
        "history_empty": "Операций пока нет.",
        "history_fail": "Не удалось получить историю.",
        "h_credit": "зачисление", "h_debit": "списание", "h_hold": "заморозка", "h_reversal": "разморозка",
        "send_format": "Формат: <code>/send кому сумма</code>\nНапример: <code>/send bob 500</code>",
        "send_bad_amount": "Сумма должна быть положительным числом (UZS). Пример: <code>/send bob 500</code>",
        "recipient_not_found": "Получатель не найден. Проверь ник или телефон.",
        "transfer_created": (
            "🔐 Перевод <b>{amount}</b> → <b>{recipient}</b> создан.\n"
            "Код отправлен в этот чат. Подтверди: <code>/confirm код</code>\nОтменить: /cancel"
        ),
        "demo_code": "\n\n<i>демо-код: {code}</i>",
        "confirm_no_pending": "Нет активного перевода. Сначала /send <кому> <сумма>.",
        "confirm_format": "Формат: <code>/confirm код</code> (6 цифр).",
        "transfer_done": "✅ Перевод <b>{amount}</b> → <b>{recipient}</b> выполнен.",
        "balance_left": "\n💰 Остаток: {bal}",
        "cancel_ok": "Черновик перевода отменён. (Запрос сам истечёт на сервере.)",
        "cancel_none": "Нет активного перевода.",
        "whoami_in": "вошёл как <b>{username}</b>", "whoami_out": "не в системе",
        "whoami": "chat_id: <code>{chat_id}</code>\nСтатус: {state}{extra}",
        "whoami_draft": "\nЧерновик: {amount} → {recipient} (ждёт /confirm)",
        "info": (
            "ℹ️ <b>Hamyon</b> — это ledger-кошелёк: деньги хранятся не как одно число, "
            "а как неизменяемый журнал операций (как в банках). Пополнение, перевод по нику "
            "или QR, OTP-подтверждение, KYC-лимиты.\n\n"
            "Как это устроено простыми словами:\n{url}"
        ),
        "stats_title": "📊 <b>Аналитика за 30 дней</b>",
        "stats_in": "Поступило", "stats_out": "Потрачено", "stats_net": "Нетто",
        "bd_topup": "Пополнения", "bd_received": "Получено", "bd_withdraw": "Выводы", "bd_sent": "Отправлено",
        "stats_top": "Топ-контрагенты", "stats_empty": "За 30 дней операций не было.",
        "limit": (
            "🎚 <b>KYC-лимит ({level})</b>\n"
            "Лимит на 30 дней: <b>{limit}</b>\nПотрачено: {spent}\nОсталось: <b>{remaining}</b>"
        ),
        "qr_caption": "📲 Твой постоянный QR. Покажи его, чтобы тебе перевели.",
        "qr_fail": "Не удалось получить QR.",
        "lang_prompt": "Выбери язык / Tilni tanlang:",
        "lang_set": "Готово. Язык: Русский 🇷🇺",
        "unknown_cmd": "Неизвестная команда. /help — список.",
        "not_command": "Не понял. /menu — меню, /help — команды.",
        "internal_error": "⚠️ Внутренняя ошибка, попробуй ещё раз.",
        "op_blocked": "Операция заблокирована.",
        "err_generic": "Ошибка ({status}).",
        "err_insufficient_funds": "Недостаточно средств.",
        "err_recipient_not_found": "Получатель не найден.",
        "err_otp_invalid": "Неверный код. Попробуй ещё раз: /confirm <код>",
        "err_otp_missing_or_expired": "Код истёк. Начни перевод заново: /send <кому> <сумма>",
        "err_otp_locked": "Слишком много попыток. Подожди 10 минут.",
        "err_kyc_limit_exceeded": "Превышен лимит по твоему уровню KYC.",
        "err_kyc_rejected": "KYC отклонён.",
        "err_invalid_state_transition": "Перевод уже завершён или недоступен.",
    },
    "uz": {
        "welcome": (
            "👋 <b>Hamyon</b> — to‘g‘ridan-to‘g‘ri Telegramdagi hamyon.\n\n"
            "Buyruqlar:\n"
            "• /login <i>login parol</i> — kirish\n"
            "• /balance — balans · /history — amallar\n"
            "• /stats — tahlil · /limit — KYC limiti\n"
            "• /qr — mening QR · /info — loyiha haqida\n"
            "• /send <i>kimga summa</i> — o‘tkazma (login/telefon, UZS)\n"
            "• /confirm <i>kod</i> · /cancel — tasdiqlash/bekor qilish\n"
            "• /lang — til · /whoami — holat · /logout — chiqish\n\n"
            "Demo kirish: <code>/login alice demo123</code>"
        ),
        "menu_title": "Menyu — amalni tanlang:",
        "m_balance": "💰 Balans", "m_history": "🧾 Tarix", "m_stats": "📊 Tahlil",
        "m_limit": "🎚 Limit", "m_qr": "📲 Mening QR", "m_info": "ℹ️ Loyiha haqida", "m_lang": "🌐 Til/Язык",
        "need_login": "Avval kiring: <code>/login login parol</code>",
        "login_format": "Format: <code>/login login parol</code>",
        "login_bad": "❌ Login yoki parol noto‘g‘ri.",
        "service_down": "⚠️ Xizmat mavjud emas, keyinroq urinib ko‘ring.",
        "login_ok": "✅ <b>{username}</b> sifatida kirdingiz. {tail}\n/menu yoki /balance bosing.",
        "tail_bound": "OTP kodlar endi shu chatga keladi.",
        "tail_unbound": "(OTP bog‘lashni yoqib bo‘lmadi — kodlar boshqa yo‘l bilan keladi.)",
        "logout_ok": "Chiqdingiz. Qayta kirish: /login.",
        "logout_none": "Siz allaqachon tizimda emassiz.",
        "no_wallet": "Hamyon topilmadi.",
        "balance": "💰 Balans: <b>{bal}</b>\nMavjud: {avail}",
        "balance_held": "\nMuzlatilgan: {held}",
        "history_title": "🧾 <b>So‘nggi amallar:</b>",
        "history_empty": "Hozircha amallar yo‘q.",
        "history_fail": "Tarixni olishning iloji bo‘lmadi.",
        "h_credit": "kirim", "h_debit": "chiqim", "h_hold": "muzlatish", "h_reversal": "bo‘shatish",
        "send_format": "Format: <code>/send kimga summa</code>\nMasalan: <code>/send bob 500</code>",
        "send_bad_amount": "Summa musbat son bo‘lishi kerak (UZS). Masalan: <code>/send bob 500</code>",
        "recipient_not_found": "Qabul qiluvchi topilmadi. Login yoki telefonni tekshiring.",
        "transfer_created": (
            "🔐 <b>{amount}</b> → <b>{recipient}</b> o‘tkazmasi yaratildi.\n"
            "Kod shu chatga yuborildi. Tasdiqlang: <code>/confirm kod</code>\nBekor qilish: /cancel"
        ),
        "demo_code": "\n\n<i>demo-kod: {code}</i>",
        "confirm_no_pending": "Faol o‘tkazma yo‘q. Avval /send <kimga> <summa>.",
        "confirm_format": "Format: <code>/confirm kod</code> (6 raqam).",
        "transfer_done": "✅ <b>{amount}</b> → <b>{recipient}</b> o‘tkazma bajarildi.",
        "balance_left": "\n💰 Qoldiq: {bal}",
        "cancel_ok": "O‘tkazma qoralamasi bekor qilindi. (So‘rov serverda o‘zi tugaydi.)",
        "cancel_none": "Faol o‘tkazma yo‘q.",
        "whoami_in": "<b>{username}</b> sifatida kirgan", "whoami_out": "tizimda emas",
        "whoami": "chat_id: <code>{chat_id}</code>\nHolat: {state}{extra}",
        "whoami_draft": "\nQoralama: {amount} → {recipient} (/confirm kutilmoqda)",
        "info": (
            "ℹ️ <b>Hamyon</b> — bu ledger-hamyon: pul bitta son sifatida emas, balki "
            "o‘zgarmas amallar jurnali sifatida saqlanadi (banklardagidek). To‘ldirish, "
            "login yoki QR bo‘yicha o‘tkazma, OTP tasdiq, KYC limitlari.\n\n"
            "Oddiy so‘zlar bilan qanday ishlashi:\n{url}"
        ),
        "stats_title": "📊 <b>30 kunlik tahlil</b>",
        "stats_in": "Tushdi", "stats_out": "Sarflandi", "stats_net": "Sof",
        "bd_topup": "To‘ldirishlar", "bd_received": "Qabul qilindi", "bd_withdraw": "Yechishlar", "bd_sent": "Yuborilgan",
        "stats_top": "Top-kontragentlar", "stats_empty": "30 kun ichida amal bo‘lmagan.",
        "limit": (
            "🎚 <b>KYC limiti ({level})</b>\n"
            "30 kunlik limit: <b>{limit}</b>\nSarflangan: {spent}\nQoldi: <b>{remaining}</b>"
        ),
        "qr_caption": "📲 Sizning doimiy QR. Pul o‘tkazishlari uchun ko‘rsating.",
        "qr_fail": "QR olishning iloji bo‘lmadi.",
        "lang_prompt": "Tilni tanlang / Выберите язык:",
        "lang_set": "Tayyor. Til: O‘zbekcha 🇺🇿",
        "unknown_cmd": "Noma’lum buyruq. /help — ro‘yxat.",
        "not_command": "Tushunmadim. /menu — menyu, /help — buyruqlar.",
        "internal_error": "⚠️ Ichki xato, qayta urinib ko‘ring.",
        "op_blocked": "Amal bloklangan.",
        "err_generic": "Xato ({status}).",
        "err_insufficient_funds": "Mablag‘ yetarli emas.",
        "err_recipient_not_found": "Qabul qiluvchi topilmadi.",
        "err_otp_invalid": "Noto‘g‘ri kod. Qayta urinib ko‘ring: /confirm <kod>",
        "err_otp_missing_or_expired": "Kod muddati tugadi. Qaytadan: /send <kimga> <summa>",
        "err_otp_locked": "Juda ko‘p urinish. 10 daqiqa kuting.",
        "err_kyc_limit_exceeded": "KYC darajangiz bo‘yicha limit oshib ketdi.",
        "err_kyc_rejected": "KYC rad etilgan.",
        "err_invalid_state_transition": "O‘tkazma allaqachon yakunlangan yoki mavjud emas.",
    },
}


def get_lang(chat_id) -> str:
    return sessions.get(str(chat_id), {}).get("lang", "ru")


def set_lang(chat_id, lang: str) -> None:
    sessions.setdefault(str(chat_id), {})["lang"] = lang
    save_sessions()


def T(chat_id, key: str, **fmt) -> str:
    lang = get_lang(chat_id)
    raw = STR.get(lang, STR["ru"]).get(key) or STR["ru"].get(key, key)
    return raw.format(**fmt) if fmt else raw


# ----------------------------------------------------------- persistence ---

def load_sessions() -> None:
    global sessions
    try:
        with open(SESSIONS_PATH) as f:
            sessions = json.load(f)
        log.info("loaded %d session(s)", len(sessions))
    except (FileNotFoundError, json.JSONDecodeError):
        sessions = {}


def save_sessions() -> None:
    os.makedirs(os.path.dirname(SESSIONS_PATH), exist_ok=True)
    tmp = SESSIONS_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(sessions, f)
    os.replace(tmp, SESSIONS_PATH)


# -------------------------------------------------------------- telegram ---

def send(chat_id, text: str, buttons=None) -> None:
    """buttons: list of rows, each row a list of (label, callback_data) tuples."""
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
               "disable_web_page_preview": True}
    if buttons:
        payload["reply_markup"] = {
            "inline_keyboard": [
                [{"text": lbl, "callback_data": data} for (lbl, data) in row]
                for row in buttons
            ]
        }
    try:
        requests.post(f"{TG}/sendMessage", json=payload, timeout=10)
    except requests.RequestException:
        log.warning("sendMessage failed for chat %s", chat_id)


def answer_callback(callback_id) -> None:
    try:
        requests.post(f"{TG}/answerCallbackQuery",
                      json={"callback_query_id": callback_id}, timeout=10)
    except requests.RequestException:
        pass


def menu_buttons(chat_id):
    return [
        [(T(chat_id, "m_balance"), "cmd:balance"), (T(chat_id, "m_history"), "cmd:history")],
        [(T(chat_id, "m_stats"), "cmd:stats"), (T(chat_id, "m_limit"), "cmd:limit")],
        [(T(chat_id, "m_qr"), "cmd:qr"), (T(chat_id, "m_info"), "cmd:info")],
        [(T(chat_id, "m_lang"), "cmd:lang")],
    ]


# ------------------------------------------------------------------ api ---

def api_get(token: str, path: str):
    return requests.get(
        f"{API_BASE}{path}", headers={"Authorization": f"Token {token}"}, timeout=10
    )


def api_post(token: str, path: str, body: dict):
    return requests.post(
        f"{API_BASE}{path}",
        headers={"Authorization": f"Token {token}"},
        json=body,
        timeout=10,
    )


def err_text(chat_id, resp) -> str:
    if resp.status_code == 403 and not resp.text.strip():
        return T(chat_id, "op_blocked")
    try:
        code = resp.json().get("code")
    except ValueError:
        code = None
    key = f"err_{code}" if code else None
    if key and (get_lang(chat_id) in STR and key in STR["ru"]):
        return T(chat_id, key)
    return T(chat_id, "err_generic", status=resp.status_code)


def fmt_uzs(tiyin: int) -> str:
    return f"{tiyin // 100:,}".replace(",", " ") + " UZS"


def first_wallet_id(token: str):
    r = api_get(token, "/api/wallet/")
    if r.status_code == 200 and r.json():
        return r.json()[0]["id"]
    return None


def parse_amount_to_tiyin(raw: str):
    try:
        uzs = float(raw.replace(",", "."))
    except ValueError:
        return None
    tiyin = int(round(uzs * 100))
    return tiyin if tiyin >= 1 else None


def _require_login(chat_id):
    sess = sessions.get(str(chat_id))
    if not sess or not sess.get("token"):
        send(chat_id, T(chat_id, "need_login"))
        return None
    return sess


# --------------------------------------------------------------- команды ---

def cmd_start(chat_id, _args):
    send(chat_id, T(chat_id, "welcome"), buttons=menu_buttons(chat_id))


def cmd_menu(chat_id, _args):
    send(chat_id, T(chat_id, "menu_title"), buttons=menu_buttons(chat_id))


def cmd_info(chat_id, _args):
    send(chat_id, T(chat_id, "info", url=ABOUT_URL))


def cmd_lang(chat_id, _args):
    send(chat_id, T(chat_id, "lang_prompt"),
         buttons=[[("Русский 🇷🇺", "lang:ru"), ("O‘zbekcha 🇺🇿", "lang:uz")]])


def cmd_login(chat_id, args):
    if len(args) != 2:
        send(chat_id, T(chat_id, "login_format"))
        return
    username, password = args
    try:
        r = requests.post(
            f"{API_BASE}/api/auth/token/",
            json={"username": username, "password": password},
            timeout=10,
        )
    except requests.RequestException:
        send(chat_id, T(chat_id, "service_down"))
        return
    if r.status_code == 200 and "token" in r.json():
        token = r.json()["token"]
        sess = sessions.setdefault(str(chat_id), {})
        sess.update({"token": token, "username": username})
        sess.pop("pending", None)
        save_sessions()
        bound = False
        try:
            br = api_post(token, "/api/me/telegram/", {"telegram_chat_id": str(chat_id)})
            bound = br.status_code == 200
        except requests.RequestException:
            pass
        tail = T(chat_id, "tail_bound") if bound else T(chat_id, "tail_unbound")
        send(chat_id, T(chat_id, "login_ok", username=username, tail=tail),
             buttons=menu_buttons(chat_id))
    else:
        send(chat_id, T(chat_id, "login_bad"))


def cmd_logout(chat_id, _args):
    sess = sessions.get(str(chat_id))
    if sess and sess.get("token"):
        lang = sess.get("lang", "ru")
        sessions[str(chat_id)] = {"lang": lang}   # keep language preference
        save_sessions()
        send(chat_id, T(chat_id, "logout_ok"))
    else:
        send(chat_id, T(chat_id, "logout_none"))


def cmd_balance(chat_id, _args):
    sess = _require_login(chat_id)
    if not sess:
        return
    token = sess["token"]
    wid = first_wallet_id(token)
    if not wid:
        send(chat_id, T(chat_id, "no_wallet"))
        return
    br = api_get(token, f"/api/wallet/{wid}/balance/")
    if br.status_code != 200:
        send(chat_id, T(chat_id, "no_wallet"))
        return
    b = br.json()
    text = T(chat_id, "balance", bal=fmt_uzs(b["balance"]), avail=fmt_uzs(b["available"]))
    if b.get("held"):
        text += T(chat_id, "balance_held", held=fmt_uzs(b["held"]))
    send(chat_id, text)


def cmd_history(chat_id, _args):
    sess = _require_login(chat_id)
    if not sess:
        return
    token = sess["token"]
    wid = first_wallet_id(token)
    if not wid:
        send(chat_id, T(chat_id, "no_wallet"))
        return
    hr = api_get(token, f"/api/wallet/{wid}/history/?page_size=10")
    if hr.status_code != 200:
        send(chat_id, T(chat_id, "history_fail"))
        return
    rows = hr.json().get("results", [])
    if not rows:
        send(chat_id, T(chat_id, "history_empty"))
        return
    lines = [T(chat_id, "history_title")]
    for e in rows[:10]:
        etype = e.get("type")
        sign = "＋" if etype == "credit" else ("－" if etype == "debit" else "•")
        label = T(chat_id, f"h_{etype}") if f"h_{etype}" in STR["ru"] else etype
        lines.append(f"{sign} {fmt_uzs(e.get('amount', 0))}  <i>{label}</i>")
    send(chat_id, "\n".join(lines))


def _get_analytics(token):
    wid = first_wallet_id(token)
    if not wid:
        return None
    r = api_get(token, f"/api/wallet/{wid}/analytics/?days=30")
    return r.json() if r.status_code == 200 else None


def cmd_stats(chat_id, _args):
    sess = _require_login(chat_id)
    if not sess:
        return
    a = _get_analytics(sess["token"])
    if a is None:
        send(chat_id, T(chat_id, "no_wallet"))
        return
    if a["in_total"] == 0 and a["out_total"] == 0:
        send(chat_id, T(chat_id, "stats_empty"))
        return
    net = a["net"]
    sign = "+" if net >= 0 else "−"
    by = {b["key"]: b for b in a["breakdown"]}
    lines = [
        T(chat_id, "stats_title"),
        f"⬇️ {T(chat_id, 'stats_in')}: <b>{fmt_uzs(a['in_total'])}</b>",
        f"⬆️ {T(chat_id, 'stats_out')}: <b>{fmt_uzs(a['out_total'])}</b>",
        f"= {T(chat_id, 'stats_net')}: <b>{sign}{fmt_uzs(abs(net))}</b>",
        "",
        f"• {T(chat_id, 'bd_topup')}: {fmt_uzs(by['topup']['total'])}",
        f"• {T(chat_id, 'bd_received')}: {fmt_uzs(by['received']['total'])}",
        f"• {T(chat_id, 'bd_withdraw')}: {fmt_uzs(by['withdraw']['total'])}",
        f"• {T(chat_id, 'bd_sent')}: {fmt_uzs(by['sent']['total'])}",
    ]
    cps = a.get("top_counterparties", [])
    if cps:
        lines.append("")
        lines.append(f"<b>{T(chat_id, 'stats_top')}:</b>")
        for c in cps[:5]:
            lines.append(f"• {c['username']}: ↑{fmt_uzs(c['sent'])} · ↓{fmt_uzs(c['received'])}")
    send(chat_id, "\n".join(lines))


def cmd_limit(chat_id, _args):
    sess = _require_login(chat_id)
    if not sess:
        return
    a = _get_analytics(sess["token"])
    if a is None or "kyc" not in a:
        send(chat_id, T(chat_id, "no_wallet"))
        return
    k = a["kyc"]
    send(chat_id, T(chat_id, "limit",
                    level=k["level"].upper(),
                    limit=fmt_uzs(k["limit_30d"]),
                    spent=fmt_uzs(k["spent_30d"]),
                    remaining=fmt_uzs(k["remaining_30d"])))


def cmd_qr(chat_id, _args):
    sess = _require_login(chat_id)
    if not sess:
        return
    token = sess["token"]
    wid = first_wallet_id(token)
    if not wid:
        send(chat_id, T(chat_id, "no_wallet"))
        return
    r = api_get(token, f"/api/wallet/{wid}/qr/static/")
    if r.status_code != 200 or not r.content:
        send(chat_id, T(chat_id, "qr_fail"))
        return
    try:
        requests.post(
            f"{TG}/sendPhoto",
            data={"chat_id": chat_id, "caption": T(chat_id, "qr_caption")},
            files={"photo": ("qr.png", r.content, "image/png")},
            timeout=15,
        )
    except requests.RequestException:
        send(chat_id, T(chat_id, "qr_fail"))


def cmd_send(chat_id, args):
    sess = _require_login(chat_id)
    if not sess:
        return
    if len(args) != 2:
        send(chat_id, T(chat_id, "send_format"))
        return
    recipient, amount_raw = args
    amount_tiyin = parse_amount_to_tiyin(amount_raw)
    if amount_tiyin is None:
        send(chat_id, T(chat_id, "send_bad_amount"))
        return

    token = sess["token"]
    wid = first_wallet_id(token)
    if not wid:
        send(chat_id, T(chat_id, "no_wallet"))
        return

    rr = api_post(token, "/api/p2p/resolve/", {"query": recipient})
    if rr.status_code == 404:
        send(chat_id, T(chat_id, "recipient_not_found"))
        return
    if rr.status_code != 200:
        send(chat_id, err_text(chat_id, rr))
        return
    rec = rr.json()

    ir = api_post(token, "/api/p2p/transfer/", {
        "sender_wallet": wid,
        "recipient_wallet": rec["wallet_id"],
        "amount": amount_tiyin,
        "idempotency_key": str(uuid.uuid4()),
    })
    if ir.status_code not in (200, 201):
        send(chat_id, err_text(chat_id, ir))
        return
    transfer_id = ir.json()["id"]

    sess["pending"] = {
        "transfer_id": transfer_id,
        "recipient": rec["username"],
        "amount_tiyin": amount_tiyin,
    }
    save_sessions()

    msg = T(chat_id, "transfer_created", amount=fmt_uzs(amount_tiyin), recipient=rec["username"])
    try:
        d = api_get(token, "/api/demo/last-otp/")
        if d.status_code == 200 and d.json().get("code"):
            msg += T(chat_id, "demo_code", code=d.json()["code"])
    except requests.RequestException:
        pass
    send(chat_id, msg)


def cmd_confirm(chat_id, args):
    sess = _require_login(chat_id)
    if not sess:
        return
    pending = sess.get("pending")
    if not pending:
        send(chat_id, T(chat_id, "confirm_no_pending"))
        return
    if len(args) != 1:
        send(chat_id, T(chat_id, "confirm_format"))
        return
    code = args[0]
    token = sess["token"]

    cr = api_post(token, f"/api/p2p/transfers/{pending['transfer_id']}/confirm/", {"code": code})
    if cr.status_code == 200:
        amount = pending["amount_tiyin"]
        recipient = pending["recipient"]
        sess.pop("pending", None)
        save_sessions()
        text = T(chat_id, "transfer_done", amount=fmt_uzs(amount), recipient=recipient)
        wid = first_wallet_id(token)
        if wid:
            br = api_get(token, f"/api/wallet/{wid}/balance/")
            if br.status_code == 200:
                text += T(chat_id, "balance_left", bal=fmt_uzs(br.json()["balance"]))
        send(chat_id, text)
        return

    try:
        ecode = cr.json().get("code")
    except ValueError:
        ecode = None
    if ecode in ("otp_missing_or_expired", "otp_locked", "invalid_state_transition"):
        sess.pop("pending", None)
        save_sessions()
    send(chat_id, err_text(chat_id, cr))


def cmd_cancel(chat_id, _args):
    sess = _require_login(chat_id)
    if not sess:
        return
    if sess.pop("pending", None):
        save_sessions()
        send(chat_id, T(chat_id, "cancel_ok"))
    else:
        send(chat_id, T(chat_id, "cancel_none"))


def cmd_whoami(chat_id, _args):
    sess = sessions.get(str(chat_id))
    if sess and sess.get("token"):
        state = T(chat_id, "whoami_in", username=sess["username"])
    else:
        state = T(chat_id, "whoami_out")
    extra = ""
    if sess and sess.get("pending"):
        p = sess["pending"]
        extra = T(chat_id, "whoami_draft", amount=fmt_uzs(p["amount_tiyin"]), recipient=p["recipient"])
    send(chat_id, T(chat_id, "whoami", chat_id=chat_id, state=state, extra=extra))


COMMANDS = {
    "/start": cmd_start,
    "/help": cmd_start,
    "/menu": cmd_menu,
    "/info": cmd_info,
    "/lang": cmd_lang,
    "/login": cmd_login,
    "/logout": cmd_logout,
    "/balance": cmd_balance,
    "/history": cmd_history,
    "/stats": cmd_stats,
    "/limit": cmd_limit,
    "/qr": cmd_qr,
    "/send": cmd_send,
    "/confirm": cmd_confirm,
    "/cancel": cmd_cancel,
    "/whoami": cmd_whoami,
}

# Commands reachable from the inline menu (no arguments needed).
MENU_DISPATCH = {
    "balance": cmd_balance, "history": cmd_history, "stats": cmd_stats,
    "limit": cmd_limit, "qr": cmd_qr, "info": cmd_info, "lang": cmd_lang,
}


def handle_callback(cb: dict) -> None:
    answer_callback(cb.get("id"))
    data = cb.get("data") or ""
    msg = cb.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    if chat_id is None:
        return
    if data.startswith("lang:"):
        lang = data.split(":", 1)[1]
        if lang in STR:
            set_lang(chat_id, lang)
            send(chat_id, T(chat_id, "lang_set"), buttons=menu_buttons(chat_id))
        return
    if data.startswith("cmd:"):
        handler = MENU_DISPATCH.get(data.split(":", 1)[1])
        if handler:
            try:
                handler(chat_id, [])
            except Exception:  # noqa: BLE001
                log.exception("callback handler error for %s", data)
                send(chat_id, T(chat_id, "internal_error"))


def handle_update(upd: dict) -> None:
    if "callback_query" in upd:
        handle_callback(upd["callback_query"])
        return
    msg = upd.get("message") or upd.get("edited_message")
    if not msg:
        return
    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()
    if not text.startswith("/"):
        send(chat_id, T(chat_id, "not_command"))
        return
    parts = text.split()
    cmd = parts[0].split("@")[0].lower()  # /balance@HamyonBot -> /balance
    handler = COMMANDS.get(cmd)
    if not handler:
        send(chat_id, T(chat_id, "unknown_cmd"))
        return
    try:
        handler(chat_id, parts[1:])
    except Exception:  # noqa: BLE001 — бот не должен падать из-за одной команды
        log.exception("handler error for %s", cmd)
        send(chat_id, T(chat_id, "internal_error"))


def main() -> None:
    if not TOKEN:
        log.error("TELEGRAM_OTP_BOT_TOKEN не задан — бот не может стартовать")
        raise SystemExit(1)
    load_sessions()
    try:
        requests.get(f"{TG}/deleteWebhook", timeout=10)
        me = requests.get(f"{TG}/getMe", timeout=10).json()
        log.info("bot online: @%s", me.get("result", {}).get("username"))
        requests.post(f"{TG}/setMyCommands", json={"commands": [
            {"command": "menu", "description": "Меню / Menyu"},
            {"command": "balance", "description": "Баланс / Balans"},
            {"command": "history", "description": "История / Tarix"},
            {"command": "stats", "description": "Аналитика / Tahlil"},
            {"command": "limit", "description": "KYC-лимит / limit"},
            {"command": "qr", "description": "Мой QR / Mening QR"},
            {"command": "send", "description": "Перевод / O‘tkazma"},
            {"command": "info", "description": "О проекте / Loyiha haqida"},
            {"command": "lang", "description": "Язык / Til"},
            {"command": "login", "description": "Войти / Kirish"},
            {"command": "logout", "description": "Выйти / Chiqish"},
        ]}, timeout=10)
    except requests.RequestException:
        log.warning("не смог обратиться к Telegram API на старте")

    offset = None
    while True:
        try:
            r = requests.get(
                f"{TG}/getUpdates",
                params={"timeout": 30, "offset": offset},
                timeout=40,
            )
            data = r.json()
            if not data.get("ok"):
                log.warning("getUpdates not ok: %s", data)
                time.sleep(3)
                continue
            for upd in data["result"]:
                offset = upd["update_id"] + 1
                handle_update(upd)
        except requests.RequestException:
            time.sleep(3)
        except Exception:  # noqa: BLE001
            log.exception("poll loop error")
            time.sleep(3)


if __name__ == "__main__":
    main()
