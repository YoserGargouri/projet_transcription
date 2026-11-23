"""
Moteur de workflows à slots, piloté par le YAML du pack (WP6).

Un workflow = des slots à remplir (avec validation par type), une confirmation, puis un
appel d'outil final (on_complete) dont les arguments sont des modèles de texte :
    « {slots.nom} », « {item.code} », « {result.reference} »

    run = engine.start("booking")
    engine.set_slots(run, {"nom": "Martin"})         # -> erreurs de validation éventuelles
    engine.next_missing(run)                          # prochain slot requis, ou None
    engine.confirmation_text(run)
    result, message = engine.complete(run)            # appelle l'outil, rend success_message

Dates : les slots date / time / datetime sont stockés en ISO (le LLM convertit « demain à
10 h » ; sans LLM, agentkit.nlu.dates analyse les formes courantes) et lus à voix haute dans
les messages (« jeudi 26 novembre à 10 heures »).
Avant le récapitulatif, precheck() demande à l'outil si l'action est possible (créneau libre,
référence existante...) : sinon le slot fautif est vidé et l'outil propose des alternatives.
TODO(WP6) : annulation / retour en arrière.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from agentkit.domain.schema import DomainPack, SlotSpec, WorkflowSpec
from agentkit.nlu import dates
from agentkit.tools.base import ToolError
from agentkit.tools.registry import ToolRegistry


@dataclass
class WorkflowRun:
    workflow_id: str
    slots: dict[str, Any] = field(default_factory=dict)
    item: dict[str, str] | None = None        # élément du catalogue choisi (Item.as_context())
    status: Literal["collecting", "confirming", "done", "failed"] = "collecting"
    result: dict[str, Any] | None = None


class _Acces(dict):
    """Permet {slots.nom} dans str.format ; un champ manquant devient une chaîne vide."""

    def __getattr__(self, k):
        return self.get(k, "")


def render(template: str, run: WorkflowRun, result: dict | None = None, langue: str | None = None) -> str:
    """langue renseignée : texte destiné à l'utilisateur (dates ISO dites en toutes lettres) ;
    None : arguments d'outil (valeurs brutes)."""
    dire = (lambda v: dates.dire(v, langue)) if langue else (lambda v: v)
    return template.format(slots=_Acces({k: dire(v) for k, v in run.slots.items() if v is not None}),
                           item=_Acces(run.item or {}),
                           result=_Acces({k: dire(v) if isinstance(v, str) else v
                                          for k, v in (result or run.result or {}).items()}))


def valider(slot: SlotSpec, valeur: Any) -> str | None:
    """Message d'erreur, ou None si la valeur est acceptable."""
    v = str(valeur).strip()
    if not v:
        return "valeur vide"
    if slot.type == "phone" and len(re.sub(r"\D", "", v)) < 8:
        return "numéro de téléphone trop court"
    if slot.type == "email" and not re.fullmatch(r"[^@\s]+@[^@\s]+\.\w+", v):
        return "adresse e-mail invalide"
    if slot.type == "number" and not re.fullmatch(r"-?\d+([.,]\d+)?", v):
        return "nombre attendu"
    if slot.type == "choice" and slot.choices and v not in slot.choices:
        return f"valeur attendue parmi {slot.choices}"
    if slot.type in ("date", "time", "datetime") and not dates.normaliser(v, slot.type):
        return {"date": "date attendue (AAAA-MM-JJ)", "time": "heure attendue (HH:MM)",
                "datetime": "date et heure attendues (AAAA-MM-JJTHH:MM)"}[slot.type]
    if slot.type == "reference" and not re.fullmatch(r"[\w-]{3,}", v):
        return "référence invalide"
    if slot.pattern and not re.fullmatch(slot.pattern, v):
        return "format invalide"
    return None


class WorkflowEngine:
    def __init__(self, pack: DomainPack, tools: ToolRegistry):
        self.pack = pack
        self.tools = tools

    def spec(self, run: WorkflowRun) -> WorkflowSpec:
        return self.pack.workflow(run.workflow_id)

    def start(self, workflow_id: str) -> WorkflowRun:
        self.pack.workflow(workflow_id)  # erreur claire si le workflow n'existe pas
        return WorkflowRun(workflow_id=workflow_id)

    def item_slot(self, run: WorkflowRun) -> SlotSpec | None:
        return next((s for s in self.spec(run).slots if s.type == "catalogue_item"), None)

    def set_item(self, run: WorkflowRun, item: dict[str, str]) -> None:
        run.item = item
        slot = self.item_slot(run)
        if slot:
            run.slots[slot.name] = item.get("id")

    def set_slots(self, run: WorkflowRun, valeurs: dict[str, Any]) -> dict[str, str]:
        """Remplit les slots (hors catalogue_item, fixé par set_item après revalidation)."""
        erreurs, par_nom = {}, {s.name: s for s in self.spec(run).slots}
        for nom, v in valeurs.items():
            if v is None or nom not in par_nom or par_nom[nom].type == "catalogue_item":
                continue
            spec = par_nom[nom]
            if spec.type in ("date", "time", "datetime"):
                v = dates.normaliser(str(v), spec.type, self.pack.language) or v
            if spec.type == "reference":                       # dictée lettre par lettre : « R D V 1 2 »
                v = re.sub(r"\s+", "", str(v)).upper()
            if err := valider(spec, v):
                erreurs[nom] = err
            else:
                run.slots[nom] = str(v).strip()
        return erreurs

    def missing(self, run: WorkflowRun) -> list[SlotSpec]:
        return [s for s in self.spec(run).slots if s.required and not run.slots.get(s.name)]

    def next_missing(self, run: WorkflowRun) -> SlotSpec | None:
        return next(iter(self.missing(run)), None)

    def confirmation_text(self, run: WorkflowRun) -> str | None:
        spec = self.spec(run)
        return render(spec.confirmation, run, langue=self.pack.language) if spec.confirmation else None

    def precheck(self, run: WorkflowRun) -> dict | None:
        """Demande à l'outil final si l'action est possible, AVANT le récapitulatif.
        None si oui (ou si l'outil ne sait pas vérifier) ; sinon {"slot", "reason", "options"} :
        le slot fautif est vidé pour être redemandé, options = propositions de l'outil (ISO)."""
        spec = self.spec(run)
        if not spec.on_complete:
            return None
        args = {k: render(v, run) for k, v in spec.on_complete.arguments.items()}
        pb = self.tools.check(spec.on_complete.tool, spec.on_complete.action, args)
        if pb is None:
            for arg, valeur in self.tools.canonical(spec.on_complete.tool, spec.on_complete.action, args).items():
                if m := re.search(r"\{slots\.(\w+)\}", spec.on_complete.arguments.get(arg, "")):
                    run.slots[m.group(1)] = valeur
            return None
        modele = spec.on_complete.arguments.get(pb.get("argument") or "", "")
        m = re.search(r"\{slots\.(\w+)\}", modele)
        slot = m.group(1) if m else None
        if slot:
            run.slots.pop(slot, None)
        return {"slot": slot, "reason": pb.get("reason", ""), "options": pb.get("options", [])}

    def complete(self, run: WorkflowRun) -> tuple[dict[str, Any], str]:
        spec = self.spec(run)
        resultat: dict[str, Any] = {}
        if spec.on_complete:
            args = {k: render(v, run) for k, v in spec.on_complete.arguments.items()}
            try:
                resultat = self.tools.call(spec.on_complete.tool, spec.on_complete.action, args)
            except ToolError:
                run.status = "failed"
                raise
        run.result, run.status = resultat, "done"
        return resultat, render(spec.success_message, run, resultat, self.pack.language) if spec.success_message else ""
