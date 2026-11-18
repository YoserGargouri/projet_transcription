"""
Orchestrateur : la boucle d'un tour de conversation, indépendante du domaine et du canal.

    orch = Orchestrator.from_domain("demo_minimal")       # LLM pris dans .env, sinon règles seules
    print(orch.start())
    r = orch.handle_text("je voudrais louer un VTT")      # -> TurnResult (réponse, trace...)

Un tour, dans l'ordre (les étapes sans LLM d'abord) :
 1. signaux en parallèle (frustration...)            6. escalade par signal
 2. demande explicite d'un humain -> transfert        7. traitement selon l'intention :
 3. réponse à une question de sécurité en attente        escalate | knowledge (FAQ) | workflow
 4. réponse à une confirmation en attente             8. workflow : résolveur -> politique d'agent
 5. intention (routeur) puis périmètre interdit          (au plus 1 appel LLM) -> revalidation ->
                                                         scripts de sécurité -> slot suivant ->
                                                         confirmation -> outil final
Chaque tour est journalisé, anonymisé (logging.redaction).
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from agentkit.agent.policy import AgentPolicy, NoLLMPolicy, SingleCallPolicy, TurnContext
from agentkit.domain.catalogue import Catalogue
from agentkit.domain.loader import load_domain
from agentkit.domain.schema import DomainPack
from agentkit.knowledge.retriever import build_retriever
from agentkit.llm.gateway import LLMGateway, gateway_from_env
from agentkit.logging.redaction import ConversationLogger
from agentkit.nlu.resolver import CatalogueResolver, Resolution
from agentkit.nlu.router import RuleRouter
from agentkit.policy.escalation import Escalation, EscalationPolicy
from agentkit.policy.guardrails import SafetyScripts, ScopeGuard
from agentkit.signals.base import build_signals
from agentkit.tools.base import ToolError
from agentkit.tools.registry import ToolRegistry
from agentkit.workflows.engine import WorkflowEngine, WorkflowRun


@dataclass
class ConversationState:
    session_id: str
    turn: int = 0
    intent: str | None = None
    run: WorkflowRun | None = None
    resolution_context: dict[str, str] = field(default_factory=dict)
    candidates: list[str] = field(default_factory=list)
    pending_slot: str | None = None          # slot demandé au tour précédent
    pending_clarification: bool = False       # une question de clarification attend sa réponse
    awaiting_confirmation: bool = False
    safety_queue: list[str] = field(default_factory=list)
    safety_pending: str | None = None
    safety_retries: int = 0
    failed_clarifications: int = 0
    unrecognised_turns: int = 0
    audio_failures: int = 0
    history: list[dict] = field(default_factory=list)
    escalation: Escalation | None = None


@dataclass
class TurnResult:
    reply: str
    intent: str | None = None
    escalated: bool = False
    escalation_reason: str | None = None
    item_id: str | None = None
    candidates: list[str] = field(default_factory=list)
    llm_calls: int = 0
    signals: dict[str, float] = field(default_factory=dict)
    trace: dict[str, Any] = field(default_factory=dict)


class Orchestrator:
    def __init__(self, pack: DomainPack, gateway: LLMGateway | None = None, policy: AgentPolicy | None = None,
                 session_id: str | None = None, log: bool = True):
        self.pack = pack
        self.catalogue = Catalogue(pack) if pack.catalogue else None
        self.resolver = CatalogueResolver(pack, self.catalogue) if self.catalogue else None
        self.router = RuleRouter(pack)
        self.retriever = build_retriever(pack)
        self.signals = build_signals(pack)
        self.guard = ScopeGuard(pack)
        self.safety = SafetyScripts(pack)
        self.escalation_policy = EscalationPolicy(pack.escalation)
        self.tools = ToolRegistry.from_pack(pack)
        self.workflows = WorkflowEngine(pack, self.tools)
        self.gateway = gateway
        self.policy = policy or (SingleCallPolicy(pack, gateway) if gateway else NoLLMPolicy())
        self.state = ConversationState(session_id=session_id or uuid.uuid4().hex[:12])
        self.logger = ConversationLogger(pack, self.state.session_id) if log else None

    @classmethod
    def from_domain(cls, domain: str, gateway: LLMGateway | None | str = "env", **kw) -> Orchestrator:
        return cls(load_domain(domain), gateway_from_env() if gateway == "env" else gateway, **kw)

    # ================================================================== tour ==================
    def start(self) -> str:
        self.state.history.append({"role": "agent", "text": self.pack.persona.greeting})
        return self.pack.persona.greeting

    def handle_text(self, text: str) -> TurnResult:
        s = self.state
        s.turn += 1
        if self.gateway:
            self.gateway.begin_turn(f"{s.session_id}:{s.turn}", self.policy.max_llm_calls_per_turn)
        s.history.append({"role": "user", "text": text})
        trace: dict[str, Any] = {"turn": s.turn}
        if s.escalation:                                        # déjà transféré
            return self._result(self.pack.persona.handoff_message, trace)

        scores = {sig.id: sig.score(text) for sig in self.signals}   # 1. signaux
        trace["signals"] = scores
        if self.guard.wants_human(text):                        # 2. humain demandé
            return self._escalate(Escalation("explicit_request"), trace)
        if s.safety_pending:                                    # 3. script de sécurité
            return self._safety_answer(text, trace)
        if s.awaiting_confirmation:                             # 4. confirmation
            return self._confirmation_answer(text, trace)

        route = self.router.route(text)                         # 5. intention
        intent = route.intent
        trace["route"] = asdict(route)
        handler = self.pack.intent(intent).handler
        if s.run and (not route.matched or handler == f"workflow:{s.run.workflow_id}"):
            intent, handler = s.intent, f"workflow:{s.run.workflow_id}"   # on reste dans le workflow
        if v := self.guard.check(text, intent):                 # périmètre interdit
            return self._escalate(Escalation("out_of_scope", v.rule_id), trace)
        if e := self.escalation_policy.from_signals(scores):    # 6. frustration...
            return self._escalate(e, trace)

        if handler == "escalate":                               # 7. selon l'intention
            if route.matched:
                return self._escalate(Escalation("intent_escalate", intent), trace)
            return self._unrecognised(trace)
        if handler == "knowledge":
            return self._knowledge(text, trace)
        return self._workflow_turn(intent, handler.split(":", 1)[1], text, scores, trace)

    # ================================================================== branches ==============
    def _knowledge(self, text: str, trace: dict) -> TurnResult:
        hit = self.retriever.answer(text) if self.retriever else None
        trace["knowledge"] = {"id": hit.id, "score": hit.score} if hit else None
        if hit is None:
            # TODO(WP3) : en cas de doute, l'appel LLM du tour choisira parmi les 3 meilleures fiches
            return self._unrecognised(trace)
        reply = hit.answer
        if self.state.run and (slot := self.workflows.next_missing(self.state.run)):
            reply += " " + slot.prompt                          # on revient au workflow en cours
        return self._result(reply, trace)

    def _workflow_turn(self, intent: str, workflow_id: str, text: str, scores: dict, trace: dict) -> TurnResult:
        s = self.state
        if s.run is None or s.run.workflow_id != workflow_id:
            s.run, s.intent = self.workflows.start(workflow_id), intent
            s.resolution_context, s.candidates, s.pending_slot = {}, [], None
        run = s.run
        slot_item = self.workflows.item_slot(run)

        resolution: Resolution | None = None                     # 8a. résolveur (sans LLM)
        if slot_item and run.item is None and self.resolver:
            resolution = self.resolver.resolve(text, s.resolution_context)
            s.resolution_context = {**s.resolution_context, **resolution.context}
            trace["resolution"] = {"status": resolution.status, "item": resolution.item_id,
                                   "candidates": resolution.candidates[:10], "confidence": resolution.confidence}
            if resolution.item_id:
                self._set_item(resolution.item_id)
            else:
                s.candidates = resolution.candidates
                if resolution.status == "ambiguous" and s.pending_clarification:
                    s.failed_clarifications += 1

        regles = {}                                              # réponse brute au slot demandé
        if s.pending_slot and (slot_item is None or s.pending_slot != slot_item.name):
            regles[s.pending_slot] = text
        trace["slot_errors"] = self.workflows.set_slots(run, regles)

        ctx = self._contexte(text, intent, run, resolution, scores)   # 8b. politique d'agent
        decision = self.policy.decide(ctx)
        trace["agent"] = {"llm_used": decision.llm_used, "fallback": decision.fallback}
        if decision.escalate:
            return self._escalate(Escalation("agent_requested", decision.escalate_reason), trace)
        if decision.item_code and run.item is None:              # revalidation (D3)
            if decision.item_code in ctx.candidates and self.catalogue and decision.item_code in self.catalogue.by_id:
                self._set_item(decision.item_code)
                trace["item_source"] = "llm"
        erreurs = self.workflows.set_slots(run, {k: v for k, v in decision.slots.items() if k in ctx.slot_names})
        trace["slot_errors"].update(erreurs)

        if e := self.escalation_policy.from_counters(s.failed_clarifications, s.unrecognised_turns,
                                                     s.audio_failures):
            return self._escalate(e, trace)
        return self._next_step(trace, reply=decision.reply if decision.llm_used else None,
                               resolution=resolution)

    def _next_step(self, trace: dict, reply: str | None = None, resolution: Resolution | None = None) -> TurnResult:
        """Le SYSTÈME choisit l'étape suivante ; le LLM ne fait que formuler la réponse."""
        s, run = self.state, self.state.run
        s.pending_clarification = False
        if s.safety_queue:                                       # scripts de sécurité d'abord
            return self._ask_safety(trace)
        manquant = self.workflows.next_missing(run)
        if manquant is not None:
            s.pending_slot = manquant.name
            if manquant.type == "catalogue_item" and resolution is not None and not reply:
                if resolution.status == "ambiguous" and resolution.question:
                    s.pending_clarification = True
                    s.pending_slot = None
                    return self._result(resolution.question, trace)
                if resolution.status == "infeasible":
                    return self._result(f"{self.pack.persona.not_found_message} {manquant.prompt}", trace)
            return self._result(reply or manquant.prompt, trace)
        s.pending_slot = None
        if (texte := self.workflows.confirmation_text(run)) is not None:
            s.awaiting_confirmation = True
            return self._result(texte, trace)
        return self._complete(trace)

    def _contexte(self, text, intent, run: WorkflowRun, resolution: Resolution | None, scores) -> TurnContext:
        s, spec = self.state, self.workflows.spec(run)
        manquant = self.workflows.next_missing(run)
        candidats = []
        if run.item is not None:                    # élément déjà fixé : le LLM peut seulement le répéter
            candidats = [run.item["id"]]
        elif self.resolver and resolution is not None:
            candidats = (resolution.candidates if resolution.status == "ambiguous"
                         else self.resolver.candidates_for_llm(resolution, text))
        details = [{"code": c, "libelle": self.catalogue.by_id[c].label, **self.catalogue.by_id[c].attributes}
                   for c in candidats] if self.catalogue else []
        clarification = resolution.question if resolution and resolution.status == "ambiguous" else None
        # Réponse des règles : clarification, sinon question du prochain slot (ou récapitulatif)
        regles = clarification or (manquant.prompt if manquant else self.workflows.confirmation_text(run) or "")
        # D1 : pas d'appel LLM quand les règles ont une question précise de clarification
        besoin = self.gateway is not None and clarification is None
        return TurnContext(
            text=text, intent=intent, rules_reply=regles or self.pack.persona.fallback_message, needs_llm=besoin,
            workflow=spec.id, slot_names=[x.name for x in spec.slots if x.type != "catalogue_item"],
            filled_slots={k: v for k, v in run.slots.items() if v}, candidates=candidats, candidate_details=details,
            next_slot={"name": manquant.name, "prompt": manquant.prompt} if manquant else None,
            clarification=clarification, history=s.history[:-1], signals=scores)

    # ================================================================== sécurité / fin ========
    def _set_item(self, item_id: str) -> None:
        item = self.catalogue.by_id[item_id]
        self.workflows.set_item(self.state.run, item.as_context())
        self.state.candidates = [item_id]
        self.state.failed_clarifications = 0
        self.state.safety_queue = [sc.id for sc in self.safety.applicable(item.attributes)]

    def _ask_safety(self, trace: dict) -> TurnResult:
        s = self.state
        s.safety_pending, s.safety_retries = s.safety_queue.pop(0), 0
        trace["safety"] = {"asked": s.safety_pending}
        return self._result(self.safety.get(s.safety_pending).question, trace)

    def _safety_answer(self, text: str, trace: dict) -> TurnResult:
        s = self.state
        script = self.safety.get(s.safety_pending)
        reponse = self.safety.parse_answer(text)
        trace["safety"] = {"script": script.id, "answer": reponse}
        if reponse == "yes":
            return self._escalate(Escalation("safety_positive", script.id), trace)
        if reponse == "unclear":
            if script.on_unclear == "ask_again_once" and s.safety_retries == 0:
                s.safety_retries = 1
                return self._result(script.question, trace)
            return self._escalate(Escalation("safety_positive", f"{script.id} (réponse floue)"), trace)
        s.safety_pending = None
        return self._next_step(trace)

    def _confirmation_answer(self, text: str, trace: dict) -> TurnResult:
        s = self.state
        reponse = self.safety.parse_answer(text)                # mêmes règles oui / non que le pack
        trace["confirmation"] = reponse
        if reponse == "yes":
            s.awaiting_confirmation = False
            return self._complete(trace)
        if reponse == "no":
            s.awaiting_confirmation = False
            # TODO(WP6) : ne vider que l'information à corriger
            garder = {k: v for k, v in s.run.slots.items() if k == getattr(self.workflows.item_slot(s.run), "name", None)}
            s.run.slots = garder
            return self._result(self.pack.persona.change_prompt, trace)
        return self._result(self.workflows.confirmation_text(s.run) or self.pack.persona.fallback_message, trace)

    def _complete(self, trace: dict) -> TurnResult:
        s = self.state
        try:
            resultat, message = self.workflows.complete(s.run)
        except ToolError as e:
            return self._escalate(Escalation("tool_error", str(e)), trace)
        trace["tool_result"] = resultat
        s.run, s.intent, s.candidates, s.resolution_context = None, None, [], {}
        return self._result(message or self.pack.persona.goodbye_message, trace)

    def _unrecognised(self, trace: dict) -> TurnResult:
        self.state.unrecognised_turns += 1
        if e := self.escalation_policy.from_counters(0, self.state.unrecognised_turns, self.state.audio_failures):
            return self._escalate(e, trace)
        return self._result(self.pack.persona.fallback_message, trace)

    def _escalate(self, e: Escalation, trace: dict) -> TurnResult:
        self.state.escalation = e
        trace["escalation"] = asdict(e)
        return self._result(self.pack.persona.handoff_message, trace)

    def _result(self, reply: str, trace: dict) -> TurnResult:
        s = self.state
        s.history.append({"role": "agent", "text": reply})
        appels = self.gateway.calls_this_turn() if self.gateway else 0
        r = TurnResult(reply=reply, intent=s.intent or trace.get("route", {}).get("intent"),
                       escalated=s.escalation is not None,
                       escalation_reason=s.escalation.reason if s.escalation else None,
                       item_id=(s.run.item or {}).get("id") if s.run else None, candidates=list(s.candidates),
                       llm_calls=appels, signals=trace.get("signals", {}), trace=trace)
        if self.logger:
            slots = s.run.slots if s.run else {}
            self.logger.log_turn({"session": s.session_id, "tour": s.turn, "utilisateur": s.history[-2]["text"],
                                  "agent": reply, "intention": r.intent, "element": r.item_id,
                                  "appels_llm": appels, "escalade": r.escalation_reason, "trace": trace}, slots)
        return r
