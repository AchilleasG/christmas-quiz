"""add quiz instructions

Revision ID: 6e0b2f2d2dcb
Revises: 2c3b6d3e9c1a
Create Date: 2026-01-06 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6e0b2f2d2dcb'
down_revision = '2c3b6d3e9c1a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('quizzes', sa.Column('instructions', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('quizzes', 'instructions')
