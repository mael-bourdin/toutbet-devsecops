# ToutBet' : socle MVP sécurisé

Atelier 1 DevSecOps (EPSI 2026-2027) : conception sécurisée et modélisation des menaces d'une plateforme
mobile-first de paris personnalisés entre particuliers.

## Livrables

| Étape | Document |
|---|---|
| 1. Backlog (User Stories + Abuse Stories) | [docs/backlog.md](docs/backlog.md) |
| 2. Architecture et frontières de confiance | [docs/architecture.md](docs/architecture.md) |
| 3. Matrice STRIDE | [docs/stride.md](docs/stride.md) |
| 4. Prompts de vibe coding | [docs/prompts.md](docs/prompts.md) |
| Rapport PDF de remise | [docs/rapport_atelier1.pdf](docs/rapport_atelier1.pdf) |
| **Atelier 2** : validation et tests offensifs | [docs/rapport_atelier2.pdf](docs/rapport_atelier2.pdf) (`python docs/build_report_atelier2.py`) |

Les documents sont générés depuis une source unique (`docs/content.py`) : `python docs/build_report.py`.

## API

FastAPI + SQLAlchemy 2 (SQLite en dev, compatible PostgreSQL).

| Méthode | Route | Rôle |
|---|---|---|
| POST | `/auth/register`, `/auth/login` | inscription, connexion (JWT 15 min) |
| POST | `/bets` | créer un pari (bookie) |
| POST | `/bets/{id}/invitations` | inviter un parieur (bookie) |
| POST | `/bets/{id}/wagers` | miser (en-tête `Idempotency-Key` obligatoire) |
| POST | `/bets/{id}/result` | proposer le résultat après clôture (bookie) |
| POST | `/bets/{id}/votes` | confirmer / contester le résultat (parieurs) |
| POST | `/bets/{id}/resolve` | arbitrer un litige (modérateur) |
| GET/POST | `/wallet`, `/wallet/deposits`, `/wallet/withdrawals` | portefeuille |
| POST | `/payments/webhook` | webhook PSP signé HMAC |

### Mécanismes de sécurité

- Argon2id, JWT à algorithme figé (iss/aud/exp), limitation de débit, messages génériques
- Contrôle d'accès au niveau objet (anti-IDOR), schémas stricts (anti mass-assignment)
- Grand livre en partie double append-only, montants en centimes, idempotence, règlement atomique
- Résultat validé par quorum des parieurs, litige arbitré par un modérateur
- Reçu HMAC par mise et journal d'audit chaîné (non-répudiation)
- Aucun secret en dur : l'application refuse de démarrer sans secrets

## Lancer

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # puis renseigner les secrets
set -a && source .env && set +a
uvicorn app.main:app --port 8000 --workers 4 --no-server-header   # sans bannière « Server: uvicorn »
```

Swagger, ReDoc et `/openapi.json` sont désactivés par défaut ; `TOUTBET_EXPOSE_DOCS=1` les active en développement.

## Tests

```bash
pytest -q          # 24 tests : parcours nominaux + une vérification par abuse story
bandit -r app -ll  # SAST
pip-audit -r requirements.txt
```

La CI GitHub Actions exécute tests, bandit, pip-audit et gitleaks à chaque push.

### Atelier 2 : tests offensifs (serveur lancé, mêmes variables d'environnement)

```bash
BASE_URL=http://127.0.0.1:8000 pytest tests/e2e -v                  # abuse stories E2E contre le serveur réel
locust -f tests/load/locustfile.py --host http://127.0.0.1:8000      # charge (interface http://localhost:8089)
BASE_URL=http://127.0.0.1:8000 python security/dast/run_dast.py apres  # DAST + fuzzing (ffuf, Schemathesis ; TOUTBET_EXPOSE_DOCS=1 côté serveur)
uvicorn security.iast.instrumented_app:app --workers 4               # serveur instrumenté (IAST) -> reports/iast/
python security/iast/check_invariants.py                             # invariants financiers en base
semgrep scan --config p/default --config p/python --config p/owasp-top-ten --config p/secrets --config p/github-actions .
```

Résultats bruts : `reports/` (Semgrep avant/après, DAST, IAST, Locust).
