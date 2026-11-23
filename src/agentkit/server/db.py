"""
Base de la plateforme (SQLite, bibliothèque standard) : comptes, espaces de travail (locataires),
agents, base de connaissances par agent, conversations, tours, actions, demandes de démo.

Isolation des locataires : toute table de données métier porte workspace_id, et chaque requête
de l'API filtre sur l'espace de travail tiré de la session (côté serveur, jamais côté navigateur).
Les textes de conversation sont stockés déjà anonymisés (agentkit.logging.redaction).

Fichier : PLATFORM_DB, sinon runtime/platform/platform.sqlite (hors dépôt Git).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from agentkit import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
    password_hash TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, business_type TEXT NOT NULL DEFAULT '',
    settings TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS members (
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'owner', PRIMARY KEY (workspace_id, user_id));
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL, created_at TEXT NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS password_resets (
    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name TEXT NOT NULL, template TEXT NOT NULL, business_domain TEXT NOT NULL DEFAULT '',
    business_type TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',
    config TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS knowledge_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    entry_id TEXT NOT NULL, category TEXT NOT NULL DEFAULT '', question TEXT NOT NULL,
    answer TEXT NOT NULL, variants TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'manual',
    updated_at TEXT NOT NULL, UNIQUE (agent_id, entry_id));
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    agent_id TEXT, agent_name TEXT NOT NULL DEFAULT '', channel TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'playground', customer_ref TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL, last_activity_at TEXT NOT NULL, ended_at TEXT,
    status TEXT NOT NULL DEFAULT 'active', outcome TEXT NOT NULL DEFAULT 'in_progress',
    escalation_reason TEXT, turns INTEGER NOT NULL DEFAULT 0, llm_calls INTEGER NOT NULL DEFAULT 0,
    prompt_tokens INTEGER NOT NULL DEFAULT 0, completion_tokens INTEGER NOT NULL DEFAULT 0,
    tts_chars INTEGER NOT NULL DEFAULT 0, stt_seconds REAL NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS conv_ws ON conversations (workspace_id, started_at);
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL, idx INTEGER NOT NULL, created_at TEXT NOT NULL,
    user_text TEXT NOT NULL DEFAULT '', agent_text TEXT NOT NULL DEFAULT '', intent TEXT,
    channel TEXT NOT NULL DEFAULT 'chat', llm_used INTEGER NOT NULL DEFAULT 0, llm_failed INTEGER NOT NULL DEFAULT 0,
    understood INTEGER, escalated INTEGER NOT NULL DEFAULT 0, latency_ms REAL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0, completion_tokens INTEGER NOT NULL DEFAULT 0,
    tts_chars INTEGER NOT NULL DEFAULT 0, audio_file TEXT, details TEXT NOT NULL DEFAULT '{}');
CREATE INDEX IF NOT EXISTS turns_conv ON turns (conversation_id, idx);
CREATE TABLE IF NOT EXISTS actions (
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    agent_id TEXT, conversation_id TEXT REFERENCES conversations(id) ON DELETE CASCADE,
    turn_idx INTEGER, type TEXT NOT NULL, label TEXT NOT NULL, workflow TEXT, tool TEXT, tool_action TEXT,
    status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, duration_ms REAL,
    details TEXT NOT NULL DEFAULT '{}');
CREATE INDEX IF NOT EXISTS actions_ws ON actions (workspace_id, created_at);
CREATE TABLE IF NOT EXISTS demo_requests (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, business_name TEXT NOT NULL, email TEXT NOT NULL,
    business_domain TEXT NOT NULL DEFAULT '', message TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
"""


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def dumps(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, default=str)


def loads(v: str | None, defaut=None):
    if not v:
        return {} if defaut is None else defaut
    try:
        return json.loads(v)
    except ValueError:
        return {} if defaut is None else defaut


class Database:
    """Une connexion par thread (FastAPI exécute les routes synchrones dans un pool de threads)."""

    def __init__(self, chemin: str | Path | None = None):
        self.chemin = str(chemin or config.env("PLATFORM_DB") or config.runtime_dir("platform") / "platform.sqlite")
        self._local = threading.local()
        with self.tx() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.chemin, timeout=10)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys = ON")
            c.execute("PRAGMA journal_mode = WAL")
            self._local.conn = c
        return c

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        c = self._conn()
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise

    def one(self, sql: str, params: tuple | dict = ()) -> dict | None:
        r = self._conn().execute(sql, params).fetchone()
        return dict(r) if r else None

    def all(self, sql: str, params: tuple | dict = ()) -> list[dict]:
        return [dict(r) for r in self._conn().execute(sql, params).fetchall()]

    def run(self, sql: str, params: tuple | dict = ()) -> int:
        with self.tx() as c:
            return c.execute(sql, params).rowcount

    def insert(self, table: str, row: dict) -> None:
        cols = ", ".join(row)
        marks = ", ".join(f":{k}" for k in row)
        with self.tx() as c:
            c.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", row)

    def update(self, table: str, where: dict, values: dict) -> int:
        if not values:
            return 0
        sets = ", ".join(f"{k} = :v_{k}" for k in values)
        cond = " AND ".join(f"{k} = :w_{k}" for k in where)
        params = {**{f"v_{k}": v for k, v in values.items()}, **{f"w_{k}": v for k, v in where.items()}}
        with self.tx() as c:
            return c.execute(f"UPDATE {table} SET {sets} WHERE {cond}", params).rowcount
