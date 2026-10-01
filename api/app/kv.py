"""Valkey client and the small shared-state helpers built on it."""

import json
import logging
import socket
import time

import valkey

from .config import settings

log = logging.getLogger("tixlab.kv")
client = valkey.from_url(settings.valkey_url, decode_responses=True)

POD = socket.gethostname()
PODS_KEY = "tixlab:pods"
RUSH_KEY = "tixlab:rush"


def live_channel(event_id: int) -> str:
    return f"tixlab:live:{event_id}"


def expired_channel() -> str:
    db = client.connection_pool.connection_kwargs.get("db", 0)
    return f"__keyevent@{db}__:expired"


def publish(event_id: int, message: dict) -> None:
    """Fan a change out to every live seat map, whichever API pod it's connected to."""
    client.publish(live_channel(event_id), json.dumps(message))


def enable_expiry_events() -> None:
    """Hold expiry is pushed to browsers via keyspace notifications. Best effort: the
    chart also sets this on the Valkey command line."""
    try:
        client.config_set("notify-keyspace-events", "Ex")
    except Exception:
        log.warning("could not enable keyspace expiry events; expired holds will appear on refresh only")


_last_seen = 0.0


def mark_pod_alive(force: bool = False) -> None:
    """Records which API pods are serving traffic (shown on the organizer dashboard).
    Throttled to one write per second per pod unless forced."""
    global _last_seen
    now = time.time()
    if not force and now - _last_seen < 1:
        return
    _last_seen = now
    try:
        pipe = client.pipeline()
        pipe.zadd(PODS_KEY, {POD: now})
        pipe.zremrangebyscore(PODS_KEY, 0, now - 60)
        pipe.execute()
    except valkey.ValkeyError:
        pass


def active_pods(window_seconds: int = 10) -> list[str]:
    return sorted(client.zrangebyscore(PODS_KEY, time.time() - window_seconds, "+inf"))


def enqueue_email(to: str, subject: str, body: str) -> None:
    """The worker consumes from the right, so LPUSH keeps the queue FIFO."""
    client.lpush(settings.email_queue, json.dumps({"to": to, "subject": subject, "body": body}))


def ping() -> bool:
    return bool(client.ping())
