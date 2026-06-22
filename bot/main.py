"""Hamyon Telegram bot — интерактивный интерфейс к API кошелька.

Долгий поллинг (getUpdates) — только исходящие соединения, портов наружу не нужно.
Бот живёт рядом с кошельком в той же docker-сети и ходит в API по http://web:8000.

Тот же токен (TELEGRAM_OTP_BOT_TOKEN) кошелёк использует для ОТПРАВКИ OTP, а бот —
для ПРИЁМА команд. Это не конфликтует: poll (бот) и sendMessage (кошелёк) независимы.

Команды:
  /start, /help            — приветствие и список команд
  /login <user> <pass>     — войти (получить API-токен и привязать чат)
  /logout                  — выйти
  /balance                 — баланс кошелька
  /history                 — последние операции
  /send <кому> <сумма>     — перевод (по нику или телефону), сумма в UZS
  /confirm <код>           — подтвердить перевод OTP-кодом
  /cancel                  — отменить черновик перевода
  /whoami                  — статус входа и chat_id
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
TG = f"https://api.telegram.org/bot{TOKEN}"
SESSIONS_PATH = os.environ.get("BOT_SESSIONS_PATH", "/data/sessions.json")

# chat_id (str) -> {"token": str, "username": str, "pending": {...}|absent}
sessions: dict[str, dict] = {}

# Доменные коды ошибок API -> понятный текст (см. apps/core/api.py).
ERROR_MSG = {
    "insufficient_funds": "Недостаточно средств.",
    "recipient_not_found": "Получатель не найден.",
    "otp_invalid": "Неверный код. Попробуй ещё раз: /confirm <код>",
    "otp_missing_or_expired": "Код истёк. Начни перевод заново: /send <кому> <сумма>",
    "otp_locked": "Слишком много попыток. Подожди 10 минут.",
    "kyc_limit_exceeded": "Превышен лимит по твоему уровню KYC.",
    "kyc_rejected": "KYC отклонён.",
    "invalid_state_transition": "Перевод уже завершён или недоступен.",
}


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


def send(chat_id, text: str) -> None:
    try:
        requests.post(
            f"{TG}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except requests.RequestException:
        log.warning("sendMessage failed for chat %s", chat_id)


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


def err_text(resp) -> str:
    """Достаёт понятное сообщение из ответа API с доменной ошибкой."""
    if resp.status_code == 403 and not resp.text.strip():
        return "Операция заблокирована."
    try:
        code = resp.json().get("code")
    except ValueError:
        code = None
    return ERROR_MSG.get(code, f"Ошибка ({resp.status_code}).")


def fmt_uzs(tiyin: int) -> str:
    return f"{tiyin // 100:,}".replace(",", " ") + " UZS"


def first_wallet_id(token: str):
    r = api_get(token, "/api/wallet/")
    if r.status_code == 200 and r.json():
        return r.json()[0]["id"]
    return None


def parse_amount_to_tiyin(raw: str):
    """'500' / '500.50' / '500,50' UZS -> тиыны (int). None если некорректно."""
    try:
        uzs = float(raw.replace(",", "."))
    except ValueError:
        return None
    tiyin = int(round(uzs * 100))
    return tiyin if tiyin >= 1 else None


# --------------------------------------------------------------- команды ---

WELCOME = (
    "👋 <b>Hamyon</b> — кошелёк прямо в Telegram.\n\n"
    "Команды:\n"
    "• /login <i>логин пароль</i> — войти\n"
    "• /balance — баланс\n"
    "• /history — последние операции\n"
    "• /send <i>кому сумма</i> — перевод (ник или телефон, сумма в UZS)\n"
    "• /confirm <i>код</i> — подтвердить перевод\n"
    "• /cancel — отменить черновик перевода\n"
    "• /whoami — статус · /logout — выйти\n\n"
    "Демо-вход: <code>/login alice demo123</code>\n"
    "Пример перевода: <code>/send bob 500</code>"
)


def cmd_start(chat_id, _args):
    send(chat_id, WELCOME)


def cmd_login(chat_id, args):
    if len(args) != 2:
        send(chat_id, "Формат: <code>/login логин пароль</code>")
        return
    username, password = args
    try:
        r = requests.post(
            f"{API_BASE}/api/auth/token/",
            json={"username": username, "password": password},
            timeout=10,
        )
    except requests.RequestException:
        send(chat_id, "⚠️ Сервис недоступен, попробуй позже.")
        return
    if r.status_code == 200 and "token" in r.json():
        token = r.json()["token"]
        sessions[str(chat_id)] = {"token": token, "username": username}
        save_sessions()
        # Привязываем этот чат к аккаунту, чтобы реальные OTP приходили сюда.
        # chat_id берётся из Telegram-апдейта (не из ввода) — подделать нельзя.
        bound = False
        try:
            br = api_post(token, "/api/me/telegram/", {"telegram_chat_id": str(chat_id)})
            bound = br.status_code == 200
        except requests.RequestException:
            pass
        tail = ("OTP-коды теперь будут приходить в этот чат."
                if bound else "(OTP-привязку включить не удалось — коды придут другим способом.)")
        send(chat_id, f"✅ Вход выполнен как <b>{username}</b>. {tail}\nКоманда /balance покажет баланс.")
    else:
        send(chat_id, "❌ Неверный логин или пароль.")


def cmd_logout(chat_id, _args):
    if sessions.pop(str(chat_id), None):
        save_sessions()
        send(chat_id, "Вышел. /login — чтобы войти снова.")
    else:
        send(chat_id, "Ты и так не в системе.")


def _require_login(chat_id):
    sess = sessions.get(str(chat_id))
    if not sess:
        send(chat_id, "Сначала войди: <code>/login логин пароль</code>")
        return None
    return sess


def cmd_balance(chat_id, _args):
    sess = _require_login(chat_id)
    if not sess:
        return
    token = sess["token"]
    wid = first_wallet_id(token)
    if not wid:
        send(chat_id, "Кошелёк не найден.")
        return
    br = api_get(token, f"/api/wallet/{wid}/balance/")
    if br.status_code != 200:
        send(chat_id, "Не удалось получить баланс.")
        return
    b = br.json()
    send(
        chat_id,
        f"💰 Баланс: <b>{fmt_uzs(b['balance'])}</b>\n"
        f"Доступно: {fmt_uzs(b['available'])}"
        + (f"\nВ холде: {fmt_uzs(b['held'])}" if b.get("held") else ""),
    )


def cmd_history(chat_id, _args):
    sess = _require_login(chat_id)
    if not sess:
        return
    token = sess["token"]
    wid = first_wallet_id(token)
    if not wid:
        send(chat_id, "Кошелёк не найден.")
        return
    hr = api_get(token, f"/api/wallet/{wid}/history/?page_size=10")
    if hr.status_code != 200:
        send(chat_id, "Не удалось получить историю.")
        return
    rows = hr.json().get("results", [])
    if not rows:
        send(chat_id, "Операций пока нет.")
        return
    lines = ["🧾 <b>Последние операции:</b>"]
    for e in rows[:10]:
        sign = "＋" if e.get("type") == "credit" else "－"
        lines.append(f"{sign} {fmt_uzs(e.get('amount', 0))}  <i>{e.get('type')}</i>")
    send(chat_id, "\n".join(lines))


def cmd_send(chat_id, args):
    sess = _require_login(chat_id)
    if not sess:
        return
    if len(args) != 2:
        send(chat_id, "Формат: <code>/send кому сумма</code>\nНапример: <code>/send bob 500</code>")
        return
    recipient, amount_raw = args
    amount_tiyin = parse_amount_to_tiyin(amount_raw)
    if amount_tiyin is None:
        send(chat_id, "Сумма должна быть положительным числом (в UZS). Пример: <code>/send bob 500</code>")
        return

    token = sess["token"]
    wid = first_wallet_id(token)
    if not wid:
        send(chat_id, "Твой кошелёк не найден.")
        return

    # 1) находим получателя по нику или телефону
    rr = api_post(token, "/api/p2p/resolve/", {"query": recipient})
    if rr.status_code == 404:
        send(chat_id, "Получатель не найден. Проверь ник или телефон.")
        return
    if rr.status_code != 200:
        send(chat_id, err_text(rr))
        return
    rec = rr.json()

    # 2) инициируем перевод -> уходит OTP, статус otp_pending
    ir = api_post(token, "/api/p2p/transfer/", {
        "sender_wallet": wid,
        "recipient_wallet": rec["wallet_id"],
        "amount": amount_tiyin,
        "idempotency_key": str(uuid.uuid4()),
    })
    if ir.status_code not in (200, 201):
        send(chat_id, err_text(ir))
        return
    transfer_id = ir.json()["id"]

    sess["pending"] = {
        "transfer_id": transfer_id,
        "recipient": rec["username"],
        "amount_tiyin": amount_tiyin,
    }
    save_sessions()

    msg = (
        f"🔐 Перевод <b>{fmt_uzs(amount_tiyin)}</b> → <b>{rec['username']}</b> создан.\n"
        f"Код отправлен тебе в этот чат. Подтверди: <code>/confirm код</code>\n"
        f"Отменить: /cancel"
    )
    # В демо-режиме подскажем код (в проде эндпоинт отдаёт null — подсказки не будет,
    # пользователь возьмёт код из своего Telegram).
    try:
        d = api_get(token, "/api/demo/last-otp/")
        if d.status_code == 200 and d.json().get("code"):
            msg += f"\n\n<i>демо-код: {d.json()['code']}</i>"
    except requests.RequestException:
        pass
    send(chat_id, msg)


def cmd_confirm(chat_id, args):
    sess = _require_login(chat_id)
    if not sess:
        return
    pending = sess.get("pending")
    if not pending:
        send(chat_id, "Нет активного перевода. Сначала /send <кому> <сумма>.")
        return
    if len(args) != 1:
        send(chat_id, "Формат: <code>/confirm код</code> (6 цифр).")
        return
    code = args[0]

    cr = api_post(token := sess["token"], f"/api/p2p/transfers/{pending['transfer_id']}/confirm/",
                  {"code": code})
    if cr.status_code == 200:
        amount = pending["amount_tiyin"]
        recipient = pending["recipient"]
        sess.pop("pending", None)
        save_sessions()
        text = f"✅ Перевод <b>{fmt_uzs(amount)}</b> → <b>{recipient}</b> выполнен."
        wid = first_wallet_id(token)
        if wid:
            br = api_get(token, f"/api/wallet/{wid}/balance/")
            if br.status_code == 200:
                text += f"\n💰 Остаток: {fmt_uzs(br.json()['balance'])}"
        send(chat_id, text)
        return

    # ошибка: при истечении/локе черновик уже бесполезен — убираем
    try:
        ecode = cr.json().get("code")
    except ValueError:
        ecode = None
    if ecode in ("otp_missing_or_expired", "otp_locked", "invalid_state_transition"):
        sess.pop("pending", None)
        save_sessions()
    send(chat_id, err_text(cr))


def cmd_cancel(chat_id, _args):
    sess = _require_login(chat_id)
    if not sess:
        return
    if sess.pop("pending", None):
        save_sessions()
        send(chat_id, "Черновик перевода отменён. (Запрос сам истечёт на сервере.)")
    else:
        send(chat_id, "Нет активного перевода.")


def cmd_whoami(chat_id, _args):
    sess = sessions.get(str(chat_id))
    state = f"вошёл как <b>{sess['username']}</b>" if sess else "не в системе"
    extra = ""
    if sess and sess.get("pending"):
        p = sess["pending"]
        extra = f"\nЧерновик: {fmt_uzs(p['amount_tiyin'])} → {p['recipient']} (ждёт /confirm)"
    send(chat_id, f"chat_id: <code>{chat_id}</code>\nСтатус: {state}{extra}")


COMMANDS = {
    "/start": cmd_start,
    "/help": cmd_start,
    "/login": cmd_login,
    "/logout": cmd_logout,
    "/balance": cmd_balance,
    "/history": cmd_history,
    "/send": cmd_send,
    "/confirm": cmd_confirm,
    "/cancel": cmd_cancel,
    "/whoami": cmd_whoami,
}


def handle_update(upd: dict) -> None:
    msg = upd.get("message") or upd.get("edited_message")
    if not msg:
        return
    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()
    if not text.startswith("/"):
        send(chat_id, "Не понял. /help — список команд.")
        return
    parts = text.split()
    cmd = parts[0].split("@")[0].lower()  # /balance@HamyonBot -> /balance
    handler = COMMANDS.get(cmd)
    if not handler:
        send(chat_id, "Неизвестная команда. /help — список.")
        return
    try:
        handler(chat_id, parts[1:])
    except Exception:  # noqa: BLE001 — бот не должен падать из-за одной команды
        log.exception("handler error for %s", cmd)
        send(chat_id, "⚠️ Внутренняя ошибка, попробуй ещё раз.")


def main() -> None:
    if not TOKEN:
        log.error("TELEGRAM_OTP_BOT_TOKEN не задан — бот не может стартовать")
        raise SystemExit(1)
    load_sessions()
    # Снять возможный вебхук, иначе getUpdates вернёт конфликт.
    try:
        requests.get(f"{TG}/deleteWebhook", timeout=10)
        me = requests.get(f"{TG}/getMe", timeout=10).json()
        log.info("bot online: @%s", me.get("result", {}).get("username"))
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
