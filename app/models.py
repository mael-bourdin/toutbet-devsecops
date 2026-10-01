"""Modèle de données. Tous les montants sont des entiers en centimes (pas de float)."""
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(str, enum.Enum):
    USER = "user"
    ADMIN = "admin"  # modérateur des litiges


class BetStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"
    PENDING_VALIDATION = "pending_validation"
    DISPUTED = "disputed"
    SETTLED = "settled"
    CANCELLED = "cancelled"


class Outcome(str, enum.Enum):
    YES = "yes"
    NO = "no"


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.USER)
    kyc_verified: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Bet(Base):
    __tablename__ = "bets"
    __table_args__ = (
        CheckConstraint("min_stake_cents >= 100", name="min_stake_positive"),
        CheckConstraint("bookie_fee_bps >= 0 AND bookie_fee_bps <= 1000", name="bookie_fee_cap"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    bookie_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(140))
    description: Mapped[str] = mapped_column(Text, default="")
    min_stake_cents: Mapped[int] = mapped_column(Integer, default=100)
    bookie_fee_bps: Mapped[int] = mapped_column(Integer, default=0)
    platform_fee_bps: Mapped[int] = mapped_column(Integer)
    closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[BetStatus] = mapped_column(Enum(BetStatus), default=BetStatus.OPEN)
    proposed_outcome: Mapped[Outcome | None] = mapped_column(Enum(Outcome), nullable=True)
    final_outcome: Mapped[Outcome | None] = mapped_column(Enum(Outcome), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    version: Mapped[int] = mapped_column(Integer, default=1)  # verrou optimiste

    __mapper_args__ = {"version_id_col": version}

    wagers: Mapped[list["Wager"]] = relationship(back_populates="bet")


class Invitation(Base):
    __tablename__ = "invitations"
    __table_args__ = (UniqueConstraint("bet_id", "user_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    bet_id: Mapped[str] = mapped_column(ForeignKey("bets.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Wager(Base):
    """Une mise est immuable : aucune route ne permet de la modifier."""

    __tablename__ = "wagers"
    __table_args__ = (
        UniqueConstraint("bet_id", "user_id", name="one_wager_per_user"),
        CheckConstraint("stake_cents > 0", name="stake_positive"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    bet_id: Mapped[str] = mapped_column(ForeignKey("bets.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    outcome: Mapped[Outcome] = mapped_column(Enum(Outcome))
    stake_cents: Mapped[int] = mapped_column(Integer)
    receipt: Mapped[str] = mapped_column(String(64))  # HMAC du contenu signé -> non-répudiation
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    bet: Mapped[Bet] = relationship(back_populates="wagers")


class ResultVote(Base):
    __tablename__ = "result_votes"
    __table_args__ = (UniqueConstraint("bet_id", "user_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    bet_id: Mapped[str] = mapped_column(ForeignKey("bets.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    confirms: Mapped[bool] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LedgerEntry(Base):
    """Grand livre en partie double, append-only. Le solde = somme des écritures."""

    __tablename__ = "ledger_entries"
    __table_args__ = (CheckConstraint("amount_cents <> 0", name="non_zero"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tx_id: Mapped[str] = mapped_column(String(36), index=True)
    account: Mapped[str] = mapped_column(String(80), index=True)  # user:<id> | escrow:<bet> | platform | psp
    amount_cents: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PaymentEvent(Base):
    """Événements PSP déjà traités (anti-rejeu des webhooks)."""

    __tablename__ = "payment_events"
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Deposit(Base):
    __tablename__ = "deposits"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("user_id", "key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(36))
    key: Mapped[str] = mapped_column(String(64))
    response_json: Mapped[str] = mapped_column(Text)
    status_code: Mapped[int] = mapped_column(Integer)


class AuditLog(Base):
    """Journal chaîné par HMAC : toute modification/suppression casse la chaîne."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    payload: Mapped[str] = mapped_column(Text)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
