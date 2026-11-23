"""
Journaux anonymisés (WP7) : rien d'identifiant n'est écrit en clair.

Masquage, dans cet ordre :
1. valeurs des slots marqués « pii » dans les workflows (nom, téléphone...) -> [NOM], [TELEPHONE] ;
2. motifs génériques : e-mail, téléphone, date, longue suite de chiffres ;
3. motifs propres au pack (logging.extra_patterns) -> [MASQUE].
Les journaux sont écrits en JSON Lines dans runtime/logs/<pack>/<session>.jsonl.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from agentkit import config
from agentkit.domain.schema import DomainPack

GENERIQUES = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[EMAIL]"),
    (re.compile(r"(?<!\w)(?:\+\d{1,3}[\s.-]?)?(?:\d[\s.-]?){8,}\d(?!\w)"), "[TELEPHONE]"),
    (re.compile(r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b"), "[DATE]"),
    (re.compile(r"\b\d{5,}\b"), "[NUMERO]"),
]


class Redactor:
    def __init__(self, pack: DomainPack):
        self.pii_slots = sorted({s.name for w in pack.workflows for s in w.slots if s.pii})
        self.extra = [re.compile(p) for p in pack.logging.extra_patterns]

    def redact(self, texte: str, slots: dict | None = None) -> str:
        if not texte:
            return texte
        for nom in self.pii_slots:
            valeur = (slots or {}).get(nom)
            if valeur and len(str(valeur).strip()) >= 2:
                texte = re.sub(re.escape(str(valeur).strip()), f"[{nom.upper()}]", texte, flags=re.IGNORECASE)
        for motif in self.extra:
            texte = motif.sub("[MASQUE]", texte)
        for motif, remplacement in GENERIQUES:
            texte = motif.sub(remplacement, texte)
        return texte


class ConversationLogger:
    def __init__(self, pack: DomainPack, session_id: str, dossier: Path | None = None):
        self.redactor = Redactor(pack)
        self.chemin = (dossier or config.runtime_dir("logs", pack.id)) / f"{session_id}.jsonl"

    def log_turn(self, enregistrement: dict, slots: dict | None = None) -> None:
        sur = {k: (self.redactor.redact(v, slots) if isinstance(v, str) else v) for k, v in enregistrement.items()}
        sur["horodatage"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        with open(self.chemin, "a", encoding="utf-8") as f:
            f.write(json.dumps(sur, ensure_ascii=False, default=str) + "\n")
