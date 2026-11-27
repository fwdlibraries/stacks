"""rollover import: primaries, rollover items, remembered matches (rollover stage 2)

Revision ID: 8c4d1e7f2a3b
Revises: 5b8e2f6a9c1d
Create Date: 2026-11-26 18:00:00

Primaries are course variants' primary shells. A rollover item is one live section in an
upcoming term's rollover: its primary, how that was found, and its review status.
Remembered matches carry a librarian's choice of primary into later terms.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8c4d1e7f2a3b"
down_revision: str | None = "5b8e2f6a9c1d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "primaries",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "course_template_id", sa.UUID(), sa.ForeignKey("course_templates.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text()),
        sa.Column("mode", sa.Text()),
        sa.Column("length", sa.Text()),
        sa.Column("lms_org_unit_id", sa.Text()),
        sa.Column("lms_department", sa.Text()),
        sa.Column("reading_list_id", sa.UUID(), sa.ForeignKey("reading_lists.id", ondelete="SET NULL")),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "code", name="uq_primaries_organization_code"),
    )
    op.create_index("ix_primaries_organization_id", "primaries", ["organization_id"])
    op.create_index("ix_primaries_course_template_id", "primaries", ["course_template_id"])

    op.create_table(
        "rollover_items",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("term_id", sa.UUID(), sa.ForeignKey("terms.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "course_offering_id", sa.UUID(), sa.ForeignKey("course_offerings.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("primary_id", sa.UUID(), sa.ForeignKey("primaries.id", ondelete="SET NULL")),
        sa.Column("match_source", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="needs_source"),
        sa.Column("part_of_term", sa.Text()),
        sa.Column("length", sa.Text()),
        sa.Column("mode", sa.Text()),
        sa.Column("department", sa.Text()),
        sa.Column("instructors", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("file_primary_code", sa.Text()),
        sa.Column("problems", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("row", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("notes", sa.Text()),
        sa.Column("decided_by", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("term_id", "course_offering_id", name="uq_rollover_items_term_offering"),
    )
    op.create_index("ix_rollover_items_term_id", "rollover_items", ["term_id"])
    op.create_index("ix_rollover_items_primary_id", "rollover_items", ["primary_id"])

    op.create_table(
        "remembered_matches",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "course_template_id", sa.UUID(), sa.ForeignKey("course_templates.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("length", sa.Text(), nullable=False, server_default=""),
        sa.Column("mode", sa.Text(), nullable=False, server_default=""),
        sa.Column("primary_id", sa.UUID(), sa.ForeignKey("primaries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("course_template_id", "length", "mode", name="uq_remembered_matches_variant"),
    )
    op.create_index("ix_remembered_matches_organization_id", "remembered_matches", ["organization_id"])


def downgrade() -> None:
    op.drop_table("remembered_matches")
    op.drop_table("rollover_items")
    op.drop_table("primaries")
