"""Virtual waiting room for ticket drops.

Fans join a per-event sorted set (score = join time). Admission is a pure function of time:
once the drop opens, the first `admit_batch` fans are let in, then `admit_per_second` more
every second. So every API replica agrees on who is in without coordinating, and a fan's
position only ever goes down.
"""

import uuid
from datetime import UTC, datetime

from .config import settings
from .kv import client


def _key(event_id: int) -> str:
    return f"tixlab:queue:{event_id}"


def admitted_count(opens_at: datetime | None, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    if opens_at is None or now < opens_at:
        return 0
    elapsed = (now - opens_at).total_seconds()
    return settings.admit_batch + int(elapsed * settings.admit_per_second)


def join(event_id: int) -> str:
    queue_id = uuid.uuid4().hex[:16]
    client.zadd(_key(event_id), {queue_id: datetime.now(UTC).timestamp()}, nx=True)
    client.expire(_key(event_id), 86400)
    return queue_id


def position(event_id: int, queue_id: str) -> int | None:
    """0-based place in line, or None if this id never joined."""
    return client.zrank(_key(event_id), queue_id)


def length(event_id: int) -> int:
    return client.zcard(_key(event_id))


def clear(event_id: int) -> None:
    client.delete(_key(event_id))
