"""
Signaux : mesures calculées à chaque tour, en parallèle du dialogue (WP5).

Un signal renvoie un score 0..1 ; le pack fixe le seuil de détection (signals[].threshold)
et le seuil de transfert humain (escalation.signal_thresholds). Premier signal : la
frustration envers le système. Baseline : lexique du pack. Modèle entraîné : phase 4.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod

from agentkit.domain.schema import DomainPack, SignalSpec
from agentkit.nlu.text import normalise


class Signal(ABC):
    def __init__(self, spec: SignalSpec):
        self.id = spec.id
        self.threshold = spec.threshold

    @abstractmethod
    def score(self, text: str) -> float: ...

    def detected(self, text: str) -> bool:
        return self.score(text) >= self.threshold


class LexiconSignal(Signal):
    """1.0 dès qu'un motif du lexique correspond, 0.0 sinon (baseline sans apprentissage)."""

    def __init__(self, spec: SignalSpec):
        super().__init__(spec)
        self._motifs = [re.compile(p) for p in spec.patterns]

    def score(self, text: str) -> float:
        t = normalise(text)
        return 1.0 if any(m.search(t) for m in self._motifs) else 0.0


class ModelSignal(Signal):
    """Modèle neuronal entraîné par l'équipe (MLP sur embeddings multilingues)."""

    def __init__(self, spec: SignalSpec, pack: DomainPack):
        super().__init__(spec)
        self.model_path = pack.path(spec.model) if spec.model else None

    def score(self, text: str) -> float:
        raise NotImplementedError("TODO(WP5) : charger le MLP entraîné et renvoyer sa probabilité")


def build_signals(pack: DomainPack) -> list[Signal]:
    return [LexiconSignal(s) if s.kind == "lexicon" else ModelSignal(s, pack) for s in pack.signals]
