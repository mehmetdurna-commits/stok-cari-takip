"""Use fixed precision decimals for financial values.

Revision ID: e9a4c2d7f631
Revises: c7e4a1b2d9f0
Create Date: 2026-07-23
"""

from alembic import op
import sqlalchemy as sa


revision = "e9a4c2d7f631"
down_revision = "c7e4a1b2d9f0"
branch_labels = None
depends_on = None


COLUMN_GROUPS = {
    "subscription_payment": {"amount": (18, 2)},
    "account": {"opening_balance": (18, 2)},
    "cari": {"borc": (18, 2), "alacak": (18, 2)},
    "urun": {
        "alis_fiyati": (18, 2),
        "satis_fiyati": (18, 2),
        "stok_miktari": (18, 4),
        "kritik_stok": (18, 4),
    },
    "account_reconciliation": {
        "expected_balance": (18, 2),
        "counted_balance": (18, 2),
        "difference": (18, 2),
    },
    "cari_hareket": {"tutar": (18, 2)},
    "cash_transaction": {"tutar": (18, 2)},
    "iade": {"iade_tutari": (18, 2)},
    "personel": {"maas": (18, 2)},
    "satis": {
        "ara_toplam": (18, 2),
        "kdv_orani": (7, 4),
        "kdv_tutar": (18, 2),
        "iskonto": (18, 2),
        "genel_toplam": (18, 2),
    },
    "stok_hareket": {
        "miktar": (18, 4),
        "eski_stok": (18, 4),
        "yeni_stok": (18, 4),
    },
    "teklif": {
        "toplam_tutar": (18, 2),
        "kdv_orani": (7, 4),
        "genel_toplam": (18, 2),
    },
    "avans": {"tutar": (18, 2)},
    "egitim_kaydi": {"ucret": (18, 2)},
    "iade_kalem": {
        "miktar": (18, 4),
        "birim_fiyat": (18, 2),
        "eski_stok": (18, 4),
        "yeni_stok": (18, 4),
    },
    "maas_kaydi": {
        "brut_ucret": (18, 2),
        "net_ucret": (18, 2),
        "sgk_kesinti": (18, 2),
        "gelir_vergisi": (18, 2),
        "damga_vergisi": (18, 2),
        "diger_kesintiler": (18, 2),
    },
    "prim": {"tutar": (18, 2)},
    "satis_kalemi": {
        "miktar": (18, 4),
        "birim_fiyat": (18, 2),
        "toplam": (18, 2),
    },
    "teklif_kalemi": {
        "miktar": (18, 4),
        "birim_fiyat": (18, 2),
        "kdv_orani": (7, 4),
        "toplam": (18, 2),
    },
}


def _alter_columns(target_type_factory, existing_type, use_postgresql_cast=False):
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    for table_name, columns in COLUMN_GROUPS.items():
        if is_sqlite:
            with op.batch_alter_table(table_name) as batch_op:
                for column_name, precision_scale in columns.items():
                    batch_op.alter_column(
                        column_name,
                        existing_type=existing_type,
                        type_=target_type_factory(*precision_scale),
                    )
            continue

        for column_name, precision_scale in columns.items():
            kwargs = {}
            if use_postgresql_cast and bind.dialect.name == "postgresql":
                kwargs["postgresql_using"] = (
                    f"ROUND({column_name}::numeric, {precision_scale[1]})"
                )
            op.alter_column(
                table_name,
                column_name,
                existing_type=existing_type,
                type_=target_type_factory(*precision_scale),
                **kwargs,
            )


def upgrade():
    _alter_columns(sa.Numeric, sa.Float(), use_postgresql_cast=True)


def downgrade():
    _alter_columns(lambda _precision, _scale: sa.Float(), sa.Numeric())
