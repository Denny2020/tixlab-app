"""Seat holds and the email queue, both in Valkey.

A hold is two keys with the same TTL:
  tixlab:hold:seat:<seat_id> -> hold_id      (SET NX: one hold per seat)
  tixlab:hold:id:<hold_id>   -> "<event_id>:<seat_id>"
Expiry releases the seat, so no cleanup job is needed for holds.
"""

import json
import uuid

import valkey

from .config import settings

client = valkey.from_url(settings.valkey_url, decode_responses=True)


def _seat_key(seat_id: int) -> str:
    return f"tixlab:hold:seat:{seat_id}"


def _hold_key(hold_id: str) -> str:
    return f"tixlab:hold:id:{hold_id}"


def create(event_id: int, seat_id: int) -> str | None:
    """Returns the new hold id, or None if the seat is already held."""
    hold_id = uuid.uuid4().hex
    ttl = settings.hold_ttl_seconds
    if not client.set(_seat_key(seat_id), hold_id, nx=True, ex=ttl):
        return None
    client.set(_hold_key(hold_id), f"{event_id}:{seat_id}", ex=ttl)
    return hold_id


def get(hold_id: str) -> tuple[int, int] | None:
    """Returns (event_id, seat_id) for a live hold."""
    value = client.get(_hold_key(hold_id))
    if value is None:
        return None
    event_id, seat_id = (int(part) for part in value.split(":"))
    if client.get(_seat_key(seat_id)) != hold_id:
        return None
    return event_id, seat_id


def ttl(hold_id: str) -> int:
    return max(client.ttl(_hold_key(hold_id)), 0)


def release(hold_id: str, seat_id: int) -> None:
    pipe = client.pipeline()
    pipe.delete(_hold_key(hold_id))
    pipe.delete(_seat_key(seat_id))
    pipe.execute()


def held_seat_ids(seat_ids: list[int]) -> set[int]:
    if not seat_ids:
        return set()
    values = client.mget([_seat_key(s) for s in seat_ids])
    return {seat_id for seat_id, value in zip(seat_ids, values) if value is not None}


def enqueue_email(to: str, subject: str, body: str) -> None:
    """The worker consumes from the right, so LPUSH keeps the queue FIFO."""
    client.lpush(settings.email_queue, json.dumps({"to": to, "subject": subject, "body": body}))


def ping() -> bool:
    return bool(client.ping())
