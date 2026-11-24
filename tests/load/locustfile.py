"""Test de charge : afflux de parieurs simultanés sur UN MÊME événement (finale de Coupe du monde).

    set -a && source .env && set +a
    uvicorn app.main:app --port 8000 --workers 4 --no-server-header &
    locust -f tests/load/locustfile.py --host http://127.0.0.1:8000      # interface web : http://localhost:8089

Deux profils :
  - Parieur (x N)          : s'inscrit, approvisionne son portefeuille, consulte le pari, mise une fois
                             (avec rejeu « double clic » de la même Idempotency-Key), consulte son solde ;
  - ParieurFrenetique (x1) : un même utilisateur lance 20 mises SIMULTANÉES sur 20 événements avec un solde
                             qui n'en couvre qu'une : tout solde négatif est compté comme un échec Locust.

Mise en place : seules les invitations sont écrites directement en base (seul le bookie peut inviter et il est
limité à 30 écritures/min : inviter des centaines de parieurs par l'API saturerait sa limite, pas le serveur).
"""
import hashlib
import hmac
import json
import os
import random
import time
import uuid
from datetime import datetime, timedelta, timezone

import sys
from pathlib import Path

import gevent
from locust import HttpUser, between, events, task
from locust.exception import StopUser

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # racine du dépôt (paquet app)
PASSWORD = "motdepasse-solide-42"
STATE: dict = {}


def _ip() -> dict:
    return {"X-Forwarded-For": f"10.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"}


def _db():
    from app.db import SessionLocal, init_engine
    if "engine" not in STATE:
        STATE["engine"] = init_engine(os.environ["TOUTBET_DATABASE_URL"])
    return SessionLocal()


def _invite(bet_id: str, username: str) -> None:
    from app.models import Invitation, User
    with _db() as s:
        uid = s.query(User.id).filter_by(username=username).scalar()
        s.add(Invitation(bet_id=bet_id, user_id=uid))
        s.commit()


class Base(HttpUser):
    abstract = True

    def account(self, prefix: str) -> tuple[str, dict]:
        name = f"{prefix}_{uuid.uuid4().hex[:12]}"
        ip = _ip()
        self.client.post("/auth/register", json={"username": name, "email": f"{name}@ex.fr",
                                                 "password": PASSWORD}, headers=ip, name="/auth/register")
        r = self.client.post("/auth/login", json={"username": name, "password": PASSWORD}, headers=ip,
                             name="/auth/login")
        if r.status_code != 200:
            raise StopUser()
        return name, {"Authorization": f"Bearer {r.json()['access_token']}", **ip}

    def signup(self, prefix: str) -> None:
        self.name_, self.h = self.account(prefix)

    def fund(self, amount: int) -> bool:
        with self.client.post("/wallet/deposits", json={"amount_cents": amount}, headers=self.h,
                              name="/wallet/deposits", catch_response=True) as r:
            if r.status_code == 429:  # limitation de débit : refus attendu, on réessaiera plus tard
                r.success()
                return False
            dep = r.json()
        raw = json.dumps({"id": f"evt_{uuid.uuid4().hex}", "type": "payment.succeeded",
                          "data": {"deposit_id": dep["id"], "amount_cents": amount}}).encode()
        ts = int(time.time())
        sig = hmac.new(os.environ["TOUTBET_PSP_WEBHOOK_SECRET"].encode(), f"{ts}.".encode() + raw,
                       hashlib.sha256).hexdigest()
        self.client.post("/payments/webhook", data=raw, name="/payments/webhook",
                         headers={"PSP-Signature": f"t={ts},v1={sig}", "Content-Type": "application/json"})
        return True

    def new_bet(self, headers: dict) -> str:
        closes = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        r = self.client.post("/bets", json={"title": "La France gagne-t-elle la finale ?", "min_stake_cents": 100,
                                            "closes_at": closes}, headers=headers, name="/bets [création]")
        return r.json()["id"]


@events.test_start.add_listener
def create_shared_event(environment, **_):
    """Le bookie crée l'événement unique sur lequel tout le monde va parier."""
    from locust.clients import HttpSession
    s = HttpSession(base_url=environment.host, request_event=environment.events.request, user=None)
    name = f"bookie_{uuid.uuid4().hex[:10]}"
    s.post("/auth/register", json={"username": name, "email": f"{name}@ex.fr", "password": PASSWORD}, headers=_ip())
    tok = s.post("/auth/login", json={"username": name, "password": PASSWORD}, headers=_ip()).json()["access_token"]
    closes = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    r = s.post("/bets", json={"title": "Finale : la France gagne-t-elle ?", "min_stake_cents": 100,
                              "closes_at": closes}, headers={"Authorization": f"Bearer {tok}"})
    STATE["bet_id"] = r.json()["id"]


class Parieur(Base):
    weight = 50
    wait_time = between(0.5, 2)

    def on_start(self):
        self.signup("parieur")
        self.fund(5_000)
        _invite(STATE["bet_id"], self.name_)
        self.bet_url = f"/bets/{STATE['bet_id']}"

    @task(5)
    def consulter_pari(self):
        self.client.get(self.bet_url, headers=self.h, name="/bets/{id}")

    @task(3)
    def consulter_solde(self):
        self.client.get("/wallet", headers=self.h, name="/wallet")

    @task(2)
    def miser(self):
        key = uuid.uuid4().hex
        body = {"outcome": random.choice(["yes", "no"]), "stake_cents": random.choice([100, 500, 1000, 2000])}
        for label in ("/bets/{id}/wagers", "/bets/{id}/wagers [rejeu double clic]"):
            with self.client.post(f"{self.bet_url}/wagers", json=body, headers={**self.h, "Idempotency-Key": key},
                                  name=label, catch_response=True) as r:
                # 201 = mise acceptée ; 409 = déjà parié (1 mise/parieur) ; 429 = limitation de débit
                if r.status_code in (201, 409, 429):
                    r.success()


class ParieurFrenetique(Base):
    """Le même utilisateur mise en parallèle sur 20 événements : le solde ne doit jamais passer sous 0."""
    fixed_count = 1
    wait_time = between(30, 40)  # ~21 écritures par rafale : reste sous la limite de 30 écritures/min

    def on_start(self):
        self.signup("frenetique")

    @task
    def rafale_simultanee(self):
        if not self.fund(10_000):  # 100 €
            return
        _, bookie_h = self.account("bookiefr")  # nouveau bookie à chaque rafale (limite 30 écritures/min)
        bets = [self.new_bet(bookie_h) for _ in range(20)]
        for b in bets:
            _invite(b, self.name_)
        before = self.client.get("/wallet", headers=self.h, name="/wallet").json()["balance_cents"]

        def one(bet_id):
            with self.client.post(f"/bets/{bet_id}/wagers", json={"outcome": "yes", "stake_cents": 8000},
                                  headers={**self.h, "Idempotency-Key": uuid.uuid4().hex},
                                  name="/bets/{id}/wagers [rafale même parieur]", catch_response=True) as r:
                if r.status_code in (201, 409, 429):  # 409 solde insuffisant / 429 limitation : refus attendus
                    r.success()
                return r.status_code

        jobs = [gevent.spawn(one, b) for b in bets]
        gevent.joinall(jobs)
        accepted = sum(1 for j in jobs if j.value == 201)
        after = self.client.get("/wallet", headers=self.h, name="/wallet").json()["balance_cents"]
        ok = after >= 0 and after == before - 8000 * accepted and accepted <= before // 8000
        events.request.fire(request_type="CHECK", name="solde >= 0 après rafale simultanée", response_time=0,
                            response_length=0, context={},
                            exception=None if ok else AssertionError(
                                f"solde {after} c, {accepted} mises acceptées pour {before} c"))
