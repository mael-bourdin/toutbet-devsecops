"""Schémas d'entrée/sortie : validation stricte, champs inconnus refusés (anti mass-assignment)."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import BetStatus, Outcome


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RegisterIn(Strict):
    username: str = Field(pattern=r"^[a-zA-Z0-9_]{3,32}$")
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class LoginIn(Strict):
    username: str = Field(max_length=32)
    password: str = Field(max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    username: str
    kyc_verified: bool


class BetCreateIn(Strict):
    title: str = Field(min_length=5, max_length=140)
    description: str = Field(default="", max_length=2000)
    min_stake_cents: int = Field(default=100, ge=100, le=50_000)
    bookie_fee_bps: int = Field(default=0, ge=0, le=1000)
    closes_at: datetime


class BetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    bookie_id: str
    title: str
    description: str
    min_stake_cents: int
    bookie_fee_bps: int
    platform_fee_bps: int
    closes_at: datetime
    status: BetStatus
    proposed_outcome: Outcome | None
    final_outcome: Outcome | None


class InviteIn(Strict):
    username: str = Field(pattern=r"^[a-zA-Z0-9_]{3,32}$")


class WagerIn(Strict):
    outcome: Outcome
    stake_cents: int = Field(ge=100, le=50_000)


class WagerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    bet_id: str
    outcome: Outcome
    stake_cents: int
    receipt: str
    created_at: datetime


class ProposeResultIn(Strict):
    outcome: Outcome


class VoteIn(Strict):
    confirms: bool


class ResolveIn(Strict):
    outcome: Outcome | None = None  # None = annulation et remboursement


class DepositIn(Strict):
    amount_cents: int = Field(ge=100, le=100_000)


class DepositOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    amount_cents: int
    status: str


class WithdrawIn(Strict):
    amount_cents: int = Field(ge=100, le=100_000)
    password: str = Field(max_length=128)  # ré-authentification pour les opérations sensibles


class BalanceOut(BaseModel):
    balance_cents: int
