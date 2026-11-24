"""IAST « maison » : l'application réelle, instrumentée de l'intérieur pendant les tests dynamiques.

    uvicorn security.iast.instrumented_app:app --port 8000 --workers 4

Capteurs (écrits en JSON Lines dans reports/iast/events.jsonl) :
  - taint SQL : toute valeur reçue du client (corps JSON, chemin, query) retrouvée telle quelle dans le
    TEXTE d'une requête SQL (et non dans ses paramètres liés) => injection SQL possible ;
  - exceptions non gérées : type, message et pile d'appels côté serveur, avec la requête qui l'a causée ;
  - fuite dans la réponse : marqueurs internes (Traceback, sqlalchemy, chemins...) dans un corps renvoyé ;
  - volumétrie : nombre de requêtes SQL et durée par appel HTTP (détection de N+1 / requêtes lentes).
"""
import contextvars
import json
import os
import time
import traceback
from pathlib import Path

from fastapi import Request
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.main import create_app

LOG = Path(os.environ.get("IAST_LOG", "reports/iast/events.jsonl"))
LOG.parent.mkdir(parents=True, exist_ok=True)
LEAKS = ("Traceback", "sqlalchemy", "sqlite", "File \"", "/Users/", "site-packages", "IntegrityError")

_ctx: contextvars.ContextVar[dict | None] = contextvars.ContextVar("iast", default=None)


def emit(kind: str, **data) -> None:
    with LOG.open("a") as f:
        f.write(json.dumps({"t": time.time(), "pid": os.getpid(), "kind": kind, **data}, default=str) + "\n")


def _tainted_values(obj) -> list[str]:
    if isinstance(obj, dict):
        return [v for x in obj.values() for v in _tainted_values(x)]
    if isinstance(obj, list):
        return [v for x in obj for v in _tainted_values(x)]
    return [str(obj)] if isinstance(obj, str) and len(obj) >= 4 else []


@event.listens_for(Engine, "before_cursor_execute")
def _sql_sink(conn, cursor, statement, parameters, context, executemany):
    ctx = _ctx.get()
    if ctx is None:
        return
    ctx["sql"] += 1
    for value in ctx["taint"]:
        if value in statement:  # la donnée client est concaténée dans le SQL au lieu d'être liée
            emit("sql_taint", path=ctx["path"], value=value, statement=statement[:300])


app = create_app()


@app.middleware("http")
async def iast_sensor(request: Request, call_next):
    raw = await request.body()
    taint = [p for p in request.url.path.split("/") if len(p) >= 4] + list(request.query_params.values())
    try:
        taint += _tainted_values(json.loads(raw)) if raw else []
    except ValueError:
        pass
    # valeurs légitimes qui apparaissent normalement dans le SQL (noms de tables, routes)
    taint = [t for t in taint if t not in {"bets", "wagers", "wallet", "auth", "deposits", "withdrawals",
                                           "invitations", "result", "votes", "resolve", "payments", "webhook",
                                           "health", "login", "register", "openapi.json"}]
    ctx = {"path": request.url.path, "taint": taint, "sql": 0}
    token = _ctx.set(ctx)
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:  # pragma: no cover - capteur
        emit("exception", method=request.method, path=request.url.path, type=type(exc).__name__,
             message=str(exc)[:500], stack=traceback.format_exc()[-3000:])
        raise
    finally:
        _ctx.reset(token)
    body = b""
    async for chunk in response.body_iterator:
        body += chunk
    text = body.decode(errors="replace")
    found = [k for k in LEAKS if k in text]
    if found:
        emit("response_leak", path=request.url.path, status=response.status_code, markers=found, body=text[:300])
    if response.status_code >= 500:
        emit("server_error", method=request.method, path=request.url.path, status=response.status_code,
             body=text[:300])
    emit("request", method=request.method, path=request.url.path, status=response.status_code, sql=ctx["sql"],
         ms=round((time.perf_counter() - start) * 1000, 1))
    from starlette.responses import Response
    return Response(content=body, status_code=response.status_code, headers=dict(response.headers),
                    media_type=response.media_type)


_original_handler = app.exception_handlers.get(Exception)


async def _log_unhandled(request: Request, exc: Exception):
    emit("exception", method=request.method, path=request.url.path, type=type(exc).__name__,
         message=str(exc)[:500], stack="".join(traceback.format_exception(exc))[-3000:])
    return await _original_handler(request, exc)


app.exception_handlers[Exception] = _log_unhandled
