"""
Enregistrement des conversations de la plateforme : un tour de l'orchestrateur -> une ligne
« turns » (textes anonymisés, trace réduite), des lignes « actions » et les cumuls de la conversation.

Actions suivies (uniquement ce que l'agent a réellement fait) :
- action finale d'une démarche (trace « action » de l'orchestrateur) : succeeded / failed ;
- récapitulatif soumis à la personne : pending, jusqu'à sa confirmation ;
- transfert vers un humain : requires_human (et une action en attente passe aussi à requires_human).
Le contenu des traces est filtré : ni texte libre de l'utilisateur, ni valeur de slot personnelle.
"""
from __future__ import annotations

from typing import Any

from agentkit.domain.schema import DomainPack
from agentkit.logging.redaction import Redactor
from agentkit.orchestrator import TurnResult
from agentkit.server.agents import ACTION_TYPES
from agentkit.server.db import Database, dumps, loads, new_id, now_iso

OUTCOMES = ("action_completed", "information_provided", "escalated", "in_progress", "unresolved")


class Anonymiser:
    """Redactor du pack + mémoire des valeurs personnelles vues pendant la conversation (un nom
    donné au tour 3 est aussi masqué dans le récapitulatif du tour 5, même après la démarche)."""

    def __init__(self, pack: DomainPack):
        self.redactor = Redactor(pack)
        self.pii_slots = set(self.redactor.pii_slots)
        self.valeurs: list[tuple[str, str]] = []

    def observe(self, slots: dict | None) -> None:
        for nom, v in (slots or {}).items():
            if nom in self.pii_slots and v and (nom, str(v)) not in self.valeurs:
                self.valeurs.append((nom, str(v)))

    def __call__(self, texte: str) -> str:
        if not texte:
            return texte
        for nom, valeur in self.valeurs:
            texte = self.redactor.redact(texte, {nom: valeur})
        return self.redactor.redact(texte, {})

    def deep(self, v: Any) -> Any:
        if isinstance(v, str):
            return self(v)
        if isinstance(v, dict):
            return {k: self.deep(x) for k, x in v.items()}
        if isinstance(v, list):
            return [self.deep(x) for x in v]
        return v


def trace_details(trace: dict, anonymise: Anonymiser) -> dict:
    """Trace réduite et sûre à afficher : décisions, sources, vérifications, action."""
    a = trace.get("agent") or {}
    d: dict[str, Any] = {"mode": trace.get("mode")}
    if a:
        d["llm"] = {k: a.get(k) for k in ("llm_used", "fallback", "intent", "understood", "sources", "asks_for")
                    if a.get(k) not in (None, "", [])}
    if trace.get("llm_failure"):
        d["llm_failure"] = str(trace["llm_failure"]).split(":")[1] if ":" in str(trace["llm_failure"]) else "error"
    route = trace.get("route") or {}
    if route.get("matched"):
        d["rules_hint"] = route.get("intent")
    # fiches citées : réponse d'information (knowledge.used) ou question annexe pendant une démarche
    # (sources de la décision, déjà limitées par le contrat aux fiches réellement fournies)
    utilisees = ((trace.get("knowledge") or {}).get("used") or a.get("sources") or [])
    if utilisees:
        d["knowledge_used"] = list(utilisees)
    if (k := trace.get("knowledge")) and k.get("unsupported"):
        d["knowledge_unsupported"] = True
    if p := trace.get("precheck"):
        d["precheck"] = {"reason": p.get("reason"), "options": p.get("options", [])}
    if e := trace.get("escalation"):
        d["escalation"] = {"reason": e.get("reason"), "detail": anonymise(str(e.get("detail") or ""))[:200]}
    if act := trace.get("action"):
        d["action"] = anonymise.deep(act)
    if r := trace.get("tool_result"):
        d["tool_result"] = anonymise.deep({k: v for k, v in r.items() if k != "contact"})
    if "confirmation" in trace:
        d["confirmation"] = trace["confirmation"]
    if "audio_quality" in trace:
        d["audio_quality"] = trace["audio_quality"]
    if "unusable_input" in trace:
        d["unusable_input"] = trace["unusable_input"]
    return d


def action_type(pack: DomainPack, tool: str | None, action: str | None, workflow: str | None) -> tuple[str, str]:
    genre = next((t.builtin or "custom" for t in pack.tools if t.name == tool), "custom")
    if (genre, action) in ACTION_TYPES:
        return ACTION_TYPES[(genre, action)]
    desc = next((w.description for w in pack.workflows if w.id == workflow), workflow or "workflow")
    return f"{tool or 'workflow'}.{action or 'run'}", desc[:1].upper() + desc[1:]


class Recorder:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------ conversation ---------
    def open_conversation(self, conv: dict, greeting: str) -> None:
        self.db.insert("conversations", conv)
        self.db.insert("turns", {"conversation_id": conv["id"], "workspace_id": conv["workspace_id"], "idx": 0,
                                 "created_at": conv["started_at"], "user_text": "", "agent_text": greeting,
                                 "channel": conv["channel"], "details": dumps({"greeting": True})})

    def close_conversation(self, conv_id: str, workspace_id: str) -> None:
        # ouverte puis fermée sans un seul message du client : ce n'est pas une conversation
        if self.db.run("DELETE FROM conversations WHERE id = ? AND workspace_id = ? AND turns = 0", (conv_id, workspace_id)):
            return
        self.db.update("conversations", {"id": conv_id, "workspace_id": workspace_id},
                       {"status": "ended", "ended_at": now_iso()})
        self._outcome(conv_id, workspace_id)

    # ------------------------------------------------------------------ tour -----------------
    def record_turn(self, *, conv_id: str, workspace_id: str, agent_id: str, pack: DomainPack,
                    anonymise: Anonymiser, result: TurnResult, user_text: str, channel: str,
                    latency_ms: float, usage: dict, awaiting_confirmation: bool, run_workflow: str | None,
                    run_item: str | None, tts_chars: int = 0, stt_seconds: float = 0.0,
                    audio_file: str | None = None, timings: dict | None = None) -> dict:
        trace = result.trace
        details = trace_details(trace, anonymise)
        if timings:
            details["timings"] = timings
        a = trace.get("agent") or {}
        turn = {
            "conversation_id": conv_id, "workspace_id": workspace_id, "idx": trace.get("turn", 0),
            "created_at": now_iso(), "user_text": anonymise(user_text), "agent_text": anonymise(result.reply),
            "intent": result.intent, "channel": channel, "llm_used": int(bool(a.get("llm_used"))),
            "llm_failed": int(bool(trace.get("llm_failure"))),
            "understood": None if "understood" not in a else int(bool(a["understood"])),
            "escalated": int("escalation" in trace), "latency_ms": round(latency_ms, 1),
            "prompt_tokens": usage.get("prompt_tokens", 0), "completion_tokens": usage.get("completion_tokens", 0),
            "tts_chars": tts_chars, "audio_file": audio_file, "details": dumps(details),
        }
        self.db.insert("turns", turn)
        self._actions(conv_id, workspace_id, agent_id, pack, anonymise, trace, details, awaiting_confirmation,
                      run_workflow, run_item, result.reply)
        maj = {"last_activity_at": turn["created_at"]}
        if "escalation" in trace:
            maj["escalation_reason"] = trace["escalation"].get("reason")
        if channel == "voice":
            maj["channel"] = "voice"
        self.db.update("conversations", {"id": conv_id, "workspace_id": workspace_id}, maj)
        self.db.run("""UPDATE conversations SET turns = turns + 1, llm_calls = llm_calls + ?,
                       prompt_tokens = prompt_tokens + ?, completion_tokens = completion_tokens + ?,
                       tts_chars = tts_chars + ?, stt_seconds = stt_seconds + ? WHERE id = ? AND workspace_id = ?""",
                    (result.llm_calls, turn["prompt_tokens"], turn["completion_tokens"], tts_chars,
                     round(stt_seconds, 2), conv_id, workspace_id))
        self._outcome(conv_id, workspace_id)
        return {**turn, "details": details}

    def record_greeting_audio(self, conv_id: str, workspace_id: str, audio_file: str, tts_chars: int) -> None:
        self.db.run("UPDATE turns SET audio_file = ?, tts_chars = ? WHERE conversation_id = ? AND idx = 0 AND workspace_id = ?",
                    (audio_file, tts_chars, conv_id, workspace_id))
        self.db.run("UPDATE conversations SET tts_chars = tts_chars + ? WHERE id = ? AND workspace_id = ?",
                    (tts_chars, conv_id, workspace_id))

    # ------------------------------------------------------------------ actions ---------------
    def _pending(self, conv_id: str, workspace_id: str, workflow: str | None = None) -> dict | None:
        sql = "SELECT * FROM actions WHERE conversation_id = ? AND workspace_id = ? AND status = 'pending'"
        params: tuple = (conv_id, workspace_id)
        if workflow:
            sql += " AND workflow = ?"
            params += (workflow,)
        return self.db.one(sql + " ORDER BY created_at DESC LIMIT 1", params)

    def _actions(self, conv_id, workspace_id, agent_id, pack, anonymise, trace, details, awaiting, wf, item, reply):
        tour, t = trace.get("turn"), now_iso()
        if act := trace.get("action"):
            type_, libelle = action_type(pack, act.get("tool"), act.get("action"), act.get("workflow"))
            info = {"workflow": act.get("workflow"), "item": act.get("item"),
                    "result": details.get("tool_result"), "error": act.get("error")}
            statut = "succeeded" if act.get("status") == "succeeded" else "failed"
            if p := self._pending(conv_id, workspace_id, act.get("workflow")):
                self.db.update("actions", {"id": p["id"], "workspace_id": workspace_id},
                               {"status": statut, "updated_at": t, "duration_ms": act.get("duration_ms"),
                                "turn_idx": tour, "details": dumps({**loads(p["details"]), **info})})
            else:
                self._insert(workspace_id, agent_id, conv_id, tour, type_, libelle, act.get("workflow"),
                             act.get("tool"), act.get("action"), statut, act.get("duration_ms"), info)
        if awaiting and wf and not self._pending(conv_id, workspace_id, wf):
            spec = next((w for w in pack.workflows if w.id == wf), None)
            appel = spec.on_complete if spec else None
            type_, libelle = action_type(pack, appel.tool if appel else None, appel.action if appel else None, wf)
            self._insert(workspace_id, agent_id, conv_id, tour, type_, libelle, wf, appel.tool if appel else None,
                         appel.action if appel else None, "pending", None,
                         {"workflow": wf, "item": item, "summary": anonymise(reply),
                          "note": "Summary read back to the caller; waiting for confirmation"})
        if esc := trace.get("escalation"):
            if p := self._pending(conv_id, workspace_id):
                self.db.update("actions", {"id": p["id"], "workspace_id": workspace_id},
                               {"status": "requires_human", "updated_at": t})
            self._insert(workspace_id, agent_id, conv_id, tour, "handoff.human", "Human hand-off",
                         None, None, None, "requires_human", None,
                         {"reason": esc.get("reason"), "detail": details.get("escalation", {}).get("detail", "")})

    def _insert(self, workspace_id, agent_id, conv_id, tour, type_, libelle, wf, tool, action, statut, duree, info):
        t = now_iso()
        self.db.insert("actions", {"id": new_id("act_"), "workspace_id": workspace_id, "agent_id": agent_id,
                                   "conversation_id": conv_id, "turn_idx": tour, "type": type_, "label": libelle,
                                   "workflow": wf, "tool": tool, "tool_action": action, "status": statut,
                                   "created_at": t, "updated_at": t, "duration_ms": duree, "details": dumps(info)})

    # ------------------------------------------------------------------ issue ------------------
    def _outcome(self, conv_id: str, workspace_id: str) -> None:
        c = self.db.one("SELECT status, escalation_reason FROM conversations WHERE id = ? AND workspace_id = ?",
                        (conv_id, workspace_id))
        if c is None:
            return
        reussie = self.db.one("SELECT 1 FROM actions WHERE conversation_id = ? AND status = 'succeeded' LIMIT 1",
                              (conv_id,))
        info = self.db.one("""SELECT 1 FROM turns WHERE conversation_id = ? AND details LIKE '%"knowledge_used"%'
                              LIMIT 1""", (conv_id,))
        if c["escalation_reason"]:
            issue = "escalated"
        elif reussie:
            issue = "action_completed"
        elif info:
            issue = "information_provided"
        elif c["status"] == "active":
            issue = "in_progress"
        else:
            issue = "unresolved"
        self.db.update("conversations", {"id": conv_id, "workspace_id": workspace_id}, {"outcome": issue})
