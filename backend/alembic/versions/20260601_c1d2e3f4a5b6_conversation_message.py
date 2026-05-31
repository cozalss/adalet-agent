"""conversation + message + uploaded_file tables

Kalıcı sohbet geçmişi (kayıtlı kullanıcı): conversation (metadata) + message
(turlar) + uploaded_file (OCR metadata; metin saklanmaz). owner_sub_hash =
fingerprint(sub); KVKK: ham email saklanmaz.

Revision ID: c1d2e3f4a5b6
Revises: a1b2c3d4e5f6
Create Date: 2026-06-01 00:30:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision: str = 'c1d2e3f4a5b6'
down_revision: str | Sequence[str] | None = 'a1b2c3d4e5f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('conversation',
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('owner_sub_hash', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('title', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('domain', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('message_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_conversation_owner_sub_hash'), 'conversation', ['owner_sub_hash'], unique=False)
    op.create_index(op.f('ix_conversation_created_at'), 'conversation', ['created_at'], unique=False)
    op.create_index(op.f('ix_conversation_updated_at'), 'conversation', ['updated_at'], unique=False)

    op.create_table('message',
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('conversation_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('turn_index', sa.Integer(), nullable=False),
    sa.Column('role', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('domain', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('citations_json', sa.JSON(), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversation.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_message_conversation_id'), 'message', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_message_created_at'), 'message', ['created_at'], unique=False)

    op.create_table('uploaded_file',
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('owner_sub_hash', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('conversation_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('filename', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('ocr_engine', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('n_chars', sa.Integer(), nullable=False),
    sa.Column('pii_flag', sa.Boolean(), nullable=False),
    sa.Column('uploaded_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_uploaded_file_owner_sub_hash'), 'uploaded_file', ['owner_sub_hash'], unique=False)
    op.create_index(op.f('ix_uploaded_file_uploaded_at'), 'uploaded_file', ['uploaded_at'], unique=False)


def downgrade() -> None:
    op.drop_table('uploaded_file')
    op.drop_index(op.f('ix_message_created_at'), table_name='message')
    op.drop_index(op.f('ix_message_conversation_id'), table_name='message')
    op.drop_table('message')
    op.drop_index(op.f('ix_conversation_updated_at'), table_name='conversation')
    op.drop_index(op.f('ix_conversation_created_at'), table_name='conversation')
    op.drop_index(op.f('ix_conversation_owner_sub_hash'), table_name='conversation')
    op.drop_table('conversation')
