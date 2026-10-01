import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone

os.environ.setdefault("TOUTBET_JWT_SECRET", secrets.token_hex(32))
os.environ.setdefault("TOUTBET_AUDIT_KEY", secrets.token_hex(32))
os.environ.setdefault("TOUTBET_PSP_WEBHOOK_SECRET", secrets.token_hex(32))

import pytest
from fastapi.testclient import TestClient

from app.db import Base, SessionLocal, init_engine
from app.main import create_app
from app.models import Bet, Role, User
from app.security import limiter


@pytest.fixture()
def client():
    engine = init_engine("sqlite://")
    limiter.reset()
    with TestClient(create_app(with_lifespan=False)) as c:
        yield c
    Base.metadata.drop_all(engine)


@pytest.fixture()
def db():
    s = SessionLocal()
    yield s
    s.close()


def register(client, username, password="motdepasse-solide-42"):
    r = client.post("/auth/register", json={"username": username, "email": f"{username}@ex.fr", "password": password})
    assert r.status_code == 201, r.text
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def psp_post(client, event: dict, secret: str | None = None, ts: int | None = None):
    raw = json.dumps(event).encode()
    ts = ts or int(time.time())
    secret = secret or os.environ["TOUTBET_PSP_WEBHOOK_SECRET"]
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    return client.post("/payments/webhook", content=raw,
                       headers={"PSP-Signature": f"t={ts},v1={sig}", "Content-Type": "application/json"})


def fund(client, headers, amount=10_000):
    dep = client.post("/wallet/deposits", json={"amount_cents": amount}, headers=headers).json()
    r = psp_post(client, {"id": f"evt_{uuid.uuid4().hex}", "type": "payment.succeeded",
                          "data": {"deposit_id": dep["id"], "amount_cents": amount}})
    assert r.status_code == 200, r.text


def create_bet(client, headers, **kw):
    body = {"title": "Matis va-t-il réussir son créneau ?", "min_stake_cents": 500, "bookie_fee_bps": 500,
            "closes_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
    body.update(kw)
    r = client.post("/bets", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def wager(client, headers, bet_id, outcome="yes", stake=1000, key=None):
    return client.post(f"/bets/{bet_id}/wagers", json={"outcome": outcome, "stake_cents": stake},
                       headers={**headers, "Idempotency-Key": key or uuid.uuid4().hex})


def close_bet(db, bet_id):
    """Simule l'écoulement du temps jusqu'à la clôture."""
    bet = db.get(Bet, bet_id)
    bet.closes_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()


def make_admin(db, username):
    u = db.query(User).filter_by(username=username).one()
    u.role = Role.ADMIN
    db.commit()
