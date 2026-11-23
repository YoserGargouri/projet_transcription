"""
Application web de la plateforme (FastAPI) : API sous /api, application React servie depuis web/dist.

    python -m agentkit.server            # http://127.0.0.1:8000

Sécurité :
- session : jeton aléatoire dans un cookie HttpOnly SameSite=Lax (empreinte seule en base) ;
- CSRF : toute requête qui modifie quelque chose doit porter l'en-tête X-Requested-With (un
  formulaire d'un autre site ne peut pas l'ajouter) ;
- locataires : l'espace de travail vient TOUJOURS de la session, jamais d'un paramètre ;
- aucune clé d'API ne quitte le serveur (l'API dit seulement si un service est configuré).
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from agentkit import config
from agentkit.server.db import Database
from agentkit.server.security import RateLimiter, token_hash
from agentkit.server.sessions import SessionError, SessionManager

log = logging.getLogger("agentkit.platform")

COOKIE = "ak_session"
SESSION_DAYS = 14
WEB_DIST = config.REPO_ROOT / "web" / "dist"


@dataclass
class Ctx:
    user: dict
    workspace: dict
    token_hash: str

    @property
    def ws(self) -> str:
        return self.workspace["id"]


class Platform:
    def __init__(self, db: Database | None = None, gateway_factory=None):
        self.db = db or Database()
        kw = {"gateway_factory": gateway_factory} if gateway_factory else {}
        self.sessions = SessionManager(self.db, **kw)
        # Les conversations en direct ne survivent pas à un redémarrage : celles restées ouvertes sont closes
        for c in self.db.all("SELECT id, workspace_id FROM conversations WHERE status = 'active'"):
            self.sessions.recorder.close_conversation(c["id"], c["workspace_id"])
        self.login_limiter = RateLimiter(limite=8, fenetre_s=300)
        self.public_limiter = RateLimiter(limite=5, fenetre_s=600)


def platform(request: Request) -> Platform:
    return request.app.state.platform


def current(request: Request, p: Platform = Depends(platform)) -> Ctx:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "Not signed in")
    h = token_hash(token)
    s = p.db.one("SELECT * FROM sessions WHERE token_hash = ?", (h,))
    if s is None or s["expires_at"] < time.time():
        raise HTTPException(401, "Session expired")
    user = p.db.one("SELECT id, email, name, created_at FROM users WHERE id = ?", (s["user_id"],))
    ws = p.db.one("""SELECT w.* FROM workspaces w JOIN members m ON m.workspace_id = w.id
                     WHERE w.id = ? AND m.user_id = ?""", (s["workspace_id"], s["user_id"]))
    if user is None or ws is None:
        raise HTTPException(401, "Session invalid")
    return Ctx(user=user, workspace=ws, token_hash=h)


def create_app(db: Database | None = None, gateway_factory=None, serve_web: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        app.state.platform.sessions.close_all()      # conversations ouvertes : marquées terminées

    app = FastAPI(title="Agent platform API", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json",
                  redoc_url=None)
    app.state.platform = Platform(db, gateway_factory)

    @app.middleware("http")
    async def csrf_et_entetes(request: Request, call_next):
        if (request.url.path.startswith("/api/") and request.method in ("POST", "PUT", "PATCH", "DELETE")
                and request.headers.get("x-requested-with") != "fetch"):
            return JSONResponse({"detail": "Missing X-Requested-With header"}, status_code=403)
        reponse = await call_next(request)
        reponse.headers.setdefault("X-Content-Type-Options", "nosniff")
        reponse.headers.setdefault("Referrer-Policy", "same-origin")
        if request.url.path.startswith("/api/"):
            reponse.headers.setdefault("Cache-Control", "no-store")
        return reponse

    @app.exception_handler(SessionError)
    async def erreur_session(request: Request, e: SessionError):
        return JSONResponse({"detail": str(e)}, status_code=e.status)

    from agentkit.server.api import router

    app.include_router(router, prefix="/api")

    if serve_web and WEB_DIST.exists():
        index = WEB_DIST / "index.html"

        @app.get("/{chemin:path}", include_in_schema=False)
        async def spa(chemin: str):
            if chemin.startswith("api/"):
                raise HTTPException(404)
            fichier = (WEB_DIST / chemin).resolve()
            if chemin and fichier.is_file() and WEB_DIST.resolve() in fichier.parents:
                return FileResponse(fichier)
            return FileResponse(index)            # routes de l'application React

    return app


def web_dist_path() -> Path:
    return WEB_DIST
