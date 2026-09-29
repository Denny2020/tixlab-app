from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    venue: str
    starts_at: datetime
    price_cents: int


class SeatOut(BaseModel):
    id: int
    label: str
    status: Literal["available", "held", "booked"]


class EventDetail(EventOut):
    seats: list[SeatOut]


class HoldIn(BaseModel):
    seat_id: int


class HoldOut(BaseModel):
    hold_id: str
    seat_id: int
    expires_in: int


class ConfirmIn(BaseModel):
    email: EmailStr


class BookingOut(BaseModel):
    code: str
    event: str
    seat: str
    email: str
