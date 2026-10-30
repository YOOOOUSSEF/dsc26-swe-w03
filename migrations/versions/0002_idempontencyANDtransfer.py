"""idempontencyANDtransfers

Revision ID: 0002
Revises:
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # second table
    op.create_table(
        "transfers",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("from_account_id",sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("to_account_id",sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("amount_piastres", sa.Integer(), nullable=False),
        sa.Column("memo", sa.String(140), nullable=True),
        sa.Column("status", sa.String(),nullable=False, default="completed"),
        sa.CheckConstraint("amount_piastres >= 0", name="ck_amount_non_negative"),
        sa.CheckConstraint("from_account_id != to_account_id", name="ck_different_accounts"),
    )
    op.create_index("ix_transfers_from_account_id", "transfers", ["from_account_id"])
    op.create_index("ix_transfers_to_account_id", "transfers", ["to_account_id"])

    # third and last table
    op.create_table(
        "requests_keys",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("key",sa.String(32), primary_key=True),
        sa.Column("from_account_id",sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("to_account_id",sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("amount_piastres", sa.Integer(), nullable=False),
        sa.Column("memo", sa.String(140), nullable=True),
        sa.Column("status_code",sa.Integer,nullable=True),
        sa.Column("response_body",sa.JSON,nullable=True),
    )


# Drop idempotencyRecord first because dependency (default RESTRICT/NO ACTION)
# I do not set it ON DELETE CASCADE.
# because sqllite does not support it (unless you run PRAGMA foreign_keys=ON ).
def downgrade() -> None:
    op.drop_table("requests_keys")

    op.drop_index("ix_transfers_from_account_id", table_name="transfers")
    op.drop_index("ix_transfers_to_account_id", table_name="transfers")
    op.drop_table("transfers")