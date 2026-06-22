"""Hamyon Telegram bot — интерактивный интерфейс к API кошелька.

Долгий поллинг (getUpdates) — только исходящие соединения, портов наружу не нужно.
Бот живёт рядом с кошельком в той же docker-сети и ходит в API по http://web:8000.

Тот же токен (TELEGRAM_OTP_BOT_TOKEN) кошелёк использует для ОТПРАВКИ OTP, а бот —
для ПРИЁМА команд. Это не конфликтует: poll (бот) и sendMessage (кошелёк) независимы.

Команды:
  /start, /help        — приветствие и список команд
  /login <user> <pass> — войти (получить API-токен и привязать чат)
  /logout              — выйти
  /balance             — баланс кошелька
  /history             — последние операции
  /whoami              — статус входа и chat_id
"""

import json
import logging
import os
import time

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

# chat_id (str) -> {"token": str, "username": str}
sessions: dict[str, dict] = {}


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


def fmt_uzs(tiyin: int) -> str:
    return f"{tiyin // 100:,}".replace(",", " ") + " UZS"


# --------------------------------------------------------------- команды ---

WELCOME = (
    "👋 <b>Hamyon</b> — кошелёк прямо в Telegram.\n\n"
    "Команды:\n"
    "• /login <i>логин пароль</i> — войти\n"
    "• /balance — баланс\n"
    "• /history — последние операции\n"
    "• /whoami — статус\n"
    "• /logout — выйти\n\n"
    "Демо-вход: <code>/login alice demo123</code>"
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
        sessions[str(chat_id)] = {"token": r.json()["token"], "username": username}
        save_sessions()
        send(chat_id, f"✅ Вход выполнен как <b>{username}</b>. Команда /balance покажет баланс.")
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
    wr = api_get(token, "/api/wallet/")
    if wr.status_code != 200 or not wr.json():
        send(chat_id, "Кошелёк не найден.")
        return
    wid = wr.json()[0]["id"]
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
    wr = api_get(token, "/api/wallet/")
    if wr.status_code != 200 or not wr.json():
        send(chat_id, "Кошелёк не найден.")
        return
    wid = wr.json()[0]["id"]
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


def cmd_whoami(chat_id, _args):
    sess = sessions.get(str(chat_id))
    state = f"вошёл как <b>{sess['username']}</b>" if sess else "не в системе"
    send(chat_id, f"chat_id: <code>{chat_id}</code>\nСтатус: {state}")


COMMANDS = {
    "/start": cmd_start,
    "/help": cmd_start,
    "/login": cmd_login,
    "/logout": cmd_logout,
    "/balance": cmd_balance,
    "/history": cmd_history,
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
