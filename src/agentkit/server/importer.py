"""
Import des journaux existants (runtime/logs/<pack>/*.jsonl, déjà anonymisés) dans un espace de
travail : les conversations réelles des essais en ligne de commande (texte et voix) deviennent
visibles dans le tableau de bord, marquées source = « import ».

    python -m agentkit.server import-logs --email vous@exemple.com [--pack imagerie_medicale]

Ce qui n'était pas journalisé reste vide (latence par tour, jetons) : rien n'est inventé.
"""
from __future__ import annotations

import json
from pathlib import Path

from agentkit import config
from agentkit.domain.loader import load_domain
from agentkit.server.db import Database, dumps, new_id
from agentkit.server.recorder import Anonymiser, Recorder, action_type, trace_details


def _lire(chemin: Path) -> list[dict]:
    lignes = []
    for l in chemin.read_text(encoding="utf-8").splitlines():
        try:
            lignes.append(json.loads(l))
        except ValueError:
            continue
    return lignes


def import_logs(db: Database, workspace_id: str, pack_id: str) -> dict:
    pack = load_domain(pack_id)
    agent = db.one("SELECT id, name FROM agents WHERE workspace_id = ? AND template = ? ORDER BY created_at LIMIT 1",
                   (workspace_id, pack_id))
    dossier = config.runtime_dir("logs", pack_id)
    appels = config.runtime_dir("appels")
    rec, faits, ignores = Recorder(db), 0, 0
    for fichier in sorted(dossier.glob("*.jsonl")):
        tours = _lire(fichier)
        if not tours:
            continue
        conv_id = f"imp_{fichier.stem}"
        if db.one("SELECT 1 FROM conversations WHERE id = ? AND workspace_id = ?", (conv_id, workspace_id)):
            ignores += 1
            continue
        voix = (appels / fichier.stem).exists() or any("audio_quality" in (t.get("trace") or {}) for t in tours)
        canal = "voice" if voix else "chat"
        debut, fin = tours[0].get("horodatage"), tours[-1].get("horodatage")
        rec.open_conversation({"id": conv_id, "workspace_id": workspace_id, "agent_id": agent["id"] if agent else None,
                               "agent_name": agent["name"] if agent else pack.name, "channel": canal, "source": "import",
                               "customer_ref": "CUST-" + fichier.stem[:6].upper(), "started_at": debut,
                               "last_activity_at": fin, "status": "ended", "outcome": "unresolved"},
                              pack.persona.greeting)
        anonyme = Anonymiser(pack)
        derniere_intention, deja_transfere = None, False
        for t in tours:
            trace = t.get("trace") or {}
            details = trace_details(trace, anonyme)
            a = trace.get("agent") or {}
            db.insert("turns", {
                "conversation_id": conv_id, "workspace_id": workspace_id, "idx": t.get("tour", 0),
                "created_at": t.get("horodatage"), "user_text": anonyme(t.get("utilisateur") or ""),
                "agent_text": anonyme(t.get("agent") or ""), "intent": t.get("intention"), "channel": canal,
                "llm_used": int(bool(a.get("llm_used"))), "llm_failed": int(bool(trace.get("llm_failure"))),
                "understood": None if "understood" not in a else int(bool(a["understood"])),
                "escalated": int(bool(t.get("escalade"))), "latency_ms": None, "details": dumps(details)})
            # le tour de confirmation (« oui ») n'a pas d'intention : c'est celle de la démarche en cours
            intention = t.get("intention") or derniere_intention
            derniere_intention = intention or derniere_intention
            if trace.get("tool_result") and intention:
                try:
                    handler = pack.intent(intention).handler
                except StopIteration:
                    handler = ""
                wf = handler.split(":", 1)[1] if handler.startswith("workflow:") else None
                spec = next((w for w in pack.workflows if w.id == wf), None)
                appel = spec.on_complete if spec else None
                type_, libelle = action_type(pack, appel.tool if appel else None, appel.action if appel else None, wf)
                rec._insert(workspace_id, agent["id"] if agent else None, conv_id, t.get("tour"), type_, libelle, wf,
                            appel.tool if appel else None, appel.action if appel else None, "succeeded", None,
                            {"workflow": wf, "result": details.get("tool_result"), "imported": True})
            if t.get("escalade") and not deja_transfere:     # les tours suivants répètent l'escalade
                deja_transfere = True
                rec._insert(workspace_id, agent["id"] if agent else None, conv_id, t.get("tour"), "handoff.human",
                            "Human hand-off", None, None, None, "requires_human", None,
                            {"reason": t["escalade"], "imported": True})
        escalade = next((t["escalade"] for t in tours if t.get("escalade")), None)
        db.run("""UPDATE conversations SET turns = ?, llm_calls = ?, escalation_reason = ? WHERE id = ?""",
               (len(tours), sum(int(t.get("appels_llm") or 0) for t in tours), escalade, conv_id))
        db.run("UPDATE actions SET created_at = ?, updated_at = ? WHERE conversation_id = ?", (fin, fin, conv_id))
        rec._outcome(conv_id, workspace_id)
        faits += 1
    return {"imported": faits, "skipped": ignores}
