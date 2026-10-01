"""Chaque test vérifie qu'une Abuse Story du backlog est bloquée (cf. docs/backlog.md)."""
import time
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import func, select

from app.audit import verify_chain
from app.models import AuditLog, LedgerEntry, Wager
from app.settlement import compute_payouts
from tests.conftest import close_bet, create_bet, fund, make_admin, psp_post, register, wager


def _setup(client, *players):
    bookie = register(client, "bookie")
    heads = {p: register(client, p) for p in players}
    for h in heads.values():
        fund(client, h)
    bet = create_bet(client, bookie)
    for p in players:
        client.post(f"/bets/{bet['id']}/invitations", json={"username": p}, headers=bookie)
    return bookie, heads, bet


# AS-01 : énumération / brute-force de comptes
def test_as01_bruteforce_login_limite(client):
    register(client, "alice")
    codes = [client.post("/auth/login", json={"username": "alice", "password": "mauvais"}).status_code
             for _ in range(6)]
    assert codes[:4] == [401] * 4 and codes[-1] == 429


def test_as01_message_generique(client):
    register(client, "alice")
    a = client.post("/auth/login", json={"username": "alice", "password": "mauvais"}).json()
    b = client.post("/auth/login", json={"username": "inconnu", "password": "mauvais"}).json()
    assert a == b


# AS-02 : jeton forgé (alg none / mauvaise clé / expiré)
def test_as02_jeton_forge_refuse(client):
    register(client, "alice")
    forged = jwt.encode({"sub": "x", "iss": "toutbet-api", "aud": "toutbet-mobile",
                         "exp": int(time.time()) + 60}, "cle-pirate-" * 4, algorithm="HS256")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    none_tok = jwt.encode({"sub": "x", "iss": "toutbet-api", "aud": "toutbet-mobile",
                           "exp": int(time.time()) + 60}, None, algorithm="none")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {none_tok}"}).status_code == 401


# AS-03 : le bookie fixe une commission abusive / se met en mass-assignment admin
def test_as03_commission_plafonnee_et_champs_inconnus(client):
    bookie = register(client, "bookie")
    body = {"title": "Pari test abusif", "bookie_fee_bps": 9000,
            "closes_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
    assert client.post("/bets", json=body, headers=bookie).status_code == 422
    body.update(bookie_fee_bps=100, platform_fee_bps=0)
    assert client.post("/bets", json=body, headers=bookie).status_code == 422


# AS-04 : parier sur un pari privé sans invitation / lire un pari d'autrui (IDOR)
def test_as04_non_invite_ne_voit_ni_ne_parie(client):
    _, heads, bet = _setup(client, "alice")
    eve = register(client, "eve")
    fund(client, eve)
    assert client.get(f"/bets/{bet['id']}", headers=eve).status_code == 404
    assert wager(client, eve, bet["id"]).status_code == 404


# AS-05 : modifier / placer une mise après la clôture
def test_as05_mise_apres_cloture_refusee(client, db):
    _, heads, bet = _setup(client, "alice", "bob")
    assert wager(client, heads["alice"], bet["id"]).status_code == 201
    close_bet(db, bet["id"])
    assert wager(client, heads["bob"], bet["id"]).status_code == 409
    assert wager(client, heads["alice"], bet["id"], "no").status_code == 409


def test_as05_pas_de_route_de_modification(client):
    _, heads, bet = _setup(client, "alice")
    w = wager(client, heads["alice"], bet["id"]).json()
    for method in ("put", "patch", "delete"):
        r = getattr(client, method)(f"/bets/{bet['id']}/wagers/{w['id']}", headers=heads["alice"])
        assert r.status_code in (404, 405)


# AS-06 : double dépense (double clic / rejeu de requête)
def test_as06_idempotence_pas_de_double_debit(client):
    _, heads, bet = _setup(client, "alice")
    r1 = wager(client, heads["alice"], bet["id"], stake=2000, key="cle-unique-123")
    r2 = wager(client, heads["alice"], bet["id"], stake=2000, key="cle-unique-123")
    assert r1.json() == r2.json()
    assert client.get("/wallet", headers=heads["alice"]).json()["balance_cents"] == 8000
    assert wager(client, heads["alice"], bet["id"], stake=2000).status_code == 409  # 1 mise / parieur


# AS-07 : miser plus que son solde / mise négative
def test_as07_solde_insuffisant_et_montant_negatif(client):
    _, heads, bet = _setup(client, "alice")
    assert wager(client, heads["alice"], bet["id"], stake=-500).status_code == 422
    assert wager(client, heads["alice"], bet["id"], stake=20_000).status_code == 409


# AS-08 : le bookie parie sur son propre pari puis truque le résultat
def test_as08_bookie_ne_peut_pas_parier(client):
    bookie, _, bet = _setup(client, "alice")
    fund(client, bookie)
    assert wager(client, bookie, bet["id"]).status_code == 403


# AS-09 : le bookie impose un faux résultat -> contestation -> litige -> modération
def test_as09_faux_resultat_conteste(client, db):
    bookie, heads, bet = _setup(client, "alice", "bob", "carol")
    wager(client, heads["alice"], bet["id"], "yes")
    wager(client, heads["bob"], bet["id"], "no")
    wager(client, heads["carol"], bet["id"], "no")
    close_bet(db, bet["id"])
    client.post(f"/bets/{bet['id']}/result", json={"outcome": "yes"}, headers=bookie)
    r = client.post(f"/bets/{bet['id']}/votes", json={"confirms": False}, headers=heads["bob"])
    assert r.json()["status"] == "disputed"
    # aucun argent n'a bougé, l'escrow est conservé
    assert client.get("/wallet", headers=heads["alice"]).json()["balance_cents"] == 9000
    # un simple utilisateur ne peut pas trancher
    assert client.post(f"/bets/{bet['id']}/resolve", json={"outcome": "no"}, headers=bookie).status_code == 403
    modo = register(client, "modo")
    make_admin(db, "modo")  # le rôle est relu en base à chaque requête
    assert client.post(f"/bets/{bet['id']}/resolve", json={"outcome": "no"}, headers=modo).json()["status"] == "settled"


def test_as09_resultat_avant_cloture_refuse(client):
    bookie, heads, bet = _setup(client, "alice")
    wager(client, heads["alice"], bet["id"])
    assert client.post(f"/bets/{bet['id']}/result", json={"outcome": "yes"}, headers=bookie).status_code == 409


def test_as09_un_parieur_ne_propose_pas_le_resultat(client, db):
    _, heads, bet = _setup(client, "alice")
    wager(client, heads["alice"], bet["id"])
    close_bet(db, bet["id"])
    assert client.post(f"/bets/{bet['id']}/result", json={"outcome": "yes"},
                       headers=heads["alice"]).status_code == 403


def test_as09_vote_unique(client, db):
    bookie, heads, bet = _setup(client, "alice", "bob", "carol")
    for p in heads:
        wager(client, heads[p], bet["id"])
    close_bet(db, bet["id"])
    client.post(f"/bets/{bet['id']}/result", json={"outcome": "yes"}, headers=bookie)
    client.post(f"/bets/{bet['id']}/votes", json={"confirms": True}, headers=heads["alice"])
    assert client.post(f"/bets/{bet['id']}/votes", json={"confirms": True},
                       headers=heads["alice"]).status_code == 409


# AS-10 : faux webhook de paiement pour créditer son compte
def test_as10_webhook_forge_refuse(client):
    alice = register(client, "alice")
    dep = client.post("/wallet/deposits", json={"amount_cents": 50_000}, headers=alice).json()
    evt = {"id": "evt_1", "type": "payment.succeeded", "data": {"deposit_id": dep["id"], "amount_cents": 50_000}}
    assert psp_post(client, evt, secret="faux-secret").status_code == 400
    assert psp_post(client, evt, ts=int(time.time()) - 3600).status_code == 400  # signature périmée
    assert client.get("/wallet", headers=alice).json()["balance_cents"] == 0


def test_as10_webhook_rejoue_ou_montant_modifie(client):
    alice = register(client, "alice")
    dep = client.post("/wallet/deposits", json={"amount_cents": 1000}, headers=alice).json()
    evt = {"id": "evt_2", "type": "payment.succeeded", "data": {"deposit_id": dep["id"], "amount_cents": 1000}}
    assert psp_post(client, evt).status_code == 200
    assert psp_post(client, evt).json()["status"] == "already_processed"
    assert client.get("/wallet", headers=alice).json()["balance_cents"] == 1000
    dep2 = client.post("/wallet/deposits", json={"amount_cents": 1000}, headers=alice).json()
    evt2 = {"id": "evt_3", "type": "payment.succeeded", "data": {"deposit_id": dep2["id"], "amount_cents": 99_000}}
    assert psp_post(client, evt2).status_code == 422


# AS-11 : retrait avec un jeton volé / sans identité vérifiée
def test_as11_retrait_exige_reauth_et_kyc(client):
    alice = register(client, "alice")
    fund(client, alice)
    r = client.post("/wallet/withdrawals", json={"amount_cents": 1000, "password": "pas-le-bon-mdp"}, headers=alice)
    assert r.status_code == 401
    r = client.post("/wallet/withdrawals", json={"amount_cents": 1000, "password": "motdepasse-solide-42"},
                    headers=alice)
    assert r.status_code == 403


# AS-12 : effacer/altérer la trace d'une mise (répudiation)
def test_as12_journal_infalsifiable(client, db):
    _, heads, bet = _setup(client, "alice")
    wager(client, heads["alice"], bet["id"])
    assert verify_chain(db)
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "wager.placed")).one()
    entry.payload = entry.payload.replace("yes", "no")
    db.commit()
    assert not verify_chain(db)


# AS-13 : DoS par requêtes massives / corps énormes
def test_as13_limite_ecritures_et_taille(client):
    alice = register(client, "alice")
    codes = [client.post("/wallet/deposits", json={"amount_cents": 100}, headers=alice).status_code
             for _ in range(31)]
    assert codes[-1] == 429
    r = client.post("/auth/login", content=b"x" * 70_000, headers={"Content-Type": "application/json"})
    assert r.status_code == 413


# Invariant comptable : rien ne se crée ni ne se perd
def test_invariant_grand_livre_equilibre(client, db):
    bookie, heads, bet = _setup(client, "alice", "bob", "carol")
    wager(client, heads["alice"], bet["id"], "yes", 777)
    wager(client, heads["bob"], bet["id"], "yes", 1333)
    wager(client, heads["carol"], bet["id"], "no", 999)
    close_bet(db, bet["id"])
    client.post(f"/bets/{bet['id']}/result", json={"outcome": "yes"}, headers=bookie)
    for p in ("alice", "bob"):
        client.post(f"/bets/{bet['id']}/votes", json={"confirms": True}, headers=heads[p])
    assert db.scalar(select(func.sum(LedgerEntry.amount_cents))) == 0


def test_compute_payouts_somme_egale_pot():
    ws = [Wager(user_id=f"u{i}", outcome="yes" if i % 2 else "no", stake_cents=s)
          for i, s in enumerate([101, 333, 777, 1001, 50_000])]
    p = compute_payouts(ws, "yes", 500, 333)
    assert p["platform"] + p["bookie"] + sum(p["winners"].values()) == sum(w.stake_cents for w in ws)
