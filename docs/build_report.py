"""Génère docs/*.md et docs/rapport_atelier1.pdf à partir de docs/content.py.

Usage : python docs/build_report.py
"""
import math
import sys
from pathlib import Path

from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

sys.path.insert(0, str(Path(__file__).parent))
import content as C  # noqa: E402

DOCS = Path(__file__).parent
RED = colors.HexColor("#d62828")
INK = colors.HexColor("#1d2433")
MUTED = colors.HexColor("#5c6475")
ACCENT = colors.HexColor("#1f6feb")
FILL = colors.HexColor("#eef3fb")
DATA = colors.HexColor("#fff4e0")


# --------------------------------------------------------------------------- schéma
def _box(d, x, y, w, h, title, lines=(), fill=FILL):
    d.add(Rect(x, y, w, h, rx=4, ry=4, fillColor=fill, strokeColor=INK, strokeWidth=0.8))
    d.add(String(x + w / 2, y + h - 11, title, fontName="Helvetica-Bold", fontSize=7.5, textAnchor="middle",
                 fillColor=INK))
    for i, line in enumerate(lines):
        d.add(String(x + w / 2, y + h - 21 - i * 8.5, line, fontName="Helvetica", fontSize=6.2, textAnchor="middle",
                     fillColor=MUTED))


def _label(d, x, y, text, color=INK):
    w = len(text) * 2.9 + 4
    d.add(Rect(x - w / 2, y - 2.5, w, 8, fillColor=colors.white, strokeColor=None))
    d.add(String(x, y, text, fontName="Helvetica-Oblique", fontSize=5.8, textAnchor="middle", fillColor=color))


def _arrow(d, x1, y1, x2, y2, label="", both=False, dy=4, color=ACCENT):
    d.add(Line(x1, y1, x2, y2, strokeColor=color, strokeWidth=0.9))
    for (ax, ay, bx, by) in [(x1, y1, x2, y2)] + ([(x2, y2, x1, y1)] if both else []):
        ang = math.atan2(by - ay, bx - ax)
        p1 = (bx - 6 * math.cos(ang - 0.4), by - 6 * math.sin(ang - 0.4))
        p2 = (bx - 6 * math.cos(ang + 0.4), by - 6 * math.sin(ang + 0.4))
        d.add(Polygon([bx, by, *p1, *p2], fillColor=color, strokeColor=color, strokeWidth=0.1))
    if label:
        _label(d, (x1 + x2) / 2, (y1 + y2) / 2 + dy, label, color if color == RED else INK)


def _zone(d, x, y, w, h, label):
    d.add(Rect(x, y, w, h, fillColor=None, strokeColor=RED, strokeWidth=1.6, strokeDashArray=[5, 3]))
    d.add(String(x + 5, y + h - 10, label, fontName="Helvetica-Bold", fontSize=6.5, fillColor=RED))


def architecture_drawing() -> Drawing:
    d = Drawing(530, 430)
    # Zones de confiance (lignes rouges)
    _zone(d, 2, 155, 118, 270, "Zone non maîtrisée")
    _zone(d, 2, 5, 118, 140, "Back-office")
    _zone(d, 130, 155, 86, 270, "DMZ")
    _zone(d, 226, 155, 162, 270, "Réseau privé applicatif")
    _zone(d, 226, 5, 162, 140, "Zone données")
    _zone(d, 398, 5, 130, 420, "Prestataires tiers")

    # Libellés des frontières (sur les lignes rouges)
    for x, y, t in [(125, 400, "TB1"), (221, 400, "TB2"), (307, 150, "TB3"), (393, 400, "TB4"), (61, 150, "TB5")]:
        d.add(Rect(x - 10, y - 4, 20, 11, fillColor=RED, strokeColor=RED))
        d.add(String(x, y - 0.5, t, fontName="Helvetica-Bold", fontSize=6.5, textAnchor="middle",
                     fillColor=colors.white))

    _box(d, 12, 345, 98, 55, "Parieur / Bookie", ["rôles utilisateurs", "(acteurs humains)"])
    _box(d, 12, 190, 88, 120, "Client mobile", ["iOS / Android", "JWT en Keychain", "/ Keystore",
                                                 "TLS 1.3 + pinning", "aucun secret serveur", "aucune donnée carte"])
    _box(d, 12, 30, 98, 80, "Modérateur (admin)", ["arbitrage des litiges", "VPN + MFA", "KYC manuel"])
    _box(d, 140, 230, 66, 120, "Passerelle API", ["CDN / WAF", "terminaison TLS", "rate limiting", "max 64 Ko",
                                                  "anti-DDoS"])
    _box(d, 250, 190, 122, 190, "Serveur d'application", ["FastAPI (stateless)", "", "auth : Argon2id + JWT",
                                                          "paris / invitations", "validation résultat (quorum)",
                                                          "règlement + commissions", "grand livre partie double",
                                                          "journal d'audit chaîné", "contrôle d'accès objet",
                                                          "webhook PSP (HMAC)"])
    _box(d, 240, 18, 72, 105, "Base de données", ["PostgreSQL", "SOLDES (ledger)", "escrow par pari", "mises + reçus",
                                                  "audit_log", "hash mots de passe"], fill=DATA)
    _box(d, 320, 18, 60, 105, "Coffre secrets", ["KMS / Vault", "CLÉ JWT", "CLÉ HMAC audit", "secret webhook",
                                                 "clés API PSP"], fill=DATA)
    _box(d, 412, 300, 108, 80, "PSP paiement", ["ex. Stripe Connect", "fonds réellement séquestrés", "cartes / IBAN",
                                               "(PCI-DSS)"], fill=DATA)
    _box(d, 412, 185, 108, 70, "Prestataire KYC", ["vérif. d'identité", "pièces d'identité"], fill=DATA)
    _box(d, 412, 75, 108, 60, "Notifications push", ["APNs / FCM"])

    _arrow(d, 61, 345, 61, 312)
    _arrow(d, 100, 280, 140, 280, "HTTPS+JWT", both=True)
    _arrow(d, 206, 280, 250, 280, "mTLS", both=True)
    _arrow(d, 110, 70, 250, 205, "HTTPS + MFA", dy=-2)
    _arrow(d, 276, 190, 276, 123, "SQL / TLS", dy=10)
    _arrow(d, 350, 190, 350, 123, "secrets", dy=10)
    _arrow(d, 372, 350, 412, 350, "paiement")
    _arrow(d, 412, 320, 372, 320, "webhook", color=RED)
    _label(d, 392, 310, "signé HMAC", RED)
    _arrow(d, 372, 220, 412, 220, "KYC", both=True)
    _arrow(d, 372, 200, 412, 110, "push", dy=0)
    return d


MERMAID = """```mermaid
flowchart LR
  subgraph Z1["Zone non maîtrisée"]
    U["Parieur / Bookie"] --> M["Client mobile<br/>JWT en Keychain/Keystore"]
  end
  subgraph Z5["Back-office"]
    A["Modérateur (admin)<br/>VPN + MFA"]
  end
  subgraph Z2["DMZ"]
    G["Passerelle API<br/>CDN/WAF, TLS, rate limit"]
  end
  subgraph Z3["Réseau privé applicatif"]
    S["Serveur d'application FastAPI<br/>auth, paris, résultat, règlement,<br/>grand livre, audit"]
  end
  subgraph Z4["Zone données"]
    DB[("PostgreSQL<br/>soldes, escrow, mises, audit")]
    K[("Coffre de secrets<br/>clé JWT, HMAC, PSP")]
  end
  subgraph Z6["Prestataires tiers"]
    P["PSP paiement"]
    KYC["Prestataire KYC"]
    N["Push APNs/FCM"]
  end
  M -- "TB1 · HTTPS + JWT" --> G
  G -- "TB2 · mTLS" --> S
  A -- "TB5 · HTTPS + MFA" --> S
  S -- "TB3 · SQL/TLS" --> DB
  S -- "TB3" --> K
  S -- "TB4 · intention de paiement" --> P
  P -- "TB4 · webhook signé HMAC" --> S
  S -- "TB4" --> KYC
  S -- "TB4" --> N
  classDef zone stroke:#d62828,stroke-width:3px,stroke-dasharray:6 4
  class Z1,Z2,Z3,Z4,Z5,Z6 zone
```"""


# --------------------------------------------------------------------------- Markdown
def _md_escape(s: str) -> str:
    return s.replace("|", "\\|")


def write_markdown():
    lines = ["# Backlog MVP : User Stories et Abuse Stories", "",
             "| ID | User Story | Abuse Story | Mitigation | Test |", "|---|---|---|---|---|"]
    for uid, us, abuses, mit, test in C.BACKLOG:
        ab = "<br/><br/>".join(f"**{aid}** {_md_escape(a)}" for aid, a in abuses)
        lines.append(f"| {uid} | {_md_escape(us)} | {ab} | {_md_escape(mit)} | `{test}` |")
    (DOCS / "backlog.md").write_text("\n".join(lines) + "\n")

    lines = ["# Architecture et frontières de confiance", "",
             "Les cadres rouges en pointillés délimitent les zones ; chaque flux qui traverse un cadre franchit une "
             "frontière de confiance.", "", MERMAID, "", "## Frontières de confiance", "",
             "| ID | Frontière |", "|---|---|"]
    lines += [f"| {i} | {t} |" for i, t in C.TRUST_BOUNDARIES]
    lines += ["", "## Données sensibles", "", "| Donnée | Emplacement / protection |", "|---|---|"]
    lines += [f"| {_md_escape(a)} | {_md_escape(b)} |" for a, b in C.SENSITIVE_DATA]
    (DOCS / "architecture.md").write_text("\n".join(lines) + "\n")

    lines = ["# Matrice STRIDE", "", "| Catégorie | Menace identifiée | Composant visé | Mitigation proposée | Statut MVP |",
             "|---|---|---|---|---|"]
    lines += ["| " + " | ".join(_md_escape(c) for c in row) + " |" for row in C.STRIDE]
    lines += ["", "## Risques résiduels", ""] + [f"- {r}" for r in C.RESIDUAL_RISKS]
    (DOCS / "stride.md").write_text("\n".join(lines) + "\n")

    lines = ["# Prompts utilisés", ""]
    for title, p in C.PROMPTS:
        lines += [f"## {title}", "", "```text", p, "```", ""]
    (DOCS / "prompts.md").write_text("\n".join(lines))


# --------------------------------------------------------------------------- PDF
def write_pdf(path: Path):
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=16, textColor=INK, spaceBefore=6, spaceAfter=8)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=12, textColor=ACCENT, spaceBefore=8, spaceAfter=4)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9.5, leading=13, textColor=INK)
    cell = ParagraphStyle("c", parent=body, fontSize=7.4, leading=9.4)
    cellb = ParagraphStyle("cb", parent=cell, fontName="Helvetica-Bold")
    head = ParagraphStyle("hd", parent=cell, fontName="Helvetica-Bold", textColor=colors.white)
    mono = ParagraphStyle("m", parent=body, fontName="Courier", fontSize=6.9, leading=8.6)
    title = ParagraphStyle("t", parent=ss["Title"], fontSize=24, textColor=INK, alignment=TA_CENTER)
    sub = ParagraphStyle("s", parent=body, fontSize=12, alignment=TA_CENTER, textColor=MUTED)

    def table(rows, widths, header, bold_first=True, zebra=True):
        data = [[Paragraph(h, head) for h in header]]
        for r in rows:
            data.append([Paragraph(str(v), cellb if (i == 0 and bold_first) else cell) for i, v in enumerate(r)])
        t = Table(data, colWidths=widths, repeatRows=1)
        st = [("BACKGROUND", (0, 0), (-1, 0), INK), ("VALIGN", (0, 0), (-1, -1), "TOP"),
              ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#c9cfda")),
              ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]
        if zebra:
            st += [("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f5f7fb")) for i in range(2, len(data), 2)]
        t.setStyle(TableStyle(st))
        return t

    s = []
    s += [Spacer(1, 4 * cm), Paragraph("Atelier 1", sub), Spacer(1, 6),
          Paragraph("Conception sécurisée et modélisation des menaces", title), Spacer(1, 10),
          Paragraph("ToutBet' : plateforme mobile-first de paris personnalisés entre particuliers", sub),
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

    s += [Paragraph("Sommaire", h1)]
    for i, t in enumerate(["Backlog produit / MVP : User Stories et Abuse Stories",
                           "Architecture et frontières de confiance", "Modélisation STRIDE des menaces",
                           "Prototype : prompts utilisés et dépôt Git"], 1):
        s.append(Paragraph(f"{i}. {t}", body))
    s += [Spacer(1, 8), Paragraph(
        "Démarche : chaque User Story du MVP est accompagnée d'au moins une Abuse Story. Les Abuse Stories alimentent "
        "la matrice STRIDE, qui a elle-même été injectée dans le prompt de génération du code. Chaque Abuse Story est "
        "enfin vérifiée par un test automatisé (<font face='Courier'>tests/test_abuse_stories.py</font>), "
        "exécuté en intégration continue.", body), PageBreak()]

    s += [Paragraph("1. Backlog produit / MVP", h1)]
    rows = []
    for uid, us, abuses, mit, test in C.BACKLOG:
        ab = "<br/><br/>".join(f"<b>{aid}</b> {a}" for aid, a in abuses)
        rows.append([uid, us, ab, f"{mit}<br/><font color='#5c6475' face='Courier' size='6.5'>{test}</font>"])
    s.append(table(rows, [1.2 * cm, 4.6 * cm, 5.6 * cm, 6.0 * cm],
                   ["ID", "User Story", "Abuse Story", "Mitigation / test"]))
    s.append(PageBreak())

    s += [Paragraph("2. Architecture technique et frontières de confiance", h1),
          Paragraph("Les cadres <font color='#d62828'><b>rouges en pointillés</b></font> matérialisent les zones de "
                    "confiance : tout flux qui traverse une ligne rouge franchit une frontière (TB1 à TB5) et doit "
                    "être authentifié, chiffré et validé. Les composants en orange contiennent des données sensibles.",
                    body), Spacer(1, 6), architecture_drawing(), Spacer(1, 6)]
    s.append(KeepTogether([Paragraph("Frontières de confiance", h2),
                           table(C.TRUST_BOUNDARIES, [1.4 * cm, 16 * cm], ["ID", "Changement de confiance"])]))
    s.append(PageBreak())
    s += [Paragraph("Flux de données principaux", h2)]
    flows = [
        ("1", "Mobile -> API", "Inscription / connexion ; l'API renvoie un JWT de 15 min.", "TB1"),
        ("2", "Mobile -> API", "Création de pari, invitations, mise (Idempotency-Key) ; reçu HMAC renvoyé.", "TB1, TB2"),
        ("3", "API -> BDD", "Débit du compte parieur, crédit du compte escrow du pari (transaction équilibrée).", "TB3"),
        ("4", "API -> PSP -> API", "Intention de dépôt, paiement chez le PSP, puis webhook signé qui crédite le solde.", "TB4"),
        ("5", "Mobile -> API", "Bookie : proposition du résultat après clôture ; parieurs : confirmation / contestation.", "TB1"),
        ("6", "API -> BDD", "Règlement : escrow -> gagnants, commission bookie, commission plateforme.", "TB3"),
        ("7", "Admin -> API", "Arbitrage d'un litige, validation KYC.", "TB5"),
        ("8", "API -> PSP / KYC", "Retrait (ré-authentification + KYC), vérification d'identité.", "TB4"),
    ]
    s.append(table(flows, [0.8 * cm, 3 * cm, 11.6 * cm, 2 * cm], ["#", "Sens", "Échange", "Frontière"]))
    s += [Paragraph("Localisation des données sensibles", h2),
          table(C.SENSITIVE_DATA, [6.4 * cm, 11 * cm], ["Donnée sensible", "Emplacement / protection"]),
          PageBreak()]

    s += [Paragraph("3. Modélisation STRIDE des menaces", h1)]
    s.append(table(C.STRIDE, [2.4 * cm, 4.2 * cm, 2.6 * cm, 5.6 * cm, 2.6 * cm],
                   ["Catégorie", "Menace identifiée", "Composant visé", "Mitigation proposée", "Statut MVP"]))
    s += [Paragraph("Risques résiduels", h2)] + [Paragraph(f"- {r}", body) for r in C.RESIDUAL_RISKS]
    s.append(PageBreak())

    s += [Paragraph("4. Prototype en vibe coding", h1),
          Paragraph("Le prompt de génération reprend les "
                    "recommandations du cours (secure by design, moindre privilège, aucun secret en dur, tests des "
                    "abuse stories, pipeline DevSecOps) et embarque explicitement le backlog et la matrice STRIDE.",
                    body),
          Paragraph(f"Dépôt public : <link href='{C.REPO_URL}' color='blue'>{C.REPO_URL}</link>", body)]
    for t, p in C.PROMPTS:
        s += [Paragraph(t, h2), Preformatted(p, mono, maxLineLength=118)]
    s += [Paragraph("Résultat des tests", h2), Paragraph(
        "Socle généré : API FastAPI (auth, paris, invitations, mises, validation du résultat par quorum, litiges, "
        "règlement, portefeuille, webhook PSP), grand livre en partie double et journal d'audit chaîné. "
        "<b>24 tests pytest passent</b> (3 parcours nominaux, 21 tests d'abuse stories et d'invariants). La CI GitHub "
        "Actions exécute pytest, bandit (SAST), pip-audit (dépendances) et gitleaks (secrets) à chaque push.", body)]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(1.5 * cm, 1 * cm, "ToutBet' - Atelier 1 DevSecOps")
        canvas.drawRightString(A4[0] - 1.5 * cm, 1 * cm, f"{doc.page}")
        canvas.restoreState()

    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm,
                      bottomMargin=1.6 * cm, title="Atelier 1 - ToutBet'", author="Groupe ToutBet'").build(
        s, onFirstPage=footer, onLaterPages=footer)


if __name__ == "__main__":
    write_markdown()
    write_pdf(DOCS / "rapport_atelier1.pdf")
    print("OK")
