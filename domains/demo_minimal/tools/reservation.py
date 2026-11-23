"""Outil propre au pack démo (chargé par son chemin via « entrypoint ») : réservations en mémoire."""
from pydantic import BaseModel

from agentkit.tools.base import Tool


class Creer(BaseModel):
    velo: str
    date: str
    nom: str


class ReservationFictive(Tool):
    description = "enregistre une réservation de vélo (en mémoire, pour les tests)"
    actions = {"creer": Creer}

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.reservations = {}

    def creer(self, p: Creer) -> dict:
        numero = f"LOC-{len(self.reservations) + 1:03d}"
        self.reservations[numero] = p.model_dump()
        return {"numero": numero}
