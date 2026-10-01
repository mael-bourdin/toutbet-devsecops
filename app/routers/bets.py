import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import ledger
from app.audit import audit
from app.config import get_settings
from app.db import get_db
from app.models import Bet, BetStatus, IdempotencyKey, Invitation, ResultVote, User, Wager
from app.schemas import BetCreateIn, BetOut, InviteIn, ProposeResultIn, ResolveIn, VoteIn, WagerIn, WagerOut
from app.security import get_current_user, rate_limit_writes, require_admin, sign
from app.settlement import evaluate_votes, refund, settle

router = APIRouter(prefix="/bets", tags=["bets"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _is_invited(db: Session, bet_id: str, user_id: str) -> bool:
    return db.scalar(select(exists().where(Invitation.bet_id == bet_id, Invitation.user_id == user_id)))


def _load_bet_for(db: Session, bet_id: str, user: User) -> Bet:
    """Contrôle d'accès objet (anti-IDOR) : seul le bookie, un invité ou un admin voit le pari. 404 sinon."""
    bet = db.get(Bet, bet_id)
    if bet is None or not (bet.bookie_id == user.id or user.role.value == "admin"
                           or _is_invited(db, bet_id, user.id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pari introuvable")
    return bet


def _refresh_status(bet: Bet) -> None:
    if bet.status == BetStatus.OPEN and _now() >= _aware(bet.closes_at):
        bet.status = BetStatus.CLOSED


@router.post("", response_model=BetOut, status_code=201)
def create_bet(body: BetCreateIn, user: User = Depends(rate_limit_writes), db: Session = Depends(get_db)):
    closes_at = _aware(body.closes_at)
    if not (_now() + timedelta(minutes=5) <= closes_at <= _now() + timedelta(days=90)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Date de clôture invalide")
    bet = Bet(bookie_id=user.id, title=body.title, description=body.description,
              min_stake_cents=body.min_stake_cents, bookie_fee_bps=body.bookie_fee_bps,
              platform_fee_bps=get_settings().platform_fee_bps, closes_at=closes_at)
    db.add(bet)
    db.flush()
    audit(db, user.id, "bet.created", bet_id=bet.id, title=bet.title, closes_at=closes_at)
    db.commit()
    return bet


@router.get("/{bet_id}", response_model=BetOut)
def get_bet(bet_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bet = _load_bet_for(db, bet_id, user)
    _refresh_status(bet)
    db.commit()
    return bet


@router.post("/{bet_id}/invitations", status_code=201)
def invite(bet_id: str, body: InviteIn, user: User = Depends(rate_limit_writes), db: Session = Depends(get_db)):
    bet = _load_bet_for(db, bet_id, user)
    if bet.bookie_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Seul le bookie peut inviter")
    _refresh_status(bet)
    if bet.status != BetStatus.OPEN:
        raise HTTPException(status.HTTP_409_CONFLICT, "Pari clos")
    invitee = db.scalar(select(User).where(User.username == body.username))
    if invitee is None or invitee.id == user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Utilisateur introuvable")
    if not _is_invited(db, bet_id, invitee.id):
        db.add(Invitation(bet_id=bet_id, user_id=invitee.id))
        audit(db, user.id, "bet.invited", bet_id=bet_id, invitee=invitee.id)
    db.commit()
    return {"status": "invited"}


@router.post("/{bet_id}/wagers", response_model=WagerOut, status_code=201)
def place_wager(bet_id: str, body: WagerIn, idempotency_key: str = Header(min_length=8, max_length=64),
                user: User = Depends(rate_limit_writes), db: Session = Depends(get_db)):
    # Rejeu d'une requête déjà traitée (double clic, retry réseau) -> même réponse, pas de double débit
    previous = db.scalar(select(IdempotencyKey).where(IdempotencyKey.user_id == user.id,
                                                      IdempotencyKey.key == idempotency_key))
    if previous:
        return WagerOut(**json.loads(previous.response_json))

    bet = _load_bet_for(db, bet_id, user)
    _refresh_status(bet)
    if bet.bookie_id == user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Le bookie ne peut pas parier sur son propre pari")
    if bet.status != BetStatus.OPEN:  # heure serveur uniquement, jamais celle du client
        raise HTTPException(status.HTTP_409_CONFLICT, "Les paris sont clos")
    if body.stake_cents < bet.min_stake_cents:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Mise inférieure au minimum")

    created_at = _now()
    receipt = sign({"bet_id": bet.id, "user_id": user.id, "outcome": body.outcome.value,
                    "stake_cents": body.stake_cents, "created_at": created_at.isoformat()})
    wager = Wager(bet_id=bet.id, user_id=user.id, outcome=body.outcome, stake_cents=body.stake_cents,
                  receipt=receipt, created_at=created_at)
    try:
        ledger.transfer(db, "stake", ledger.user_account(user.id), ledger.escrow_account(bet.id), body.stake_cents)
        db.add(wager)
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Vous avez déjà parié sur ce pari")
    out = WagerOut.model_validate(wager)
    db.add(IdempotencyKey(user_id=user.id, key=idempotency_key, status_code=201,
                          response_json=out.model_dump_json()))
    audit(db, user.id, "wager.placed", bet_id=bet.id, wager_id=wager.id, outcome=body.outcome.value,
          stake_cents=body.stake_cents, receipt=receipt)
    db.commit()
    return out


@router.post("/{bet_id}/result", response_model=BetOut)
def propose_result(bet_id: str, body: ProposeResultIn, user: User = Depends(rate_limit_writes),
                   db: Session = Depends(get_db)):
    bet = _load_bet_for(db, bet_id, user)
    if bet.bookie_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Seul le bookie propose le résultat")
    _refresh_status(bet)
    if bet.status != BetStatus.CLOSED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Le résultat ne peut être proposé qu'après la clôture")
    bet.proposed_outcome = body.outcome
    bet.status = BetStatus.PENDING_VALIDATION
    audit(db, user.id, "result.proposed", bet_id=bet.id, outcome=body.outcome.value)
    if not bet.wagers:
        refund(db, bet, user.id)
    db.commit()
    return bet


@router.post("/{bet_id}/votes", response_model=BetOut)
def vote(bet_id: str, body: VoteIn, user: User = Depends(rate_limit_writes), db: Session = Depends(get_db)):
    bet = _load_bet_for(db, bet_id, user)
    if bet.status != BetStatus.PENDING_VALIDATION:
        raise HTTPException(status.HTTP_409_CONFLICT, "Aucun résultat en attente de validation")
    if not any(w.user_id == user.id for w in bet.wagers):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Seuls les parieurs votent")
    try:
        db.add(ResultVote(bet_id=bet.id, user_id=user.id, confirms=body.confirms))
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Vote déjà enregistré")
    audit(db, user.id, "result.voted", bet_id=bet.id, confirms=body.confirms)
    evaluate_votes(db, bet)
    db.commit()
    return bet


@router.post("/{bet_id}/resolve", response_model=BetOut)
def resolve_dispute(bet_id: str, body: ResolveIn, admin: User = Depends(require_admin),
                    db: Session = Depends(get_db)):
    bet = db.get(Bet, bet_id)
    if bet is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pari introuvable")
    if bet.status != BetStatus.DISPUTED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Pari non litigieux")
    if body.outcome is None:
        refund(db, bet, admin.id)
    else:
        settle(db, bet, body.outcome, admin.id)
    db.commit()
    return bet
