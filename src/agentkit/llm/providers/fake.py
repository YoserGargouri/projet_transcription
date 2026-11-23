"""
FakeLLM : fournisseur déterministe pour les tests (aucun réseau, aucun coût).

    fake = FakeLLM([{"intent": "louer", ...}, '{"pas": "valide"}'])   # réponses dans l'ordre
    fake = FakeLLM(lambda messages, schema: {...})                       # ou une fonction
    fake.calls  # messages reçus, pour vérifier ce qui a été envoyé au LLM
"""
from __future__ import annotations

import json
from collections.abc import Callable

from agentkit.llm.providers.base import ProviderResponse


class FakeLLM:
    name = "fake"

    def __init__(self, responses: list | Callable, model: str = "fake-1"):
        self.model = model
        self._responses = responses if callable(responses) else list(responses)
        self.calls: list[list[dict]] = []

    def chat(self, messages: list[dict], json_schema: dict) -> ProviderResponse:
        self.calls.append(messages)
        if callable(self._responses):
            r = self._responses(messages, json_schema)
        else:
            if not self._responses:
                raise RuntimeError("FakeLLM : plus de réponse scriptée")
            r = self._responses.pop(0)
        texte = r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)
        entree = sum(len(m.get("content", "")) for m in messages)
        return ProviderResponse(text=texte, prompt_tokens=entree // 4, completion_tokens=len(texte) // 4)
