from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

SeatStatus = Literal["available", "held", "booked"]
SaleStatus = Literal["upcoming", "on_sale", "sold_out"]


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str | None
    name: str
    artist: str
    tagline: str
    genre: str
    venue: str
    starts_at: datetime
    opens_at: datetime | None
    waiting_room: bool
    price_cents: int
    hue: int
    status: SaleStatus
    sold: int
    capacity: int


class SeatOut(BaseModel):
    id: int
    label: str
    section: str
    price_cents: int
    status: SeatStatus


class EventDetail(EventOut):
    description: str
    seats: list[SeatOut]


class QueueJoinOut(BaseModel):
    queue_id: str


class QueueStatus(BaseModel):
    ahead: int  # fans in front of you who aren't admitted yet
    admitted: bool
    opens_in: int  # seconds until the drop opens (0 once open)
    queue_length: int
    queue_pass: str | None = None
    pass_expires_at: int | None = None


class HoldIn(BaseModel):
    seat_id: int


class HoldOut(BaseModel):
    hold_id: str
    seat_id: int
    label: str
    section: str
    price_cents: int
    expires_in: int


class ConfirmIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr


class TicketOut(BaseModel):
    code: str
    ticket: str  # signed token encoded in the QR code
    ticket_url: str
    name: str
    email: str
    event_id: int
    event: str
    artist: str
    venue: str
    starts_at: datetime
    hue: int
    seat: str
    section: str
    price_cents: int
    checked_in_at: datetime | None


class EventStats(BaseModel):
    id: int
    name: str
    artist: str
    opens_at: datetime | None
    waiting_room: bool
    status: SaleStatus
    sold: int
    capacity: int
    revenue_cents: int
    holds: int
    queue: int
    admitted: int
    checked_in: int


class RushStatus(BaseModel):
    event_id: int
    bots: int
    ends_in: int


class Stats(BaseModel):
    events: list[EventStats]
    pods: list[str]
    sales_timeline: list[int]  # bookings per 10s bucket, oldest first, last 5 minutes
    rush: RushStatus | None


class CheckinIn(BaseModel):
    ticket: str = Field(max_length=500)  # the token, or the ticket URL from the QR code


class CheckinOut(BaseModel):
    result: Literal["valid", "already_used", "invalid"]
    ticket: TicketOut | None = None


class RushIn(BaseModel):
    event_id: int
    bots: int = Field(ge=1, le=300)
    seconds: int = Field(ge=10, le=600)


class DropIn(BaseModel):
    opens_in_seconds: int = Field(ge=0, le=7 * 86400)
    waiting_room: bool = True
