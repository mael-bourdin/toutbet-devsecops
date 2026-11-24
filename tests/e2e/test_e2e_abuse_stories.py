"""Abuse stories de l'atelier 1 (docs/backlog.md) automatisées de bout en bout contre le serveur réel."""
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx
import jwt

from tests.e2e.conftest import BASE_URL, PASSWORD, fake_ip


def _players(api, n, amount=10_000):
    bookie = api.user("bookie")
    players = [api.user("p") for _ in range(n)]
    for p in players:
        api.fund(p, amount)
    return bookie, players, api.bet(bookie, players)


# AS-01 : credential stuffing / énumération de pseudos
def test_as01_bruteforce_bloque_par_limite(api):
    u = api.user("alice")
    ip = {"X-Forwarded-For": fake_ip()}
    codes = [api.http.post("/auth/login", json={"username": u["name"], "password": "mauvais"},
                           headers=ip).status_code for _ in range(30)]
    assert 429 in codes  # limite atteinte (5/min/IP+pseudo et par processus)
    assert set(codes) <= {401, 429}


def test_as01_message_identique_compte_existant_ou_non(api):
    u = api.user("alice")
    a = api.http.post("/auth/login", json={"username": u["name"], "password": "mauvais"},
                      headers={"X-Forwarded-For": fake_ip()})
    b = api.http.post("/auth/login", json={"username": "inconnu_" + uuid.uuid4().hex[:8], "password": "mauvais"},
                      headers={"X-Forwarded-For": fake_ip()})
    assert (a.status_code, a.json()) == (b.status_code, b.json())


def test_as01_inscription_doublon_message_generique(api):
    u = api.user("alice")
    r = api.http.post("/auth/register", json={"username": u["name"], "email": "autre@ex.fr", "password": PASSWORD},
                      headers={"X-Forwarded-For": fake_ip()})
    assert r.status_code == 409 and r.json() == {"detail": "Inscription impossible"}


# AS-02 : jeton forgé (alg none, clé devinée, expiré, mauvaise audience)
def test_as02_jetons_forges_refuses(api):
    api.user("alice")
    base = {"sub": "x", "iss": "toutbet-api", "aud": "toutbet-mobile", "exp": int(time.time()) + 60}
    tokens = [
        jwt.encode(base, "cle-pirate-" * 4, algorithm="HS256"),
        jwt.encode(base, None, algorithm="none"),
        jwt.encode({**base, "exp": int(time.time()) - 10}, "cle-pirate-" * 4, algorithm="HS256"),
        "pas.un.jwt",
    ]
    for t in tokens:
        assert api.http.get("/auth/me", headers={"Authorization": f"Bearer {t}"}).status_code == 401


# AS-03 : commission abusive et mass-assignment
def test_as03_commission_et_champs_caches(api):
    bookie = api.user("bookie")
    body = {"title": "Pari test abusif", "closes_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
    assert api.http.post("/bets", json={**body, "bookie_fee_bps": 9000}, headers=bookie["h"]).status_code == 422
    for extra in ({"platform_fee_bps": 0}, {"status": "settled"}, {"bookie_id": "x"}):
        assert api.http.post("/bets", json={**body, **extra}, headers=bookie["h"]).status_code == 422
    r = api.http.post("/auth/register", json={"username": "x" + uuid.uuid4().hex[:8], "email": "r@ex.fr",
                                              "password": PASSWORD, "role": "admin"},
                      headers={"X-Forwarded-For": fake_ip()})
    assert r.status_code == 422


# AS-04 : IDOR sur un pari privé
def test_as04_non_invite_ne_voit_ni_ne_parie(api):
    _, _, bet = _players(api, 1)
    eve = api.user("eve")
    api.fund(eve)
    assert api.http.get(f"/bets/{bet['id']}", headers=eve["h"]).status_code == 404
    assert api.wager(eve, bet["id"]).status_code == 404
    assert api.http.get(f"/bets/{uuid.uuid4()}", headers=eve["h"]).json() == \
        api.http.get(f"/bets/{bet['id']}", headers=eve["h"]).json()  # 404 indiscernable


# AS-05 : mise après clôture / modification de mise
def test_as05_mise_apres_cloture_refusee(api, close_bet):
    _, (alice, bob), bet = _players(api, 2)
    w = api.wager(alice, bet["id"])
    assert w.status_code == 201
    close_bet(bet["id"])
    assert api.wager(bob, bet["id"]).status_code == 409
    for method in ("PUT", "PATCH", "DELETE"):
        r = api.http.request(method, f"/bets/{bet['id']}/wagers/{w.json()['id']}", headers=alice["h"])
        assert r.status_code in (404, 405)


# AS-06 : double dépense par rejeu (séquentiel puis simultané)
def test_as06_rejeu_meme_cle_pas_de_double_debit(api):
    _, (alice,), bet = _players(api, 1)
    r1 = api.wager(alice, bet["id"], stake=2000, key="cle-unique-123")
    r2 = api.wager(alice, bet["id"], stake=2000, key="cle-unique-123")
    assert r1.json() == r2.json()
    assert api.balance(alice) == 8000


def test_as06_rejeu_simultane_meme_cle(api):
    _, (alice,), bet = _players(api, 1)
    key = uuid.uuid4().hex
    with ThreadPoolExecutor(10) as ex:
        codes = list(ex.map(lambda _: api.wager(alice, bet["id"], stake=2000, key=key).status_code, range(10)))
    assert 500 not in codes, codes
    assert api.balance(alice) == 8000


# AS-07 : mise négative, supérieure au solde, et course critique sur le solde
def test_as07_montant_negatif_ou_superieur_au_solde(api):
    _, (alice,), bet = _players(api, 1)
    assert api.wager(alice, bet["id"], stake=-500).status_code == 422
    assert api.wager(alice, bet["id"], stake=0).status_code == 422
    assert api.wager(alice, bet["id"], stake=20_000).status_code == 409


def test_as07_paris_simultanes_ne_depassent_pas_le_solde(api):
    """Le même parieur (solde 100 €) mise 80 € sur 20 paris différents au même instant.
    Une seule mise doit passer ; le solde ne doit jamais devenir négatif."""
    alice = api.user("alice")
    api.fund(alice, 10_000)
    bets = [api.bet(api.user("bookie"), [alice]) for _ in range(20)]  # 1 bookie/pari : limite d'écriture
    with ThreadPoolExecutor(20) as ex:
        codes = list(ex.map(lambda b: api.wager(alice, b["id"], stake=8000).status_code, bets))
    accepted = codes.count(201)
    solde = api.balance(alice)
    assert solde >= 0, f"Solde négatif : {solde} centimes, {accepted} mises acceptées ({codes})"
    assert accepted == 1, codes
    assert solde == 2000


# AS-08 : le bookie mise sur son propre pari
def test_as08_bookie_ne_mise_pas(api):
    bookie, _, bet = _players(api, 1)
    api.fund(bookie)
    assert api.wager(bookie, bet["id"]).status_code == 403


# AS-09 : faux résultat, résultat anticipé, vote multiple, arbitrage
def test_as09_faux_resultat_conteste_puis_arbitre(api, close_bet, make_admin):
    bookie, (alice, bob, carol), bet = _players(api, 3)
    api.wager(alice, bet["id"], "yes")
    api.wager(bob, bet["id"], "no")
    api.wager(carol, bet["id"], "no")
    assert api.http.post(f"/bets/{bet['id']}/result", json={"outcome": "yes"},
                         headers=bookie["h"]).status_code == 409  # avant clôture
    close_bet(bet["id"])
    assert api.http.post(f"/bets/{bet['id']}/result", json={"outcome": "yes"},
                         headers=alice["h"]).status_code == 403  # un parieur ne propose pas
    api.http.post(f"/bets/{bet['id']}/result", json={"outcome": "yes"}, headers=bookie["h"])
    r = api.http.post(f"/bets/{bet['id']}/votes", json={"confirms": False}, headers=bob["h"])
    assert r.json()["status"] == "disputed"
    assert api.http.post(f"/bets/{bet['id']}/votes", json={"confirms": False},
                         headers=bob["h"]).status_code == 409  # vote unique
    assert api.balance(alice) == 9000  # escrow conservé
    assert api.http.post(f"/bets/{bet['id']}/resolve", json={"outcome": "no"},
                         headers=bookie["h"]).status_code == 403
    modo = api.user("modo")
    make_admin(modo)
    assert api.http.post(f"/bets/{bet['id']}/resolve", json={"outcome": "no"},
                         headers=modo["h"]).json()["status"] == "settled"


# AS-10 : faux webhook / rejeu / montant modifié
def test_as10_webhook_forge_rejoue_ou_modifie(api):
    alice = api.user("alice")
    dep = api.http.post("/wallet/deposits", json={"amount_cents": 1000}, headers=alice["h"]).json()
    evt = {"id": f"evt_{uuid.uuid4().hex}", "type": "payment.succeeded",
           "data": {"deposit_id": dep["id"], "amount_cents": 1000}}
    assert api.psp(evt, secret="faux-secret-" * 3).status_code == 400
    assert api.psp(evt, ts=int(time.time()) - 3600).status_code == 400
    assert api.http.post("/payments/webhook", json=evt).status_code == 400  # sans signature
    assert api.psp(evt).status_code == 200
    assert api.psp(evt).json()["status"] == "already_processed"
    dep2 = api.http.post("/wallet/deposits", json={"amount_cents": 1000}, headers=alice["h"]).json()
    evt2 = {"id": f"evt_{uuid.uuid4().hex}", "type": "payment.succeeded",
            "data": {"deposit_id": dep2["id"], "amount_cents": 99_000}}
    assert api.psp(evt2).status_code == 422
    assert api.balance(alice) == 1000


# AS-11 : retrait avec un jeton volé
def test_as11_retrait_exige_reauth_et_kyc(api):
    alice = api.user("alice")
    api.fund(alice)
    r = api.http.post("/wallet/withdrawals", json={"amount_cents": 1000, "password": "pas-le-bon-mdp"},
                      headers=alice["h"])
    assert r.status_code == 401
    r = api.http.post("/wallet/withdrawals", json={"amount_cents": 1000, "password": PASSWORD}, headers=alice["h"])
    assert r.status_code == 403
    assert api.balance(alice) == 10_000


# AS-12 : reçu non répudiable
def test_as12_recu_hmac_present(api):
    _, (alice,), bet = _players(api, 1)
    w = api.wager(alice, bet["id"]).json()
    assert len(w["receipt"]) == 64 and int(w["receipt"], 16) >= 0


# AS-13 : flood et corps énormes
def test_as13_flood_et_corps_enorme(api):
    alice = api.user("alice")
    codes = [api.http.post("/wallet/deposits", json={"amount_cents": 100}, headers=alice["h"]).status_code
             for _ in range(150)]
    assert 429 in codes
    r = api.http.post("/auth/login", content=b"x" * 70_000, headers={"Content-Type": "application/json"})
    assert r.status_code == 413


# AS-14 : arrondis — le grand livre reste équilibré après un règlement réel
def test_as14_reglement_somme_nulle(api, close_bet, db):
    from sqlalchemy import func, select

    from app.models import LedgerEntry
    bookie, (alice, bob, carol), bet = _players(api, 3)
    api.wager(alice, bet["id"], "yes", 777)
    api.wager(bob, bet["id"], "yes", 1333)
    api.wager(carol, bet["id"], "no", 999)
    close_bet(bet["id"])
    api.http.post(f"/bets/{bet['id']}/result", json={"outcome": "yes"}, headers=bookie["h"])
    for p in (alice, bob):
        api.http.post(f"/bets/{bet['id']}/votes", json={"confirms": True}, headers=p["h"])
    assert api.http.get(f"/bets/{bet['id']}", headers=alice["h"]).json()["status"] == "settled"
    db.expire_all()
    assert db.scalar(select(func.sum(LedgerEntry.amount_cents))) == 0


# Fuite d'information : aucune trace interne dans les erreurs
def test_erreurs_sans_detail_interne(api):
    alice = api.user("alice")
    for r in (api.http.post("/payments/webhook", content=b"{", headers={"PSP-Signature": "t=1,v1=x"}),
              api.http.get("/bets/" + "a" * 5000, headers=alice["h"]),
              api.http.post("/bets", content=b"{not json", headers={**alice["h"], "Content-Type": "application/json"})):
        body = r.text
        for leak in ("Traceback", "sqlalchemy", "sqlite", "File \"", "/Users/", "app/"):
            assert leak not in body, (r.status_code, body[:300])


def test_entetes_de_securite(api):
    r = httpx.get(BASE_URL + "/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"
