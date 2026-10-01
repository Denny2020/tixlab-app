"""Organizer API: dashboard stats, door check-in, drop control and the bot rush."""

import hmac
import json
import re
import time
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import holds, kv, signing, waiting_room
from ..config import settings
from ..db import get_session
from ..metrics import CHECKINS
from ..models import Booking, Event, Seat
from ..schemas import CheckinIn, CheckinOut, DropIn, EventStats, RushIn, RushStatus, Stats
from .public import sale_status, ticket_out


def require_organizer(authorization: str | None = Header(default=None)) -> None:
    expected = f"Bearer {settings.organizer_token}"
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(401, "organizer token required", headers={"WWW-Authenticate": "Bearer"})


router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_organizer)])

TIMELINE_BUCKET_SECONDS, TIMELINE_BUCKETS = 10, 30
TICKET_IN_TEXT = re.compile(r"TIX\.[A-Z0-9]+\.[A-Z2-7]+")


@router.get("/stats", response_model=Stats)
def stats(session: Session = Depends(get_session)):
    rows = session.execute(
        select(
            Event,
            func.count(Seat.id),
            func.count(Booking.id),
            func.coalesce(func.sum(Seat.price_cents).filter(Booking.id.isnot(None)), 0),
            func.count(Booking.checked_in_at),
        )
        .join(Seat, Seat.event_id == Event.id)
        .outerjoin(Booking, Booking.seat_id == Seat.id)
        .group_by(Event.id)
        .order_by(Event.starts_at)
    ).all()
    events = [
        EventStats(
            id=e.id,
            name=e.name,
            artist=e.artist,
            opens_at=e.opens_at,
            waiting_room=e.waiting_room,
            status=sale_status(e, sold, capacity),
            sold=sold,
            capacity=capacity,
            revenue_cents=revenue,
            holds=holds.count(e.id),
            queue=waiting_room.length(e.id) if e.waiting_room else 0,
            admitted=min(waiting_room.admitted_count(e.opens_at), waiting_room.length(e.id)) if e.waiting_room else 0,
            checked_in=checked_in,
        )
        for e, capacity, sold, revenue, checked_in in rows
    ]

    now = datetime.now(UTC)
    since = now - timedelta(seconds=TIMELINE_BUCKET_SECONDS * TIMELINE_BUCKETS)
    timeline = [0] * TIMELINE_BUCKETS
    for (created,) in session.execute(select(Booking.created_at).where(Booking.created_at >= since)):
        bucket = int((created - since).total_seconds() // TIMELINE_BUCKET_SECONDS)
        timeline[min(bucket, TIMELINE_BUCKETS - 1)] += 1

    kv.mark_pod_alive(force=True)  # the pod answering is alive by definition
    return Stats(events=events, pods=kv.active_pods(), sales_timeline=timeline, rush=rush_status())


@router.post("/checkin", response_model=CheckinOut)
def checkin(body: CheckinIn, session: Session = Depends(get_session)):
    """Door scan. Accepts the token or the full ticket URL from the QR code. Single use."""
    match = TICKET_IN_TEXT.search(body.ticket)
    code = signing.verify_ticket(match.group(0)) if match else None
    booking = session.scalar(select(Booking).where(Booking.code == code)) if code else None
    if booking is None:
        CHECKINS.labels("invalid").inc()
        return CheckinOut(result="invalid")
    # Atomic: only the first scan flips checked_in_at.
    updated = session.execute(
        Booking.__table__.update()
        .where(Booking.id == booking.id, Booking.checked_in_at.is_(None))
        .values(checked_in_at=func.now())
    ).rowcount
    session.commit()
    session.refresh(booking)
    result = "valid" if updated else "already_used"
    CHECKINS.labels(result).inc()
    return CheckinOut(result=result, ticket=ticket_out(booking))


@router.post("/events/{event_id}/drop", status_code=204)
def schedule_drop(event_id: int, body: DropIn, session: Session = Depends(get_session)):
    """Resets an event for a fresh drop: clears bookings, holds and the queue, sets the open time."""
    event = session.get(Event, event_id)
    if event is None:
        raise HTTPException(404, "event not found")
    session.execute(delete(Booking).where(Booking.seat_id.in_(select(Seat.id).where(Seat.event_id == event_id))))
    event.opens_at = datetime.now(UTC) + timedelta(seconds=body.opens_in_seconds)
    event.waiting_room = body.waiting_room
    session.commit()
    holds.clear(event_id)
    waiting_room.clear(event_id)
    kv.publish(event_id, {"type": "reset"})


def rush_status() -> RushStatus | None:
    raw = kv.client.get(kv.RUSH_KEY)
    if raw is None:
        return None
    rush = json.loads(raw)
    return RushStatus(event_id=rush["event_id"], bots=rush["bots"], ends_in=max(0, int(rush["until"] - time.time())))


@router.post("/rush", response_model=RushStatus, status_code=201)
def start_rush(body: RushIn, session: Session = Depends(get_session)):
    """Tells the bot pods to start booking. They watch this key in Valkey."""
    if session.get(Event, body.event_id) is None:
        raise HTTPException(404, "event not found")
    rush = {"event_id": body.event_id, "bots": body.bots, "until": time.time() + body.seconds}
    kv.client.set(kv.RUSH_KEY, json.dumps(rush), ex=body.seconds)
    return rush_status()


@router.delete("/rush", status_code=204)
def stop_rush():
    kv.client.delete(kv.RUSH_KEY)
