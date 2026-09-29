import secrets
import time

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from prometheus_client import Counter, Histogram, make_asgi_app
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from . import __version__, holds
from .config import settings
from .db import get_session
from .models import Booking, Event, Seat
from .schemas import BookingOut, ConfirmIn, EventDetail, EventOut, HoldIn, HoldOut, SeatOut

REQUESTS = Histogram(
    "tixlab_http_request_duration_seconds", "HTTP request latency", ["method", "route", "status"]
)
HOLDS = Counter("tixlab_holds_total", "Seat hold attempts", ["result"])
BOOKINGS = Counter("tixlab_bookings_total", "Confirmed bookings")

app = FastAPI(title="TixLab API", version=__version__)
app.mount("/metrics", make_asgi_app())
api = APIRouter(prefix="/api")


@app.middleware("http")
async def record_latency(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    if route is not None:  # skip 404s so unknown paths can't blow up label cardinality
        REQUESTS.labels(request.method, route.path, response.status_code).observe(
            time.perf_counter() - start
        )
    return response


@app.get("/healthz")
def healthz():
    """Liveness: the process is up. Deliberately checks no dependencies."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz(response: Response, session: Session = Depends(get_session)):
    """Readiness: take traffic only while Postgres and Valkey both answer."""
    checks = {}
    try:
        session.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception:
        checks["postgres"] = "down"
    try:
        checks["valkey"] = "ok" if holds.ping() else "down"
    except Exception:
        checks["valkey"] = "down"
    if "down" in checks.values():
        response.status_code = 503
    return checks


@api.get("/version")
def version():
    return {"version": settings.version or __version__}


@api.get("/events", response_model=list[EventOut])
def list_events(session: Session = Depends(get_session)):
    return session.scalars(select(Event).order_by(Event.starts_at)).all()


@api.get("/events/{event_id}", response_model=EventDetail)
def get_event(event_id: int, session: Session = Depends(get_session)):
    event = session.scalar(
        select(Event)
        .where(Event.id == event_id)
        .options(selectinload(Event.seats).selectinload(Seat.booking))
    )
    if event is None:
        raise HTTPException(404, "event not found")
    held = holds.held_seat_ids([s.id for s in event.seats])
    seats = [
        SeatOut(
            id=s.id,
            label=s.label,
            status="booked" if s.booking else "held" if s.id in held else "available",
        )
        for s in event.seats
    ]
    return EventDetail(**EventOut.model_validate(event).model_dump(), seats=seats)


@api.post("/events/{event_id}/holds", response_model=HoldOut, status_code=201)
def hold_seat(event_id: int, body: HoldIn, session: Session = Depends(get_session)):
    seat = session.get(Seat, body.seat_id)
    if seat is None or seat.event_id != event_id:
        raise HTTPException(404, "seat not found for this event")
    if seat.booking is not None:
        HOLDS.labels("booked").inc()
        raise HTTPException(409, "seat already booked")
    hold_id = holds.create(event_id, seat.id)
    if hold_id is None:
        HOLDS.labels("conflict").inc()
        raise HTTPException(409, "seat is held by someone else")
    HOLDS.labels("ok").inc()
    return HoldOut(hold_id=hold_id, seat_id=seat.id, expires_in=settings.hold_ttl_seconds)


@api.get("/holds/{hold_id}", response_model=HoldOut)
def get_hold(hold_id: str):
    hold = holds.get(hold_id)
    if hold is None:
        raise HTTPException(404, "hold not found or expired")
    return HoldOut(hold_id=hold_id, seat_id=hold[1], expires_in=holds.ttl(hold_id))


@api.delete("/holds/{hold_id}", status_code=204)
def release_hold(hold_id: str):
    hold = holds.get(hold_id)
    if hold is not None:
        holds.release(hold_id, hold[1])


@api.post("/holds/{hold_id}/confirm", response_model=BookingOut, status_code=201)
def confirm_hold(hold_id: str, body: ConfirmIn, session: Session = Depends(get_session)):
    hold = holds.get(hold_id)
    if hold is None:
        raise HTTPException(404, "hold not found or expired")
    seat = session.get(Seat, hold[1])
    booking = Booking(seat=seat, email=body.email, code=secrets.token_hex(4).upper())
    session.add(booking)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "seat already booked")
    holds.release(hold_id, seat.id)
    BOOKINGS.inc()

    event = seat.event
    holds.enqueue_email(
        to=body.email,
        subject=f"Your TixLab booking {booking.code}",
        body=(
            f"You're going to {event.name}!\n\n"
            f"Venue:   {event.venue}\n"
            f"When:    {event.starts_at:%A %d %B %Y, %H:%M %Z}\n"
            f"Seat:    {seat.label}\n"
            f"Code:    {booking.code}\n"
        ),
    )
    return BookingOut(code=booking.code, event=event.name, seat=seat.label, email=body.email)


app.include_router(api)
