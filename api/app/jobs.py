"""One-off and scheduled jobs, run from the API image:

  python -m app.jobs seed     # sample events; no-op if any exist
  python -m app.jobs report   # sales report emailed via the worker (nightly CronJob)
"""

import argparse
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from . import holds
from .config import settings
from .db import SessionLocal
from .models import Booking, Event, Seat

log = logging.getLogger("tixlab.jobs")

SAMPLE_EVENTS = [
    ("GitOps Jazz Night", "The Reconcile Loop Lounge", 14, 4500),
    ("Container Classics Live", "Pod Arena", 30, 6000),
    ("KubeCon Afterparty", "Control Plane Hall", 45, 2500),
]
ROWS, SEATS_PER_ROW = "ABCDE", 8


def seed() -> None:
    with SessionLocal() as session:
        if session.scalar(select(func.count(Event.id))):
            log.info("events already present, skipping seed")
            return
        now = datetime.now(UTC).replace(hour=19, minute=30, second=0, microsecond=0)
        for name, venue, days, price in SAMPLE_EVENTS:
            event = Event(name=name, venue=venue, starts_at=now + timedelta(days=days), price_cents=price)
            event.seats = [Seat(label=f"{r}{n}") for r in ROWS for n in range(1, SEATS_PER_ROW + 1)]
            session.add(event)
        session.commit()
        log.info("seeded %d events", len(SAMPLE_EVENTS))


def report() -> None:
    with SessionLocal() as session:
        rows = session.execute(
            select(Event.name, Event.price_cents, func.count(Booking.id))
            .join(Seat, Seat.event_id == Event.id)
            .outerjoin(Booking, Booking.seat_id == Seat.id)
            .group_by(Event.id)
            .order_by(Event.starts_at)
        ).all()
    lines = [f"{name:<30} {sold:>4} sold  {sold * price / 100:>10.2f}" for name, price, sold in rows]
    total = sum(sold * price for _, price, sold in rows) / 100
    body = "\n".join(lines + ["", f"{'Total revenue':<41} {total:>10.2f}"])
    holds.enqueue_email(settings.report_email, f"TixLab sales report {datetime.now(UTC):%Y-%m-%d}", body)
    log.info("sales report queued:\n%s", body)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(prog="python -m app.jobs")
    parser.add_argument("job", choices=["seed", "report"])
    {"seed": seed, "report": report}[parser.parse_args().job]()


if __name__ == "__main__":
    main()
