"""Tests run against real Postgres and Valkey (compose `api-test`, or CI service containers).

They use a separate `<db>_test` database, built with the Alembic migrations, and Valkey DB 15.
The environment is rewritten before any `app` module is imported, because settings load at import.
"""

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

_base = make_url(os.environ.get("TIXLAB_DATABASE_URL", "postgresql+psycopg://tixlab:tixlab@localhost:5432/tixlab"))
_test_url = _base.set(database=f"{_base.database}_test")
os.environ["TIXLAB_DATABASE_URL"] = _test_url.render_as_string(hide_password=False)
os.environ["TIXLAB_VALKEY_URL"] = os.environ.get("TIXLAB_TEST_VALKEY_URL", "redis://localhost:6379/15")

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import kv  # noqa: E402
from app.db import SessionLocal, engine, normalize_url  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Event, Seat  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def database():
    admin = create_engine(normalize_url(_base.render_as_string(hide_password=False)), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{_test_url.database}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{_test_url.database}"'))
    admin.dispose()
    command.upgrade(Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini")), "head")
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_state():
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE bookings, seats, events RESTART IDENTITY CASCADE"))
    kv.client.flushdb()


@pytest.fixture
def client():
    return TestClient(app)


def make_event(opens_at=None, waiting_room=False):
    """An event with seats A1-A4 (Front, 50.00) and returns its ids."""
    with SessionLocal() as session:
        ev = Event(
            slug=None, name="Test Gig", artist="The Fixtures", venue="Test Hall",
            starts_at=datetime(2030, 1, 1, 20, tzinfo=UTC), opens_at=opens_at,
            waiting_room=waiting_room, price_cents=5000,
        )
        ev.seats = [Seat(label=f"A{n}", section="Front", price_cents=5000) for n in range(1, 5)]
        session.add(ev)
        session.commit()
        return {"id": ev.id, "seat_ids": [s.id for s in ev.seats]}


@pytest.fixture
def event():
    """An event that is on sale, without a waiting room."""
    return make_event()


@pytest.fixture
def organizer():
    from app.config import settings

    return {"Authorization": f"Bearer {settings.organizer_token}"}
