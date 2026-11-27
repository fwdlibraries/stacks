"""terms and section lists (rollover stage 1)

Revision ID: 5b8e2f6a9c1d
Revises: 1c202463c1ba
Create Date: 2026-11-26 12:00:00

Adds Term records, links offerings to them (and to their LMS course code), lets a
reading list belong to one offering and remember what it was copied from, and gives
sections and citations an item_key that survives copies.

Existing lists stay course lists (kind 'course'): every term of a course keeps showing
the same list, exactly as before. Terms are created from the term codes offerings
already use.
"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5b8e2f6a9c1d"
down_revision: str | None = "1c202463c1ba"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _name(code: str) -> str:
    return code if code.isdigit() else " ".join(p.capitalize() for p in code.split("-"))


def upgrade() -> None:
    op.create_table(
        "terms",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("rollover_on", sa.Date(), nullable=True),
        sa.Column("lists_due_on", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "code", name="uq_terms_organization_code"),
    )
    op.create_index("ix_terms_organization_id", "terms", ["organization_id"])

    op.add_column("course_offerings", sa.Column("term_id", sa.UUID(), nullable=True))
    op.add_column("course_offerings", sa.Column("lms_code", sa.Text(), nullable=True))
    op.create_foreign_key("fk_course_offerings_term_id", "course_offerings", "terms", ["term_id"], ["id"])
    op.create_index("ix_course_offerings_term_id", "course_offerings", ["term_id"])
    op.create_index("ix_course_offerings_lms_code", "course_offerings", ["lms_code"])

    op.add_column("reading_lists", sa.Column("kind", sa.Text(), server_default="course", nullable=False))
    op.add_column("reading_lists", sa.Column("course_offering_id", sa.UUID(), nullable=True))
    op.add_column("reading_lists", sa.Column("copied_from_list_id", sa.UUID(), nullable=True))
    op.add_column("reading_lists", sa.Column("copied_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_reading_lists_course_offering_id", "reading_lists", "course_offerings", ["course_offering_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_reading_lists_copied_from_list_id",
        "reading_lists",
        "reading_lists",
        ["copied_from_list_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_reading_lists_course_offering_id", "reading_lists", ["course_offering_id"])

    for table in ("list_sections", "citations"):
        op.add_column(
            table, sa.Column("item_key", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False)
        )

    # Terms from the codes offerings already use, per organization
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            """
            SELECT DISTINCT c.organization_id, o.term
            FROM course_offerings o
            JOIN course_templates t ON t.id = o.course_template_id
            JOIN departments d ON d.id = t.department_id
            JOIN colleges c ON c.id = d.college_id
            """
        )
    ).all()
    terms = sa.table(
        "terms", sa.column("id", sa.UUID()), sa.column("organization_id", sa.UUID()),
        sa.column("code", sa.Text()), sa.column("name", sa.Text()),
    )
    if rows:
        op.bulk_insert(
            terms,
            [{"id": uuid.uuid4(), "organization_id": org, "code": code, "name": _name(code)} for org, code in rows],
        )
    conn.execute(
        sa.text(
            """
            UPDATE course_offerings o SET term_id = tm.id
            FROM course_templates t, departments d, colleges c, terms tm
            WHERE t.id = o.course_template_id AND d.id = t.department_id AND c.id = d.college_id
              AND tm.organization_id = c.organization_id AND tm.code = o.term
            """
        )
    )
    # Each offering's LMS course code, from its most recent LMS launch
    conn.execute(
        sa.text(
            """
            UPDATE course_offerings o SET lms_code = m.lti_context_label
            FROM (
                SELECT DISTINCT ON (course_offering_id) course_offering_id, lti_context_label
                FROM lti_context_mappings
                WHERE course_offering_id IS NOT NULL AND lti_context_label IS NOT NULL
                ORDER BY course_offering_id, last_launched_at DESC NULLS LAST
            ) m
            WHERE o.id = m.course_offering_id
            """
        )
    )


def downgrade() -> None:
    for table in ("citations", "list_sections"):
        op.drop_column(table, "item_key")
    op.drop_index("ix_reading_lists_course_offering_id", table_name="reading_lists")
    op.drop_constraint("fk_reading_lists_copied_from_list_id", "reading_lists", type_="foreignkey")
    op.drop_constraint("fk_reading_lists_course_offering_id", "reading_lists", type_="foreignkey")
    for column in ("copied_at", "copied_from_list_id", "course_offering_id", "kind"):
        op.drop_column("reading_lists", column)
    op.drop_index("ix_course_offerings_lms_code", table_name="course_offerings")
    op.drop_index("ix_course_offerings_term_id", table_name="course_offerings")
    op.drop_constraint("fk_course_offerings_term_id", "course_offerings", type_="foreignkey")
    op.drop_column("course_offerings", "lms_code")
    op.drop_column("course_offerings", "term_id")
    op.drop_index("ix_terms_organization_id", table_name="terms")
    op.drop_table("terms")
