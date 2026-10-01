"""Authentification, contrôle d'accès, signatures et limitation de débit."""
import hashlib
import hmac
import json
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Role, User

_ph = PasswordHasher()  # Argon2id, paramètres OWASP par défaut
_DUMMY_HASH = _ph.hash("dummy-password-for-timing")
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        # Vérification même si l'utilisateur n'existe pas : temps constant (anti-énumération)
        return _ph.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except VerificationError:
        return False


def create_access_token(user: User) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    claims = {
        "sub": user.id,
        "role": user.role.value,
        "iss": s.jwt_issuer,
        "aud": s.jwt_audience,
        "iat": now,
        "exp": now + timedelta(seconds=s.jwt_ttl_seconds),
    }
    return jwt.encode(claims, s.jwt_secret, algorithm="HS256")


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)
) -> User:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentification requise",
                                 headers={"WWW-Authenticate": "Bearer"})
    if creds is None:
        raise unauthorized
    s = get_settings()
    try:
        claims = jwt.decode(creds.credentials, s.jwt_secret, algorithms=["HS256"],  # algo figé : pas de "none"
                            audience=s.jwt_audience, issuer=s.jwt_issuer,
                            options={"require": ["exp", "sub", "iss", "aud"]})
    except jwt.PyJWTError:
        raise unauthorized
    user = db.get(User, claims["sub"])
    if user is None:
        raise unauthorized
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Réservé aux modérateurs")
    return user


def sign(payload: dict) -> str:
    """HMAC-SHA256 d'une représentation canonique (clés triées) -> reçu non répudiable."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hmac.new(get_settings().audit_hmac_key.encode(), canonical.encode(), hashlib.sha256).hexdigest()


def verify_psp_signature(raw_body: bytes, header: str | None) -> None:
    """En-tête 't=<timestamp>,v1=<hmac>' (modèle Stripe). Refuse signature absente, fausse ou expirée."""
    s = get_settings()
    if not header:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Signature manquante")
    try:
        parts = dict(item.split("=", 1) for item in header.split(","))
        ts, sig = int(parts["t"]), parts["v1"]
    except (ValueError, KeyError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Signature mal formée")
    if abs(time.time() - ts) > s.webhook_tolerance_seconds:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Signature expirée")
    expected = hmac.new(s.psp_webhook_secret.encode(), f"{ts}.".encode() + raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Signature invalide")


class RateLimiter:
    """Fenêtre glissante en mémoire (à remplacer par Redis en production multi-instance)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window: float = 60.0) -> None:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > window:
                hits.popleft()
            if len(hits) >= limit:
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Trop de requêtes",
                                    headers={"Retry-After": str(int(window))})
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def rate_limit_writes(request: Request, user: User = Depends(get_current_user)) -> User:
    limiter.check(f"write:{user.id}", get_settings().write_rate_limit)
    return user
