"""Cursor pagination. Offset pagination is banned.

Cursor = base64(created_at_iso + ':' + id). The page query is an index seek:
WHERE (created_at, id) < (cursor_ts, cursor_id) ORDER BY created_at DESC, id DESC
— constant time at any depth, stable under concurrent inserts, and never runs
COUNT(*) (enforced by assertNumQueries in tests).
"""

import base64
import binascii
import uuid
from dataclasses import dataclass
from datetime import datetime

from django.db.models import Q

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


class InvalidCursor(Exception):
    pass


def encode_cursor(created_at, entry_id) -> str:
    raw = f"{created_at.isoformat()}:{entry_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str):
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        # isoformat itself contains ':' — the id is after the LAST colon.
        ts_raw, id_raw = raw.rsplit(":", 1)
        return datetime.fromisoformat(ts_raw), uuid.UUID(id_raw)
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise InvalidCursor(str(exc)) from exc


@dataclass
class Page:
    items: list
    next_cursor: str | None


def paginate(queryset, cursor: str | None, page_size: int = DEFAULT_PAGE_SIZE) -> Page:
    page_size = min(max(1, page_size), MAX_PAGE_SIZE)
    if cursor:
        ts, last_id = decode_cursor(cursor)
        queryset = queryset.filter(
            Q(created_at__lt=ts) | Q(created_at=ts, id__lt=last_id)
        )
    queryset = queryset.order_by("-created_at", "-id")
    # Fetch one extra row to know whether a next page exists — no COUNT(*).
    items = list(queryset[: page_size + 1])
    has_next = len(items) > page_size
    items = items[:page_size]
    next_cursor = (
        encode_cursor(items[-1].created_at, items[-1].id) if has_next and items else None
    )
    return Page(items=items, next_cursor=next_cursor)
