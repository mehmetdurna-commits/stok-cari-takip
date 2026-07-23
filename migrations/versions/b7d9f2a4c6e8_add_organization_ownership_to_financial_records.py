"""Add organization ownership to financial records.

Revision ID: b7d9f2a4c6e8
Revises: a6c8e1f3b5d7
Create Date: 2026-07-23
"""

from alembic import op
import sqlalchemy as sa


revision = "b7d9f2a4c6e8"
down_revision = "a6c8e1f3b5d7"
branch_labels = None
depends_on = None


TABLES = ("account", "cash_transaction", "account_reconciliation")


def _missing_count(connection, table_name):
    return connection.execute(sa.text(
        f"SELECT COUNT(*) FROM {table_name} WHERE organization_id IS NULL"
    )).scalar_one()


def upgrade():
    for table_name in TABLES:
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(sa.Column("organization_id", sa.Integer(), nullable=True))

    connection = op.get_bind()
    connection.execute(sa.text(
        '''
        UPDATE account
        SET organization_id = (
            SELECT organization_id
            FROM "user"
            WHERE "user".id = account.user_id
        )
        WHERE organization_id IS NULL
        '''
    ))
    connection.execute(sa.text(
        '''
        UPDATE cash_transaction
        SET organization_id = COALESCE(
            (
                SELECT organization_id
                FROM account
                WHERE account.id = cash_transaction.account_id
            ),
            (
                SELECT organization_id
                FROM "user"
                WHERE "user".id = cash_transaction.user_id
            )
        )
        WHERE organization_id IS NULL
        '''
    ))
    connection.execute(sa.text(
        '''
        UPDATE account_reconciliation
        SET organization_id = COALESCE(
            (
                SELECT organization_id
                FROM account
                WHERE account.id = account_reconciliation.account_id
            ),
            (
                SELECT organization_id
                FROM "user"
                WHERE "user".id = account_reconciliation.user_id
            )
        )
        WHERE organization_id IS NULL
        '''
    ))

    for table_name in TABLES:
        missing_count = _missing_count(connection, table_name)
        if missing_count:
            raise RuntimeError(
                f"{table_name} tablosunda firmaya baglanamayan {missing_count} kayit var."
            )

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
