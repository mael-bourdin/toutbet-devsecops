"""Parcours nominal du MVP (User Stories)."""
from tests.conftest import close_bet, create_bet, fund, register, wager


def test_parcours_complet_pari_gagne(client, db):
    bookie, alice, bob = register(client, "bookie"), register(client, "alice"), register(client, "bob")
    fund(client, alice), fund(client, bob)
    bet = create_bet(client, bookie)
    for name in ("alice", "bob"):
        assert client.post(f"/bets/{bet['id']}/invitations", json={"username": name}, headers=bookie).status_code == 201

    r = wager(client, alice, bet["id"], "yes", 3000)
    assert r.status_code == 201 and len(r.json()["receipt"]) == 64
    assert wager(client, bob, bet["id"], "no", 1000).status_code == 201
    assert client.get("/wallet", headers=alice).json()["balance_cents"] == 7000

    close_bet(db, bet["id"])
    assert client.post(f"/bets/{bet['id']}/result", json={"outcome": "yes"}, headers=bookie).status_code == 200
    r = client.post(f"/bets/{bet['id']}/votes", json={"confirms": True}, headers=alice)
    assert r.json()["status"] == "pending_validation"  # 1/2 n'est pas > 50 %
    r = client.post(f"/bets/{bet['id']}/votes", json={"confirms": True}, headers=bob)
    assert r.json()["status"] == "settled"

    # pot 4000 ; plateforme 5 % = 200 ; bookie 5 % = 200 ; alice gagne 3600
    assert client.get("/wallet", headers=alice).json()["balance_cents"] == 7000 + 3600
    assert client.get("/wallet", headers=bob).json()["balance_cents"] == 9000
    assert client.get("/wallet", headers=bookie).json()["balance_cents"] == 200


def test_personne_ne_gagne_remboursement(client, db):
    bookie, alice = register(client, "bookie"), register(client, "alice")
    fund(client, alice)
    bet = create_bet(client, bookie)
    client.post(f"/bets/{bet['id']}/invitations", json={"username": "alice"}, headers=bookie)
    wager(client, alice, bet["id"], "yes", 2000)
    close_bet(db, bet["id"])
    client.post(f"/bets/{bet['id']}/result", json={"outcome": "no"}, headers=bookie)
    client.post(f"/bets/{bet['id']}/votes", json={"confirms": True}, headers=alice)
    assert client.get("/wallet", headers=alice).json()["balance_cents"] == 10_000


def test_retrait_apres_kyc(client, db):
    from app.models import User

    alice = register(client, "alice")
    fund(client, alice)
    u = db.query(User).filter_by(username="alice").one()
    u.kyc_verified = True
    db.commit()
    r = client.post("/wallet/withdrawals", json={"amount_cents": 4000, "password": "motdepasse-solide-42"},
                    headers=alice)
    assert r.status_code == 202
    assert client.get("/wallet", headers=alice).json()["balance_cents"] == 6000
