"""Live seat-map updates over Server-Sent Events.

Every API pod subscribes to the event's Valkey channel, so a seat taken through pod A shows up
instantly for a fan connected to pod B. Hold expiry comes from Valkey keyspace notifications.
"""

import json
import time

import valkey.asyncio as avalkey
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .. import holds, kv
from ..config import settings

router = APIRouter(prefix="/api/live")
KEEPALIVE_SECONDS = 15


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


@router.get("/events/{event_id}")
async def live_event(event_id: int, request: Request):
    channel, expired = kv.live_channel(event_id), kv.expired_channel()

    async def stream():
        client = avalkey.from_url(settings.valkey_url, decode_responses=True)
        pubsub = client.pubsub()
        await pubsub.subscribe(channel, expired)
        yield "retry: 2000\n\n"
        last_sent = time.monotonic()
        try:
            while not await request.is_disconnected():
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=5)
                if message is None:
                    if time.monotonic() - last_sent > KEEPALIVE_SECONDS:
                        yield ": keepalive\n\n"
                        last_sent = time.monotonic()
                    continue
                if message["channel"] == expired:
                    parsed = holds.parse_seat_key(message["data"])
                    if parsed is None or parsed[0] != event_id:
                        continue
                    yield _sse({"type": "seat", "seat_id": parsed[1], "status": "available"})
                else:
                    yield f"data: {message['data']}\n\n"
                last_sent = time.monotonic()
        finally:
            await pubsub.aclose()
            await client.aclose()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
