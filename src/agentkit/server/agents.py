"""
Agents de la plateforme : un agent = un modèle (pack de domaine existant) + les réglages de
l'entreprise + SA base de connaissances + SON agenda.

Le pack reste la source de vérité du comportement (intentions, démarches, garde-fous, outils) ;
la plateforme ne fait que surcharger ce qu'une entreprise peut régler sans toucher au code :
persona (nom, accueil, style), mode de compréhension (LLM d'abord ou règles d'abord), voix,
et le contenu de la base de connaissances. Chaque agent a ses propres fichiers d'exécution
(runtime/platform/agents/<agent_id>/) : la FAQ d'un locataire ne se mélange jamais à celle d'un autre.
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path

import pandas as pd

from agentkit import config
from agentkit.domain.loader import DomainPackError, load_domain
from agentkit.domain.schema import DomainPack
from agentkit.server.db import Database, loads, now_iso

log = logging.getLogger("agentkit.platform")

# Libellés des actions connues des outils fournis par le moteur (outil intégré « calendar »)
ACTION_TYPES = {
    ("calendar", "book"): ("appointment.created", "Appointment created"),
    ("calendar", "move"): ("appointment.modified", "Appointment modified"),
    ("calendar", "cancel"): ("appointment.cancelled", "Appointment cancelled"),
    ("calendar", "find"): ("appointment.retrieved", "Appointment retrieved"),
    ("calendar", "free_slots"): ("availability.checked", "Availability checked"),
}

AGENT_SETTINGS = ("persona_name", "greeting", "style", "llm_mode", "voice_engine", "channels")


def agent_dir(agent_id: str) -> Path:
    return config.runtime_dir("platform", "agents", agent_id)


def list_templates() -> list[dict]:
    """Packs de domaine disponibles comme modèles d'agent."""
    modeles = []
    for dossier in sorted(config.domains_dir().iterdir()):
        if not (dossier / "domain.yaml").exists():
            continue
        try:
            pack = load_domain(dossier)
        except DomainPackError as e:
            log.warning("modèle ignoré %s : %s", dossier.name, str(e).splitlines()[0])
            continue
        modeles.append(describe_template(pack))
    # le plus complet d'abord (voix, nombre de démarches) : c'est lui que l'assistant de création
    # présélectionne ; un pack de démonstration minimal ne doit pas être le choix par défaut
    return sorted(modeles, key=lambda m: (not m["voice"], -len(m["workflows"]), m["name"]))


def describe_template(pack: DomainPack) -> dict:
    outils = {t.name: t for t in pack.tools}
    demarches = []
    for w in pack.workflows:
        outil = outils.get(w.on_complete.tool) if w.on_complete else None
        genre = (outil.builtin or "custom") if outil else None
        type_, libelle = ACTION_TYPES.get((genre, w.on_complete.action), (None, None)) if w.on_complete else (None, None)
        demarches.append({"id": w.id, "description": w.description, "action_type": type_, "action_label": libelle,
                          "slots": [{"name": s.name, "type": s.type, "pii": s.pii} for s in w.slots]})
    nb_fiches = 0
    if pack.knowledge:
        try:
            nb_fiches = len(pd.read_csv(pack.path(pack.knowledge.file), dtype=str, keep_default_na=False))
        except (OSError, ValueError):
            pass
    return {
        "id": pack.id, "name": pack.name, "description": pack.description.strip(), "language": pack.language,
        "llm_mode": pack.llm.mode, "voice": pack.channels.audio is not None,
        "tts_engine": pack.channels.audio.tts.engine if pack.channels.audio else None,
        "persona": {"name": pack.persona.name, "greeting": pack.persona.greeting, "style": pack.persona.style.strip()},
        "scope": {"description": pack.scope.description, "allowed": pack.scope.allowed,
                  "forbidden": [r.description for r in pack.scope.forbidden]},
        "workflows": demarches, "intents": [{"id": i.id, "description": i.description} for i in pack.intents],
        "tools": [{"name": t.name, "kind": t.builtin or "custom", "description": t.description} for t in pack.tools],
        "knowledge_entries": nb_fiches,
        "catalogue_items": _taille_catalogue(pack),
        "safety_scripts": len(pack.safety_scripts),
    }


def _taille_catalogue(pack: DomainPack) -> int:
    if not pack.catalogue:
        return 0
    try:
        return len(pd.read_csv(pack.path(pack.catalogue.file), dtype=str, keep_default_na=False))
    except (OSError, ValueError):
        return 0


def template_knowledge(pack: DomainPack) -> list[dict]:
    """Fiches du modèle, copiées dans la base de l'agent à sa création."""
    k = pack.knowledge
    if k is None:
        return []
    df = pd.read_csv(pack.path(k.file), dtype=str, keep_default_na=False)
    categorie = next((c for c in ("theme", "category", "categorie") if c in df.columns), None)
    return [{"entry_id": r[k.id_column], "question": r[k.question_column], "answer": r[k.answer_column],
             "variants": r[k.variants_column] if k.variants_column and k.variants_column in df.columns else "",
             "category": r[categorie] if categorie else ""} for _, r in df.iterrows()]


def seed_knowledge(db: Database, workspace_id: str, agent_id: str, pack: DomainPack) -> int:
    fiches = template_knowledge(pack)
    with db.tx() as c:
        c.execute("DELETE FROM knowledge_entries WHERE agent_id = ? AND workspace_id = ?", (agent_id, workspace_id))
        for f in fiches:
            c.execute("""INSERT INTO knowledge_entries (workspace_id, agent_id, entry_id, category, question, answer,
                         variants, source, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'template', ?)""",
                      (workspace_id, agent_id, f["entry_id"], f["category"], f["question"], f["answer"],
                       f["variants"], now_iso()))
    return len(fiches)


def effective_settings(agent: dict, pack: DomainPack) -> dict:
    """Réglages de l'agent, complétés par les valeurs du modèle."""
    cfg = loads(agent.get("config"))
    audio = pack.channels.audio
    return {
        "persona_name": cfg.get("persona_name") or pack.persona.name,
        "greeting": cfg.get("greeting") or pack.persona.greeting,
        "style": cfg.get("style") if cfg.get("style") is not None else pack.persona.style.strip(),
        "llm_mode": cfg.get("llm_mode") or pack.llm.mode,
        "voice_engine": (cfg.get("voice_engine") or audio.tts.engine) if audio else None,
        "channels": {"web_chat": True, "voice": bool(audio), "phone": False,
                     **{k: v for k, v in (cfg.get("channels") or {}).items() if k in ("web_chat", "voice")}},
        "language": pack.language,
    }


def build_pack(db: Database, agent: dict) -> DomainPack:
    """Pack effectif de l'agent : modèle + réglages + FAQ et agenda propres à l'agent."""
    pack = load_domain(agent["template"])
    s = effective_settings(agent, pack)
    dossier = agent_dir(agent["id"])
    maj: dict = {
        "persona": pack.persona.model_copy(update={"name": s["persona_name"], "greeting": s["greeting"],
                                                   "style": s["style"]}),
        "llm": pack.llm.model_copy(update={"mode": s["llm_mode"]}),
    }
    if pack.channels.audio and s["voice_engine"]:
        tts = pack.channels.audio.tts
        repli = ["gtts"] if s["voice_engine"] != "gtts" else []
        maj["channels"] = pack.channels.model_copy(update={"audio": pack.channels.audio.model_copy(
            update={"tts": tts.model_copy(update={"engine": s["voice_engine"], "fallback": repli})})})
    if pack.knowledge:
        k = pack.knowledge
        fichier = dossier / "knowledge.csv"
        lignes = db.all("""SELECT entry_id, category, question, answer, variants FROM knowledge_entries
                           WHERE agent_id = ? AND workspace_id = ? ORDER BY entry_id""",
                        (agent["id"], agent["workspace_id"]))
        colonnes = [k.id_column, k.question_column, k.answer_column, *([k.variants_column] if k.variants_column else []),
                    "theme"]
        with open(fichier, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(colonnes)
            for l in lignes:
                w.writerow([l["entry_id"], l["question"], l["answer"],
                            *([l["variants"]] if k.variants_column else []), l["category"]])
        maj["knowledge"] = k.model_copy(update={"file": str(fichier.resolve())})
    outils = []
    for t in pack.tools:
        if t.builtin == "calendar":       # agenda propre à l'agent (donc au locataire)
            t = t.model_copy(update={"config": {**t.config, "database": str((dossier / f"{t.name}.sqlite").resolve())}})
        outils.append(t)
    maj["tools"] = outils
    return pack.model_copy(update=maj)
