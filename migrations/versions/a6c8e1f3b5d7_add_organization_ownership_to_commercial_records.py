"""Add organization ownership to commercial records.

Revision ID: a6c8e1f3b5d7
Revises: f4b7c9d2e1a0
Create Date: 2026-07-23
"""

from alembic import op
import sqlalchemy as sa


revision = "a6c8e1f3b5d7"
down_revision = "f4b7c9d2e1a0"
branch_labels = None
depends_on = None


TABLES = ("cari", "satis", "teklif", "iade", "cari_hareket")


def _backfill_organization_ids(connection, table_name):
    connection.execute(sa.text(
        f'''
        UPDATE {table_name}
        SET organization_id = (
            SELECT organization_id
            FROM "user"
            WHERE "user".id = {table_name}.user_id
        )
        WHERE organization_id IS NULL
        '''
    ))
    missing_count = connection.execute(sa.text(
        f"SELECT COUNT(*) FROM {table_name} WHERE organization_id IS NULL"
    )).scalar_one()
    if missing_count:
        raise RuntimeError(
            f"{table_name} tablosunda firmaya baglanamayan {missing_count} kayit var."
        )


def upgrade():
    for table_name in TABLES:
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(sa.Column("organization_id", sa.Integer(), nullable=True))

    connection = op.get_bind()
    for table_name in TABLES:
        _backfill_organization_ids(connection, table_name)

    for table_name in TABLES:
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column(
                "organization_id",
                existing_type=sa.Integer(),
                nullable=False,
            )
            batch_op.create_foreign_key(
                f"fk_{table_name}_organization_id",
                "organization",
                ["organization_id"],
                ["id"],
            )
        op.create_index(
            f"ix_{table_name}_organization_id",
            table_name,
            ["organization_id"],
            unique=False,
        )


def downgrade():
    for table_name in reversed(TABLES):
        op.drop_index(f"ix_{table_name}_organization_id", table_name=table_name)
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_constraint(
                f"fk_{table_name}_organization_id",
                type_="foreignkey",
            )
            batch_op.drop_column("organization_id")
