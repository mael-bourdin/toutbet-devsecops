# Architecture et frontières de confiance

Les cadres rouges en pointillés délimitent les zones ; chaque flux qui traverse un cadre franchit une frontière de confiance.

```mermaid
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
```

## Frontières de confiance

| ID | Frontière |
|---|---|
| TB1 | Smartphone de l'utilisateur <-> passerelle API (Internet, appareil non maîtrisé) |
| TB2 | Passerelle/WAF <-> serveur d'application (réseau privé) |
| TB3 | Serveur d'application <-> zone données (BDD, coffre de secrets) |
| TB4 | Plateforme <-> prestataires tiers (PSP de paiement, KYC, notifications push) |
| TB5 | Back-office modérateur <-> API (accès privilégié, VPN + MFA) |

## Données sensibles

| Donnée | Emplacement / protection |
|---|---|
| Secrets (clé JWT, clé HMAC d'audit, secret webhook PSP, clés API PSP/KYC) | Gestionnaire de secrets / KMS, injectés en variables d'environnement ; jamais dans le code ni l'app mobile |
| Soldes utilisateurs et fonds séquestrés | BDD : grand livre ledger_entries (comptes user:*, escrow:*, platform, psp) ; les fonds réels sont chez le PSP |
| Mises, reçus, votes | BDD : tables wagers, result_votes |
| Mots de passe | BDD : hash Argon2id uniquement |
| Journal d'audit | BDD audit_log chaîné + export WORM (prévu) |
| Données d'identité (KYC), IBAN, carte | Chez les prestataires KYC/PSP ; la plateforme ne garde qu'un statut / jeton |
| Jeton de session | Smartphone : Keychain (iOS) / Keystore (Android) |
