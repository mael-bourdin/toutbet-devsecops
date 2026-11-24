"""Non-régression des défauts trouvés par l'exploration dynamique (atelier 2, étape 2)."""
from tests.conftest import create_bet, fund, register, wager


def test_nan_infinity_ne_provoquent_plus_d_erreur_500(client):
    bookie, alice = register(client, "bookie"), register(client, "alice")
    fund(client, alice)
    bet = create_bet(client, bookie)
    client.post(f"/bets/{bet['id']}/invitations", json={"username": "alice"}, headers=bookie)
    for raw in (b'{"outcome":"yes","stake_cents":NaN}', b'{"outcome":"yes","stake_cents":Infinity}',
                b'{"outcome":"yes","stake_cents":-Infinity}'):
        r = client.post(f"/bets/{bet['id']}/wagers", content=raw,
                        headers={**alice, "Idempotency-Key": "k" * 16, "Content-Type": "application/json"})
        assert r.status_code == 422, r.text
    assert wager(client, alice, bet["id"]).status_code == 201


def test_erreur_de_validation_ne_renvoie_pas_les_valeurs_saisies(client):
    r = client.post("/auth/register", json={"username": "a", "email": "x", "password": "trop-court",
                                            "role": "admin"})
    assert r.status_code == 422
    assert r.json() == {"detail": "Requête invalide", "fields": ["email", "password", "role", "username"]}
    for leak in ("trop-court", "pattern", "^[a-zA-Z0-9_]", "pydantic", "extra_forbidden"):
        assert leak not in r.text


def test_documentation_api_masquee_par_defaut(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_montants_entiers_stricts(client):
    bookie = register(client, "bookie")
    for raw in (b'"100"', b"1e3", b"100.0", b"true"):
        r = client.post("/bets", content=b'{"title":"Pari strict","closes_at":"2099-01-01T00:00:00Z",'
                                         b'"min_stake_cents":' + raw + b"}",
                        headers={**bookie, "Content-Type": "application/json"})
        assert r.status_code == 422 and "min_stake_cents" in r.json()["fields"], (raw, r.text)
    r = client.post("/wallet/deposits", json={"amount_cents": "1000"}, headers=bookie)
    assert r.status_code == 422
