"""Journal d'audit infalsifiable (chaîne de hachage HMAC)."""
import hashlib
import hmac
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AuditLog

GENESIS = "0" * 64


def _digest(prev_hash: str, actor_id: str | None, action: str, payload: str) -> str:
    msg = f"{prev_hash}|{actor_id or ''}|{action}|{payload}".encode()
    return hmac.new(get_settings().audit_hmac_key.encode(), msg, hashlib.sha256).hexdigest()


def audit(db: Session, actor_id: str | None, action: str, **data) -> AuditLog:
    """Ajoute une entrée dans la même transaction que l'action métier."""
    last = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(1)).first()
    prev_hash = last.hash if last else GENESIS
    payload = json.dumps(data, sort_keys=True, default=str)
    entry = AuditLog(actor_id=actor_id, action=action, payload=payload, prev_hash=prev_hash,
                     hash=_digest(prev_hash, actor_id, action, payload))
    db.add(entry)
    db.flush()
    return entry


def verify_chain(db: Session) -> bool:
    prev = GENESIS
    for entry in db.scalars(select(AuditLog).order_by(AuditLog.id)):
        if entry.prev_hash != prev:
            return False
        if not hmac.compare_digest(entry.hash, _digest(prev, entry.actor_id, entry.action, entry.payload)):
            return False
        prev = entry.hash
    return True
