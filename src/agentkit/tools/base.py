"""
Outils : actions que l'agent peut déclencher (réserver, annuler, chercher...).

Un outil expose des « actions », chacune décrite par un modèle pydantic de paramètres :
le schéma JSON sert au contrat du LLM, la validation protège l'exécution.

    class MonOutil(Tool):
        actions = {"creer": ParamsCreer}
        def creer(self, p: ParamsCreer) -> dict: ...

    outil.call("creer", {"x": 1})   # valide les paramètres puis appelle la méthode creer
"""
from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, ValidationError


class ToolError(Exception):
    """Échec d'un outil (paramètres invalides, élément introuvable, créneau pris...)."""


class Tool:
    actions: ClassVar[dict[str, type[BaseModel]]] = {}
    description: ClassVar[str] = ""

    def __init__(self, name: str, config: dict[str, Any] | None = None, pack=None):
        self.name = name
        self.config = config or {}
        self.pack = pack

    def call(self, action: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if action not in self.actions:
            raise ToolError(f"outil {self.name} : action inconnue {action!r} ({', '.join(self.actions)})")
        try:
            params = self.actions[action](**arguments)
        except ValidationError as e:
            raise ToolError(f"outil {self.name}.{action} : paramètres invalides : {e.errors()}") from e
        return getattr(self, action)(params)

    def json_schema(self) -> dict[str, Any]:
        """Schéma des actions, pour le prompt / le contrat du LLM."""
        return {"name": self.name, "description": self.description,
                "actions": {a: m.model_json_schema() for a, m in self.actions.items()}}
