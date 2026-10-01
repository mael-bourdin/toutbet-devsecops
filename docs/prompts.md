# Prompts utilisés

Modèle : **Claude Opus 5.5** (Anthropic), via Claude Code.

## P1 - Génération du socle (Claude Opus 5.5 via Claude Code)

```text
Rôle : tu es un développeur backend senior spécialisé en sécurité applicative (DevSecOps).

Contexte : nous lançons « ToutBet' », une plateforme mobile-first de paris personnalisés entre particuliers. Un Bookie crée un pari (ex. « Matis va-t-il réussir son créneau ? »), fixe éventuellement une mise minimum et sa commission, invite des Parieurs. L'argent est séquestré par la plateforme puis redistribué aux gagnants après validation du résultat, déduction faite des commissions bookie et plateforme.

Objectif : générer le socle technique de l'API backend du MVP en Python 3 / FastAPI / SQLAlchemy 2 (SQLite en dev, compatible PostgreSQL), avec une suite de tests pytest.

Périmètre fonctionnel (User Stories) : [coller le backlog US-01 à US-12]

Exigences de sécurité (Secure by Design, OWASP ASVS niveau 2, OWASP API Top 10) :
1. Chaque Abuse Story du backlog [coller AS-01 à AS-14] DOIT être bloquée et couverte par au moins un test automatisé nommé test_asXX_*.
2. Chaque mitigation de la matrice STRIDE [coller le tableau] marquée « Implémenté » doit apparaître dans le code.
3. Aucun secret en dur : configuration par variables d'environnement, refus de démarrer si un secret manque ou fait moins de 32 caractères ; fournir un .env.example sans valeur réelle.
4. Authentification : Argon2id, JWT à algorithme figé avec iss/aud/exp, durée courte ; messages d'erreur génériques ; limitation de débit sur la connexion.
5. Autorisation au niveau objet sur chaque route (anti-IDOR), principe du moindre privilège, rôle relu en base.
6. Validation stricte des entrées (pydantic, extra=forbid), montants en centimes entiers, jamais de float.
7. Argent : grand livre en partie double append-only, transactions atomiques, clés d'idempotence, invariant « somme des écritures = 0 ».
8. Paiement : le solde n'est crédité que par un webhook PSP signé HMAC, horodaté, anti-rejeu.
9. Non-répudiation : reçu signé HMAC pour chaque mise, journal d'audit chaîné et vérifiable.
10. Disponibilité : limitation de débit des écritures, taille de requête bornée.
11. En-têtes de sécurité HTTP, pas de stacktrace exposée.
12. Dépendances épinglées ; pipeline CI GitHub Actions : tests, SAST (bandit), audit des dépendances (pip-audit), détection de secrets (gitleaks) ; Dependabot.

Contraintes de qualité : code lisible, commenté là où la sécurité l'exige, sans fonctionnalité hors périmètre ; explique les risques résiduels que le MVP ne couvre pas.
Livrables : arborescence complète, README (installation, lancement, tests), et lance les tests jusqu'à ce qu'ils passent tous.
```

## P2 - Revue de sécurité du code généré

```text
Relis le code généré avec un regard d'attaquant : pour chaque ligne de la matrice STRIDE, indique le fichier et la fonction qui implémentent la mitigation, ou signale qu'elle manque. Propose un test qui échouerait si la mitigation était retirée.
```

## P3 - Correction et tests

```text
Exécute la suite pytest, corrige les échecs sans affaiblir les contrôles de sécurité, puis vérifie que bandit et pip-audit ne remontent aucune alerte bloquante.
```
