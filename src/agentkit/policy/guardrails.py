"""
Garde-fous : périmètre de l'agent et scripts de sécurité fixes.

- ScopeGuard : un sujet interdit par le pack (scope.forbidden) déclenche le transfert humain,
  sans jamais passer par le LLM. Les motifs « faibles » ne comptent pas quand l'intention
  détectée figure dans except_if_intents (un symptôme cité en prenant rendez-vous).
- SafetyScripts : questions fixes posées avant l'action finale selon les attributs de
  l'élément choisi. Réponse positive -> humain ; réponse floue -> on repose une fois, puis
  humain (selon le pack). L'agent ne décide jamais seul et le LLM n'interprète pas la réponse.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from agentkit.domain.schema import DomainPack, SafetyScript
from agentkit.nlu.text import normalise


@dataclass
class ScopeViolation:
    rule_id: str
    pattern: str


class ScopeGuard:
    def __init__(self, pack: DomainPack):
        self._regles = [(r.id, [re.compile(p) for p in r.patterns], [re.compile(p) for p in r.weak_patterns],
                         set(r.except_if_intents)) for r in pack.scope.forbidden]
        self._humain = [re.compile(p) for p in pack.scope.human_request_patterns]

    def check(self, text: str, intent: str | None = None) -> ScopeViolation | None:
        t = normalise(text)
        for rid, forts, faibles, sauf in self._regles:
            for m in forts:
                if m.search(t):
                    return ScopeViolation(rid, m.pattern)
            if intent not in sauf:
                for m in faibles:
                    if m.search(t):
                        return ScopeViolation(rid, m.pattern)
        return None

    def wants_human(self, text: str) -> bool:
        t = normalise(text)
        return any(m.search(t) for m in self._humain)


Answer = Literal["yes", "no", "unclear"]


class SafetyScripts:
    def __init__(self, pack: DomainPack):
        self.scripts = pack.safety_scripts
        self._oui = [re.compile(p) for p in pack.answers.positive]
        self._non = [re.compile(p) for p in pack.answers.negative]

    def applicable(self, attributes: dict[str, str]) -> list[SafetyScript]:
        return [s for s in self.scripts
                if all(attributes.get(attr) in valeurs for attr, valeurs in s.applies_if.items())]

    def get(self, script_id: str) -> SafetyScript:
        return next(s for s in self.scripts if s.id == script_id)

    def parse_answer(self, text: str) -> Answer:
        """Oui / non / flou, par règles (jamais par le LLM). Les deux à la fois = flou."""
        t = normalise(text)
        oui = any(m.search(t) for m in self._oui)
        non = any(m.search(t) for m in self._non)
        if oui and not non:
            return "yes"
        if non and not oui:
            return "no"
        return "unclear"
