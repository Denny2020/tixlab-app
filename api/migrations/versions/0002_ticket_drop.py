"""ticket drops: event details, drop time, waiting room, seat sections, check-in

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-01
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("events") as t:
        t.add_column(sa.Column("slug", sa.String(80), nullable=True))
        t.add_column(sa.Column("artist", sa.String(200), nullable=False, server_default=""))
        t.add_column(sa.Column("tagline", sa.String(300), nullable=False, server_default=""))
        t.add_column(sa.Column("description", sa.Text, nullable=False, server_default=""))
        t.add_column(sa.Column("genre", sa.String(60), nullable=False, server_default=""))
        t.add_column(sa.Column("opens_at", sa.DateTime(timezone=True), nullable=True))
        t.add_column(sa.Column("waiting_room", sa.Boolean, nullable=False, server_default=sa.false()))
        t.add_column(sa.Column("hue", sa.Integer, nullable=False, server_default="280"))
        t.create_unique_constraint("uq_events_slug", ["slug"])
    with op.batch_alter_table("seats") as t:
        t.add_column(sa.Column("section", sa.String(40), nullable=False, server_default="Floor"))
        t.add_column(sa.Column("price_cents", sa.Integer, nullable=False, server_default="0"))
    # existing seats take their event's price
    op.execute("UPDATE seats SET price_cents = e.price_cents FROM events e WHERE seats.event_id = e.id")
    with op.batch_alter_table("bookings") as t:
        t.add_column(sa.Column("name", sa.String(120), nullable=False, server_default=""))
        t.add_column(sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_bookings_created_at", "bookings", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_bookings_created_at", table_name="bookings")
    with op.batch_alter_table("bookings") as t:
        t.drop_column("checked_in_at")
        t.drop_column("name")
    with op.batch_alter_table("seats") as t:
        t.drop_column("price_cents")
        t.drop_column("section")
    with op.batch_alter_table("events") as t:
        t.drop_constraint("uq_events_slug", type_="unique")
        for col in ("hue", "waiting_room", "opens_at", "genre", "description", "tagline", "artist", "slug"):
            t.drop_column(col)
