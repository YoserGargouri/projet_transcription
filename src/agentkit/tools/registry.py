"""
Registre des outils d'un pack.

- builtin   : outil fourni et testé par le moteur, seulement CONFIGURÉ par le pack
              (voie normale, et la seule qu'un générateur de packs devrait utiliser) ;
- entrypoint: outil propre au pack, « tools/<fichier>.py:<Classe> », chargé par son chemin.
              Liste blanche : seuls les fichiers déclarés dans domain.yaml et situés DANS le
              dossier du pack sont chargés (le pack n'est pas un paquet Python importable).
"""
from __future__ import annotations

import importlib
import importlib.util
from typing import Any

from agentkit.domain.schema import DomainPack
from agentkit.tools.base import Tool, ToolError

BUILTINS = {"calendar": "agentkit.tools.builtin.calendar:CalendarTool"}


def _importer(chemin: str):
    module, classe = chemin.split(":")
    return getattr(importlib.import_module(module), classe)


def _charger_depuis_pack(pack: DomainPack, entrypoint: str):
    fichier, classe = entrypoint.split(":")
    chemin = (pack.root / fichier).resolve()
    if pack.root not in chemin.parents:
        raise ToolError(f"outil hors du pack refusé : {entrypoint}")
    nom_module = f"agentkit_pack_{pack.id}_{chemin.stem}"
    spec = importlib.util.spec_from_file_location(nom_module, chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, classe)


class ToolRegistry:
    def __init__(self, tools: dict[str, Tool] | None = None):
        self.tools = tools or {}

    @classmethod
    def from_pack(cls, pack: DomainPack) -> ToolRegistry:
        outils = {}
        for t in pack.tools:
            if t.builtin:
                if t.builtin not in BUILTINS:
                    raise ToolError(f"outil intégré inconnu : {t.builtin} (disponibles : {', '.join(BUILTINS)})")
                classe = _importer(BUILTINS[t.builtin])
            else:
                classe = _charger_depuis_pack(pack, t.entrypoint)
            if not (isinstance(classe, type) and issubclass(classe, Tool)):
                raise ToolError(f"{t.name} : la classe doit hériter de agentkit.tools.base.Tool")
            outils[t.name] = classe(t.name, t.config, pack)
        return cls(outils)

    def get(self, name: str) -> Tool:
        if name not in self.tools:
            raise ToolError(f"outil inconnu : {name}")
        return self.tools[name]

    def call(self, name: str, action: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.get(name).call(action, arguments)

    def names(self) -> list[str]:
        return list(self.tools)
