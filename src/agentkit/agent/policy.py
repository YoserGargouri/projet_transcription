"""
Politiques d'agent : combien d'appels LLM par tour, et comment.

    AgentPolicy        interface : decide(contexte du tour) -> AgentDecision
    NoLLMPolicy        0 appel : la réponse préparée par les règles (sans clé, ou tours simples)
    SingleCallPolicy   AU PLUS 1 appel par tour (spec WP6) : un seul appel LLM qui renvoie
                       intention, slots, élément, réponse, sentiment, escalade. Si les règles
                       suffisent (ctx.needs_llm = False), 0 appel (D1).
    (plus tard)        ToolLoopPolicy : plusieurs étapes outil/LLM, sans toucher à l'orchestrateur.

Le LLM ne décide jamais seul : sa sortie est validée (contrat pydantic), l'élément est
revalidé par le résolveur, l'action finale passe par la confirmation et les scripts fixes.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from agentkit.agent.contract import build_agent_output_model
from agentkit.domain.schema import DomainPack
from agentkit.llm.gateway import InvalidOutput, LLMError, LLMGateway


@dataclass
class TurnContext:
    text: str
    intent: str
    rules_reply: str                                  # réponse que donneraient les règles seules
    needs_llm: bool = False                           # les règles ne suffisent pas pour ce tour
    workflow: str | None = None
    slot_names: list[str] = field(default_factory=list)       # slots que le LLM peut remplir
    filled_slots: dict[str, Any] = field(default_factory=dict)
    next_slot: dict[str, str] | None = None           # {"name", "prompt"}
    candidates: list[str] = field(default_factory=list)       # item_code autorisés ce tour
    candidate_details: list[dict] = field(default_factory=list)
    clarification: str | None = None
    knowledge: list[dict] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    signals: dict[str, float] = field(default_factory=dict)


@dataclass
class AgentDecision:
    intent: str
    reply: str
    slots: dict[str, Any] = field(default_factory=dict)
    item_code: str | None = None
    tool_call: dict | None = None
    sentiment: str = "neutre"
    escalate: bool = False
    escalate_reason: str = ""
    llm_used: bool = False
    fallback: str = ""           # pourquoi on est revenu aux règles ("" = pas de repli)


class AgentPolicy(ABC):
    max_llm_calls_per_turn: int = 0

    @abstractmethod
    def decide(self, ctx: TurnContext) -> AgentDecision: ...


class NoLLMPolicy(AgentPolicy):
    max_llm_calls_per_turn = 0

    def decide(self, ctx: TurnContext, fallback: str = "") -> AgentDecision:
        return AgentDecision(intent=ctx.intent, reply=ctx.rules_reply, fallback=fallback)


class SingleCallPolicy(AgentPolicy):
    max_llm_calls_per_turn = 1

    def __init__(self, pack: DomainPack, gateway: LLMGateway):
        self.pack = pack
        self.gateway = gateway
        self.rules = NoLLMPolicy()
        p = pack.persona
        self.system = (pack.llm.system_prompt.replace("{persona_name}", p.name)
                       .replace("{scope}", pack.scope.description).replace("{style}", p.style))

    def messages(self, ctx: TurnContext) -> list[dict]:
        contexte = {
            "intention_detectee": ctx.intent, "workflow": ctx.workflow,
            "slots_deja_remplis": ctx.filled_slots, "prochaine_information": ctx.next_slot,
            "candidats": ctx.candidate_details, "question_de_clarification": ctx.clarification,
            "fiches_connaissance": ctx.knowledge, "reponse_proposee_par_les_regles": ctx.rules_reply,
        }
        historique = [{"role": "assistant" if h["role"] == "agent" else "user", "content": h["text"]}
                      for h in ctx.history[-2 * self.pack.llm.max_history_turns:]]
        return [{"role": "system", "content": self.system}, *historique,
                {"role": "user", "content": "Contexte du tour (JSON) :\n" + json.dumps(contexte, ensure_ascii=False)
                                            + f"\n\nMessage de l'utilisateur : « {ctx.text} »"}]

    def decide(self, ctx: TurnContext) -> AgentDecision:
        if not ctx.needs_llm:
            return self.rules.decide(ctx)                       # D1 : 0 appel quand les règles suffisent
        modele = build_agent_output_model([i.id for i in self.pack.intents], ctx.slot_names, ctx.candidates)
        try:
            sortie = self.gateway.complete_json(self.messages(ctx), modele)
        except InvalidOutput as e:
            # D3 : jamais de code hors candidats. Si le reste est valide, item_code -> null.
            if e.raw is not None:
                brut = {**e.raw, "item_code": None}
                try:
                    sortie = modele.model_validate(brut)
                    d = self._decision(sortie)
                    d.fallback = "item_code_invalide"
                    return d
                except ValidationError:
                    pass
            return self.rules.decide(ctx, fallback="sortie_llm_invalide")
        except LLMError as e:                                   # réseau, budget, quota...
            return self.rules.decide(ctx, fallback=f"llm_indisponible:{type(e).__name__}")
        return self._decision(sortie)

    @staticmethod
    def _decision(sortie) -> AgentDecision:
        return AgentDecision(
            intent=sortie.intent, reply=sortie.reply, slots=sortie.slots.model_dump(), item_code=sortie.item_code,
            tool_call=sortie.tool_call.model_dump() if sortie.tool_call else None, sentiment=sortie.sentiment,
            escalate=sortie.escalate.needed, escalate_reason=sortie.escalate.reason, llm_used=True)
