"""create_session_training_logs_table

Revision ID: 14b491096f8b
Revises: 6f43c380cb59
Create Date: 2026-10-15 15:24:03.636403

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '14b491096f8b'
down_revision: str | None = '6f43c380cb59'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'session_training_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('participant_id', sa.Integer(), nullable=False),
        sa.Column('caregiver_id', sa.Integer(), nullable=False),
        sa.Column('training_mode', sa.String(length=30), nullable=False),
        sa.Column('title', sa.String(length=150), nullable=False),
        sa.Column('status', sa.String(length=20), server_default='completed', nullable=False),
        sa.Column('duration_minutes', sa.Integer(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('logged_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['caregiver_id'], ['users.id']),
        sa.ForeignKeyConstraint(['participant_id'], ['participants.id']),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_session_training_logs_participant_id'), 'session_training_logs', ['participant_id'], unique=False)
    op.create_index(op.f('ix_session_training_logs_session_id'), 'session_training_logs', ['session_id'], unique=False)
    op.create_index('ix_training_logs_participant', 'session_training_logs', ['participant_id'], unique=False)
    op.create_index('ix_training_logs_session', 'session_training_logs', ['session_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_training_logs_session', table_name='session_training_logs')
    op.drop_index('ix_training_logs_participant', table_name='session_training_logs')
    op.drop_index(op.f('ix_session_training_logs_session_id'), table_name='session_training_logs')
    op.drop_index(op.f('ix_session_training_logs_participant_id'), table_name='session_training_logs')
    op.drop_table('session_training_logs')
