"""link returns to original sales

Revision ID: c7e4a1b2d9f0
Revises: 8f3b6a7c9d21
Create Date: 2026-07-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c7e4a1b2d9f0'
down_revision = '8f3b6a7c9d21'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('iade') as batch_op:
        batch_op.add_column(sa.Column('satis_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('refund_mode', sa.String(length=20), nullable=True))
        batch_op.create_foreign_key('fk_iade_satis_id', 'satis', ['satis_id'], ['id'])
    op.create_index('ix_iade_satis_id', 'iade', ['satis_id'], unique=False)

    with op.batch_alter_table('iade_kalem') as batch_op:
        batch_op.add_column(sa.Column('satis_kalemi_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_iade_kalem_satis_kalemi_id',
            'satis_kalemi',
            ['satis_kalemi_id'],
            ['id'],
        )
    op.create_index(
        'ix_iade_kalem_satis_kalemi_id',
        'iade_kalem',
        ['satis_kalemi_id'],
        unique=False,
    )


def downgrade():
    op.drop_index('ix_iade_kalem_satis_kalemi_id', table_name='iade_kalem')
    with op.batch_alter_table('iade_kalem') as batch_op:
        batch_op.drop_constraint('fk_iade_kalem_satis_kalemi_id', type_='foreignkey')
        batch_op.drop_column('satis_kalemi_id')

    op.drop_index('ix_iade_satis_id', table_name='iade')
    with op.batch_alter_table('iade') as batch_op:
        batch_op.drop_constraint('fk_iade_satis_id', type_='foreignkey')
        batch_op.drop_column('refund_mode')
        batch_op.drop_column('satis_id')
