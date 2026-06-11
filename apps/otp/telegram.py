"""OTP delivery over Telegram. Independent from the push-notification bot by
design (the brief: the two bots share no code path).

Console-imitation mode (no token configured) prints the message to stdout —
that print stands in for the Telegram chat itself; the application LOGGER
never sees the raw code.
"""

import logging

import requests
from django.conf import settings

logger = logging.getLogger("hamyon.otp.telegram")


def send_telegram_otp(user, text: str) -> bool:
    token = settings.TELEGRAM_OTP_BOT_TOKEN
    chat_id = user.telegram_chat_id

    if not token:
        print(f"[TELEGRAM-IMITATION otp-bot -> chat {chat_id or '<unset>'}] {text}",
              flush=True)
        return True

    if not chat_id:
        # chat_id is confirmed at account setup; without it we cannot deliver.
        logger.warning("otp delivery skipped: user %s has no confirmed chat_id", user.pk)
        return False

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=5,
        )
        return response.ok
    except requests.RequestException:
        # The exception carries the URL, never the message body / raw code.
        logger.warning("otp delivery failed for user %s", user.pk)
        return False
