import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app import ledger
from app.audit import audit
from app.db import get_db
from app.models import Deposit, PaymentEvent, User
from app.schemas import BalanceOut, DepositIn, DepositOut, WithdrawIn
from app.security import get_current_user, rate_limit_writes, verify_password, verify_psp_signature

router = APIRouter(tags=["wallet"])


@router.get("/wallet", response_model=BalanceOut)
def get_balance(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return BalanceOut(balance_cents=ledger.balance(db, ledger.user_account(user.id)))


@router.post("/wallet/deposits", response_model=DepositOut, status_code=201)
def create_deposit(body: DepositIn, user: User = Depends(rate_limit_writes), db: Session = Depends(get_db)):
    """Crée une intention de paiement. Le solde n'est crédité QUE par le webhook signé du PSP."""
    deposit = Deposit(user_id=user.id, amount_cents=body.amount_cents)
    db.add(deposit)
    db.flush()
    audit(db, user.id, "deposit.created", deposit_id=deposit.id, amount_cents=body.amount_cents)
    db.commit()
    return deposit


@router.post("/payments/webhook", include_in_schema=False)
async def psp_webhook(request: Request, psp_signature: str | None = Header(default=None),
                      db: Session = Depends(get_db)):
    raw = await request.body()
    verify_psp_signature(raw, psp_signature)
    event = json.loads(raw)
    if db.get(PaymentEvent, event["id"]):
        return {"status": "already_processed"}  # anti-rejeu
    db.add(PaymentEvent(event_id=event["id"]))
    if event.get("type") == "payment.succeeded":
        deposit = db.get(Deposit, event["data"]["deposit_id"])
        if deposit is None or deposit.status != "pending" or deposit.amount_cents != event["data"]["amount_cents"]:
            audit(db, None, "deposit.mismatch", event_id=event["id"])
            db.commit()
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Paiement incohérent")
        ledger.transfer(db, "deposit", ledger.PSP, ledger.user_account(deposit.user_id), deposit.amount_cents,
                        allow_negative_src=True)
        deposit.status = "succeeded"
        audit(db, None, "deposit.succeeded", deposit_id=deposit.id, event_id=event["id"])
    db.commit()
    return {"status": "ok"}


@router.post("/wallet/withdrawals", status_code=202)
def withdraw(body: WithdrawIn, user: User = Depends(rate_limit_writes), db: Session = Depends(get_db)):
    if not verify_password(user.password_hash, body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Ré-authentification échouée")
    if not user.kyc_verified:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Vérification d'identité (KYC) requise pour retirer")
    tx = ledger.transfer(db, "withdrawal", ledger.user_account(user.id), ledger.PSP, body.amount_cents)
    audit(db, user.id, "withdrawal.requested", amount_cents=body.amount_cents, tx_id=tx)
    db.commit()
    return {"status": "pending", "tx_id": tx}
