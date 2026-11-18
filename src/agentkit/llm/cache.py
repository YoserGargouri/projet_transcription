"""Cache disque des réponses du LLM : une même requête ne coûte qu'une fois."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path


def cle_requete(*parties) -> str:
    texte = json.dumps(parties, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


class ResponseCache:
    """Clé -> réponse JSON, dans un petit fichier SQLite. Seules les sorties VALIDES sont
    mises en cache (une sortie invalide doit pouvoir être redemandée)."""

    def __init__(self, chemin: Path):
        chemin.parent.mkdir(parents=True, exist_ok=True)
        self._verrou = threading.Lock()
        self._db = sqlite3.connect(chemin, check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS cache (cle TEXT PRIMARY KEY, valeur TEXT)")

    def get(self, cle: str):
        with self._verrou:
            ligne = self._db.execute("SELECT valeur FROM cache WHERE cle = ?", (cle,)).fetchone()
        return json.loads(ligne[0]) if ligne else None

    def set(self, cle: str, valeur) -> None:
        with self._verrou:
            self._db.execute("INSERT OR REPLACE INTO cache VALUES (?, ?)", (cle, json.dumps(valeur, ensure_ascii=False)))
            self._db.commit()
