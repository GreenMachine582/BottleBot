"""add notification_log table

Revision ID: a1b2c3d4e5f6
Revises: ceb2bc50a8ca
Create Date: 2026-06-19

"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "ceb2bc50a8ca"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("dispatched_at", sa.DateTime, nullable=False),
        sa.Column("channel", sa.String, nullable=False),
        sa.Column("tag", sa.String, nullable=False),
        sa.Column("product_name", sa.String),
        sa.Column("retailer_product_id", sa.Integer),
        sa.Column("score", sa.Float),
        sa.Column("price_aud", sa.Float),
        sa.Column("message_body", sa.Text),
    )
    op.create_index(
        "ix_notification_log_dispatched_at",
        "notification_log",
        ["dispatched_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_notification_log_dispatched_at", table_name="notification_log")
    op.drop_table("notification_log")
