"""
Indicateurs du tableau de bord et de la page Analytics, calculés en SQL sur les données
réellement enregistrées (conversations, tours, actions) d'UN espace de travail.

Aucun chiffre n'est inventé : sans données, les compteurs valent 0 et les moyennes None.
Les coûts ne sont estimés que si l'espace de travail a saisi ses prix unitaires.
"""
from __future__ import annotations

from datetime import date, timedelta

from agentkit.server.db import Database, loads


def _filtre(workspace_id: str, agent_id: str | None, debut: str, fin: str, alias: str = "c") -> tuple[str, list]:
    sql = f"{alias}.workspace_id = ? AND substr({alias}.started_at, 1, 10) BETWEEN ? AND ?"
    params = [workspace_id, debut, fin]
    if agent_id:
        sql += f" AND {alias}.agent_id = ?"
        params.append(agent_id)
    return sql, params


def _jours(debut: str, fin: str) -> list[str]:
    d0, d1 = date.fromisoformat(debut), date.fromisoformat(fin)
    return [(d0 + timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]


def _taux(n: float, total: float) -> float | None:
    return round(n / total, 4) if total else None


def compute(db: Database, workspace_id: str, debut: str, fin: str, agent_id: str | None = None) -> dict:
    w, p = _filtre(workspace_id, agent_id, debut, fin)
    conv = db.one(f"""
        SELECT COUNT(*) AS conversations,
               SUM(channel = 'voice') AS voice, SUM(channel = 'chat') AS chat,
               SUM(outcome = 'escalated') AS escalated,
               SUM(outcome IN ('action_completed', 'information_provided')) AS resolved,
               SUM(status = 'ended') AS ended,
               SUM(turns) AS turns, SUM(llm_calls) AS llm_calls,
               SUM(prompt_tokens) AS prompt_tokens, SUM(completion_tokens) AS completion_tokens,
               SUM(tts_chars) AS tts_chars, SUM(stt_seconds) AS stt_seconds,
               AVG(CASE WHEN turns > 0 THEN (julianday(last_activity_at) - julianday(started_at)) * 86400 END) AS avg_duration_s
        FROM conversations c WHERE {w}""", p) or {}
    tours = db.one(f"""
        SELECT COUNT(*) AS turns, SUM(t.llm_used) AS llm_turns, SUM(t.llm_failed) AS llm_failed,
               SUM(t.understood IS NOT NULL) AS judged, SUM(t.understood = 1) AS understood,
               AVG(t.latency_ms) AS avg_latency_ms,
               AVG(CASE WHEN t.channel = 'chat' THEN t.latency_ms END) AS avg_latency_chat_ms,
               AVG(CASE WHEN t.channel = 'voice' THEN t.latency_ms END) AS avg_latency_voice_ms
        FROM turns t JOIN conversations c ON c.id = t.conversation_id
        WHERE {w} AND t.idx > 0""", p) or {}
    latences = [r["latency_ms"] for r in db.all(f"""
        SELECT t.latency_ms FROM turns t JOIN conversations c ON c.id = t.conversation_id
        WHERE {w} AND t.idx > 0 AND t.latency_ms IS NOT NULL ORDER BY t.latency_ms""", p)]
    actions = db.one(f"""
        SELECT COUNT(*) AS total, SUM(a.status = 'succeeded') AS succeeded, SUM(a.status = 'failed') AS failed,
               SUM(a.status = 'pending') AS pending, SUM(a.status = 'requires_human') AS requires_human,
               AVG(CASE WHEN a.status = 'succeeded' THEN a.duration_ms END) AS avg_duration_ms
        FROM actions a JOIN conversations c ON c.id = a.conversation_id WHERE {w}""", p) or {}
    executees = (actions.get("succeeded") or 0) + (actions.get("failed") or 0)
    n = conv.get("conversations") or 0

    par_jour = {j: {"date": j, "conversations": 0, "voice": 0, "chat": 0, "actions_succeeded": 0,
                    "actions_failed": 0, "escalations": 0, "tokens": 0, "tts_chars": 0, "avg_latency_ms": None}
                for j in _jours(debut, fin)}
    for r in db.all(f"""SELECT substr(started_at, 1, 10) AS d, COUNT(*) AS n, SUM(channel = 'voice') AS v,
                               SUM(channel = 'chat') AS ch, SUM(outcome = 'escalated') AS e,
                               SUM(prompt_tokens + completion_tokens) AS tok, SUM(tts_chars) AS tts
                        FROM conversations c WHERE {w} GROUP BY d""", p):
        if r["d"] in par_jour:
            par_jour[r["d"]].update(conversations=r["n"], voice=r["v"] or 0, chat=r["ch"] or 0,
                                    escalations=r["e"] or 0, tokens=r["tok"] or 0, tts_chars=r["tts"] or 0)
    for r in db.all(f"""SELECT substr(a.created_at, 1, 10) AS d, SUM(a.status = 'succeeded') AS ok,
                               SUM(a.status = 'failed') AS ko
                        FROM actions a JOIN conversations c ON c.id = a.conversation_id WHERE {w} GROUP BY d""", p):
        if r["d"] in par_jour:
            par_jour[r["d"]].update(actions_succeeded=r["ok"] or 0, actions_failed=r["ko"] or 0)
    for r in db.all(f"""SELECT substr(t.created_at, 1, 10) AS d, AVG(t.latency_ms) AS lat
                        FROM turns t JOIN conversations c ON c.id = t.conversation_id
                        WHERE {w} AND t.idx > 0 GROUP BY d""", p):
        if r["d"] in par_jour and r["lat"] is not None:
            par_jour[r["d"]]["avg_latency_ms"] = round(r["lat"], 1)

    intentions = db.all(f"""SELECT COALESCE(t.intent, 'unknown') AS intent, COUNT(*) AS count
                            FROM turns t JOIN conversations c ON c.id = t.conversation_id
                            WHERE {w} AND t.idx > 0 GROUP BY intent ORDER BY count DESC LIMIT 12""", p)
    issues = db.all(f"SELECT outcome, COUNT(*) AS count FROM conversations c WHERE {w} GROUP BY outcome "
                    "ORDER BY count DESC", p)
    types = db.all(f"""SELECT a.type, a.label, COUNT(*) AS count, SUM(a.status = 'succeeded') AS succeeded
                       FROM actions a JOIN conversations c ON c.id = a.conversation_id WHERE {w}
                       GROUP BY a.type, a.label ORDER BY count DESC""", p)
    heures = {h: 0 for h in range(24)}
    for r in db.all(f"""SELECT CAST(substr(started_at, 12, 2) AS INTEGER) AS h, COUNT(*) AS n
                        FROM conversations c WHERE {w} GROUP BY h""", p):
        if r["h"] is not None:
            heures[r["h"]] = r["n"]
    raisons = db.all(f"""SELECT escalation_reason AS reason, COUNT(*) AS count FROM conversations c
                         WHERE {w} AND escalation_reason IS NOT NULL GROUP BY reason ORDER BY count DESC""", p)

    tokens_e, tokens_s = conv.get("prompt_tokens") or 0, conv.get("completion_tokens") or 0
    ws = db.one("SELECT settings FROM workspaces WHERE id = ?", (workspace_id,))
    prix = loads(ws["settings"] if ws else None).get("pricing") or {}
    cout = None
    if any(prix.get(k) for k in ("llm_input_per_million", "llm_output_per_million", "tts_per_thousand_chars")):
        cout = {
            "llm": round(tokens_e / 1e6 * float(prix.get("llm_input_per_million") or 0)
                         + tokens_s / 1e6 * float(prix.get("llm_output_per_million") or 0), 4),
            "tts": round((conv.get("tts_chars") or 0) / 1000 * float(prix.get("tts_per_thousand_chars") or 0), 4),
            "currency": prix.get("currency") or "USD",
        }
        cout["total"] = round(cout["llm"] + cout["tts"], 4)

    def pct(q: float):
        return round(latences[min(len(latences) - 1, int(q * len(latences)))], 1) if latences else None

    return {
        "range": {"from": debut, "to": fin, "agent_id": agent_id},
        "totals": {
            "conversations": n, "voice_conversations": conv.get("voice") or 0, "chat_conversations": conv.get("chat") or 0,
            "turns": tours.get("turns") or 0,
            "handled_without_human": n - (conv.get("escalated") or 0),
            "automation_rate": _taux(n - (conv.get("escalated") or 0), n),
            "resolution_rate": _taux(conv.get("resolved") or 0, n),
            "escalations": conv.get("escalated") or 0, "escalation_rate": _taux(conv.get("escalated") or 0, n),
            "avg_duration_s": round(conv["avg_duration_s"], 1) if conv.get("avg_duration_s") is not None else None,
            "avg_latency_ms": round(tours["avg_latency_ms"], 1) if tours.get("avg_latency_ms") is not None else None,
            "avg_latency_chat_ms": round(tours["avg_latency_chat_ms"], 1) if tours.get("avg_latency_chat_ms") else None,
            "avg_latency_voice_ms": round(tours["avg_latency_voice_ms"], 1) if tours.get("avg_latency_voice_ms") else None,
            "p50_latency_ms": pct(0.5), "p90_latency_ms": pct(0.9),
            "llm_calls": conv.get("llm_calls") or 0, "llm_turns": tours.get("llm_turns") or 0,
            "llm_failed_turns": tours.get("llm_failed") or 0,
            "llm_usage_rate": _taux(tours.get("llm_turns") or 0, tours.get("turns") or 0),
            "understood_rate": _taux(tours.get("understood") or 0, tours.get("judged") or 0),
            "prompt_tokens": tokens_e, "completion_tokens": tokens_s, "total_tokens": tokens_e + tokens_s,
            "tts_chars": conv.get("tts_chars") or 0, "stt_seconds": round(conv.get("stt_seconds") or 0, 1),
            "actions_total": actions.get("total") or 0, "actions_succeeded": actions.get("succeeded") or 0,
            "actions_failed": actions.get("failed") or 0, "actions_pending": actions.get("pending") or 0,
            "actions_requires_human": actions.get("requires_human") or 0,
            "action_success_rate": _taux(actions.get("succeeded") or 0, executees),
            "avg_action_duration_ms": round(actions["avg_duration_ms"], 1) if actions.get("avg_duration_ms") else None,
        },
        "daily": list(par_jour.values()),
        "intents": intentions, "outcomes": issues, "action_types": types,
        "hours": [{"hour": h, "count": c} for h, c in heures.items()],
        "escalation_reasons": raisons, "estimated_cost": cout,
    }
