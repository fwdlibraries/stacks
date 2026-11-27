"""encrypt LTI tool private keys at rest

Revision ID: 9a1f3c5e7b2d
Revises: 8c4d1e7f2a3b
Create Date: 2026-11-27 10:00:00

Each LMS registration's private signing key was stored as plain PEM. It's now
encrypted like library API keys (app/services/credentials.py: CREDENTIALS_KEY, or a key
derived from SECRET_KEY). Downgrading decrypts the keys again, so it needs the same key.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.services import credentials

revision: str = "9a1f3c5e7b2d"
down_revision: str | None = "8c4d1e7f2a3b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _convert(source: str, target: str, fn) -> None:
    conn = op.get_bind()
    op.add_column("lti_platforms", sa.Column(target, sa.Text(), nullable=True))
    for row_id, value in conn.execute(sa.text(f"SELECT id, {source} FROM lti_platforms")).all():
        conn.execute(
            sa.text(f"UPDATE lti_platforms SET {target} = :value WHERE id = :id"), {"value": fn(value), "id": row_id}
        )
    op.alter_column("lti_platforms", target, nullable=False)
    op.drop_column("lti_platforms", source)


def upgrade() -> None:
    _convert("tool_private_key", "tool_private_key_encrypted", credentials.encrypt)


def downgrade() -> None:
    _convert("tool_private_key_encrypted", "tool_private_key", credentials.decrypt)
