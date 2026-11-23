"""
Routeur d'intentions (WP3) : rapide, sans LLM, piloté par les motifs du pack.

    router = RuleRouter(pack)
    router.route("vous êtes ouverts le samedi ?")  ->  RouteResult(intent="info_generale", rule=...)

Les intentions sont testées par priorité décroissante (puis dans l'ordre du YAML) ; la
première dont un motif correspond l'emporte ; sinon l'intention « default » du pack.
L'interface IntentRouter permettra d'ajouter un routeur appris (embeddings) sans toucher
à l'orchestrateur. TODO(WP3) : évaluation sur le jeu de test, routeur appris en option.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

from agentkit.domain.schema import DomainPack
from agentkit.nlu.text import normalise


@dataclass
class RouteResult:
    intent: str
    rule: str = ""            # motif qui a décidé ("" = intention par défaut)
    matched: bool = False     # une règle a-t-elle vraiment reconnu quelque chose ?


class IntentRouter(ABC):
    @abstractmethod
    def route(self, text: str) -> RouteResult: ...


class RuleRouter(IntentRouter):
    def __init__(self, pack: DomainPack):
        self.default = pack.default_intent.id
        ordre = sorted(enumerate(pack.intents), key=lambda x: (-x[1].priority, x[0]))
        self._regles = [(i.id, [re.compile(p) for p in i.patterns]) for _, i in ordre]

    def route(self, text: str) -> RouteResult:
        t = normalise(text)
        for intent, motifs in self._regles:
            for m in motifs:
                if m.search(t):
                    return RouteResult(intent=intent, rule=m.pattern, matched=True)
        return RouteResult(intent=self.default)
