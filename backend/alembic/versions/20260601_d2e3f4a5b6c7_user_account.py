"""user_account table

E-posta/şifre ile kayıtlı kullanıcı hesabı. email PK, password_hash (pbkdf2 —
ham şifre saklanmaz). sub = user:<email> → geçmiş/tercih fingerprint(sub) ile.

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-06-01 01:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision: str = 'd2e3f4a5b6c7'
down_revision: str | Sequence[str] | None = 'c1d2e3f4a5b6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('user_account',
    sa.Column('email', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('password_hash', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('email')
    )
    op.create_index(op.f('ix_user_account_created_at'), 'user_account', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_user_account_created_at'), table_name='user_account')
    op.drop_table('user_account')
