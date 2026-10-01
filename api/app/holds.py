"""Seat holds in Valkey.

A hold is two keys with the same TTL:
  tixlab:hold:<event_id>:<seat_id> -> hold_id   (SET NX: one hold per seat)
  tixlab:holdid:<hold_id>          -> "<event_id>:<seat_id>"
Expiry releases the seat; the live stream turns the expiry notification into a seat update.
"""

import uuid

from .config import settings
from .kv import client, publish

SEAT_PREFIX = "tixlab:hold:"


def seat_key(event_id: int, seat_id: int) -> str:
    return f"{SEAT_PREFIX}{event_id}:{seat_id}"


def _hold_key(hold_id: str) -> str:
    return f"tixlab:holdid:{hold_id}"


def parse_seat_key(key: str) -> tuple[int, int] | None:
    if not key.startswith(SEAT_PREFIX):
        return None
    event_id, seat_id = key[len(SEAT_PREFIX):].split(":")
    return int(event_id), int(seat_id)


def create(event_id: int, seat_id: int) -> str | None:
    """Returns the new hold id, or None if the seat is already held."""
    hold_id = uuid.uuid4().hex
    ttl = settings.hold_ttl_seconds
    if not client.set(seat_key(event_id, seat_id), hold_id, nx=True, ex=ttl):
        return None
    client.set(_hold_key(hold_id), f"{event_id}:{seat_id}", ex=ttl)
    publish(event_id, {"type": "seat", "seat_id": seat_id, "status": "held"})
    return hold_id


def get(hold_id: str) -> tuple[int, int] | None:
    """Returns (event_id, seat_id) for a live hold."""
    value = client.get(_hold_key(hold_id))
    if value is None:
        return None
    event_id, seat_id = (int(part) for part in value.split(":"))
    if client.get(seat_key(event_id, seat_id)) != hold_id:
        return None
    return event_id, seat_id


def ttl(hold_id: str) -> int:
    return max(client.ttl(_hold_key(hold_id)), 0)


def release(hold_id: str, event_id: int, seat_id: int, status: str = "available") -> None:
    pipe = client.pipeline()
    pipe.delete(_hold_key(hold_id))
    pipe.delete(seat_key(event_id, seat_id))
    pipe.execute()
    publish(event_id, {"type": "seat", "seat_id": seat_id, "status": status})


def held_seat_ids(event_id: int, seat_ids: list[int]) -> set[int]:
    if not seat_ids:
        return set()
    values = client.mget([seat_key(event_id, s) for s in seat_ids])
    return {seat_id for seat_id, value in zip(seat_ids, values) if value is not None}


def count(event_id: int) -> int:
    return sum(1 for _ in client.scan_iter(f"{SEAT_PREFIX}{event_id}:*", count=500))


def clear(event_id: int) -> None:
    for key in client.scan_iter(f"{SEAT_PREFIX}{event_id}:*", count=500):
        client.delete(key)
