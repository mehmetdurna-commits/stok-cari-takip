"""add user company logo

Revision ID: 8f3b6a7c9d21
Revises: 2d1b00ba9040
Create Date: 2026-07-02 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '8f3b6a7c9d21'
down_revision = '2d1b00ba9040'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('firma_logo', sa.String(length=255), nullable=True))


def downgrade():
    op.drop_column('user', 'firma_logo')
