"""Vérifie, après une campagne de tests dynamiques, que l'argent des parieurs est intact.

    TOUTBET_DATABASE_URL=sqlite:///... python security/iast/check_invariants.py

Puis résume les événements remontés par l'instrumentation (reports/iast/events.jsonl).
"""
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sqlalchemy import func, select  # noqa: E402

from app.audit import verify_chain  # noqa: E402
from app.db import SessionLocal, init_engine  # noqa: E402
from app.models import Bet, BetStatus, LedgerEntry, Wager  # noqa: E402

init_engine(os.environ["TOUTBET_DATABASE_URL"])
db = SessionLocal()
ok = True


def check(label: str, cond: bool, detail: str = "") -> None:
    global ok
    ok &= cond
    print(f"[{'OK ' if cond else 'KO '}] {label}{' : ' + detail if detail else ''}")


total = db.scalar(select(func.coalesce(func.sum(LedgerEntry.amount_cents), 0)))
check("Grand livre équilibré (somme des écritures = 0)", total == 0, f"somme = {total}")

negatives = db.execute(select(LedgerEntry.account, func.sum(LedgerEntry.amount_cents).label("s"))
                       .where(LedgerEntry.account.like("user:%")).group_by(LedgerEntry.account)
                       .having(func.sum(LedgerEntry.amount_cents) < 0)).all()
check("Aucun solde parieur négatif", not negatives,
      f"{len(negatives)} comptes, pire = {min((s for _, s in negatives), default=0)} centimes")

bad_escrow = []
for bet in db.scalars(select(Bet).where(Bet.status.notin_([BetStatus.SETTLED, BetStatus.CANCELLED]))):
    staked = db.scalar(select(func.coalesce(func.sum(Wager.stake_cents), 0)).where(Wager.bet_id == bet.id))
    escrow = db.scalar(select(func.coalesce(func.sum(LedgerEntry.amount_cents), 0))
                       .where(LedgerEntry.account == f"escrow:{bet.id}"))
    if staked != escrow:
        bad_escrow.append(bet.id)
check("Séquestre de chaque pari ouvert = somme des mises", not bad_escrow, f"{len(bad_escrow)} écarts")
check("Chaîne d'audit HMAC intègre", verify_chain(db))

log = Path(os.environ.get("IAST_LOG", "reports/iast/events.jsonl"))
if log.exists():
    events = [json.loads(line) for line in log.read_text().splitlines()]
    kinds = Counter(e["kind"] for e in events)
    reqs = [e for e in events if e["kind"] == "request"]
    print(f"\nÉvénements IAST : {dict(kinds)}")
    if reqs:
        print(f"Requêtes HTTP observées : {len(reqs)} ; statuts : {dict(Counter(e['status'] for e in reqs))}")
        worst = max(reqs, key=lambda e: e["sql"])
        print(f"Max requêtes SQL par appel : {worst['sql']} ({worst['method']} {worst['path'][:60]})")
    for kind in ("sql_taint", "exception", "server_error", "response_leak"):
        for e in [e for e in events if e["kind"] == kind][:5]:
            print(f"  - {kind}: {json.dumps({k: v for k, v in e.items() if k not in ('t', 'pid', 'stack')}, ensure_ascii=False)[:400]}")
sys.exit(0 if ok else 1)
