"""events, seats, bookings

Revision ID: 0001
Revises:
Create Date: 2026-09-29
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("venue", sa.String(200), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price_cents", sa.Integer, nullable=False),
    )
    op.create_table(
        "seats",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("event_id", sa.Integer, sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(8), nullable=False),
        sa.UniqueConstraint("event_id", "label"),
    )
    op.create_index("ix_seats_event_id", "seats", ["event_id"])
    op.create_table(
        "bookings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("seat_id", sa.Integer, sa.ForeignKey("seats.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("code", sa.String(16), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("bookings")
    op.drop_index("ix_seats_event_id", table_name="seats")
    op.drop_table("seats")
    op.drop_table("events")
