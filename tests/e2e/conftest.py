"""Tests E2E : les abuse stories rejouées contre un serveur réel, en HTTP.

Lancement (le serveur et les tests partagent les mêmes variables d'environnement) :
    set -a && source .env && set +a
    uvicorn app.main:app --port 8000 --workers 4 &
    BASE_URL=http://127.0.0.1:8000 pytest tests/e2e -v

Sans BASE_URL, ces tests sont ignorés (la CI exécute les tests unitaires).
"""
import hashlib
import hmac
import json
import os
import random
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

BASE_URL = os.environ.get("BASE_URL")
PASSWORD = "motdepasse-solide-42"

if not BASE_URL:
    collect_ignore_glob = ["test_*.py"]


def fake_ip() -> str:
    """Adresse source simulée : uvicorn fait confiance à X-Forwarded-For venant de 127.0.0.1
    (proxy local), ce qui permet de simuler des parieurs distincts sans déclencher la limite
    d'inscription par IP."""
    return f"10.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"


class Api:
    def __init__(self) -> None:
        self.http = httpx.Client(base_url=BASE_URL, timeout=60)

    def user(self, prefix: str = "u") -> dict:
        name = f"{prefix}_{uuid.uuid4().hex[:12]}"
        ip = {"X-Forwarded-For": fake_ip()}
        r = self.http.post("/auth/register", json={"username": name, "email": f"{name}@ex.fr",
                                                   "password": PASSWORD}, headers=ip)
        assert r.status_code == 201, r.text
        r = self.http.post("/auth/login", json={"username": name, "password": PASSWORD}, headers=ip)
        assert r.status_code == 200, r.text
        return {"name": name, "id": None,
                "h": {"Authorization": f"Bearer {r.json()['access_token']}", **ip}}

    def psp(self, event: dict, secret: str | None = None, ts: int | None = None) -> httpx.Response:
        raw = json.dumps(event).encode()
        ts = ts or int(time.time())
        secret = secret or os.environ["TOUTBET_PSP_WEBHOOK_SECRET"]
        sig = hmac.new(secret.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
        return self.http.post("/payments/webhook", content=raw,
                              headers={"PSP-Signature": f"t={ts},v1={sig}", "Content-Type": "application/json"})

    def fund(self, u: dict, amount: int = 10_000) -> None:
        dep = self.http.post("/wallet/deposits", json={"amount_cents": amount}, headers=u["h"]).json()
        r = self.psp({"id": f"evt_{uuid.uuid4().hex}", "type": "payment.succeeded",
                      "data": {"deposit_id": dep["id"], "amount_cents": amount}})
        assert r.status_code == 200, r.text

    def balance(self, u: dict) -> int:
        return self.http.get("/wallet", headers=u["h"]).json()["balance_cents"]

    def bet(self, bookie: dict, invitees: list[dict] = (), **kw) -> dict:
        body = {"title": "Matis va-t-il réussir son créneau ?", "min_stake_cents": 500, "bookie_fee_bps": 500,
                "closes_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
        body.update(kw)
        r = self.http.post("/bets", json=body, headers=bookie["h"])
        assert r.status_code == 201, r.text
        b = r.json()
        for p in invitees:
            assert self.http.post(f"/bets/{b['id']}/invitations", json={"username": p["name"]},
                                  headers=bookie["h"]).status_code == 201
        return b

    def wager(self, u: dict, bet_id: str, outcome: str = "yes", stake: int = 1000,
              key: str | None = None) -> httpx.Response:
        return self.http.post(f"/bets/{bet_id}/wagers", json={"outcome": outcome, "stake_cents": stake},
                              headers={**u["h"], "Idempotency-Key": key or uuid.uuid4().hex})


@pytest.fixture(scope="session")
def api():
    return Api()


@pytest.fixture(scope="session")
def db():
    """Accès direct à la base du serveur, uniquement pour simuler l'écoulement du temps
    (clôture d'un pari) et promouvoir un modérateur : deux actions sans route API."""
    from app.db import SessionLocal, init_engine
    init_engine(os.environ["TOUTBET_DATABASE_URL"])
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture()
def close_bet(db):
    from app.models import Bet

    def _close(bet_id: str) -> None:
        db.expire_all()
        bet = db.get(Bet, bet_id)
        bet.closes_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    return _close


@pytest.fixture()
def make_admin(db):
    from app.models import Role, User

    def _admin(u: dict) -> None:
        db.expire_all()
        user = db.query(User).filter_by(username=u["name"]).one()
        user.role = Role.ADMIN
        db.commit()
    return _admin
