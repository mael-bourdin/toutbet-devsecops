"""Règlement des paris : validation du résultat et redistribution (arithmétique entière)."""
import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ledger
from app.audit import audit
from app.config import get_settings
from app.models import Bet, BetStatus, Outcome, ResultVote, Wager


def compute_payouts(wagers: list[Wager], outcome: Outcome, platform_bps: int, bookie_bps: int) -> dict:
    """Retourne {'platform': x, 'bookie': y, 'winners': {user_id: montant}} ; la somme vaut toujours le pot."""
    pot = sum(w.stake_cents for w in wagers)
    winners = [w for w in wagers if w.outcome == outcome]
    if not winners:  # personne n'a gagné : remboursement intégral, aucune commission
        return {"platform": 0, "bookie": 0, "winners": {w.user_id: w.stake_cents for w in wagers}}
    platform_fee = pot * platform_bps // 10_000
    bookie_fee = pot * bookie_bps // 10_000
    distributable = pot - platform_fee - bookie_fee
    winning_total = sum(w.stake_cents for w in winners)
    shares = {w.user_id: distributable * w.stake_cents // winning_total for w in winners}
    platform_fee += distributable - sum(shares.values())  # reliquat d'arrondi -> plateforme
    return {"platform": platform_fee, "bookie": bookie_fee, "winners": shares}


def settle(db: Session, bet: Bet, outcome: Outcome, actor_id: str | None) -> None:
    if bet.status == BetStatus.SETTLED:
        return  # idempotent
    wagers = list(db.scalars(select(Wager).where(Wager.bet_id == bet.id)))
    payouts = compute_payouts(wagers, outcome, bet.platform_fee_bps, bet.bookie_fee_bps)
    escrow = ledger.escrow_account(bet.id)
    movements = [(escrow, -ledger.balance(db, escrow)),
                 (ledger.PLATFORM, payouts["platform"]),
                 (ledger.user_account(bet.bookie_id), payouts["bookie"])]
    movements += [(ledger.user_account(uid), amt) for uid, amt in payouts["winners"].items()]
    ledger.post(db, "settlement", movements)  # lève si déséquilibré
    bet.final_outcome = outcome
    bet.status = BetStatus.SETTLED
    audit(db, actor_id, "bet.settled", bet_id=bet.id, outcome=outcome.value, payouts=payouts)


def refund(db: Session, bet: Bet, actor_id: str | None) -> None:
    escrow = ledger.escrow_account(bet.id)
    wagers = list(db.scalars(select(Wager).where(Wager.bet_id == bet.id)))
    if wagers:
        ledger.post(db, "refund", [(escrow, -ledger.balance(db, escrow))] +
                    [(ledger.user_account(w.user_id), w.stake_cents) for w in wagers])
    bet.status = BetStatus.CANCELLED
    audit(db, actor_id, "bet.cancelled", bet_id=bet.id)


def evaluate_votes(db: Session, bet: Bet) -> None:
    """Quorum : > 50 % des parieurs confirment -> règlement ; >= 1/3 contestent -> litige (modération)."""
    s = get_settings()
    n = len(bet.wagers)
    votes = list(db.scalars(select(ResultVote).where(ResultVote.bet_id == bet.id)))
    contests = sum(1 for v in votes if not v.confirms)
    confirms = sum(1 for v in votes if v.confirms)
    if contests >= max(1, math.ceil(n * s.contest_ratio)):
        bet.status = BetStatus.DISPUTED
        audit(db, None, "bet.disputed", bet_id=bet.id, contests=contests)
    elif confirms > n * s.dispute_quorum_ratio:
        settle(db, bet, bet.proposed_outcome, None)
