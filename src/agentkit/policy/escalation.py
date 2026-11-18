"""
Transfert vers un humain (WP7) : déclencheurs génériques, seuils fixés par le pack.

Déclencheurs (raison enregistrée dans les journaux) :
    explicit_request   l'utilisateur demande un humain
    out_of_scope       sujet interdit par le pack (guardrails.ScopeGuard)
    intent_escalate    intention dont le handler est « escalate »
    safety_positive    réponse positive (ou deux fois floue) à un script de sécurité
    signal:<id>        un signal dépasse escalation.signal_thresholds (ex. frustration)
    ambiguity          trop de clarifications sans résultat
    unrecognised       trop de tours incompris
    audio_unusable     trop d'audios inexploitables (canal audio)
    agent_requested    le LLM demande lui-même le transfert (escalate.needed)
    tool_error         l'action finale a échoué
"""
from __future__ import annotations

from dataclasses import dataclass

from agentkit.domain.schema import EscalationSpec


@dataclass
class Escalation:
    reason: str
    detail: str = ""


class EscalationPolicy:
    def __init__(self, spec: EscalationSpec):
        self.spec = spec

    def from_signals(self, scores: dict[str, float]) -> Escalation | None:
        for sid, seuil in self.spec.signal_thresholds.items():
            if scores.get(sid, 0.0) >= seuil:
                return Escalation(f"signal:{sid}", f"score {scores[sid]:.2f} >= {seuil}")
        return None

    def from_counters(self, failed_clarifications: int, unrecognised: int, audio_failures: int) -> Escalation | None:
        if failed_clarifications >= self.spec.max_failed_clarifications:
            return Escalation("ambiguity", f"{failed_clarifications} clarifications sans résultat")
        if unrecognised >= self.spec.max_unrecognised_turns:
            return Escalation("unrecognised", f"{unrecognised} tours incompris")
        if audio_failures >= self.spec.max_audio_failures:
            return Escalation("audio_unusable", f"{audio_failures} audios inexploitables")
        return None
