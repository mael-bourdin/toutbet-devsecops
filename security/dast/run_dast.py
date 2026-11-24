"""Campagne DAST + fuzzing contre l'API de paris (serveur lancé à part).

    set -a && source .env && set +a
    BASE_URL=http://127.0.0.1:8000 python security/dast/run_dast.py [nom_campagne]

Outils : ffuf (découverte de routes et fuzzing de paramètres) et Schemathesis (fuzzing guidé par
le schéma OpenAPI). Les résultats bruts sont écrits dans reports/dast/<campagne>/.
"""
import json
import os
import re
import subprocess  # nosec B404 - outils de test lancés localement avec des arguments fixes
import sys
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.e2e.conftest import Api  # noqa: E402

from urllib.parse import urlparse  # noqa: E402

BASE_URL = os.environ["BASE_URL"]
_u = urlparse(BASE_URL)
if _u.scheme not in ("http", "https") or not _u.hostname or BASE_URL.startswith("-"):
    sys.exit("BASE_URL invalide (attendu : http(s)://hote:port)")
HERE = Path(__file__).parent
WL = HERE / "wordlists"
OUT = Path("reports/dast") / (sys.argv[1] if len(sys.argv) > 1 else "campagne")
OUT.mkdir(parents=True, exist_ok=True)
LEAKS = ("Traceback", "sqlalchemy", "sqlite", "File \"", "/Users/", "site-packages", "IntegrityError",
         "OperationalError", "pydantic", "uvicorn", "starlette")


def ffuf(name: str, *args: str) -> dict:
    out = OUT / f"ffuf_{name}.json"
    cmd = ["ffuf", "-s", "-noninteractive", "-mc", "all", "-o", str(out), "-of", "json", "-od",
           str(OUT / f"ffuf_{name}_bodies"), *args]
    # Liste d'arguments sans shell (pas d'injection de commande possible) ; BASE_URL est validée au démarrage.
    subprocess.run(cmd, check=False, capture_output=True)  # nosec B603 # nosemgrep: dangerous-subprocess-use-tainted-env-args
    results = json.loads(out.read_text())["results"] if out.exists() else []
    leaks = []
    for f in (OUT / f"ffuf_{name}_bodies").glob("*"):
        text = f.read_text(errors="replace")
        response = text.split("Response \u2193", 1)[-1]  # on n'analyse que la réponse, pas la requête
        found = [k for k in LEAKS if k in response]
        if found:
            leaks.append({"file": f.name, "markers": found})
    summary = {"requests": len(results), "status": dict(Counter(r["status"] for r in results)),
               "leaks": leaks,
               "examples": {str(s): next(r["input"] for r in results if r["status"] == s)
                            for s in sorted({r["status"] for r in results})}}
    print(f"[ffuf:{name}] {summary['requests']} requêtes -> {summary['status']} ; fuites : {len(leaks)}")
    return summary


def main() -> None:
    api = Api()
    bookie, alice = api.user("dastbookie"), api.user("dastalice")
    api.fund(alice, 50_000)
    bet = api.bet(bookie, [alice])
    auth_a = f"Authorization: {alice['h']['Authorization']}"
    auth_b = f"Authorization: {bookie['h']['Authorization']}"
    keys = HERE / "wordlists" / "_keys.txt"
    keys.write_text("\n".join(uuid.uuid4().hex for _ in range(200)))
    report = {}
    closes = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")  # date valide

    # 1. Découverte de routes cachées / fichiers sensibles (non authentifié puis authentifié)
    report["decouverte_anonyme"] = ffuf("decouverte_anonyme", "-u", f"{BASE_URL}/FUZZ", "-w", str(WL / "endpoints.txt"))
    report["decouverte_auth"] = ffuf("decouverte_auth", "-u", f"{BASE_URL}/FUZZ", "-w", str(WL / "endpoints.txt"),
                                     "-H", auth_a)
    # 2. Méthodes HTTP inattendues sur la création de mise
    methods = HERE / "wordlists" / "_methods.txt"
    methods.write_text("\n".join(["GET", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "TRACE", "CONNECT", "FOO"]))
    report["methodes_mise"] = ffuf("methodes_mise", "-u", f"{BASE_URL}/bets/{bet['id']}/wagers", "-X", "FUZZ",
                                   "-w", str(methods), "-H", auth_a)
    # 3. Identifiant de pari : injection SQL, traversée, IDOR
    report["bet_id_injection"] = ffuf("bet_id_injection", "-u", f"{BASE_URL}/bets/FUZZ", "-w",
                                      str(WL / "injections.txt"), "-H", auth_a)
    # 4. Montant de mise : bornes, types, débordements (clé d'idempotence unique par requête)
    report["mise_montant"] = ffuf(
        "mise_montant", "-u", f"{BASE_URL}/bets/{bet['id']}/wagers", "-X", "POST", "-mode", "pitchfork",
        "-w", f"{WL / 'stakes.txt'}:FUZZ", "-w", f"{keys}:KEY", "-H", auth_a, "-H", "Idempotency-Key: KEY",
        "-H", "Content-Type: application/json", "-d", '{"outcome":"yes","stake_cents":FUZZ}', "-rate", "2")
    # 5. Issue du pari : valeurs hors énumération
    report["mise_issue"] = ffuf(
        "mise_issue", "-u", f"{BASE_URL}/bets/{bet['id']}/wagers", "-X", "POST", "-mode", "pitchfork",
        "-w", f"{WL / 'injections.txt'}:FUZZ", "-w", f"{keys}:KEY", "-H", auth_a, "-H", "Idempotency-Key: KEY",
        "-H", "Content-Type: application/json", "-d", '{"outcome":"FUZZ","stake_cents":1000}', "-rate", "2")
    # 6. Création de pari : titre et mise minimale (injection / XSS stockée / bornes)
    report["pari_titre"] = ffuf(
        "pari_titre", "-u", f"{BASE_URL}/bets", "-X", "POST", "-w", str(WL / "injections.txt"), "-H", auth_b,
        "-H", "Content-Type: application/json", "-rate", "2",
        "-d", '{"title":"FUZZ titre","closes_at":"'+closes+'"}')
    report["pari_min_stake"] = ffuf(
        "pari_min_stake", "-u", f"{BASE_URL}/bets", "-X", "POST", "-w", str(WL / "stakes.txt"), "-H",
        f"Authorization: {api.user('dastbookie2')['h']['Authorization']}", "-H", "Content-Type: application/json",
        "-rate", "2", "-d", '{"title":"Pari fuzz","min_stake_cents":FUZZ,"closes_at":"'+closes+'"}')
    # 7. Connexion : injection dans l'identifiant
    report["login_injection"] = ffuf(
        "login_injection", "-u", f"{BASE_URL}/auth/login", "-X", "POST", "-w", str(WL / "injections.txt"),
        "-H", "Content-Type: application/json", "-d", '{"username":"FUZZ","password":"x"}')
    # 8. Webhook PSP : signatures malformées
    report["webhook_signature"] = ffuf(
        "webhook_signature", "-u", f"{BASE_URL}/payments/webhook", "-X", "POST", "-w", str(WL / "injections.txt"),
        "-H", "PSP-Signature: FUZZ", "-H", "Content-Type: application/json", "-d", '{"id":"evt_x"}')

    # 9. Schemathesis : fuzzing basé sur le schéma OpenAPI (toutes les routes, authentifié)
    # Même justification que ffuf() : liste d'arguments sans shell, BASE_URL validée.
    st_cmd = [str(Path(sys.executable).parent / "schemathesis"), "run", f"{BASE_URL}/openapi.json",
              "-H", auth_a, "--checks", "not_a_server_error,status_code_conformance,content_type_conformance,"
              "response_schema_conformance", "--max-examples", "40", "--report", "junit",
              "--report-dir", str(OUT / "schemathesis")]
    st = subprocess.run(st_cmd, capture_output=True, text=True)  # nosec B603 # nosemgrep: dangerous-subprocess-use-tainted-env-args
    (OUT / "schemathesis.txt").write_text(st.stdout + st.stderr)
    print(st.stdout[-2500:])

    (OUT / "synthese.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    # Masquage des jetons JWT dans les traces conservées (sinon gitleaks les signale à juste titre)
    jwt_re = re.compile(r"eyJ[\w-]+\.[\w-]+\.[\w-]+")
    key_re = re.compile(r'("KEY"\s*:\s*")[0-9a-f]{32}(")')  # clés d'idempotence aléatoires (faux positifs gitleaks)
    for f in OUT.rglob("*"):
        if f.is_file():
            text = f.read_text(errors="replace")
            masked = key_re.sub(r"\1<cle-idempotence-aleatoire>\2", jwt_re.sub("<JWT-masque>", text))
            if masked != text:
                f.write_text(masked)
    for f in (keys, methods):
        f.unlink()


if __name__ == "__main__":
    main()
