# Matrice STRIDE

| Catégorie | Menace identifiée | Composant visé | Mitigation proposée | Statut MVP |
|---|---|---|---|---|
| Spoofing | Credential stuffing / brute-force sur un compte | API /auth | Argon2id, rate limit 5/min par IP+pseudo, message générique, MFA (prévu) | Implémenté (MFA prévu) |
| Spoofing | Jeton JWT forgé (alg=none, clé faible) ou volé | API, client mobile | Algorithme figé, iss/aud/exp requis, TTL 15 min, secret en KMS, stockage Keychain/Keystore | Implémenté |
| Spoofing | Faux webhook PSP « paiement réussi » | Endpoint /payments/webhook | Signature HMAC + horodatage, comparaison temps constant, allowlist IP du PSP | Implémenté (allowlist prévue) |
| Spoofing | Fraude à l'identité / comptes multiples (Sybil) | Comptes, vote | KYC via prestataire avant retrait, invitations nominatives, détection appareil (prévu) | Partiel |
| Tampering | Modifier une mise après la clôture | API paris, BDD | Mise immuable, heure serveur, contrainte unique, aucune route de modification | Implémenté |
| Tampering | Montant manipulé côté client (négatif, > solde, montant PSP différent) | API, PSP | Validation stricte, contrôle de solde transactionnel, montant webhook = intention | Implémenté |
| Tampering | Double dépense par rejeu / condition de concurrence | Grand livre | Idempotency-Key, transaction ACID, verrou optimiste ; SERIALIZABLE/SELECT FOR UPDATE sur PostgreSQL | Implémenté |
| Tampering | Altération directe des soldes en base | BDD | Grand livre append-only en partie double, solde calculé, compte SQL sans UPDATE/DELETE | Implémenté (droits SQL prévus) |
| Tampering | Interception/modification mobile <-> API (MITM) | Réseau | TLS 1.3, HSTS, certificate pinning dans l'app | HSTS impl., pinning prévu |
| Repudiation | Un perdant nie avoir effectué le pari | Logs / BDD | Reçu HMAC de la mise (signature électronique) + journal non répudiable chaîné | Implémenté |
| Repudiation | Le bookie nie avoir déclaré un résultat | Journal d'audit | Entrée horodatée avec actor_id dans la même transaction que l'action | Implémenté |
| Repudiation | Un administrateur efface/modifie une trace | Journal d'audit | Chaîne HMAC (vérification), export vers stockage WORM externe | Chaîne impl., WORM prévu |
| Information disclosure | IDOR : lecture d'un pari privé et de ses mises | API paris | Contrôle d'accès objet, 404 indiscernable, UUID non séquentiels | Implémenté |
| Information disclosure | Fuite de secrets (clés JWT/HMAC/PSP) dans le dépôt | Dépôt, CI | Variables d'environnement, refus de démarrer sans secret, gitleaks en CI, gestionnaire de secrets | Implémenté |
| Information disclosure | Fuite de détails techniques ou de données bancaires | API, BDD | Erreurs génériques sans stacktrace, aucune donnée carte (PSP), en-têtes no-store | Implémenté |
| Denial of service | Saturation lors d'un événement majeur | API, infra | Rate limiting, CDN/WAF, autoscaling, file d'attente pour le règlement | Rate limit impl., infra prévue |
| Denial of service | Requêtes géantes / épuisement CPU (hash Argon2) | API | Corps limité à 64 Ko, rate limit appliqué avant le hachage | Implémenté |
| Elevation of privilege | Mass assignment pour devenir admin ou changer les frais | API | Schémas extra=forbid, rôle relu en base, frais plateforme fixés serveur | Implémenté |
| Elevation of privilege | Un parieur déclare le résultat / le bookie parie sur son pari | Logique métier | Contrôle par rôle sur l'objet (bookie, parieur, modérateur) | Implémenté |
| Elevation of privilege | Le bookie impose un faux résultat pour débloquer l'escrow | Validation résultat | Quorum des parieurs, litige si >= 1/3 conteste, arbitrage modérateur uniquement | Implémenté |

## Risques résiduels

- Rate limiter en mémoire : à remplacer par Redis derrière plusieurs instances.
- Collusion d'une majorité de parieurs avec le bookie : atténuée par le seuil de contestation (1/3) et la modération, non éliminée ; prévoir preuves (photo/vidéo) et réputation.
- Pas de MFA ni de certificate pinning dans le MVP (application mobile non livrée).
- Intégrations PSP/KYC simulées : à brancher sur un prestataire agréé (ex. Stripe Connect, Onfido).
- Aspects réglementaires (ANJ, LCB-FT) hors du périmètre technique de l'atelier.
