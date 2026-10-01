from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str | None] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    artist: Mapped[str] = mapped_column(String(200), default="")
    tagline: Mapped[str] = mapped_column(String(300), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    genre: Mapped[str] = mapped_column(String(60), default="")
    venue: Mapped[str] = mapped_column(String(200))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Sales open at this time; before it the page shows a countdown.
    opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    waiting_room: Mapped[bool] = mapped_column(default=False)
    # "From" price; each seat carries its own section price.
    price_cents: Mapped[int]
    # Poster colour (0-360), so every event looks different without image assets.
    hue: Mapped[int] = mapped_column(default=280)

    seats: Mapped[list["Seat"]] = relationship(back_populates="event", order_by="Seat.id")


class Seat(Base):
    __tablename__ = "seats"
    __table_args__ = (UniqueConstraint("event_id", "label"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(8))
    section: Mapped[str] = mapped_column(String(40), default="Floor")
    price_cents: Mapped[int] = mapped_column(default=0)

    event: Mapped[Event] = relationship(back_populates="seats")
    booking: Mapped["Booking | None"] = relationship(back_populates="seat")


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    # unique: the database, not the hold, is the final guard against double booking
    seat_id: Mapped[int] = mapped_column(ForeignKey("seats.id", ondelete="CASCADE"), unique=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    email: Mapped[str] = mapped_column(String(320))
    code: Mapped[str] = mapped_column(String(16), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    seat: Mapped[Seat] = relationship(back_populates="booking")
