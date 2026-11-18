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

TODO(WP6) : interprétation des dates et heures (aujourd'hui texte libre), proposition de
créneaux libres par l'outil avant la confirmation, annulation / retour en arrière.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from agentkit.domain.schema import DomainPack, SlotSpec, WorkflowSpec
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


def render(template: str, run: WorkflowRun, result: dict | None = None) -> str:
    return template.format(slots=_Acces({k: v for k, v in run.slots.items() if v is not None}),
                           item=_Acces(run.item or {}), result=_Acces(result or run.result or {}))


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
            if err := valider(par_nom[nom], v):
                erreurs[nom] = err
            else:
                run.slots[nom] = str(v).strip()
        return erreurs

    def next_missing(self, run: WorkflowRun) -> SlotSpec | None:
        return next((s for s in self.spec(run).slots if s.required and not run.slots.get(s.name)), None)

    def confirmation_text(self, run: WorkflowRun) -> str | None:
        spec = self.spec(run)
        return render(spec.confirmation, run) if spec.confirmation else None

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
        return resultat, render(spec.success_message, run, resultat) if spec.success_message else ""
