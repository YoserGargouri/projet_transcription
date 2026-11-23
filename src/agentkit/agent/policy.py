"""
Politiques d'agent : combien d'appels LLM par tour, et comment.

    AgentPolicy        interface : decide(contexte du tour) -> AgentDecision
    NoLLMPolicy        0 appel : la réponse préparée par les règles (sans clé, ou tours simples)
    SingleCallPolicy   AU PLUS 1 appel par tour (spec WP6) : un seul appel LLM qui renvoie
                       intention, slots, élément, réponse, sentiment, escalade.
                       - mode rules_first : 0 appel si les règles suffisent (ctx.needs_llm = False) ;
                       - mode llm_first (ctx.conversational) : le LLM comprend chaque tour et rédige
                         la réponse à partir de la base de connaissances (sources citées).
    (plus tard)        ToolLoopPolicy : plusieurs étapes outil/LLM, sans toucher à l'orchestrateur.

Le LLM ne décide jamais seul : sa sortie est validée (contrat pydantic), l'élément est
revalidé par le résolveur, les sources par la liste des fiches fournies, l'action finale
passe par la vérification de l'outil, la confirmation et les scripts fixes.
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from agentkit.agent.contract import build_agent_output_model
from agentkit.domain.schema import DomainPack
from agentkit.llm.gateway import InvalidOutput, LLMError, LLMGateway

log = logging.getLogger("agentkit.agent")


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
    knowledge: list[dict] = field(default_factory=list)       # fiches proposées
    knowledge_ids: list[str] = field(default_factory=list)    # knowledge_id / sources autorisés ce tour
    history: list[dict] = field(default_factory=list)
    signals: dict[str, float] = field(default_factory=dict)
    # Mode llm_first
    conversational: bool = False
    askable_slots: list[str] = field(default_factory=list)    # valeurs possibles de asks_for
    extra: dict[str, Any] = field(default_factory=dict)       # contexte supplémentaire (date, options...)


@dataclass
class AgentDecision:
    intent: str
    reply: str
    slots: dict[str, Any] = field(default_factory=dict)
    item_code: str | None = None
    knowledge_id: str | None = None
    tool_call: dict | None = None
    sentiment: str = "neutre"
    escalate: bool = False
    escalate_reason: str = ""
    llm_used: bool = False
    fallback: str = ""           # pourquoi on est revenu aux règles ("" = pas de repli)
    understood: bool = True
    sources: list[str] = field(default_factory=list)
    asks_for: str | None = None


class AgentPolicy(ABC):
    max_llm_calls_per_turn: int = 0

    @abstractmethod
    def decide(self, ctx: TurnContext) -> AgentDecision: ...


class NoLLMPolicy(AgentPolicy):
    max_llm_calls_per_turn = 0

    def decide(self, ctx: TurnContext, fallback: str = "") -> AgentDecision:
        return AgentDecision(intent=ctx.intent, reply=ctx.rules_reply, fallback=fallback)


def _sans_vides(d: dict) -> dict:
    """Retire les entrées vides du contexte : moins de jetons, prompt plus lisible."""
    return {k: v for k, v in d.items() if v not in (None, "", [], {})}


class SingleCallPolicy(AgentPolicy):
    max_llm_calls_per_turn = 1

    def __init__(self, pack: DomainPack, gateway: LLMGateway):
        self.pack = pack
        self.gateway = gateway
        self.rules = NoLLMPolicy()
        p = pack.persona
        self.system = (pack.llm.system_prompt.replace("{persona_name}", p.name)
                       .replace("{scope}", pack.scope.description).replace("{style}", p.style))
        self._system_conv = self.system + "\n\n" + self._description_du_metier()

    def _description_du_metier(self) -> str:
        """Ce que le LLM doit savoir du pack en mode llm_first, fixe d'un tour à l'autre
        (en tête de prompt : les fournisseurs qui mettent en cache le début du prompt en profitent)."""
        intentions = [{"id": i.id, "description": i.description, "traitement": i.handler,
                       **({"exemples": i.examples} if i.examples else {})} for i in self.pack.intents]
        demarches = [{"id": w.id, "description": w.description,
                      "informations": [{"nom": s.name, "type": s.type, "question": s.prompt,
                                        **({"obligatoire": False} if not s.required else {})} for s in w.slots]}
                     for w in self.pack.workflows]
        return ("## Intentions possibles (champ intent)\n" + json.dumps(intentions, ensure_ascii=False)
                + "\n\n## Démarches (traitement workflow:<id>) et informations à recueillir\n"
                + json.dumps(demarches, ensure_ascii=False))

    def messages(self, ctx: TurnContext) -> list[dict]:
        if ctx.conversational:
            contexte = _sans_vides({
                **ctx.extra,
                "demarche_en_cours": ctx.workflow, "informations_deja_obtenues": ctx.filled_slots,
                "information_attendue": ctx.next_slot, "candidats": ctx.candidate_details,
                "question_de_clarification": ctx.clarification, "base_de_connaissances": ctx.knowledge,
            })
            systeme = self._system_conv
        else:
            contexte = {
                "intention_detectee": ctx.intent, "workflow": ctx.workflow,
                "slots_deja_remplis": ctx.filled_slots, "prochaine_information": ctx.next_slot,
                "candidats": ctx.candidate_details, "question_de_clarification": ctx.clarification,
                "fiches_connaissance": ctx.knowledge, "reponse_proposee_par_les_regles": ctx.rules_reply,
            }
            systeme = self.system
        historique = [{"role": "assistant" if h["role"] == "agent" else "user", "content": h["text"]}
                      for h in ctx.history[-2 * self.pack.llm.max_history_turns:]]
        return [{"role": "system", "content": systeme}, *historique,
                {"role": "user", "content": "Contexte du tour (JSON) :\n" + json.dumps(contexte, ensure_ascii=False)
                                            + f"\n\nMessage de l'utilisateur : « {ctx.text} »"}]

    def decide(self, ctx: TurnContext) -> AgentDecision:
        if not ctx.needs_llm and not ctx.conversational:
            return self.rules.decide(ctx)                       # D1 : 0 appel quand les règles suffisent
        modele = build_agent_output_model([i.id for i in self.pack.intents], ctx.slot_names, ctx.candidates,
                                          knowledge_ids=ctx.knowledge_ids, conversational=ctx.conversational,
                                          askable_slots=ctx.askable_slots)
        try:
            sortie = self.gateway.complete_json(self.messages(ctx), modele)
        except InvalidOutput as e:
            # D3 : jamais de code hors candidats. Si le reste est valide, on remet à vide les champs
            # contraints (élément, fiche, sources hors liste, information demandée inconnue).
            if e.raw is not None:
                brut = {**e.raw, "item_code": None}
                if "knowledge_id" in brut:
                    brut["knowledge_id"] = None
                if isinstance(brut.get("sources"), list):
                    brut["sources"] = [x for x in brut["sources"] if x in ctx.knowledge_ids]
                if "asks_for" in brut and brut["asks_for"] not in ctx.askable_slots:
                    brut["asks_for"] = None
                try:
                    sortie = modele.model_validate(brut)
                    d = self._decision(sortie)
                    d.fallback = "item_code_invalide"
                    log.warning("sortie LLM corrigée : champ hors liste remis à vide")
                    return d
                except ValidationError:
                    pass
            log.warning("sortie LLM invalide après nouvelle tentative : repli sur les règles")
            return self.rules.decide(ctx, fallback="sortie_llm_invalide")
        except LLMError as e:                                   # réseau, budget, quota...
            log.warning("LLM indisponible (%s) : repli sur les règles", type(e).__name__)
            # La cause est gardée dans la trace (délai dépassé, 503...) : sans elle, le journal
            # ne permet pas de savoir pourquoi le tour s'est replié sur les règles.
            return self.rules.decide(ctx, fallback=f"llm_indisponible:{type(e).__name__}:{str(e)[:160]}")
        return self._decision(sortie)

    @staticmethod
    def _decision(sortie) -> AgentDecision:
        return AgentDecision(
            intent=sortie.intent, reply=sortie.reply, slots=sortie.slots.model_dump(), item_code=sortie.item_code,
            knowledge_id=getattr(sortie, "knowledge_id", None),
            tool_call=sortie.tool_call.model_dump() if getattr(sortie, "tool_call", None) else None,
            sentiment=sortie.sentiment, escalate=sortie.escalate.needed, escalate_reason=sortie.escalate.reason,
            llm_used=True, understood=getattr(sortie, "understood", True),
            sources=list(getattr(sortie, "sources", []) or []), asks_for=getattr(sortie, "asks_for", None))
