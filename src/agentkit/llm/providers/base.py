"""Interface d'un fournisseur de LLM : une requête de chat, une réponse texte (JSON attendu)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ProviderResponse:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


class Provider(Protocol):
    name: str      # identifiant stable (entre dans la clé du cache)
    model: str

    def chat(self, messages: list[dict], json_schema: dict) -> ProviderResponse:
        """Envoie les messages ; json_schema décrit la sortie attendue."""
        ...
