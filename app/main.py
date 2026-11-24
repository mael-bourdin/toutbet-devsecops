from contextlib import asynccontextmanager

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import init_engine
from app.routers import auth, bets, wallet


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_engine()
    yield


def create_app(with_lifespan: bool = True) -> FastAPI:
    docs = get_settings().expose_docs  # Swagger / ReDoc / OpenAPI masqués hors développement
    app = FastAPI(title="ToutBet API", version="0.1.0", lifespan=lifespan if with_lifespan else None,
                  docs_url="/docs" if docs else None, redoc_url="/redoc" if docs else None,
                  openapi_url="/openapi.json" if docs else None)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        if int(request.headers.get("content-length") or 0) > 64_000:  # anti-DoS : corps limité
            return JSONResponse({"detail": "Requête trop volumineuse"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        response.headers["Cache-Control"] = "no-store"
        if request.url.path != "/docs":  # Swagger UI charge ses scripts depuis un CDN
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, exc: RequestValidationError):
        # Réponse épurée : ni la valeur reçue (mots de passe renvoyés en clair, NaN/Infinity qui faisaient
        # planter la sérialisation en 500), ni les motifs de validation, ni les types d'erreur Pydantic.
        fields = sorted({".".join(str(p) for p in e.get("loc", ())[1:]) or "body" for e in exc.errors()})
        return JSONResponse({"detail": "Requête invalide", "fields": fields}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        # trace complète côté serveur uniquement, réponse générique côté client
        logging.getLogger("toutbet").error("Erreur non gérée sur %s %s", request.method, request.url.path,
                                           exc_info=exc)
        return JSONResponse({"detail": "Erreur interne"}, status_code=500)

    def openapi_schema():
        """Documente le format réel des erreurs 422 (sinon le contrat OpenAPI annonce le format Pydantic)."""
        if app.openapi_schema is None:
            from fastapi.openapi.utils import get_openapi
            schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
            schema["components"]["schemas"]["HTTPValidationError"] = {
                "title": "HTTPValidationError", "type": "object",
                "properties": {"detail": {"type": "string"}, "fields": {"type": "array", "items": {"type": "string"}}},
            }
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = openapi_schema
    app.include_router(auth.router)
    app.include_router(bets.router)
    app.include_router(wallet.router)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
