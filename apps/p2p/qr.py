"""QR generation and validation.

Static QR : encodes the wallet_id only, reusable forever.
Dynamic QR: signed JWT (HS256) with wallet_id + amount + ref_id + expiry.
            Single-use: the ref_id doubles as the TransferRequest idempotency
            key, so the unique constraint burns the QR on first use.
"""

import base64
import io
import time
import uuid

import jwt
import qrcode
from django.conf import settings

from .models import TransferRequest


class QRError(Exception):
    pass


class QRInvalidError(QRError):
    """Bad signature, malformed payload, or expired token."""


class QRAlreadyUsedError(QRError):
    """The dynamic QR's ref_id has already been turned into a transfer."""


def qr_png_bytes(payload: str) -> bytes:
    image = qrcode.make(payload)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def static_qr_payload(wallet_id) -> str:
    return f"hamyon://p2p?wallet={wallet_id}"


def issue_dynamic_qr(wallet, amount: int) -> dict:
    ref_id = uuid.uuid4()
    expires_at = int(time.time()) + settings.QR_DYNAMIC_TTL_SECONDS
    token = jwt.encode(
        {
            "typ": "hamyon.p2p.dynamic",
            "wallet_id": str(wallet.id),
            "amount": amount,
            "ref_id": str(ref_id),
            "exp": expires_at,
        },
        settings.QR_JWT_SECRET,
        algorithm="HS256",
    )
    return {
        "token": token,
        "ref_id": str(ref_id),
        "expires_at": expires_at,
        "qr_png_base64": base64.b64encode(qr_png_bytes(token)).decode(),
    }


def decode_dynamic_qr(token: str) -> dict:
    """Verify signature + expiry + single-use, return the transfer intent."""
    try:
        payload = jwt.decode(token, settings.QR_JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise QRInvalidError(str(exc)) from exc

    if payload.get("typ") != "hamyon.p2p.dynamic":
        raise QRInvalidError("not a hamyon dynamic QR token")

    if TransferRequest.objects.filter(idempotency_key=payload["ref_id"]).exists():
        raise QRAlreadyUsedError("this QR has already been used")

    return {
        "recipient_wallet": payload["wallet_id"],
        "amount": payload["amount"],
        "ref_id": payload["ref_id"],
        "expires_at": payload["exp"],
    }
