"""Database models. `Base` and `Account` are provided by DSC: do not change them
(migration 0001 creates `accounts` exactly like this).

Add `Transfer` (table `transfers`) and `IdempotencyRecord` (table `idempotency_records`)
below, then write migrations/versions/0002_*.py so that `alembic upgrade head` creates
exactly what these models describe.
"""

from sqlalchemy import JSON, CheckConstraint, Integer, String, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Account(Base):  # provided by DSC (migration 0001)
    __tablename__ = "accounts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(32), index=True)
    balance_piastres: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="EGP")
    __table_args__ = (CheckConstraint("balance_piastres >= 0", name="ck_accounts_balance_non_negative"),)


class Transfer(Base): # I will search here by transfer.id for idempotency key,
    # but also join between accounts and Transfers on (from_account_id and to) so I need index here.
    __tablename__ = "transfers"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    from_account_id: Mapped[str]= mapped_column(ForeignKey("accounts.id"),nullable=False,index=True)
    to_account_id: Mapped[str]= mapped_column(ForeignKey("accounts.id"),nullable=False,index=True)
    amount_piastres: Mapped[int] = mapped_column(Integer,nullable=False)
    memo: Mapped[str|None]= mapped_column(String(140),nullable=True)
    status: Mapped[str] = mapped_column(String,nullable=False, default="completed")
    __table_args__ = (CheckConstraint("amount_piastres >= 0", name="ck_amount_non_negative"),
                    CheckConstraint("from_account_id != to_account_id", name="ck_different_accounts"),)




class IdempotencyRecord(Base): # here no need for an index (rarely used)
    __tablename__ = "requests_keys"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    # 4 fields to detect different body or not.
    from_account_id: Mapped[str]= mapped_column(ForeignKey("accounts.id"),nullable=False) 
    to_account_id: Mapped[str]= mapped_column(ForeignKey("accounts.id"),nullable=False)
    amount_piastres: Mapped[int] = mapped_column(Integer,nullable=False)
    memo: Mapped[str|None]= mapped_column(String(140),nullable=True)
    # 2 fields to replay response.
    status_code: Mapped[int] = mapped_column(Integer,nullable=False)
    response_body: Mapped[dict] =mapped_column(JSON,nullable=False)