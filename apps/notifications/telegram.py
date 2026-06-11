"""Push-notification delivery over Telegram.

Deliberately independent from apps.otp.telegram — the brief requires the OTP
bot and the push bot to share no code path (separate token, separate module,
separate failure domain: a push outage must never affect OTP delivery).
"""

import logging

import requests
from django.conf import settings

logger = logging.getLogger("hamyon.notifications.telegram")


def send_telegram_push(chat_id: str, text: str) -> bool:
    token = settings.TELEGRAM_PUSH_BOT_TOKEN

    if not token:
        print(f"[TELEGRAM-IMITATION push-bot -> chat {chat_id or '<unset>'}] {text}",
              flush=True)
        return True

    if not chat_id:
        logger.warning("push skipped: empty chat_id")
        return False

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=5,
        )
        return response.ok
    except requests.RequestException:
        logger.warning("push delivery failed")
        return False
