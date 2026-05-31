"""user_preference table

Kullanıcı UI tercihleri (görünen ad, yazı boyutu, hareket, yüksek kontrast,
tercih edilen alanlar) — auth'lu kullanıcı için cihazlar-arası senkron.
PK = sub_hash (fingerprint(principal.sub)); KVKK: ham email saklanmaz.

Revision ID: a1b2c3d4e5f6
Revises: be6a25478dda
Create Date: 2026-06-01 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision: str = 'a1b2c3d4e5f6'
down_revision: str | Sequence[str] | None = 'be6a25478dda'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('user_preference',
    sa.Column('sub_hash', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('display_name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('text_scale', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('reduce_motion', sa.Boolean(), nullable=False),
    sa.Column('high_contrast', sa.Boolean(), nullable=False),
    sa.Column('preferred_domains', sa.JSON(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('sub_hash')
    )


def downgrade() -> None:
    op.drop_table('user_preference')
