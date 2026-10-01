"""One-off and scheduled jobs, run from the API image:

  python -m app.jobs seed     # sample events; adds any that are missing (by slug)
  python -m app.jobs report   # sales report emailed via the worker (nightly CronJob)
"""

import argparse
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from . import kv
from .config import settings
from .db import SessionLocal
from .models import Booking, Event, Seat

log = logging.getLogger("tixlab.jobs")

# (slug, name, artist, genre, tagline, description, venue, days_until_show, drop_in_minutes,
#  waiting_room, base_price_cents, hue)
SAMPLE_EVENTS = [
    ("neon-nights", "Neon Nights Tour", "Aurora Static", "Synthwave",
     "One night. 96 seats. The drop everyone's waiting for.",
     "Aurora Static bring their sold-out synthwave show to an intimate room: analog synths, "
     "laser grids and the whole of 'Midnight Protocol' played front to back. Tickets drop at a "
     "fixed time and go through a virtual waiting room.",
     "The Reconcile Hall", 21, 10, True, 6500, 300),
    ("kernel-panic", "Kernel Panic Live", "The Segfaults", "Punk rock",
     "Three chords, zero downtime.",
     "Fast, loud and occasionally on-key. The Segfaults return with songs about broken builds, "
     "late-night pages and the one deploy that took down prod.",
     "Pod Arena", 9, None, False, 3500, 12),
    ("lofi-sunrise", "Lo-Fi Sunrise Sessions", "Mira Cole", "Lo-fi / Chill",
     "Headphones optional. Coffee included.",
     "An early-morning set of warm beats and soft keys as the sun comes up over the city. "
     "Bring a blanket; the first rows are bean bags.",
     "Rooftop at Control Plane", 30, None, False, 2500, 190),
    ("ctrl-alt-dance", "Ctrl+Alt+Dance", "DJ Daemonset", "Electronic",
     "Scheduled on every node. Especially yours.",
     "DJ Daemonset runs a four-hour set that scales with the crowd. Expect bass you can feel in "
     "your kubelet.",
     "Warehouse 6443", 45, 2 * 24 * 60, True, 4800, 160),
]

# Rows nearest the stage cost more.
SECTIONS = [("Front", "AB", 1.6), ("Floor", "CDE", 1.0), ("Balcony", "FGH", 0.7)]
SEATS_PER_ROW = 12


def _seats(base_price: int) -> list[Seat]:
    return [
        Seat(label=f"{row}{n}", section=section, price_cents=int(round(base_price * factor / 100)) * 100)
        for section, rows, factor in SECTIONS
        for row in rows
        for n in range(1, SEATS_PER_ROW + 1)
    ]


def seed() -> None:
    now = datetime.now(UTC)
    with SessionLocal() as session:
        existing = set(session.scalars(select(Event.slug).where(Event.slug.isnot(None))))
        added = 0
        for (slug, name, artist, genre, tagline, description, venue, days, drop_in, waiting, price, hue) in SAMPLE_EVENTS:
            if slug in existing:
                continue
            event = Event(
                slug=slug, name=name, artist=artist, genre=genre, tagline=tagline, description=description,
                venue=venue, waiting_room=waiting, price_cents=0, hue=hue,
                starts_at=(now + timedelta(days=days)).replace(hour=20, minute=0, second=0, microsecond=0),
                opens_at=now + timedelta(minutes=drop_in) if drop_in is not None else None,
            )
            event.seats = _seats(price)
            event.price_cents = min(seat.price_cents for seat in event.seats)
            session.add(event)
            added += 1
        session.commit()
        log.info("seeded %d new events (%d already present)", added, len(existing))


def report() -> None:
    with SessionLocal() as session:
        rows = session.execute(
            select(Event.name, func.count(Booking.id), func.coalesce(func.sum(Seat.price_cents).filter(Booking.id.isnot(None)), 0))
            .join(Seat, Seat.event_id == Event.id)
            .outerjoin(Booking, Booking.seat_id == Seat.id)
            .group_by(Event.id)
            .order_by(Event.starts_at)
        ).all()
    lines = [f"{name:<30} {sold:>4} sold  {revenue / 100:>10.2f}" for name, sold, revenue in rows]
    total = sum(revenue for _, _, revenue in rows) / 100
    body = "\n".join([f"{'Event':<30} {'Sold':>9}  {'AUD':>10}"] + lines + ["", f"{'Total revenue (AUD)':<41} {total:>10.2f}"])
    kv.enqueue_email(settings.report_email, f"TixLab sales report {datetime.now(UTC):%Y-%m-%d}", body)
    log.info("sales report queued:\n%s", body)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(prog="python -m app.jobs")
    parser.add_argument("job", choices=["seed", "report"])
    {"seed": seed, "report": report}[parser.parse_args().job]()


if __name__ == "__main__":
    main()
