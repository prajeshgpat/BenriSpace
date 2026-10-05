"""POST /v1/feedback: thumbs on AI summaries / chat answers and place reports.

Rows go to `feedback` (migration 0011). Each anonymous visitor (salted hash of
the client IP, the same helper the chat limit uses) may send DAILY_LIMIT items a
day. A missing table is tolerated: the item is logged and dropped.
"""

import sys
from typing import Literal

from pydantic import Field, field_validator

from api.chat import visitor_hash
from api.schemas import CamelModel
from common.db import get_connection

DAILY_LIMIT = 30
MAX_MESSAGE_CHARS = 1000
MAX_TARGET_CHARS = 200


class FeedbackRequest(CamelModel):
    kind: Literal["summary", "chat", "place"]
    target: str | None = Field(default=None, max_length=MAX_TARGET_CHARS)
    rating: int | None = Field(default=None, ge=-1, le=1)
    message: str | None = Field(default=None, max_length=MAX_MESSAGE_CHARS)

    @field_validator("message", "target")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        return value or None


def record_feedback(body: FeedbackRequest, forwarded_for: str | None, client_host: str | None) -> bool:
    """Stores one item. False when the visitor is over the daily limit; True
    otherwise (including when the table is missing or the database fails)."""
    visitor = visitor_hash(forwarded_for, client_host)
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "select count(*) as n from feedback "
                "where visitor_hash = %s and created_at > now() - interval '1 day'",
                (visitor,),
            )
            if int(cur.fetchone()["n"]) >= DAILY_LIMIT:
                return False
            cur.execute(
                "insert into feedback (kind, target, rating, message, visitor_hash) "
                "values (%s, %s, %s, %s, %s)",
                (body.kind, body.target, body.rating, body.message, visitor),
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - feedback must never break the page
        print(f"feedback: not stored ({type(exc).__name__})", file=sys.stderr)
    return True
