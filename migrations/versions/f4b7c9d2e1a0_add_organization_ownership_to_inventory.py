"""Add organization ownership to inventory records.

Revision ID: f4b7c9d2e1a0
Revises: e9a4c2d7f631
Create Date: 2026-07-23
"""

from alembic import op
import sqlalchemy as sa


revision = "f4b7c9d2e1a0"
down_revision = "e9a4c2d7f631"
branch_labels = None
depends_on = None


TABLES = ("urun", "stok_hareket", "category", "warehouse")
UNIQUE_TABLES = {
    "category": "uq_organization_category_name",
    "warehouse": "uq_organization_warehouse_name",
}


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
            f"{table_name} tablosunda firmaya bağlanamayan {missing_count} kayıt var."
        )


def _remove_exact_duplicates(connection, table_name):
    rows = connection.execute(sa.text(
        f"SELECT id, organization_id, name FROM {table_name} ORDER BY id"
    )).mappings()
    seen = set()
    duplicate_ids = []
    for row in rows:
        key = (row["organization_id"], row["name"])
        if key in seen:
            duplicate_ids.append(row["id"])
        else:
            seen.add(key)

    for record_id in duplicate_ids:
        connection.execute(
            sa.text(f"DELETE FROM {table_name} WHERE id = :record_id"),
            {"record_id": record_id},
        )


def upgrade():
    for table_name in TABLES:
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(sa.Column("organization_id", sa.Integer(), nullable=True))

    connection = op.get_bind()
    for table_name in TABLES:
        _backfill_organization_ids(connection, table_name)

    for table_name in UNIQUE_TABLES:
        _remove_exact_duplicates(connection, table_name)

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
            if table_name in UNIQUE_TABLES:
                batch_op.create_unique_constraint(
                    UNIQUE_TABLES[table_name],
                    ["organization_id", "name"],
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
            if table_name in UNIQUE_TABLES:
                batch_op.drop_constraint(UNIQUE_TABLES[table_name], type_="unique")
            batch_op.drop_constraint(
                f"fk_{table_name}_organization_id",
                type_="foreignkey",
            )
            batch_op.drop_column("organization_id")
