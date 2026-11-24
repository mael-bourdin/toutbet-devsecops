"""Génère docs/rapport_atelier2.pdf (Atelier 2 : validation et tests offensifs).

Usage : python docs/build_report_atelier2.py
Les chiffres proviennent des rapports bruts conservés dans reports/ (voir la section 8).
"""
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, Preformatted, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

DOCS = Path(__file__).parent
ROOT = DOCS.parent
sys.path.insert(0, str(DOCS))
import content as C  # noqa: E402

INK = colors.HexColor("#1d2433")
MUTED = colors.HexColor("#5c6475")
ACCENT = colors.HexColor("#1f6feb")
OK = "#1a7f37"
KO = "#d62828"

ss = getSampleStyleSheet()
h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=16, textColor=INK, spaceBefore=6, spaceAfter=8)
h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=12, textColor=ACCENT, spaceBefore=8, spaceAfter=4)
body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9.5, leading=13, textColor=INK)
cell = ParagraphStyle("c", parent=body, fontSize=7.4, leading=9.4)
cellb = ParagraphStyle("cb", parent=cell, fontName="Helvetica-Bold")
head = ParagraphStyle("hd", parent=cell, fontName="Helvetica-Bold", textColor=colors.white)
mono = ParagraphStyle("m", parent=body, fontName="Courier", fontSize=6.9, leading=8.6, textColor=INK)
title = ParagraphStyle("t", parent=ss["Title"], fontSize=24, textColor=INK, alignment=TA_CENTER)
sub = ParagraphStyle("s", parent=body, fontSize=12, alignment=TA_CENTER, textColor=MUTED)


def ok(t="OK"):
    return f"<font color='{OK}'><b>{t}</b></font>"


def ko(t="KO"):
    return f"<font color='{KO}'><b>{t}</b></font>"


def code(t):
    return f"<font face='Courier'>{t}</font>"


def table(rows, widths, header, bold_first=True):
    data = [[Paragraph(h, head) for h in header]]
    for r in rows:
        data.append([Paragraph(str(v), cellb if (i == 0 and bold_first) else cell) for i, v in enumerate(r)])
    t = Table(data, colWidths=widths, repeatRows=1)
    st = [("BACKGROUND", (0, 0), (-1, 0), INK), ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#c9cfda")),
          ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]
    st += [("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f5f7fb")) for i in range(2, len(data), 2)]
    t.setStyle(TableStyle(st))
    return t


def log(text):
    return Preformatted(text.strip("\n"), mono, maxLineLength=125)


def shot(path, width=17.6 * cm):
    img = Image(str(path))
    img.drawHeight = width * img.imageHeight / img.imageWidth
    img.drawWidth = width
    return img


# --------------------------------------------------------------------------------------------- contenu
SEMGREP_AVANT = [
    ("1", ".github/workflows/ci.yml:9", "github-actions-mutable-action-tag",
     code("actions/checkout@v4") + " : étiquette mutable (attaque de la chaîne d'approvisionnement)"),
    ("2", ".github/workflows/ci.yml:10", "github-actions-mutable-action-tag", code("actions/setup-python@v5")),
    ("3", ".github/workflows/ci.yml:23", "github-actions-mutable-action-tag", code("actions/checkout@v4") + " (job secrets)"),
    ("4", ".github/workflows/ci.yml:26", "github-actions-mutable-action-tag", code("gitleaks/gitleaks-action@v2")),
    ("5", ".github/dependabot.yml:3", "dependabot-missing-cooldown",
     "Écosystème pip : pas de délai avant de proposer une version tout juste publiée (paquet piégé)"),
    ("6", ".github/dependabot.yml:6", "dependabot-missing-cooldown", "Écosystème github-actions : idem"),
]

SEMGREP_FIX = [
    ("1 à 4", "Actions épinglées sur le SHA complet du commit, version en commentaire : "
              + code("actions/checkout@11d5960a…  # v4.4.0") + ", " + code("actions/setup-python@a26af69b…  # v5.6.0")
              + ", " + code("gitleaks/gitleaks-action@ff98106e…  # v2.3.9") + " (SHA vérifiés par git ls-remote)."),
    ("5 et 6", code("cooldown: default-days: 7") + " ajouté aux deux écosystèmes Dependabot."),
]

RULES = [
    ("R1 - Écriture comptable hors du grand livre",
     "Le solde n'est que la somme des écritures : toute écriture hors de " + code("ledger.post()") +
     " contourne le contrôle « transaction équilibrée » et permet de créer de l'argent.",
     "Alerte si (a) " + code("LedgerEntry(...)") + " est instancié ailleurs que dans la fonction " +
     code("post") + " de " + code("app/ledger.py") + " ; (b) " + code("update(LedgerEntry)") + ", " +
     code("delete(LedgerEntry)") + " ou " + code("db.delete(<LedgerEntry>)") + " apparaît n'importe où "
     "(le grand livre est append-only) ; (c) une requête SQL brute (" + code("text(...)") + ") contient "
     + code("ledger_entries") + " avec INSERT/UPDATE/DELETE."),
    ("R2 - Débit sans verrou (check-then-act sur le solde)",
     "Défaut réellement trouvé à l'étape 2 : lire le solde puis débiter sans verrou permet à des requêtes "
     "simultanées de dépenser plusieurs fois le même argent.",
     "Dans une même fonction, alerte si " + code("ledger.balance(db, $ACC)") + " est suivi d'un " +
     code("ledger.post(...)") + " ou " + code("ledger.transfer(...)") + " débitant " + code("$ACC") +
     " (montant négatif) SANS appel préalable à " + code("lock_account(db, $ACC)") + " ; et alerte si " +
     code("transfer(..., allow_negative_src=True)") + " est appelé avec une source autre que " + code("ledger.PSP") + "."),
    ("R3 - Route d'écriture sans authentification ni limitation",
     "Une nouvelle route POST/PUT/PATCH/DELETE oubliant la dépendance de sécurité serait publique et "
     "illimitée (bruteforce, flood, IDOR).",
     "Pour chaque fonction décorée " + code("@router.post|put|patch|delete") + ", alerte si aucun paramètre n'a "
     "pour défaut " + code("Depends(rate_limit_writes)") + " ou " + code("Depends(require_admin)") + ", sauf "
     "liste blanche : " + code("/auth/register") + " et " + code("/auth/login") + " (qui doivent appeler " +
     code("limiter.check") + ") et " + code("/payments/webhook") + " (qui doit appeler " +
     code("verify_psp_signature") + " AVANT " + code("json.loads") + ")."),
    ("R4 (bonus) - Montant monétaire non entier",
     "Les flottants créent des centimes fantômes ; la coercition (" + code('"100"') + ", " + code("1e3") +
     ") a été observée au fuzzing.",
     "Alerte sur tout champ ou variable dont le nom se termine par " + code("_cents") + " ou " + code("_bps") +
     " annoté " + code("float") + "/" + code("Decimal") + ", passé à " + code("float()") + ", ou déclaré dans un "
     "schéma Pydantic sans " + code("strict=True") + "."),
]

DAST = [
    ("D1", "DAST", "ffuf", "Découverte de routes, anonyme : 51 chemins (" + code("/admin") + ", " + code("/.env") +
     ", " + code("/.git/config") + ", " + code("/toutbet.db") + ", " + code("/docs") + ", " + code("/metrics") + "…)",
     "200 sur " + code("/docs /redoc /openapi.json /docs/oauth2-redirect") + " : " + ko("API documentée publiquement") +
     " ; 401 sur /wallet, /auth/me ; aucun fichier sensible ; en-tête " + code("Server: uvicorn") + " " + ko("51/51"),
     "Docs " + ok("404 par défaut") + " (activées seulement avec TOUTBET_EXPOSE_DOCS=1, utilisé pour Schemathesis) ; "
     "en-tête Server " + ok("0/51")),
    ("D2", "DAST", "ffuf", "Même découverte avec un jeton valide", "Aucune route cachée supplémentaire", ok("Idem")),
    ("D3", "DAST", "ffuf", "9 méthodes HTTP sur " + code("/bets/{id}/wagers") + " (PUT, PATCH, DELETE, TRACE…)",
     ok("405 ×8, 400 ×1") + " : aucune route de modification de mise", ok("Idem")),
    ("D4", "DAST", "pytest + httpx", "20 scénarios d'abuse stories contre le serveur réel (section 6)",
     ko("19/20") + " : AS-07 simultané échoue (solde négatif)", ok("20/20")),
    ("F1", "Fuzzing", "ffuf", "Montant " + code("stake_cents") + " : 39 valeurs (bornes, négatifs, 2^31, 2^63, "
     + code("NaN") + ", " + code("Infinity") + ", chaînes, tableaux…), 200 requêtes",
     ko("HTTP 500") + " sur " + code("NaN") + " (et " + code("Infinity") + " lors du 1er passage) ; 422 renvoie la "
     "valeur saisie", ok("0 erreur 500") + ", 422 épuré"),
    ("F2", "Fuzzing", "ffuf", "Issue " + code("outcome") + " : 24 charges (SQLi, XSS, SSTI, traversée, CRLF)",
     ok("422 ×77") + " (+429)", ok("Idem")),
    ("F3", "Fuzzing", "ffuf", "Identifiant de pari dans l'URL : 23 charges (SQLi, UUID nul, %00, ../)",
     ok("404 ×23") + ", réponse identique à un pari inexistant", ok("Idem")),
    ("F4", "Fuzzing", "ffuf", "Titre de pari : 24 charges d'injection",
     "201 ×22 : texte stocké tel quel (JSON, requêtes paramétrées : cf. I1) ; 422 ×2 (longueur)",
     "Idem (risque accepté : encodage à l'affichage côté client)"),
    ("F5", "Fuzzing", "ffuf", "Mise minimale " + code("min_stake_cents") + " : 39 valeurs",
     ko("10 acceptées") + " dont " + code("1e3") + ", " + code("100.0") + ", " + code('"100"') + " (coercition)",
     ok("7 acceptées") + " : entiers stricts uniquement"),
    ("F6", "Fuzzing", "ffuf", "Identifiant de connexion : 24 charges d'injection",
     "401 ×19 générique ; 422 ×5 " + ko("renvoyant la saisie"), ok("401 / 422 épurés")),
    ("F7", "Fuzzing", "ffuf", "En-tête " + code("PSP-Signature") + " du webhook : 24 valeurs malformées",
     ok("400 ×24"), ok("Idem")),
    ("F8", "Fuzzing", "Schemathesis", "Fuzzing guidé par le schéma OpenAPI : 14 opérations, 527 / 567 cas générés",
     ok("0 erreur serveur") + " ; 20 codes de statut non documentés (ST103)",
     ok("0 erreur serveur") + " ; 25 ST103 (documentation, cf. section 8)"),
    ("I1", "IAST", "instrumentation", "Taint SQL : toute valeur reçue retrouvée dans le TEXTE d'une requête SQL",
     ok("0 / 2413 requêtes"), ok("0 / 2453 requêtes")),
    ("I2", "IAST", "instrumentation", "Exceptions internes capturées avec pile d'appels",
     ko("1") + " " + code("ValueError: Out of range float values… nan") + " (pile en section 3)", ok("0")),
    ("I3", "IAST", "instrumentation", "Marqueurs internes dans les réponses (Traceback, sqlalchemy, chemins…)",
     ok("0") + " (le gestionnaire 500 masquait déjà les piles)", ok("0")),
    ("I4", "IAST", "check_invariants.py", "Invariants financiers après campagne : grand livre = 0, aucun solde < 0, "
     "séquestre = mises, chaîne d'audit", ko("Soldes négatifs (6 comptes, pire -380 €)") + " ; " +
     ko("chaîne d'audit rompue"), ok("4/4 OK")),
    ("I5", "IAST", "instrumentation", "Volumétrie SQL par appel HTTP (N+1)", "max 18 (vote)", "max 20 (+2 verrous)"),
    ("I6", "IAST", "uvicorn 4 workers", "Démarrage multi-processus sur base vide", ko("2 workers sur 4 plantent"),
     ok("4/4, 5 démarrages sur 5")),
]

FIXES = [
    ("Solde négatif par mises simultanées (TOCTOU)", "Verrou d'écriture pris AVANT la lecture du solde : "
     + code("lock_account()") + " (UPDATE neutre de la ligne utilisateur : verrou de ligne PostgreSQL, verrou "
     "d'écriture SQLite).", code("app/ledger.py"), "E2E AS-07 6/6, Locust CHECK, invariants"),
    ("Chaîne d'audit « fourchue » sous concurrence", "Verrou sur la dernière entrée avant lecture de "
     + code("prev_hash") + ".", code("app/audit.py"), "check_invariants : chaîne intègre"),
    ("HTTP 500 sur NaN / Infinity + écho des saisies (mot de passe compris)", "Gestionnaire "
     + code("RequestValidationError") + " : " + code('{"detail":"Requête invalide","fields":[…]}') +
     " sans valeur, motif ni type Pydantic ; schéma OpenAPI 422 mis à jour.", code("app/main.py"),
     code("tests/test_dast_regressions.py") + ", F1/F6"),
    ("Coercition des montants (" + code('"100"') + ", " + code("1e3") + ", " + code("100.0") + ")",
     code("strict=True") + " sur tous les champs en centimes / points de base.", code("app/schemas.py"),
     code("test_montants_entiers_stricts") + ", F5"),
    ("Documentation API publique", "Swagger, ReDoc et OpenAPI désactivés sauf " + code("TOUTBET_EXPOSE_DOCS=1") + ".",
     code("app/config.py, app/main.py"), code("test_documentation_api_masquee_par_defaut") + ", D1"),
    ("Bannière " + code("Server: uvicorn"), "Lancement avec " + code("--no-server-header") + " (README).",
     "README.md", "D1 : 0/51"),
    ("Plantage au démarrage multi-workers", "Création du schéma réessayée (20 tentatives, attente croissante) ; "
     "délai d'attente SQLite porté à 30 s.", code("app/db.py"), "I6 : 5/5"),
    ("Erreur 500 sans trace côté serveur", "Le gestionnaire générique journalise la pile (logger "
     + code("toutbet") + "), le client ne reçoit que « Erreur interne ».", code("app/main.py"), "relecture"),
    ("Chaîne d'approvisionnement CI (Semgrep)", "Actions épinglées par SHA, cooldown Dependabot.",
     code(".github/"), "Semgrep : 0"),
]

FILES = [
    ("tests/e2e/test_e2e_abuse_stories.py", "20 tests E2E : abuse stories AS-01 à AS-14 rejouées en HTTP contre le "
     "serveur réel, dont la course critique sur le solde et le rejeu simultané"),
    ("tests/e2e/conftest.py", "Client HTTP de test (inscription, dépôt via webhook signé, création de pari…)"),
    ("tests/load/locustfile.py", "Scénario de charge Locust (afflux sur un même événement + rafale d'un même parieur)"),
    ("tests/test_dast_regressions.py", "Non-régression unitaire des défauts trouvés en DAST / fuzzing"),
    ("tests/test_abuse_stories.py", "Tests unitaires des abuse stories (atelier 1, toujours verts)"),
    ("security/dast/run_dast.py", "Campagne DAST + fuzzing reproductible (ffuf + Schemathesis)"),
    ("security/dast/wordlists/", "Dictionnaires : routes, montants, charges d'injection"),
    ("security/iast/instrumented_app.py", "Application instrumentée (capteurs IAST)"),
    ("security/iast/check_invariants.py", "Vérification des invariants financiers après campagne"),
    ("reports/", "Résultats bruts : semgrep/, dast/avant|apres/, iast/, locust/, e2e_*.txt, race_*.txt"),
]

LOG_STARTUP = """INFO:     Started server process [29454]   (x4 workers sur une base vide)
sqlite3.OperationalError: table users already exists
sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) table users already exists
[SQL: CREATE TABLE users (id VARCHAR(36) NOT NULL, username VARCHAR(32) NOT NULL, ...)]
ERROR:    Application startup failed. Exiting.
ERROR:    Application startup failed. Exiting."""

LOG_NAN = """INFO:  "POST /bets/0f1146c9-.../wagers HTTP/1.1" 500 Internal Server Error
ERROR:    Exception in ASGI application
fastapi.exceptions.RequestValidationError: 1 validation error:
  {'type': 'finite_number', 'loc': ('body', 'stake_cents'), 'msg': 'Input should be a finite number', 'input': nan}
  File "<tmp>/toutbet_avant/app/routers/bets.py", line 88, in place_wager
  File ".../starlette/responses.py", line 197, in render
    return json.dumps(
ValueError: Out of range float values are not JSON compliant: nan
when serializing dict item 'input'
when serializing list item 0
when serializing dict item 'detail'
-> réponse client : {"detail":"Erreur interne"} (la pile n'est PAS renvoyée au client)"""

LOG_422 = """POST /auth/register  {"username":"a","email":"x","password":"y","role":"admin"}
AVANT -> 422 {"detail":[{"type":"string_pattern_mismatch","loc":["body","username"],
  "msg":"String should match pattern '^[a-zA-Z0-9_]{3,32}$'","input":"a","ctx":{"pattern":"^[a-zA-Z0-9_]{3,32}$"}},
  {"type":"string_too_short","loc":["body","password"],"msg":"String should have at least 12 characters",
  "input":"y","ctx":{"min_length":12}},{"type":"extra_forbidden","loc":["body","role"],...,"input":"admin"}]}
APRES -> 422 {"detail":"Requête invalide","fields":["email","password","role","username"]}

En-têtes AVANT : server: uvicorn            En-têtes APRES : (aucun en-tête Server)"""

LOG_RACE = """test_as07_paris_simultanes_ne_depassent_pas_le_solde  (solde 100 EUR, 20 mises de 80 EUR envoyées en même temps)
AVANT : Solde négatif : -22000 centimes, 4 mises acceptées   [201, 409, ..., 201, ..., 201, ..., 201]
        Solde négatif : -14000 centimes, 3 mises acceptées
        Solde négatif : -38000 centimes, 6 mises acceptées    -> 5 échecs sur 6 exécutions
        (session exploratoire : jusqu'à -54000 centimes, 8 mises acceptées)
APRES : 2 passed (x6)  -> 1 seule mise acceptée, solde final 20,00 EUR

check_invariants.py AVANT                                  check_invariants.py APRES
[OK ] Grand livre équilibré (somme = 0)                    [OK ] Grand livre équilibré (somme = 0)
[KO ] Aucun solde parieur négatif : 6 comptes, -38000 c    [OK ] Aucun solde parieur négatif
[OK ] Séquestre de chaque pari = somme des mises           [OK ] Séquestre de chaque pari = somme des mises
[KO ] Chaîne d'audit HMAC intègre                          [OK ] Chaîne d'audit HMAC intègre"""

E2E = [
    ("AS-01", "Bruteforce : 30 essais -> 429 ; message identique compte existant / inexistant ; doublon d'inscription générique"),
    ("AS-02", "Jetons forgés (alg=none, mauvaise clé, expiré, non-JWT) -> 401"),
    ("AS-03", "Commission 90 % et champs cachés (platform_fee_bps, status, bookie_id, role) -> 422"),
    ("AS-04", "Non-invité : lecture et mise -> 404 indiscernable d'un pari inexistant (anti-IDOR)"),
    ("AS-05", "Mise après clôture -> 409 ; PUT/PATCH/DELETE sur une mise -> 404/405"),
    ("AS-06", "Rejeu séquentiel ET 10 rejeux simultanés de la même Idempotency-Key -> un seul débit, aucun 500"),
    ("AS-07", "Montant négatif / nul / supérieur au solde ; 20 mises simultanées du même parieur -> solde jamais < 0"),
    ("AS-08", "Le bookie ne peut pas miser sur son pari -> 403"),
    ("AS-09", "Résultat avant clôture 409, proposé par un parieur 403, contestation -> litige, vote unique, arbitrage modérateur"),
    ("AS-10", "Webhook : mauvaise signature, périmé, sans signature -> 400 ; rejeu -> already_processed ; montant modifié -> 422"),
    ("AS-11", "Retrait : mauvais mot de passe 401, sans KYC 403, solde intact"),
    ("AS-12", "Reçu HMAC de 64 caractères hexadécimaux renvoyé pour chaque mise"),
    ("AS-13", "150 écritures rapides -> 429 ; corps de 70 Ko -> 413"),
    ("AS-14", "Règlement réel avec montants « tordus » (777, 1333, 999) -> grand livre à somme nulle"),
    ("Transverse", "Erreurs sans fuite interne (JSON invalide, id de 5000 car., signature malformée) ; en-têtes de sécurité"),
]


def build(path: Path) -> None:
    s = []
    s += [Spacer(1, 4 * cm), Paragraph("Atelier 2", sub), Spacer(1, 6),
          Paragraph("Validation et tests offensifs", title), Spacer(1, 10),
          Paragraph("ToutBet' : l'argent des parieurs est-il en sécurité ?", sub),
          Spacer(1, 2 * cm), Paragraph("<b>Membres du groupe</b>", ParagraphStyle("x", parent=body, alignment=TA_CENTER)),
          Spacer(1, 6)]
    mt = Table([["Nom", "Compte GitHub"]] + [list(m) for m in C.MEMBERS], colWidths=[6 * cm, 5 * cm])
    mt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), INK), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#c9cfda")),
                            ("FONTSIZE", (0, 0), (-1, -1), 10), ("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    s += [mt, Spacer(1, 1.5 * cm),
          Paragraph(f"Dépôt : <link href='{C.REPO_URL}' color='blue'>{C.REPO_URL}</link>",
                    ParagraphStyle("y", parent=body, alignment=TA_CENTER)),
          Spacer(1, 4), Paragraph("Formation DevSecOps - EPSI 2026-2027", sub), PageBreak()]

    s += [Paragraph("Synthèse", h1), Paragraph(
        "Trois couches de tests ont été appliquées au prototype de l'atelier 1 : analyse statique (Semgrep), "
        "exploration dynamique (DAST, fuzzing, IAST) et tests E2E / charge. <b>Le défaut le plus grave a été trouvé "
        "par les tests dynamiques, pas par l'analyse statique</b> : un même parieur envoyant des mises simultanées "
        "dépensait plus que son solde (jusqu'à 540 € de découvert pour 100 € déposés). Il est corrigé et couvert par "
        "un test E2E, un contrôle Locust et une vérification d'invariants.", body), Spacer(1, 6)]
    s.append(table([
        ("Semgrep (364 règles)", "6 alertes", "0 alerte (2 exclusions justifiées dans l'outillage de test)"),
        ("Erreurs serveur (500) en fuzzing", "Sur NaN et Infinity", "0"),
        ("Fuites d'information", "Saisies renvoyées (mots de passe compris), motifs de validation, types Pydantic, "
         "bannière uvicorn, documentation OpenAPI publique", "Aucune"),
        ("Abuse stories E2E", "19 / 20", "20 / 20"),
        ("Course critique sur le solde", "Échec 5 / 6 exécutions, soldes jusqu'à -540 €", "6 / 6, aucun solde négatif"),
        ("Invariants financiers après campagne", "2 / 4 (solde négatif, audit rompu)", "4 / 4"),
        ("Charge (Locust, 200 parieurs, même événement)", "-", "~196 req/s, 20 712 requêtes, 0 échec, médiane 3 ms"),
    ], [5.2 * cm, 5.2 * cm, 7 * cm], ["Indicateur", "Avant correction", "Après correction"]))
    s += [Spacer(1, 6), Paragraph(
        "Outillage (sans Docker) : Semgrep 1.157 (CLI), ffuf 2.1, Schemathesis 4.34, instrumentation IAST écrite pour "
        "le projet, pytest + httpx, Locust 2.47, Chrome sans tête pour les captures. Serveur : uvicorn 4 workers, "
        "SQLite. La campagne « avant » a été rejouée sur le commit de l'atelier 1 (git worktree), la campagne « après » "
        "sur le code corrigé, avec les mêmes scripts.", body), PageBreak()]

    # 1. Semgrep
    s += [Paragraph("1. Analyse statique avec Semgrep", h1), Paragraph(
        "Commande (packs du registre Semgrep, métriques désactivées) : " + code(
            "semgrep scan --config p/default --config p/python --config p/owasp-top-ten --config p/secrets "
            "--config p/github-actions --config p/fastapi ."), body),
        Paragraph("Rapport AVANT correction : 6 alertes bloquantes, 364 règles, 21 fichiers", h2),
        table(SEMGREP_AVANT, [0.8 * cm, 4.2 * cm, 4.6 * cm, 7.8 * cm], ["#", "Fichier:ligne", "Règle", "Détail"]),
        Spacer(1, 4), Paragraph(
            "Aucune alerte sur le code Python de l'application : le socle de l'atelier 1 avait été généré avec ces "
            "exigences (requêtes ORM paramétrées, pas de secret en dur, JWT à algorithme figé…). Bandit confirme : "
            "« No issues identified ».", body),
        Paragraph("Corrections", h2), table(SEMGREP_FIX, [2 * cm, 15.4 * cm], ["Alertes", "Correction"]),
        Paragraph("Rapport APRÈS correction : 0 alerte, 364 règles, 164 fichiers", h2), Paragraph(
            "Le second scan couvre aussi les nouveaux fichiers de l'atelier 2 (tests, outillage). Deux alertes "
            + code("dangerous-subprocess-use-tainted-env-args") + " dans " + code("security/dast/run_dast.py") +
            " (lignes 41 et 116) sont <b>exclues avec justification</b> (" + code("# nosemgrep") + ") : "
            "il s'agit de l'outil de test qui lance ffuf et Schemathesis ; les arguments sont passés en liste, "
            "sans shell (aucune injection de commande possible), et " + code("BASE_URL") + " est validée au "
            "démarrage (schéma http/https, hôte présent, pas de « - » initial). Ce fichier n'est pas déployé. "
            "Rapports bruts : " + code("reports/semgrep/avant.txt|json") + ", " + code("apres.txt|json") + ", " +
            code("apres_sans_nosemgrep.json") + ".", body),
        Paragraph("Règles personnalisées proposées (non écrites)", h2)]
    s.append(table(RULES, [4 * cm, 5.4 * cm, 8 * cm], ["Règle", "Pourquoi", "Critères concrets de vérification"]))
    s.append(PageBreak())

    # 2. Dynamique
    s += [Paragraph("2. Exploration dynamique : DAST, fuzzing, IAST", h1), Paragraph(
        "Cible principale : l'API de création de paris et de mises. Script reproductible : " +
        code("python security/dast/run_dast.py avant|apres") + ". L'IAST est une instrumentation de l'application "
        "réelle (" + code("security/iast/instrumented_app.py") + ") : un capteur SQLAlchemy vérifie qu'aucune donnée "
        "reçue n'est concaténée dans le texte SQL, un capteur d'exceptions enregistre la pile côté serveur, un capteur "
        "de réponse cherche des marqueurs internes ; " + code("check_invariants.py") + " vérifie ensuite l'argent en "
        "base. Tous les tests sont listés, quel que soit leur résultat.", body), Spacer(1, 4)]
    s.append(table(DAST, [0.9 * cm, 1.3 * cm, 1.9 * cm, 4.8 * cm, 4.6 * cm, 3.9 * cm],
                   ["ID", "Type", "Outil", "Test", "Résultat AVANT", "Résultat APRÈS"]))
    s.append(Paragraph(
        "429 = limitation de débit (30 écritures/min/utilisateur) : comportement attendu, qui réduit cependant le "
        "nombre de valeurs réellement évaluées par le fuzzing des mises (F1, F2).", ParagraphStyle(
            "n", parent=cell, textColor=MUTED)))
    s.append(PageBreak())

    s += [Paragraph("3. Logs serveur, stacktraces et informations divulguées", h1),
          Paragraph("Plantage au démarrage avec 4 workers (I6, extrait) - " + code("reports/dast/log_01_demarrage_multiworker.log"), h2),
          log(LOG_STARTUP),
          Paragraph("Erreur 500 sur une mise à NaN (F1, I2) - " + code("reports/dast/avant/server.log"), h2),
          log(LOG_NAN), Paragraph(
              "Cause : le gestionnaire 422 par défaut de FastAPI renvoie la valeur reçue (" + code("input") +
              ") ; NaN n'étant pas sérialisable en JSON, la construction de la réponse d'erreur lève elle-même une "
              "exception. Un attaquant obtient ainsi des 500 à volonté et pollue les journaux.", body),
          Paragraph("Informations sur la structure interne renvoyées au client (F6, D1)", h2), log(LOG_422)]
    s.append(table([
        ("Valeur saisie renvoyée", "Le mot de passe saisi revient en clair dans la réponse 422 (journaux de proxy, "
         "outils de supervision, historique du client)"),
        ("Règles de validation", "Expressions régulières exactes et bornes (" + code("^[a-zA-Z0-9_]{3,32}$") +
         ", min_length 12) : aide à calibrer une attaque"),
        ("Pile technique", "Types d'erreur Pydantic (" + code("string_pattern_mismatch") + ", " +
         code("extra_forbidden") + ") et en-tête " + code("server: uvicorn") + " : FastAPI/Pydantic/uvicorn identifiés"),
        ("Contrat complet", code("/openapi.json") + ", " + code("/docs") + ", " + code("/redoc") +
         " publics : toutes les routes, schémas et champs interdits"),
        ("Non divulgué", "Aucune stacktrace, requête SQL ou chemin de fichier dans les réponses (vérifié par I3 sur "
         "~2 400 réponses) : le gestionnaire 500 générique de l'atelier 1 fonctionnait"),
    ], [3.6 * cm, 13.8 * cm], ["Information", "Constat"]))
    s += [Paragraph("Course critique sur le solde et invariants (D4, I4)", h2), log(LOG_RACE), PageBreak()]

    s += [Paragraph("4. Corrections effectuées", h1)]
    s.append(table(FIXES, [4.3 * cm, 7.2 * cm, 2.6 * cm, 3.3 * cm], ["Défaut", "Correction", "Fichier", "Vérification"]))
    s += [Spacer(1, 6), Paragraph(
        "Après correction : 28 tests unitaires (24 de l'atelier 1 + 4 de non-régression) et 20 tests E2E passent ; "
        "Semgrep 0 alerte ; Bandit 0 alerte ; campagne DAST/fuzzing sans erreur 500 ni fuite.", body), PageBreak()]

    # 5. Tests automatisés
    s += [Paragraph("5. Chemin des tests automatisés dans le dépôt GitHub", h1), Paragraph(
        f"Dépôt : <link href='{C.REPO_URL}' color='blue'>{C.REPO_URL}</link>", body), Spacer(1, 4)]
    s.append(table([(code(p), d) for p, d in FILES], [6.4 * cm, 11 * cm], ["Chemin", "Contenu"], bold_first=False))
    s += [Paragraph("Lancement", h2), log("""set -a && source .env && set +a
uvicorn app.main:app --port 8000 --workers 4 --no-server-header &
BASE_URL=http://127.0.0.1:8000 pytest tests/e2e -v                     # abuse stories E2E
locust -f tests/load/locustfile.py --host http://127.0.0.1:8000         # charge, interface http://localhost:8089
TOUTBET_EXPOSE_DOCS=1 ... ; BASE_URL=... python security/dast/run_dast.py apres   # DAST + fuzzing
python security/iast/check_invariants.py                                # invariants financiers""")]
    s += [Paragraph("6. Automatisation des abuse stories (E2E)", h1), Paragraph(
        "Les abuse stories de l'atelier 1 sont rejouées en HTTP contre le serveur réel (4 processus), et non plus "
        "via le client de test en mémoire : la concurrence entre processus devient testable. Seules deux actions "
        "sans route d'API passent par la base : simuler l'heure de clôture et promouvoir un modérateur.", body),
          Spacer(1, 4)]
    s.append(table(E2E, [2 * cm, 15.4 * cm], ["Abuse story", "Ce que vérifie le test E2E"]))
    s.append(PageBreak())

    # 7. Locust
    s += [Paragraph("7. Test de charge Locust", h1), Paragraph(
        "Scénario " + code("tests/load/locustfile.py") + " : un bookie crée <b>un seul événement</b> (« Finale : la "
        "France gagne-t-elle ? ») ; 200 parieurs arrivent à 10 par seconde, s'inscrivent, déposent 50 € via le "
        "webhook signé, consultent le pari et leur solde, misent (avec un rejeu « double clic » de la même "
        "Idempotency-Key). Un profil « parieur frénétique » dépose 100 € puis envoie en parallèle 20 mises de 80 € sur 20 "
        "événements, son solde ne couvrant qu'une mise ; "
        "la ligne " + code("CHECK solde >= 0 après rafale simultanée") + " devient un échec Locust si le solde passe "
        "sous zéro.", body), Spacer(1, 4),
          shot(ROOT / "reports/locust/locust_stats.png"), Paragraph(
              "Interface web Locust en cours d'exécution : 200 utilisateurs, 195,6 req/s, 20 712 requêtes, 0 % d'échec, "
              "médiane 3 ms, 95e centile 100 ms. Inscription et connexion (Argon2id) : médianes 370 et 190 ms.",
              ParagraphStyle("cap", parent=cell, textColor=MUTED, alignment=TA_CENTER))]
    s += [PageBreak(), shot(ROOT / "reports/locust/locust_charts.png"), Paragraph(
        "Onglet Charts : montée à 200 utilisateurs, débit stable autour de 190 req/s, aucune défaillance ; le pic du "
        "95e centile pendant la montée correspond aux inscriptions (hachage Argon2id volontairement coûteux).",
        ParagraphStyle("cap2", parent=cell, textColor=MUTED, alignment=TA_CENTER)), Spacer(1, 6), Paragraph(
        "Après la charge, " + code("check_invariants.py") + " sur la base : grand livre à somme nulle, aucun solde "
        "négatif, séquestres cohérents, chaîne d'audit intègre (" + code("reports/locust/invariants_apres_charge.txt") +
        "). Rapport HTML complet : " + code("reports/locust/rapport_locust.html") + ".", body), PageBreak()]

    # 8. Solde négatif
    s += [Paragraph("8. Réponse : un même utilisateur peut-il dépenser plus que son solde ?", h1), Paragraph(
        "<b>Oui, avant correction.</b> Le contrôle du solde suivait le schéma « vérifier puis agir » : "
        + code("balance(src) &lt; amount") + " puis insertion des écritures. Avec le pilote SQLite de Python, la "
        "lecture du solde s'exécute hors transaction : 4 processus lisent le même solde de 100 € au même instant, "
        "tous voient 100 € ≥ 80 €, puis leurs écritures sont sérialisées l'une après l'autre sans nouvelle "
        "vérification. Mesure : le test « 20 mises de 80 € simultanées sur 20 paris avec 100 € » a échoué 5 fois sur "
        "6 (3 à 6 mises acceptées, solde final jusqu'à -380 €, et -540 € lors de la première exploration). La "
        "contrainte « une mise par pari » ne protège pas : l'attaque vise des paris différents. Le même défaut "
        "touchait le journal d'audit : deux entrées chaînées sur le même hash rendaient la chaîne invérifiable.",
        body), Paragraph("Correction", h2), Paragraph(
        "Le verrou est pris <b>avant</b> la lecture : " + code("lock_account()") + " exécute une mise à jour neutre de "
        "la ligne de l'utilisateur dans la transaction. En PostgreSQL c'est un verrou de ligne (seuls les débits du "
        "même compte sont sérialisés) ; en SQLite, le verrou d'écriture de la base. La seconde requête attend la "
        "validation de la première, relit un solde déjà débité et reçoit 409 « Solde insuffisant ». La même technique "
        "protège la chaîne d'audit.", body), Paragraph("Preuves", h2)]
    s.append(table([
        ("E2E " + code("test_as07_paris_simultanes_ne_depassent_pas_le_solde"), ko("5 échecs / 6"), ok("6 / 6") +
         " : 1 mise acceptée, solde 20 €"),
        ("E2E " + code("test_as06_rejeu_simultane_meme_cle") + " (10 rejeux simultanés)", ok("6 / 6"), ok("6 / 6")),
        ("Invariant « aucun solde négatif » après campagne", ko("6 comptes négatifs"), ok("0")),
        ("Invariant « chaîne d'audit intègre »", ko("Rompue"), ok("Intègre")),
        ("Locust " + code("CHECK solde >= 0") + " sous 200 utilisateurs", "-", ok("4 / 4, 0 échec")),
    ], [8 * cm, 3.4 * cm, 6 * cm], ["Vérification", "Avant", "Après"]))
    s += [Paragraph("Risques résiduels", h2)] + [Paragraph(f"- {r}", body) for r in [
        "En production multi-instance, la limitation de débit est en mémoire par processus : avec 4 workers, la limite "
        "réelle est multipliée par le nombre de processus (mesuré : 10 à 15 tentatives de connexion traitées sur 30 "
        "envoyées au lieu de 5, maximum théorique 20). À "
        "remplacer par un compteur partagé (Redis).",
        "uvicorn fait confiance à " + code("X-Forwarded-For") + " venant de 127.0.0.1 (utilisé par les tests pour "
        "simuler des parieurs distincts) : derrière un reverse proxy, restreindre " + code("--forwarded-allow-ips") +
        " à l'adresse du proxy, sinon la limitation par IP est contournable.",
        "Les titres de paris sont stockés tels quels (texte libre légitime) : l'application mobile doit encoder à "
        "l'affichage (risque de XSS stocké si un client web les injecte en HTML).",
        "25 codes de statut (400, 401, 403, 404, 409, 429) ne sont pas déclarés dans le contrat OpenAPI (Schemathesis "
        "ST103) : défaut de documentation, sans impact sécurité.",
        "L'IAST est une instrumentation maison (taint par correspondance exacte) : elle ne remplace pas un agent IAST "
        "du commerce (Contrast, Seeker).",
    ]]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(1.5 * cm, 1 * cm, "ToutBet' - Atelier 2 DevSecOps : validation et tests offensifs")
        canvas.drawRightString(A4[0] - 1.5 * cm, 1 * cm, f"{doc.page}")
        canvas.restoreState()

    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm,
                      bottomMargin=1.6 * cm, title="Atelier 2 - ToutBet'", author="Groupe ToutBet'").build(
        s, onFirstPage=footer, onLaterPages=footer)


if __name__ == "__main__":
    build(DOCS / "rapport_atelier2.pdf")
    print("OK")
