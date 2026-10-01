import secrets
from datetime import UTC, datetime

import segno
from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .. import holds, kv, signing, waiting_room
from ..config import settings
from ..db import get_session
from ..metrics import BOOKINGS, HOLDS, QUEUE_JOINS
from ..models import Booking, Event, Seat
from ..schemas import (
    ConfirmIn,
    EventDetail,
    EventOut,
    HoldIn,
    HoldOut,
    QueueJoinOut,
    QueueStatus,
    SeatOut,
    TicketOut,
)

router = APIRouter(prefix="/api")


def sale_status(event: Event, sold: int, capacity: int) -> str:
    if capacity and sold >= capacity:
        return "sold_out"
    if event.opens_at and datetime.now(UTC) < event.opens_at:
        return "upcoming"
    return "on_sale"


def event_out(event: Event, sold: int, capacity: int) -> dict:
    data = EventOut.model_validate(
        {**{c: getattr(event, c) for c in EventOut.model_fields if hasattr(event, c)},
         "status": sale_status(event, sold, capacity), "sold": sold, "capacity": capacity}
    )
    return data.model_dump()


def sold_and_capacity(session: Session) -> dict[int, tuple[int, int]]:
    rows = session.execute(
        select(Seat.event_id, func.count(Seat.id), func.count(Booking.id))
        .outerjoin(Booking, Booking.seat_id == Seat.id)
        .group_by(Seat.event_id)
    ).all()
    return {event_id: (sold, capacity) for event_id, capacity, sold in rows}


def ticket_out(booking: Booking) -> TicketOut:
    seat, event = booking.seat, booking.seat.event
    token = signing.ticket_token(booking.code)
    return TicketOut(
        code=booking.code,
        ticket=token,
        ticket_url=f"{settings.public_url}/#/ticket/{token}",
        name=booking.name,
        email=booking.email,
        event_id=event.id,
        event=event.name,
        artist=event.artist,
        venue=event.venue,
        starts_at=event.starts_at,
        hue=event.hue,
        seat=seat.label,
        section=seat.section,
        price_cents=seat.price_cents,
        checked_in_at=booking.checked_in_at,
    )


@router.get("/version")
def version():
    return {"version": settings.version or "dev", "pod": kv.POD}


@router.get("/events", response_model=list[EventOut])
def list_events(session: Session = Depends(get_session)):
    counts = sold_and_capacity(session)
    events = session.scalars(select(Event).order_by(Event.starts_at)).all()
    return [event_out(e, *counts.get(e.id, (0, 0))) for e in events]


@router.get("/events/{event_id}", response_model=EventDetail)
def get_event(event_id: int, session: Session = Depends(get_session)):
    event = session.scalar(
        select(Event).where(Event.id == event_id).options(selectinload(Event.seats).selectinload(Seat.booking))
    )
    if event is None:
        raise HTTPException(404, "event not found")
    held = holds.held_seat_ids(event.id, [s.id for s in event.seats])
    seats = [
        SeatOut(
            id=s.id,
            label=s.label,
            section=s.section,
            price_cents=s.price_cents,
            status="booked" if s.booking else "held" if s.id in held else "available",
        )
        for s in event.seats
    ]
    sold = sum(1 for s in seats if s.status == "booked")
    return EventDetail(**event_out(event, sold, len(seats)), description=event.description, seats=seats)


def _event_or_404(session: Session, event_id: int) -> Event:
    event = session.get(Event, event_id)
    if event is None:
        raise HTTPException(404, "event not found")
    return event


@router.post("/events/{event_id}/queue", response_model=QueueJoinOut, status_code=201)
def join_queue(event_id: int, session: Session = Depends(get_session)):
    event = _event_or_404(session, event_id)
    if not event.waiting_room:
        raise HTTPException(400, "this event has no waiting room")
    QUEUE_JOINS.inc()
    return QueueJoinOut(queue_id=waiting_room.join(event.id))


@router.get("/events/{event_id}/queue/{queue_id}", response_model=QueueStatus)
def queue_status(event_id: int, queue_id: str, session: Session = Depends(get_session)):
    event = _event_or_404(session, event_id)
    position = waiting_room.position(event.id, queue_id)
    if position is None:
        raise HTTPException(404, "not in the queue")
    now = datetime.now(UTC)
    admitted_upto = waiting_room.admitted_count(event.opens_at, now)
    opens_in = max(0, int((event.opens_at - now).total_seconds())) if event.opens_at else 0
    status = QueueStatus(
        ahead=max(0, position - admitted_upto),
        admitted=position < admitted_upto,
        opens_in=opens_in,
        queue_length=waiting_room.length(event.id),
    )
    if status.admitted:
        status.queue_pass, status.pass_expires_at = signing.queue_pass(event.id, queue_id)
    return status


@router.post("/events/{event_id}/holds", response_model=HoldOut, status_code=201)
def hold_seat(
    event_id: int,
    body: HoldIn,
    session: Session = Depends(get_session),
    x_queue_pass: str | None = Header(default=None),
):
    event = _event_or_404(session, event_id)
    if event.opens_at and datetime.now(UTC) < event.opens_at:
        raise HTTPException(403, "sales haven't opened yet")
    if event.waiting_room and not signing.verify_queue_pass(x_queue_pass, event.id):
        raise HTTPException(403, "join the waiting room first")
    seat = session.get(Seat, body.seat_id)
    if seat is None or seat.event_id != event_id:
        raise HTTPException(404, "seat not found for this event")
    if seat.booking is not None:
        HOLDS.labels("booked").inc()
        raise HTTPException(409, "seat already booked")
    hold_id = holds.create(event_id, seat.id)
    if hold_id is None:
        HOLDS.labels("conflict").inc()
        raise HTTPException(409, "someone just grabbed that seat")
    HOLDS.labels("ok").inc()
    return HoldOut(
        hold_id=hold_id,
        seat_id=seat.id,
        label=seat.label,
        section=seat.section,
        price_cents=seat.price_cents,
        expires_in=settings.hold_ttl_seconds,
    )


@router.get("/holds/{hold_id}", response_model=HoldOut)
def get_hold(hold_id: str, session: Session = Depends(get_session)):
    hold = holds.get(hold_id)
    if hold is None:
        raise HTTPException(404, "hold not found or expired")
    seat = session.get(Seat, hold[1])
    return HoldOut(
        hold_id=hold_id,
        seat_id=seat.id,
        label=seat.label,
        section=seat.section,
        price_cents=seat.price_cents,
        expires_in=holds.ttl(hold_id),
    )


@router.delete("/holds/{hold_id}", status_code=204)
def release_hold(hold_id: str):
    hold = holds.get(hold_id)
    if hold is not None:
        holds.release(hold_id, *hold)


@router.post("/holds/{hold_id}/confirm", response_model=TicketOut, status_code=201)
def confirm_hold(hold_id: str, body: ConfirmIn, session: Session = Depends(get_session)):
    hold = holds.get(hold_id)
    if hold is None:
        raise HTTPException(404, "hold not found or expired")
    seat = session.get(Seat, hold[1])
    booking = Booking(seat=seat, name=body.name.strip(), email=body.email, code=secrets.token_hex(4).upper())
    session.add(booking)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "seat already booked")
    holds.release(hold_id, seat.event_id, seat.id, status="booked")
    BOOKINGS.inc()

    ticket = ticket_out(booking)
    if not body.email.endswith("@" + settings.bot_email_domain):
        kv.enqueue_email(
            to=body.email,
            subject=f"🎟 Your ticket: {ticket.artist} — {ticket.event}",
            body=(
                f"Hi {ticket.name},\n\nYou're going to {ticket.event} with {ticket.artist}!\n\n"
                f"  When:   {ticket.starts_at:%A %d %B %Y, %H:%M %Z}\n"
                f"  Where:  {ticket.venue}\n"
                f"  Seat:   {ticket.seat} ({ticket.section})\n"
                f"  Code:   {ticket.code}\n\n"
                f"Your ticket with QR code:\n{ticket.ticket_url}\n\nSee you there!\n"
            ),
        )
    return ticket


def _booking_for(token: str, session: Session) -> Booking:
    code = signing.verify_ticket(token)
    booking = session.scalar(select(Booking).where(Booking.code == code)) if code else None
    if booking is None:
        raise HTTPException(404, "ticket not found")
    return booking


@router.get("/tickets/{token}", response_model=TicketOut)
def get_ticket(token: str, session: Session = Depends(get_session)):
    return ticket_out(_booking_for(token, session))


@router.get("/tickets/{token}/qr.svg")
def ticket_qr(token: str, session: Session = Depends(get_session)):
    ticket = ticket_out(_booking_for(token, session))
    svg = segno.make(ticket.ticket_url, error="m").svg_inline(scale=6, border=2, dark="#0b0b12", light="#ffffff")
    return Response(svg, media_type="image/svg+xml", headers={"Cache-Control": "private, max-age=3600"})
