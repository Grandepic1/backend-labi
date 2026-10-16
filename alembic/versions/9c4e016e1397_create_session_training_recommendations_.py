"""create_session_training_recommendations_table

Revision ID: 9c4e016e1397
Revises: 14b491096f8b
Create Date: 2026-10-15 20:15:27.892451

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '9c4e016e1397'
down_revision: str | None = '14b491096f8b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'session_training_recommendations',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('run_id', sa.Integer(), nullable=False),
        sa.Column('participant_id', sa.Integer(), nullable=False),
        sa.Column('urgency_level', sa.String(length=50), nullable=False),
        sa.Column('primary_mode', sa.String(length=30), nullable=False),
        sa.Column('secondary_mode', sa.String(length=30), nullable=True),
        sa.Column('target_goal', sa.Text(), nullable=False),
        sa.Column('overall_interpretation', sa.Text(), nullable=False),
        sa.Column('medical_alert', sa.Text(), nullable=True),
        sa.Column('home_trainings', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['participant_id'], ['participants.id'], ),
        sa.ForeignKeyConstraint(['run_id'], ['session_analysis_runs.id'], ),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_session_training_recommendations_participant_id'), 'session_training_recommendations', ['participant_id'], unique=False)
    op.create_index(op.f('ix_session_training_recommendations_run_id'), 'session_training_recommendations', ['run_id'], unique=False)
    op.create_index(op.f('ix_session_training_recommendations_session_id'), 'session_training_recommendations', ['session_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_session_training_recommendations_session_id'), table_name='session_training_recommendations')
    op.drop_index(op.f('ix_session_training_recommendations_run_id'), table_name='session_training_recommendations')
    op.drop_index(op.f('ix_session_training_recommendations_participant_id'), table_name='session_training_recommendations')
    op.drop_table('session_training_recommendations')

