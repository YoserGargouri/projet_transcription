"""
Agenda simulé générique (SQLite), configuré par le pack — aucun code métier.

Configuration (tools[].config dans domain.yaml) :
    resources          liste fixe de ressources réservables, ou
    resource_attribute attribut du catalogue dont chaque valeur est une ressource
    duration_field     colonne du catalogue donnant la durée (min) d'un élément
    default_duration_min, slot_step_min, horizon_days, reference_prefix
    opening_hours      {mon: ["08:00-12:00", "14:00-18:00"], ..., sun: []}

Actions : free_slots, book, find, cancel, move (paramètres validés par pydantic).
TODO(WP6) : fuseaux horaires, jours fériés, plusieurs machines par ressource.
"""
from __future__ import annotations

import json
import random
import sqlite3
import string
from datetime import datetime, timedelta
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

from agentkit import config
from agentkit.tools.base import Tool, ToolError

JOURS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class CalendarConfig(BaseModel):
    resources: list[str] | None = None
    resource_attribute: str | None = None
    duration_field: str | None = None
    default_duration_min: int = 30
    slot_step_min: int = 15
    horizon_days: int = 30
    reference_prefix: str = "R"
    opening_hours: dict[Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"], list[str]] = Field(
        default_factory=lambda: {j: ["09:00-17:00"] for j in JOURS[:5]})
    database: str | None = None   # chemin SQLite ; défaut : runtime/calendars/<pack>_<outil>.sqlite


class FreeSlots(BaseModel):
    resource: str
    duration_min: int | None = None
    item_id: str | None = None
    after: datetime | None = None
    limit: int = 3


class Book(BaseModel):
    resource: str
    start: datetime
    duration_min: int | None = None
    item_id: str = ""
    contact: str = ""


class Ref(BaseModel):
    reference: str


class Move(BaseModel):
    reference: str
    new_start: datetime


class CalendarTool(Tool):
    description = "agenda : créneaux libres, réservation, recherche, annulation, déplacement"
    actions = {"free_slots": FreeSlots, "book": Book, "find": Ref, "cancel": Ref, "move": Move}

    def __init__(self, name, cfg=None, pack=None):
        super().__init__(name, cfg, pack)
        self.cfg = CalendarConfig(**(cfg or {}))
        self._durees: dict[str, int] = {}
        ressources = set(self.cfg.resources or [])
        if pack is not None and pack.catalogue is not None and (self.cfg.resource_attribute or self.cfg.duration_field):
            cat = pd.read_csv(pack.path(pack.catalogue.file), dtype=str, keep_default_na=False)
            if self.cfg.resource_attribute:
                col = next(a.column for a in pack.catalogue.attributes if a.name == self.cfg.resource_attribute)
                ressources |= set(cat[col])
            if self.cfg.duration_field:
                self._durees = {i: int(float(d)) for i, d in zip(cat[pack.catalogue.id_column], cat[self.cfg.duration_field]) if d}
        self.resources = ressources
        chemin = self.cfg.database or config.runtime_dir("calendars") / f"{getattr(pack, 'id', 'local')}_{name}.sqlite"
        self.db = sqlite3.connect(chemin, check_same_thread=False)
        self.db.execute("""CREATE TABLE IF NOT EXISTS bookings (reference TEXT PRIMARY KEY, resource TEXT,
                           start TEXT, end TEXT, item_id TEXT, contact TEXT, status TEXT)""")

    # ------------------------------------------------------------------ utilitaires -------
    def _duree(self, duree: int | None, item_id: str | None) -> int:
        return duree or self._durees.get(item_id or "", self.cfg.default_duration_min)

    def _verifier_ressource(self, r: str):
        if self.resources and r not in self.resources:
            raise ToolError(f"ressource inconnue : {r}")

    def _dans_horaires(self, debut: datetime, fin: datetime) -> bool:
        for plage in self.cfg.opening_hours.get(JOURS[debut.weekday()], []):
            h1, h2 = plage.split("-")
            o = debut.replace(hour=int(h1[:2]), minute=int(h1[3:]), second=0, microsecond=0)
            f = debut.replace(hour=int(h2[:2]), minute=int(h2[3:]), second=0, microsecond=0)
            if o <= debut and fin <= f:
                return True
        return False

    def _libre(self, ressource: str, debut: datetime, fin: datetime, sauf: str = "") -> bool:
        n = self.db.execute("""SELECT COUNT(*) FROM bookings WHERE resource = ? AND status = 'booked'
                               AND reference != ? AND start < ? AND end > ?""",
                            (ressource, sauf, fin.isoformat(), debut.isoformat())).fetchone()[0]
        return n == 0

    def _ligne(self, reference: str) -> dict:
        r = self.db.execute("SELECT * FROM bookings WHERE reference = ?", (reference.strip().upper(),)).fetchone()
        if r is None:
            raise ToolError(f"référence introuvable : {reference}")
        cols = ["reference", "resource", "start", "end", "item_id", "contact", "status"]
        return dict(zip(cols, r))

    # ------------------------------------------------------------------ actions -----------
    def free_slots(self, p: FreeSlots) -> dict:
        self._verifier_ressource(p.resource)
        duree = timedelta(minutes=self._duree(p.duration_min, p.item_id))
        pas = timedelta(minutes=self.cfg.slot_step_min)
        t = (p.after or datetime.now()).replace(second=0, microsecond=0)
        t += timedelta(minutes=-t.minute % self.cfg.slot_step_min)
        fin_horizon, libres = t + timedelta(days=self.cfg.horizon_days), []
        while t < fin_horizon and len(libres) < p.limit:
            if self._dans_horaires(t, t + duree) and self._libre(p.resource, t, t + duree):
                libres.append(t.isoformat(timespec="minutes"))
            t += pas
        return {"resource": p.resource, "slots": libres}

    def book(self, p: Book) -> dict:
        self._verifier_ressource(p.resource)
        fin = p.start + timedelta(minutes=self._duree(p.duration_min, p.item_id))
        if not self._dans_horaires(p.start, fin):
            raise ToolError("créneau en dehors des horaires d'ouverture")
        if not self._libre(p.resource, p.start, fin):
            raise ToolError("créneau déjà pris")
        ref = f"{self.cfg.reference_prefix}-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        self.db.execute("INSERT INTO bookings VALUES (?, ?, ?, ?, ?, ?, 'booked')",
                        (ref, p.resource, p.start.isoformat(), fin.isoformat(), p.item_id, json.dumps(p.contact)))
        self.db.commit()
        return {"reference": ref, "resource": p.resource, "start": p.start.isoformat(timespec="minutes"),
                "end": fin.isoformat(timespec="minutes")}

    def find(self, p: Ref) -> dict:
        r = self._ligne(p.reference)
        r["contact"] = json.loads(r["contact"])
        return r

    def cancel(self, p: Ref) -> dict:
        r = self._ligne(p.reference)
        self.db.execute("UPDATE bookings SET status = 'cancelled' WHERE reference = ?", (r["reference"],))
        self.db.commit()
        return {"reference": r["reference"], "status": "cancelled"}

    def move(self, p: Move) -> dict:
        r = self._ligne(p.reference)
        if r["status"] != "booked":
            raise ToolError("rendez-vous annulé : impossible de le déplacer")
        duree = datetime.fromisoformat(r["end"]) - datetime.fromisoformat(r["start"])
        fin = p.new_start + duree
        if not self._dans_horaires(p.new_start, fin) or not self._libre(r["resource"], p.new_start, fin, r["reference"]):
            raise ToolError("nouveau créneau indisponible")
        self.db.execute("UPDATE bookings SET start = ?, end = ? WHERE reference = ?",
                        (p.new_start.isoformat(), fin.isoformat(), r["reference"]))
        self.db.commit()
        return {"reference": r["reference"], "start": p.new_start.isoformat(timespec="minutes"),
                "end": fin.isoformat(timespec="minutes")}
