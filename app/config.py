"""Configuration chargée exclusivement depuis l'environnement (aucun secret en dur)."""
import os
from dataclasses import dataclass, field


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value or len(value) < 32:
        raise RuntimeError(f"La variable d'environnement {name} doit être définie (>= 32 caractères)")
    return value


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.environ.get("TOUTBET_DATABASE_URL", "sqlite:///./toutbet.db"))
    jwt_secret: str = field(default_factory=lambda: _required("TOUTBET_JWT_SECRET"))
    audit_hmac_key: str = field(default_factory=lambda: _required("TOUTBET_AUDIT_KEY"))
    psp_webhook_secret: str = field(default_factory=lambda: _required("TOUTBET_PSP_WEBHOOK_SECRET"))
    jwt_ttl_seconds: int = 900  # jetons courts : 15 min
    jwt_issuer: str = "toutbet-api"
    jwt_audience: str = "toutbet-mobile"
    platform_fee_bps: int = 500  # 5 % de commission plateforme
    max_bookie_fee_bps: int = 1000  # commission bookie plafonnée à 10 %
    max_stake_cents: int = 50_000  # 500 € max par pari (limite anti-blanchiment / jeu responsable)
    webhook_tolerance_seconds: int = 300
    login_rate_limit: int = 5  # tentatives / minute / IP+identifiant
    write_rate_limit: int = 30  # requêtes d'écriture / minute / utilisateur
    dispute_quorum_ratio: float = 0.5  # > 50 % des parieurs doivent confirmer
    contest_ratio: float = 1 / 3  # >= 1/3 de contestations -> litige


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    global _settings
    _settings = None
