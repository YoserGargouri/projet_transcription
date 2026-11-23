"""
Routes de l'API (/api). Toutes les routes privées dépendent de `current` : l'espace de travail
(locataire) vient de la session et chaque requête SQL le filtre.
"""
from __future__ import annotations

import csv
import io
import logging
import re
import shutil
import time
from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import AfterValidator, BaseModel, Field, field_validator

from agentkit import config
from agentkit.domain.loader import DomainPackError, load_domain
from agentkit.server import analytics
from agentkit.server.agents import (agent_dir, build_pack, describe_template, effective_settings, list_templates,
                                    seed_knowledge)
from agentkit.server.app import COOKIE, SESSION_DAYS, Ctx, Platform, current, platform
from agentkit.server.db import dumps, loads, new_id, now_iso
from agentkit.server.security import hash_password, new_token, token_hash, verify_password
from agentkit.server.sessions import DEFAULT_TTS_MONTHLY_LIMIT, audio_dir

log = logging.getLogger("agentkit.platform")
router = APIRouter()
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")


def _email(v: str) -> str:
    v = v.strip().lower()
    if len(v) > 254 or not _EMAIL.match(v):
        raise ValueError("invalid email address")
    return v


EmailStr = Annotated[str, AfterValidator(_email)]   # sans dépendance email-validator


# ====================================================================== modèles d'entrée ==========
class Register(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    business_name: str = Field(min_length=1, max_length=120)


class Login(BaseModel):
    email: EmailStr
    password: str = Field(max_length=200)


class Forgot(BaseModel):
    email: EmailStr


class Reset(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=8, max_length=200)


class ProfileUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class Pricing(BaseModel):
    currency: str = Field("USD", max_length=8)
    llm_input_per_million: float | None = Field(None, ge=0)
    llm_output_per_million: float | None = Field(None, ge=0)
    tts_per_thousand_chars: float | None = Field(None, ge=0)


class WorkspaceSettings(BaseModel):
    tts_monthly_char_limit: int | None = Field(None, ge=0, le=10_000_000)
    pricing: Pricing | None = None


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    business_type: str | None = Field(None, max_length=120)
    settings: WorkspaceSettings | None = None


class Channels(BaseModel):
    web_chat: bool = True
    voice: bool = True


class AgentSettings(BaseModel):
    persona_name: str | None = Field(None, max_length=120)
    greeting: str | None = Field(None, max_length=500)
    style: str | None = Field(None, max_length=1500)
    llm_mode: Literal["llm_first", "rules_first"] | None = None
    voice_engine: Literal["elevenlabs", "gtts"] | None = None
    channels: Channels | None = None


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    template: str = Field(pattern=r"^[a-z0-9_]+$")
    business_domain: str = Field("", max_length=120)
    business_type: str = Field("", max_length=120)
    description: str = Field("", max_length=3000)
    settings: AgentSettings | None = None


class AgentUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    business_domain: str | None = Field(None, max_length=120)
    business_type: str | None = Field(None, max_length=120)
    description: str | None = Field(None, max_length=3000)
    settings: AgentSettings | None = None


class KnowledgeIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    answer: str = Field(min_length=1, max_length=3000)
    variants: str = Field("", max_length=3000)
    category: str = Field("", max_length=60)

    @field_validator("question", "answer", "category")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class Message(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class SessionStart(BaseModel):
    agent_id: str = Field(max_length=40)


class DemoRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    business_name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    business_domain: str = Field("", max_length=120)
    message: str = Field("", max_length=4000)


# ====================================================================== utilitaires ==============
def _ouvrir_session(p: Platform, response: Response, request: Request, user_id: str, workspace_id: str) -> None:
    token = new_token()
    p.db.insert("sessions", {"token_hash": token_hash(token), "user_id": user_id, "workspace_id": workspace_id,
                             "created_at": now_iso(), "expires_at": time.time() + SESSION_DAYS * 86400})
    response.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https", path="/")


def _moi(ctx: Ctx) -> dict:
    w = ctx.workspace
    return {"user": ctx.user, "workspace": {"id": w["id"], "name": w["name"], "business_type": w["business_type"],
                                            "settings": _ws_settings(w)}}


def _ws_settings(w: dict) -> dict:
    s = loads(w.get("settings"))
    return {"tts_monthly_char_limit": s.get("tts_monthly_char_limit", DEFAULT_TTS_MONTHLY_LIMIT),
            "pricing": s.get("pricing") or {}}


def _agent(p: Platform, ctx: Ctx, agent_id: str) -> dict:
    a = p.db.one("SELECT * FROM agents WHERE id = ? AND workspace_id = ?", (agent_id, ctx.ws))
    if a is None:
        raise HTTPException(404, "Agent not found")
    return a


def _agent_out(p: Platform, a: dict, detail: bool = False) -> dict:
    try:
        pack = load_domain(a["template"])
    except DomainPackError:
        pack = None
    nb = p.db.one("SELECT COUNT(*) AS n FROM knowledge_entries WHERE agent_id = ? AND workspace_id = ?",
                  (a["id"], a["workspace_id"]))["n"]
    stats = p.db.one("""SELECT COUNT(*) AS conversations, MAX(started_at) AS last_conversation FROM conversations
                        WHERE agent_id = ? AND workspace_id = ?""", (a["id"], a["workspace_id"]))
    out = {k: a[k] for k in ("id", "name", "template", "business_domain", "business_type", "description",
                             "created_at", "updated_at")}
    out.update(knowledge_entries=nb, conversations=stats["conversations"], last_conversation=stats["last_conversation"],
               settings=effective_settings(a, pack) if pack else loads(a["config"]),
               template_available=pack is not None)
    if detail and pack:
        out["template_info"] = describe_template(pack)
    return out


def _plage(debut: str | None, fin: str | None, jours: int = 30) -> tuple[str, str]:
    fin = fin or date.today().isoformat()
    debut = debut or (date.fromisoformat(fin) - timedelta(days=jours - 1)).isoformat()
    if not _DATE.match(debut) or not _DATE.match(fin) or debut > fin:
        raise HTTPException(422, "Invalid date range")
    if (date.fromisoformat(fin) - date.fromisoformat(debut)).days > 366:
        raise HTTPException(422, "Date range limited to one year")
    return debut, fin


def _ip(request: Request) -> str:
    return request.client.host if request.client else "?"


# ====================================================================== authentification =========
@router.post("/auth/register", status_code=201)
def register(body: Register, request: Request, response: Response, p: Platform = Depends(platform)):
    if not p.public_limiter.allow(f"register:{_ip(request)}"):
        raise HTTPException(429, "Too many attempts, try again later")
    email = body.email.lower()
    if p.db.one("SELECT 1 FROM users WHERE email = ?", (email,)):
        raise HTTPException(409, "An account already exists for this email")
    uid, wid, t = new_id("usr_"), new_id("ws_"), now_iso()
    p.db.insert("users", {"id": uid, "email": email, "name": body.name.strip(),
                          "password_hash": hash_password(body.password), "created_at": t})
    p.db.insert("workspaces", {"id": wid, "name": body.business_name.strip(), "business_type": "",
                               "settings": dumps({"tts_monthly_char_limit": DEFAULT_TTS_MONTHLY_LIMIT}), "created_at": t})
    p.db.insert("members", {"workspace_id": wid, "user_id": uid, "role": "owner"})
    _ouvrir_session(p, response, request, uid, wid)
    log.info("compte créé (espace %s)", wid)
    return {"ok": True}


@router.post("/auth/login")
def login(body: Login, request: Request, response: Response, p: Platform = Depends(platform)):
    email = body.email.lower()
    if not p.login_limiter.allow(f"{email}|{_ip(request)}"):
        raise HTTPException(429, "Too many attempts, try again in a few minutes")
    u = p.db.one("SELECT * FROM users WHERE email = ?", (email,))
    if u is None or not verify_password(body.password, u["password_hash"]):
        raise HTTPException(401, "Incorrect email or password")
    m = p.db.one("SELECT workspace_id FROM members WHERE user_id = ? ORDER BY rowid LIMIT 1", (u["id"],))
    if m is None:
        raise HTTPException(403, "No workspace for this account")
    _ouvrir_session(p, response, request, u["id"], m["workspace_id"])
    return {"ok": True}


@router.post("/auth/logout")
def logout(request: Request, response: Response, p: Platform = Depends(platform)):
    if token := request.cookies.get(COOKIE):
        p.db.run("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/auth/me")
def me(ctx: Ctx = Depends(current)):
    return _moi(ctx)


@router.patch("/auth/me")
def update_me(body: ProfileUpdate, ctx: Ctx = Depends(current), p: Platform = Depends(platform)):
    p.db.update("users", {"id": ctx.user["id"]}, {"name": body.name.strip()})
    return {"ok": True}


@router.post("/auth/password")
def change_password(body: PasswordChange, ctx: Ctx = Depends(current), p: Platform = Depends(platform)):
    u = p.db.one("SELECT password_hash FROM users WHERE id = ?", (ctx.user["id"],))
    if not verify_password(body.current_password, u["password_hash"]):
        raise HTTPException(400, "Current password is incorrect")
    p.db.update("users", {"id": ctx.user["id"]}, {"password_hash": hash_password(body.new_password)})
    p.db.run("DELETE FROM sessions WHERE user_id = ? AND token_hash != ?", (ctx.user["id"], ctx.token_hash))
    return {"ok": True}


@router.post("/auth/forgot-password")
def forgot_password(body: Forgot, request: Request, p: Platform = Depends(platform)):
    """Réponse identique que le compte existe ou non. L'envoi d'e-mails n'est pas encore branché :
    avec PLATFORM_EMAIL_MODE=console (développement), le lien est affiché dans la console du serveur."""
    if not p.public_limiter.allow(f"forgot:{_ip(request)}"):
        raise HTTPException(429, "Too many attempts, try again later")
    mode = config.env("PLATFORM_EMAIL_MODE")
    u = p.db.one("SELECT id FROM users WHERE email = ?", (body.email.lower(),))
    if u is not None:
        token = new_token()
        p.db.insert("password_resets", {"token_hash": token_hash(token), "user_id": u["id"],
                                        "expires_at": time.time() + 3600, "used": 0})
        if mode == "console":
            print(f"[dev] lien de réinitialisation : {request.base_url}reset-password?token={token}", flush=True)
    return {"ok": True, "email_delivery": mode == "console"}


@router.post("/auth/reset-password")
def reset_password(body: Reset, p: Platform = Depends(platform)):
    r = p.db.one("SELECT * FROM password_resets WHERE token_hash = ?", (token_hash(body.token),))
    if r is None or r["used"] or r["expires_at"] < time.time():
        raise HTTPException(400, "This reset link is invalid or has expired")
    p.db.update("users", {"id": r["user_id"]}, {"password_hash": hash_password(body.password)})
    p.db.update("password_resets", {"token_hash": r["token_hash"]}, {"used": 1})
    p.db.run("DELETE FROM sessions WHERE user_id = ?", (r["user_id"],))
    return {"ok": True}


# ====================================================================== espace de travail ========
@router.get("/workspace")
def get_workspace(ctx: Ctx = Depends(current)):
    return _moi(ctx)["workspace"]


@router.patch("/workspace")
def update_workspace(body: WorkspaceUpdate, ctx: Ctx = Depends(current), p: Platform = Depends(platform)):
    maj = {}
    if body.name is not None:
        maj["name"] = body.name.strip()
    if body.business_type is not None:
        maj["business_type"] = body.business_type.strip()
    if body.settings is not None:
        s = loads(ctx.workspace["settings"])
        if body.settings.tts_monthly_char_limit is not None:
            s["tts_monthly_char_limit"] = body.settings.tts_monthly_char_limit
        if body.settings.pricing is not None:
            s["pricing"] = body.settings.pricing.model_dump()
        maj["settings"] = dumps(s)
    p.db.update("workspaces", {"id": ctx.ws}, maj)
    return {"ok": True}


@router.get("/integrations")
def integrations(ctx: Ctx = Depends(current), p: Platform = Depends(platform)):
    """État des services : configuré ou non. Jamais la valeur d'une clé."""
    base = config.env("LLM_BASE_URL")
    hote = re.sub(r"^https?://([^/]+).*$", r"\1", base) if base else None
    fournisseur = ("Google Gemini" if hote and "googleapis" in hote else "Groq" if hote and "groq" in hote
                   else "OpenAI-compatible" if hote else None)
    mois = time.strftime("%Y-%m")
    tts = p.db.one("SELECT COALESCE(SUM(tts_chars), 0) AS n FROM conversations WHERE workspace_id = ? "
                   "AND substr(started_at, 1, 7) = ?", (ctx.ws, mois))["n"]
    return {
        "llm": {"configured": bool(base and config.env("LLM_MODEL")), "provider": fournisseur, "host": hote,
                "model": config.env("LLM_MODEL") or None,
                "fallback_models": [m.strip() for m in config.env("LLM_FALLBACK_MODELS").split(",") if m.strip()],
                "timeout_s": config.env("LLM_TIMEOUT_S") or None},
        "elevenlabs": {"configured": bool(config.env("ELEVENLABS_API_KEY")),
                       "model": config.env("ELEVENLABS_MODEL_ID") or None,
                       "voice_configured": bool(config.env("ELEVENLABS_VOICE_ID")),
                       "chars_this_month": tts, "monthly_limit": _ws_settings(ctx.workspace)["tts_monthly_char_limit"]},
        "stt": {"engines": ["whisper (local)", "vosk (local)", "elevenlabs scribe (optional)"]},
        "email": {"configured": config.env("PLATFORM_EMAIL_MODE") == "console", "mode": config.env("PLATFORM_EMAIL_MODE") or None},
        "telephony": {"configured": False},
    }


# ====================================================================== modèles et agents =========
@router.get("/templates")
def templates(ctx: Ctx = Depends(current)):
    return list_templates()


@router.get("/agents")
def agents(ctx: Ctx = Depends(current), p: Platform = Depends(platform)):
    return [_agent_out(p, a) for a in p.db.all("SELECT * FROM agents WHERE workspace_id = ? ORDER BY created_at",
                                                (ctx.ws,))]


@router.post("/agents", status_code=201)
def create_agent(body: AgentCreate, ctx: Ctx = Depends(current), p: Platform = Depends(platform)):
    try:
        pack = load_domain(body.template)
    except DomainPackError:
        raise HTTPException(422, "Unknown template") from None
    if p.db.one("SELECT COUNT(*) AS n FROM agents WHERE workspace_id = ?", (ctx.ws,))["n"] >= 20:
        raise HTTPException(422, "Agent limit reached for this workspace")
    aid, t = new_id("agt_"), now_iso()
    cfg = body.settings.model_dump(exclude_none=True) if body.settings else {}
    p.db.insert("agents", {"id": aid, "workspace_id": ctx.ws, "name": body.name.strip(), "template": body.template,
                           "business_domain": body.business_domain.strip(), "business_type": body.business_type.strip(),
                           "description": body.description.strip(), "config": dumps(cfg), "created_at": t,
                           "updated_at": t})
    seed_knowledge(p.db, ctx.ws, aid, pack)
    return _agent_out(p, _agent(p, ctx, aid), detail=True)


@router.get("/agents/{agent_id}")
def get_agent(agent_id: str, ctx: Ctx = Depends(current), p: Platform = Depends(platform)):
    return _agent_out(p, _agent(p, ctx, agent_id), detail=True)


@router.patch("/agents/{agent_id}")
def update_agent(agent_id: str, body: AgentUpdate, ctx: Ctx = Depends(current), p: Platform = Depends(platform)):
    a = _agent(p, ctx, agent_id)
    maj = {k: v.strip() for k, v in body.model_dump(include={"name", "business_domain", "business_type",
                                                              "description"}).items() if v is not None}
    if body.settings is not None:
        cfg = loads(a["config"])
        for k, v in body.settings.model_dump(exclude_unset=True).items():
            if v is None or v == "":
                cfg.pop(k, None)                       # retour à la valeur du modèle
            else:
                cfg[k] = v
        maj["config"] = dumps(cfg)
    maj["updated_at"] = now_iso()
    p.db.update("agents", {"id": agent_id, "workspace_id": ctx.ws}, maj)
    return _agent_out(p, _agent(p, ctx, agent_id), detail=True)


@router.delete("/agents/{agent_id}")
def delete_agent(agent_id: str, ctx: Ctx = Depends(current), p: Platform = Depends(platform)):
    _agent(p, ctx, agent_id)
    p.sessions.end_for_agent(ctx.ws, agent_id)
    p.db.run("DELETE FROM agents WHERE id = ? AND workspace_id = ?", (agent_id, ctx.ws))
    shutil.rmtree(agent_dir(agent_id), ignore_errors=True)
    return {"ok": True}


# ====================================================================== base de connaissances =====
def _fiche_out(r: dict) -> dict:
    return {k: r[k] for k in ("id", "entry_id", "category", "question", "answer", "variants", "source", "updated_at")}


@router.get("/agents/{agent_id}/knowledge")
def knowledge(agent_id: str, q: str = "", ctx: Ctx = Depends(current), p: Platform = Depends(platform)):
    _agent(p, ctx, agent_id)
    sql, params = "SELECT * FROM knowledge_entries WHERE agent_id = ? AND workspace_id = ?", [agent_id, ctx.ws]
    if q.strip():
        sql += " AND (question LIKE ? OR answer LIKE ? OR variants LIKE ? OR category LIKE ?)"
        params += [f"%{q.strip()}%"] * 4
    return [_fiche_out(r) for r in p.db.all(sql + " ORDER BY entry_id", tuple(params))]


def _prochain_id(p: Platform, agent_id: str) -> str:
    ids = [r["entry_id"] for r in p.db.all("SELECT entry_id FROM knowledge_entries WHERE agent_id = ?", (agent_id,))]
    n = max([int(m.group(1)) for i in ids if (m := re.fullmatch(r"K(\d+)", i))] or [0]) + 1
    return f"K{n:03d}"


@router.post("/agents/{agent_id}/knowledge", status_code=201)
def add_knowledge(agent_id: str, body: KnowledgeIn, ctx: Ctx = Depends(current), p: Platform = Depends(platform)):
    _agent(p, ctx, agent_id)
    if p.db.one("SELECT COUNT(*) AS n FROM knowledge_entries WHERE agent_id = ?", (agent_id,))["n"] >= 500:
        raise HTTPException(422, "Knowledge base limited to 500 entries")
    p.db.insert("knowledge_entries", {"workspace_id": ctx.ws, "agent_id": agent_id, "entry_id": _prochain_id(p, agent_id),
                                      "category": body.category, "question": body.question, "answer": body.answer,
                                      "variants": body.variants.strip(), "source": "manual", "updated_at": now_iso()})
    return _fiche_out(p.db.one("SELECT * FROM knowledge_entries WHERE agent_id = ? ORDER BY id DESC LIMIT 1", (agent_id,)))


@router.patch("/agents/{agent_id}/knowledge/{entry}")
def edit_knowledge(agent_id: str, entry: int, body: KnowledgeIn, ctx: Ctx = Depends(current),
                   p: Platform = Depends(platform)):
    n = p.db.update("knowledge_entries", {"id": entry, "agent_id": agent_id, "workspace_id": ctx.ws},
                    {"question": body.question, "answer": body.answer, "variants": body.variants.strip(),
                     "category": body.category, "updated_at": now_iso()})
    if not n:
        raise HTTPException(404, "Entry not found")
    return _fiche_out(p.db.one("SELECT * FROM knowledge_entries WHERE id = ?", (entry,)))


@router.delete("/agents/{agent_id}/knowledge/{entry}")
def delete_knowledge(agent_id: str, entry: int, ctx: Ctx = Depends(current), p: Platform = Depends(platform)):
    _agent(p, ctx, agent_id)
    if p.db.one("SELECT COUNT(*) AS n FROM knowledge_entries WHERE agent_id = ? AND workspace_id = ?",
                (agent_id, ctx.ws))["n"] <= 1:
        raise HTTPException(422, "An agent needs at least one knowledge entry")
    if not p.db.run("DELETE FROM knowledge_entries WHERE id = ? AND agent_id = ? AND workspace_id = ?",
                    (entry, agent_id, ctx.ws)):
        raise HTTPException(404, "Entry not found")
    return {"ok": True}


@router.post("/agents/{agent_id}/knowledge/reset")
def reset_knowledge(agent_id: str, ctx: Ctx = Depends(current), p: Platform = Depends(platform)):
    a = _agent(p, ctx, agent_id)
    return {"entries": seed_knowledge(p.db, ctx.ws, agent_id, load_domain(a["template"]))}


@router.post("/agents/{agent_id}/knowledge/import")
async def import_knowledge(agent_id: str, file: UploadFile = File(...), ctx: Ctx = Depends(current),
                           p: Platform = Depends(platform)):
    """CSV avec au moins les colonnes question et answer (variants, category facultatives)."""
    _agent(p, ctx, agent_id)
    brut = await file.read(1_000_001)
    if len(brut) > 1_000_000:
        raise HTTPException(413, "File too large (1 MB max)")
    try:
        lignes = list(csv.DictReader(io.StringIO(brut.decode("utf-8-sig"))))
    except (UnicodeDecodeError, csv.Error):
        raise HTTPException(422, "Expected a UTF-8 CSV file") from None
    cles = {k.strip().lower(): k for k in (lignes[0].keys() if lignes else [])}
    q, r = cles.get("question"), cles.get("answer") or cles.get("reponse")
    if not q or not r:
        raise HTTPException(422, "CSV must have 'question' and 'answer' columns")
    ajout, ignorees = 0, 0
    for l in lignes[:500]:
        question, reponse = (l.get(q) or "").strip(), (l.get(r) or "").strip()
        if len(question) < 3 or not reponse:
            ignorees += 1
            continue
        p.db.insert("knowledge_entries", {
            "workspace_id": ctx.ws, "agent_id": agent_id, "entry_id": _prochain_id(p, agent_id),
            "category": (l.get(cles.get("category", ""), "") or "").strip()[:60], "question": question[:500],
            "answer": reponse[:3000], "variants": (l.get(cles.get("variants", ""), "") or "").strip()[:3000],
            "source": "import", "updated_at": now_iso()})
        ajout += 1
    return {"added": ajout, "skipped": ignorees}


# ====================================================================== playground ================
@router.post("/playground/sessions", status_code=201)
def start_session(body: SessionStart, ctx: Ctx = Depends(current), p: Platform = Depends(platform)):
    a = _agent(p, ctx, body.agent_id)
    live, accueil = p.sessions.start(ctx.ws, a)
    return {"conversation_id": live.id, "greeting": accueil, "created_at": now_iso(),
            "llm_enabled": live.orch.gateway is not None, "mode": live.pack.llm.mode,
            "voice_available": live.voice_enabled,
            "state": _etat(live)}


def _etat(live) -> dict:
    """État de la démarche en cours (Playground) : ce que l'agent a compris et ce qu'il lui manque.
    Les valeurs personnelles (slots pii) sont masquées."""
    s, run = live.orch.state, live.orch.state.run
    if run is None:
        return {"intent": s.intent, "workflow": None, "escalated": s.escalation is not None}
    spec = live.pack.workflow(run.workflow_id)
    champs = []
    for slot in spec.slots:
        v = run.slots.get(slot.name)
        if slot.type == "catalogue_item" and run.item:
            v = run.item.get(live.pack.catalogue.label_column) if live.pack.catalogue else v
        champs.append({"name": slot.name, "type": slot.type, "required": slot.required, "filled": bool(v),
                       "value": ("•••" if slot.pii else v) if v else None})
    return {"intent": s.intent, "workflow": run.workflow_id, "workflow_description": spec.description,
            "fields": champs, "awaiting_confirmation": s.awaiting_confirmation,
            "candidates": len(s.candidates), "escalated": s.escalation is not None}


@router.post("/playground/sessions/{conv_id}/messages")
def send_message(conv_id: str, body: Message, ctx: Ctx = Depends(current), p: Platform = Depends(platform)):
    live = p.sessions.get(ctx.ws, conv_id)
    tour = p.sessions.text_turn(live, body.text.strip())
    return {**tour, "state": _etat(live)}


@router.post("/playground/sessions/{conv_id}/voice")
async def send_voice(conv_id: str, audio: UploadFile = File(...), ctx: Ctx = Depends(current),
                     p: Platform = Depends(platform)):
    live = p.sessions.get(ctx.ws, conv_id)
    brut = await audio.read(10_000_001)
    if len(brut) > 10_000_000:
        raise HTTPException(413, "Recording too long")
    if brut[:4] != b"RIFF":
        raise HTTPException(422, "Expected a WAV recording")
    from starlette.concurrency import run_in_threadpool

    tour = await run_in_threadpool(p.sessions.voice_turn, live, brut)
    return {**tour, "state": _etat(live)}


@router.post("/playground/sessions/{conv_id}/greeting-audio")
def greeting_audio(conv_id: str, ctx: Ctx = Depends(current), p: Platform = Depends(platform)):
    live = p.sessions.get(ctx.ws, conv_id)
    return {"audio_url": p.sessions.greeting_audio(live)}


@router.post("/playground/sessions/{conv_id}/end")
def end_session(conv_id: str, ctx: Ctx = Depends(current), p: Platform = Depends(platform)):
    p.sessions.end(ctx.ws, conv_id)
    return {"ok": True}


# ====================================================================== conversations =============
@router.get("/conversations")
def conversations(agent_id: str | None = None, channel: str | None = None, outcome: str | None = None,
                  source: str | None = None, q: str = "", date_from: str | None = Query(None, alias="from"),
                  date_to: str | None = Query(None, alias="to"), page: int = Query(1, ge=1),
                  page_size: int = Query(25, ge=1, le=100), ctx: Ctx = Depends(current),
                  p: Platform = Depends(platform)):
    w, params = ["c.workspace_id = ?"], [ctx.ws]
    for col, v in (("agent_id", agent_id), ("channel", channel), ("outcome", outcome), ("source", source)):
        if v:
            w.append(f"c.{col} = ?")
            params.append(v)
    if date_from or date_to:
        debut, fin = _plage(date_from, date_to, 3650 if not date_from else 30)
        w.append("substr(c.started_at, 1, 10) BETWEEN ? AND ?")
        params += [debut, fin]
    if q.strip():
        w.append("(c.id LIKE ? OR c.customer_ref LIKE ? OR EXISTS (SELECT 1 FROM turns t WHERE t.conversation_id = c.id "
                 "AND (t.user_text LIKE ? OR t.agent_text LIKE ?)))")
        params += [f"%{q.strip()}%"] * 4
    where = " AND ".join(w)
    total = p.db.one(f"SELECT COUNT(*) AS n FROM conversations c WHERE {where}", tuple(params))["n"]
    lignes = p.db.all(f"""
        SELECT c.*, (julianday(c.last_activity_at) - julianday(c.started_at)) * 86400 AS duration_s,
               (SELECT COUNT(*) FROM actions a WHERE a.conversation_id = c.id AND a.status = 'succeeded') AS actions_succeeded,
               (SELECT t.user_text FROM turns t WHERE t.conversation_id = c.id AND t.idx = 1) AS first_message
        FROM conversations c WHERE {where} ORDER BY c.started_at DESC LIMIT ? OFFSET ?""",
                      tuple(params) + (page_size, (page - 1) * page_size))
    return {"total": total, "page": page, "page_size": page_size, "items": lignes}


def _conversation(p: Platform, ctx: Ctx, conv_id: str) -> dict:
    c = p.db.one("""SELECT c.*, (julianday(c.last_activity_at) - julianday(c.started_at)) * 86400 AS duration_s
                    FROM conversations c WHERE c.id = ? AND c.workspace_id = ?""", (conv_id, ctx.ws))
    if c is None:
        raise HTTPException(404, "Conversation not found")
    return c


@router.get("/conversations/{conv_id}")
def conversation(conv_id: str, ctx: Ctx = Depends(current), p: Platform = Depends(platform)):
    c = _conversation(p, ctx, conv_id)
    tours = p.db.all("SELECT * FROM turns WHERE conversation_id = ? AND workspace_id = ? ORDER BY idx, id",
                     (conv_id, ctx.ws))
    for t in tours:
        t["details"] = loads(t["details"])
        if t["audio_file"]:
            t["audio_url"] = f"/api/conversations/{conv_id}/audio/{t['audio_file']}"
    actions = p.db.all("SELECT * FROM actions WHERE conversation_id = ? AND workspace_id = ? ORDER BY created_at",
                       (conv_id, ctx.ws))
    for a in actions:
        a["details"] = loads(a["details"])
    return {**c, "turns_list": tours, "actions": actions}


@router.delete("/conversations/{conv_id}")
def delete_conversation(conv_id: str, ctx: Ctx = Depends(current), p: Platform = Depends(platform)):
    _conversation(p, ctx, conv_id)
    p.sessions.end(ctx.ws, conv_id)
    p.db.run("DELETE FROM conversations WHERE id = ? AND workspace_id = ?", (conv_id, ctx.ws))
    shutil.rmtree(config.runtime_dir("platform", "audio") / conv_id, ignore_errors=True)
    return {"ok": True}


@router.get("/conversations/{conv_id}/audio/{name}")
def conversation_audio(conv_id: str, name: str, ctx: Ctx = Depends(current), p: Platform = Depends(platform)):
    if not re.fullmatch(r"turn_\d{2,3}\.wav", name):
        raise HTTPException(404)
    _conversation(p, ctx, conv_id)
    chemin = audio_dir(conv_id) / name
    if not chemin.exists():
        raise HTTPException(404, "Audio not found")
    return FileResponse(chemin, media_type="audio/wav")


# ====================================================================== actions ===================
@router.get("/actions")
def actions(status: str | None = None, type: str | None = None, agent_id: str | None = None, q: str = "",
            date_from: str | None = Query(None, alias="from"), date_to: str | None = Query(None, alias="to"),
            page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), ctx: Ctx = Depends(current),
            p: Platform = Depends(platform)):
    w, params = ["a.workspace_id = ?"], [ctx.ws]
    if status:                                              # un statut, ou plusieurs séparés par des virgules
        statuts = [s for s in status.split(",") if s in ("succeeded", "pending", "failed", "requires_human")]
        w.append(f"a.status IN ({', '.join('?' * len(statuts)) or 'NULL'})")
        params += statuts
    for col, v in (("type", type), ("agent_id", agent_id)):
        if v:
            w.append(f"a.{col} = ?")
            params.append(v)
    if date_from or date_to:
        debut, fin = _plage(date_from, date_to, 3650 if not date_from else 30)
        w.append("substr(a.created_at, 1, 10) BETWEEN ? AND ?")
        params += [debut, fin]
    if q.strip():
        w.append("(a.id LIKE ? OR a.conversation_id LIKE ? OR a.details LIKE ? OR a.label LIKE ?)")
        params += [f"%{q.strip()}%"] * 4
    where = " AND ".join(w)
    total = p.db.one(f"SELECT COUNT(*) AS n FROM actions a WHERE {where}", tuple(params))["n"]
    lignes = p.db.all(f"""SELECT a.*, c.agent_name, c.channel FROM actions a
                          LEFT JOIN conversations c ON c.id = a.conversation_id
                          WHERE {where} ORDER BY a.created_at DESC LIMIT ? OFFSET ?""",
                      tuple(params) + (page_size, (page - 1) * page_size))
    for a in lignes:
        a["details"] = loads(a["details"])
    types = p.db.all("SELECT DISTINCT type, label FROM actions WHERE workspace_id = ? ORDER BY label", (ctx.ws,))
    return {"total": total, "page": page, "page_size": page_size, "items": lignes, "types": types}


@router.get("/actions/{action_id}")
def action(action_id: str, ctx: Ctx = Depends(current), p: Platform = Depends(platform)):
    a = p.db.one("""SELECT a.*, c.agent_name, c.channel FROM actions a LEFT JOIN conversations c
                    ON c.id = a.conversation_id WHERE a.id = ? AND a.workspace_id = ?""", (action_id, ctx.ws))
    if a is None:
        raise HTTPException(404, "Action not found")
    a["details"] = loads(a["details"])
    return a


# ====================================================================== indicateurs ===============
@router.get("/analytics")
def get_analytics(date_from: str | None = Query(None, alias="from"), date_to: str | None = Query(None, alias="to"),
                  agent_id: str | None = None, ctx: Ctx = Depends(current), p: Platform = Depends(platform)):
    debut, fin = _plage(date_from, date_to)
    return analytics.compute(p.db, ctx.ws, debut, fin, agent_id)


@router.get("/dashboard")
def dashboard(days: int = Query(14, ge=1, le=90), ctx: Ctx = Depends(current), p: Platform = Depends(platform)):
    debut, fin = _plage(None, None, days)
    recentes = p.db.all("""SELECT c.*, (julianday(c.last_activity_at) - julianday(c.started_at)) * 86400 AS duration_s
                           FROM conversations c WHERE workspace_id = ? ORDER BY started_at DESC LIMIT 6""", (ctx.ws,))
    actions_rec = p.db.all("""SELECT a.*, c.agent_name FROM actions a LEFT JOIN conversations c ON c.id = a.conversation_id
                              WHERE a.workspace_id = ? ORDER BY a.created_at DESC LIMIT 6""", (ctx.ws,))
    attention = p.db.all("""SELECT a.*, c.agent_name FROM actions a LEFT JOIN conversations c ON c.id = a.conversation_id
                            WHERE a.workspace_id = ? AND a.status IN ('failed', 'pending', 'requires_human')
                            ORDER BY a.created_at DESC LIMIT 6""", (ctx.ws,))
    for a in actions_rec + attention:
        a["details"] = loads(a["details"])
    agents_ = p.db.all("SELECT id, name, template FROM agents WHERE workspace_id = ? ORDER BY created_at", (ctx.ws,))
    return {"analytics": analytics.compute(p.db, ctx.ws, debut, fin), "recent_conversations": recentes,
            "recent_actions": actions_rec, "attention": attention, "agents": agents_}


# ====================================================================== public ====================
@router.post("/public/demo-requests", status_code=201)
def demo_request(body: DemoRequest, request: Request, p: Platform = Depends(platform)):
    if not p.public_limiter.allow(f"demo:{_ip(request)}"):
        raise HTTPException(429, "Too many requests, try again later")
    p.db.insert("demo_requests", {"id": new_id("dmo_"), "name": body.name.strip(),
                                  "business_name": body.business_name.strip(), "email": body.email.lower(),
                                  "business_domain": body.business_domain.strip(), "message": body.message.strip(),
                                  "created_at": now_iso()})
    return {"ok": True}


@router.get("/health")
def health():
    return {"ok": True}
