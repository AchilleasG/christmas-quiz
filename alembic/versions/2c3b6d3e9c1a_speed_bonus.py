"""add speed bonus flag and float scores

Revision ID: 2c3b6d3e9c1a
Revises: c0c5aa4cc3a1
Create Date: 2026-01-06 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision = '2c3b6d3e9c1a'
down_revision = 'c0c5aa4cc3a1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'questions',
        sa.Column('speed_bonus', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column('questions', 'speed_bonus', server_default=None)
    op.alter_column('session_players', 'score', type_=sa.Float(), existing_type=sa.Integer(), existing_nullable=False)


def downgrade() -> None:
    op.alter_column('session_players', 'score', type_=sa.Integer(), existing_type=sa.Float(), existing_nullable=False)
    op.drop_column('questions', 'speed_bonus')
