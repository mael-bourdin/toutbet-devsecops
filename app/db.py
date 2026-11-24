import time

from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)


def init_engine(url: str | None = None):
    global _engine
    url = url or get_settings().database_url
    # timeout : un écrivain attend jusqu'à 30 s le verrou au lieu d'échouer en « database is locked »
    kwargs = {"connect_args": {"check_same_thread": False, "timeout": 30}} if url.startswith("sqlite") else {}
    if url == "sqlite://":
        from sqlalchemy.pool import StaticPool

        kwargs["poolclass"] = StaticPool
    _engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(_engine, "connect")
        def _fk_on(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    SessionLocal.configure(bind=_engine)
    from app import models  # noqa: F401  (enregistre les tables)

    # Plusieurs workers créent le schéma en même temps : chacun réessaie jusqu'à ce que toutes les
    # tables existent (create_all ignore celles déjà créées par un autre processus).
    for attempt in range(20):
        try:
            Base.metadata.create_all(_engine)
            break
        except OperationalError:
            if attempt == 19:
                raise
            time.sleep(0.05 * (attempt + 1))
    return _engine


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
