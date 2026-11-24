"""Grand livre en partie double : chaque transaction est équilibrée (somme = 0)."""
import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import LedgerEntry, User

PLATFORM = "platform"
PSP = "psp"


def user_account(user_id: str) -> str:
    return f"user:{user_id}"


def escrow_account(bet_id: str) -> str:
    return f"escrow:{bet_id}"


def balance(db: Session, account: str) -> int:
    return db.scalar(select(func.coalesce(func.sum(LedgerEntry.amount_cents), 0))
                     .where(LedgerEntry.account == account))


def post(db: Session, kind: str, movements: list[tuple[str, int]]) -> str:
    """Enregistre des mouvements équilibrés. Lève une erreur si la somme n'est pas nulle."""
    movements = [(acc, amt) for acc, amt in movements if amt != 0]
    if sum(amt for _, amt in movements) != 0:
        raise ValueError("Transaction déséquilibrée")
    tx_id = str(uuid.uuid4())
    for account, amount in movements:
        db.add(LedgerEntry(tx_id=tx_id, account=account, amount_cents=amount, kind=kind))
    db.flush()
    return tx_id


def lock_account(db: Session, account: str) -> None:
    """Prend un verrou d'écriture sur le compte AVANT de lire son solde (anti « check-then-act »).

    Écriture neutre sur la ligne de l'utilisateur : verrou de ligne en PostgreSQL, verrou d'écriture
    de la base en SQLite. Deux débits simultanés du même compte sont ainsi sérialisés : le second
    attend la validation du premier et lit le solde déjà débité."""
    if account.startswith("user:"):
        uid = account.removeprefix("user:")
        db.execute(update(User).where(User.id == uid).values(kyc_verified=User.kyc_verified))


def transfer(db: Session, kind: str, src: str, dst: str, amount: int, allow_negative_src: bool = False) -> str:
    if amount <= 0:
        raise ValueError("Montant invalide")
    if not allow_negative_src:
        lock_account(db, src)
    if not allow_negative_src and balance(db, src) < amount:
        raise HTTPException(status.HTTP_409_CONFLICT, "Solde insuffisant")
    return post(db, kind, [(src, -amount), (dst, amount)])
