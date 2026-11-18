"""Compteurs d'usage du LLM (budget API limité : on compte tout)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Usage:
    logical_calls: int = 0      # appels demandés par le moteur (1 par tour au plus)
    requests: int = 0           # requêtes HTTP réellement envoyées (nouvelles tentatives comprises)
    cache_hits: int = 0
    retries: int = 0            # nouvelles tentatives après une sortie invalide
    invalid_outputs: int = 0    # sorties restées invalides après la nouvelle tentative
    errors: int = 0             # erreurs réseau / HTTP
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0
    per_turn: dict[str, int] = field(default_factory=dict)  # tour -> appels logiques

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def snapshot(self) -> dict:
        d = asdict(self)
        d.pop("per_turn")
        d["total_tokens"] = self.total_tokens
        return d
