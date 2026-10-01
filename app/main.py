from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.db import init_engine
from app.routers import auth, bets, wallet


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_engine()
    yield


def create_app(with_lifespan: bool = True) -> FastAPI:
    app = FastAPI(title="ToutBet API", version="0.1.0", lifespan=lifespan if with_lifespan else None)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        if int(request.headers.get("content-length") or 0) > 64_000:  # anti-DoS : corps limité
            return JSONResponse({"detail": "Requête trop volumineuse"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        return response

    @app.exception_handler(Exception)
    async def unhandled(_: Request, __: Exception):
        return JSONResponse({"detail": "Erreur interne"}, status_code=500)  # pas de stacktrace exposée

    app.include_router(auth.router)
    app.include_router(bets.router)
    app.include_router(wallet.router)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
