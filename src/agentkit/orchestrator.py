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
Mode llm_first (llm.mode du pack) : à l'étape 5, le LLM comprend le tour (un seul appel) :
intention, informations, élément, réponse rédigée à partir de la base de connaissances (sources
citées et vérifiées). Les règles du routeur deviennent un indice ; si le LLM est indisponible, le
tour repart sur le chemin des règles. Restent hors LLM : demande d'humain, motifs forts du
périmètre interdit, scripts de sécurité, revalidation de l'élément (D3), vérification par l'outil,
récapitulatif et confirmation, action finale.
Chaque tour est journalisé, anonymisé (logging.redaction) ; les étapes sont tracées par le
module logging (« agentkit.* », sans texte de l'utilisateur ni clé).
"""
from __future__ import annotations

import logging
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
from agentkit.nlu import dates
from agentkit.nlu.resolver import CatalogueResolver, Resolution
from agentkit.nlu.router import RuleRouter
from agentkit.policy.escalation import Escalation, EscalationPolicy
from agentkit.policy.guardrails import SafetyScripts, ScopeGuard
from agentkit.signals.base import build_signals
from agentkit.tools.base import ToolError
from agentkit.tools.registry import ToolRegistry
from agentkit.workflows.engine import WorkflowEngine, WorkflowRun

log = logging.getLogger("agentkit.tour")


def _option_choisie(texte: str, options: list[str]) -> str | None:
    return dates.option_choisie(texte, options)


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
    last_question: str | None = None          # dernière question posée (reposée après une digression)
    safety_queue: list[str] = field(default_factory=list)
    safety_pending: str | None = None
    safety_retries: int = 0
    failed_clarifications: int = 0
    unrecognised_turns: int = 0
    audio_failures: int = 0
    slot_options: dict[str, list[str]] = field(default_factory=dict)   # alternatives proposées par l'outil
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
        self._sans_llm = False      # vrai pendant un tour où le LLM a échoué (repli sur les règles)

    @property
    def llm_first(self) -> bool:
        return self.pack.llm.mode == "llm_first" and self.gateway is not None

    @classmethod
    def from_domain(cls, domain: str, gateway: LLMGateway | None | str = "env", **kw) -> Orchestrator:
        return cls(load_domain(domain), gateway_from_env() if gateway == "env" else gateway, **kw)

    # ================================================================== tour ==================
    def warmup(self) -> None:
        """Charge à l'avance ce qui est chargé à la demande (modèle d'embeddings de la FAQ) :
        à appeler au démarrage d'un canal, pour que le premier tour ne paie pas le chargement."""
        if self.retriever is not None:
            self.retriever.search("bonjour", k=1)

    def start(self) -> str:
        self.state.history.append({"role": "agent", "text": self.pack.persona.greeting})
        return self.pack.persona.greeting

    def handle_text(self, text: str) -> TurnResult:
        s = self.state
        s.turn += 1
        s.audio_failures = 0                                    # entrée comprise : compteur remis à zéro
        if self.gateway:
            self.gateway.begin_turn(f"{s.session_id}:{s.turn}", self.policy.max_llm_calls_per_turn)
        s.history.append({"role": "user", "text": text})
        self._sans_llm = False
        trace: dict[str, Any] = {"turn": s.turn, "mode": "llm_first" if self.llm_first else "rules_first"}
        log.info("tour %d (%s, %d car.)", s.turn, trace["mode"], len(text))
        if s.escalation:                                        # déjà transféré
            return self._result(self.pack.persona.handoff_message, trace)

        scores = {sig.id: sig.score(text) for sig in self.signals}   # 1. signaux
        trace["signals"] = scores
        if self.guard.wants_human(text):                        # 2. humain demandé
            return self._escalate(Escalation("explicit_request"), trace)
        if s.safety_pending:                                    # 3. script de sécurité
            return self._safety_answer(text, trace)
        if s.awaiting_confirmation:                             # 4. confirmation
            # Oui / non nets : règles. Réponse floue (« oui mais plutôt à 10 h ») : le LLM en mode llm_first
            if not self.llm_first or self.safety.parse_answer(text) != "unclear":
                return self._confirmation_answer(text, trace)

        route = self.router.route(text)                         # 5. intention
        trace["route"] = asdict(route)
        if self.llm_first:
            r = self._llm_turn(text, route, scores, trace)
            if r is not None:
                return r
            self._sans_llm = True                               # LLM indisponible : ce tour suit les règles
            if s.awaiting_confirmation:
                return self._confirmation_answer(text, trace)
        intent = route.intent
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
            if self.retriever is not None:                      # aucune règle : la FAQ a peut-être la réponse
                return self._knowledge(text, trace)
            return self._unrecognised(trace)
        if handler == "knowledge":
            return self._knowledge(text, trace)
        return self._workflow_turn(intent, handler.split(":", 1)[1], text, scores, trace)

    def handle_unusable_input(self, retry_message: str) -> TurnResult:
        """Entrée inexploitable (audio vide, inaudible...) : on redemande, puis transfert
        après escalation.max_audio_failures échecs consécutifs."""
        s = self.state
        s.turn += 1
        s.audio_failures += 1
        s.history.append({"role": "user", "text": "[entrée inexploitable]"})
        trace = {"turn": s.turn, "unusable_input": s.audio_failures}
        if e := self.escalation_policy.from_counters(0, 0, s.audio_failures):
            return self._escalate(e, trace)
        return self._result(retry_message, trace)

    # ================================================================== branches ==============
    def _knowledge(self, text: str, trace: dict) -> TurnResult:
        """Fiche lue mot pour mot. Zone « direct » : 0 appel LLM. Zone grise : l'appel LLM du
        tour choisit parmi les meilleures fiches, ou aucune ; on lit alors la fiche choisie,
        jamais un texte rédigé par le LLM."""
        if self.retriever is None:
            return self._unrecognised(trace)
        d = self.retriever.decide(text)
        trace["knowledge"] = {"zone": d.zone, "hits": [(h.id, h.score) for h in d.hits]}
        fiche = d.best if d.zone == "direct" else None
        if d.zone == "grey" and self.gateway is not None and not self._sans_llm:
            ctx = TurnContext(text=text, intent=self.state.intent or self.router.route(text).intent,
                              rules_reply=self.pack.persona.fallback_message, needs_llm=True,
                              knowledge=[{"id": h.id, "question": h.question, "reponse": h.answer} for h in d.hits],
                              knowledge_ids=[h.id for h in d.hits], history=self.state.history[:-1])
            decision = self.policy.decide(ctx)
            trace["agent"] = {"llm_used": decision.llm_used, "fallback": decision.fallback,
                              "knowledge_id": decision.knowledge_id}
            if decision.escalate:
                return self._escalate(Escalation("agent_requested", decision.escalate_reason), trace)
            fiche = next((h for h in d.hits if h.id == decision.knowledge_id), None)
        if fiche is None:
            return self._unrecognised(trace)
        reply = fiche.answer
        if self.state.run and self.state.last_question:
            reply += " " + self.state.last_question            # on revient au workflow en cours
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

        if s.pending_slot in s.slot_options and not self.llm_first:
            # sans LLM, « la première » / « la deuxième » désigne une des options proposées
            if (choix := _option_choisie(text, s.slot_options[s.pending_slot])) is not None:
                text = choix
        regles = {}                                              # réponse brute au slot demandé
        if s.pending_slot and (slot_item is None or s.pending_slot != slot_item.name):
            regles[s.pending_slot] = text
        trace["slot_errors"] = self.workflows.set_slots(run, regles)
        if s.pending_slot and s.pending_slot in trace["slot_errors"] and self._sans_llm is False and self.gateway is None:
            s.failed_clarifications += 1                         # sans LLM : réponse non comprise au slot demandé

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

    def _next_step(self, trace: dict, reply: str | None = None, resolution: Resolution | None = None,
                   asks_for: str | None = None, conversational: bool = False, answered: bool = False) -> TurnResult:
        """Le SYSTÈME choisit l'étape suivante ; le LLM ne fait que formuler la réponse.

        conversational (llm_first) : la réponse du LLM est gardée si elle demande une
        information réellement manquante (asks_for) ; sinon le système pose sa propre question
        (précédée de la réponse du LLM si celle-ci répondait à une question d'information)."""
        s, run = self.state, self.state.run
        s.pending_clarification = False
        if s.safety_queue:                                       # scripts de sécurité d'abord
            return self._ask_safety(trace)
        manquants = self.workflows.missing(run)
        if manquants and conversational:
            noms = {m.name: m for m in manquants}
            ambigu = resolution is not None and resolution.status == "ambiguous" and resolution.question
            if asks_for in noms and reply:
                s.pending_slot = asks_for
                s.pending_clarification = bool(ambigu and noms[asks_for].type == "catalogue_item")
                return self._result(reply, trace, question=True)
            manquant = manquants[0]
            s.pending_slot = manquant.name
            question = manquant.prompt
            if manquant.type == "catalogue_item" and ambigu:
                s.pending_clarification, s.pending_slot, question = True, None, resolution.question
            elif manquant.type == "catalogue_item" and resolution is not None and resolution.status == "infeasible":
                question = f"{self.pack.persona.not_found_message} {manquant.prompt}"
            texte = f"{reply} {question}" if answered and reply else question
            return self._result(texte, trace, question=True)
        manquant = manquants[0] if manquants else None
        if manquant is not None:
            s.pending_slot = manquant.name
            if manquant.type == "catalogue_item" and resolution is not None and not reply:
                if resolution.status == "ambiguous" and resolution.question:
                    s.pending_clarification = True
                    s.pending_slot = None
                    return self._result(resolution.question, trace, question=True)
                if resolution.status == "infeasible":
                    return self._result(f"{self.pack.persona.not_found_message} {manquant.prompt}", trace)
            return self._result(reply or manquant.prompt, trace, question=True)
        s.pending_slot = None
        if (pb := self.workflows.precheck(run)) is not None:    # l'outil refuserait : on redemande
            trace["precheck"] = pb
            log.info("vérification de l'outil : refus (%s), %d alternative(s)", pb["reason"], len(pb["options"]))
            slot = next((x for x in self.workflows.spec(run).slots if x.name == pb["slot"]), None)
            s.pending_slot = pb["slot"]
            if pb["options"] and pb["slot"]:
                s.slot_options[pb["slot"]] = pb["options"]
                texte = self.pack.persona.unavailable_message.format(options=self._dire_options(pb["options"]))
            else:
                texte = f"{pb['reason'][:1].upper()}{pb['reason'][1:]}. {slot.prompt if slot else ''}".strip()
            if not slot:                                         # problème non rattaché à un slot : humain
                return self._escalate(Escalation("tool_error", pb["reason"]), trace)
            return self._result(texte, trace, question=True)
        if (texte := self.workflows.confirmation_text(run)) is not None:
            s.awaiting_confirmation = True
            return self._result(texte, trace, question=True)
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
        besoin = self.gateway is not None and clarification is None and not self._sans_llm
        return TurnContext(
            text=text, intent=intent, rules_reply=regles or self.pack.persona.fallback_message, needs_llm=besoin,
            workflow=spec.id, slot_names=[x.name for x in spec.slots if x.type != "catalogue_item"],
            filled_slots={k: v for k, v in run.slots.items() if v}, candidates=candidats, candidate_details=details,
            next_slot={"name": manquant.name, "prompt": manquant.prompt} if manquant else None,
            clarification=clarification, history=s.history[:-1], signals=scores)

    # ================================================================== mode llm_first ========
    def _llm_turn(self, text: str, route, scores: dict, trace: dict) -> TurnResult | None:
        """Le LLM comprend le tour (un appel). None si le LLM est indisponible : l'appelant
        reprend alors le chemin des règles pour ce tour."""
        s = self.state
        if v := self.guard.check_strong(text):                  # motifs forts : jamais par le LLM
            return self._escalate(Escalation("out_of_scope", v.rule_id), trace)
        if e := self.escalation_policy.from_signals(scores):
            return self._escalate(e, trace)
        alerte = self.guard.check(text, route.intent if route.matched else None)   # motif faible -> au LLM

        fiches = self._fiches_pour_llm(text)
        trace["knowledge"] = {"provided": [f["id"] for f in fiches]}
        run = s.run
        resolution: Resolution | None = None
        if self.resolver and (run is None or (self.workflows.item_slot(run) and run.item is None)):
            resolution = self.resolver.resolve(text, s.resolution_context if run else {})
        if run is not None and run.item is not None:
            candidats = [run.item["id"]]
        elif resolution is not None and resolution.status != "unknown":
            candidats = (resolution.candidates if resolution.status == "ambiguous"
                         else self.resolver.candidates_for_llm(resolution, text))
        elif run is not None and self.workflows.item_slot(run):
            candidats = self.resolver.candidates_for_llm(resolution, text) if resolution else []
        else:
            candidats = []
        details = [{"code": c, "libelle": self.catalogue.by_id[c].label, **self.catalogue.by_id[c].attributes}
                   for c in candidats] if self.catalogue else []
        clarification = resolution.question if resolution and resolution.status == "ambiguous" else None

        manquants = self.workflows.missing(run) if run else []
        tous_slots = [x for w in self.pack.workflows for x in w.slots]
        extra = {
            "date_et_heure_actuelles": dates.maintenant_pour_llm(),
            "indice_des_regles": route.intent if route.matched else None,
            "alerte_perimetre": self.guard.rule(alerte.rule_id).description if alerte else None,
            "element_choisi": run.item.get("libelle") if run and run.item else None,
            "informations_manquantes": [m.name for m in manquants],
            "question_posee_au_tour_precedent": s.last_question if run else None,
            "options_proposees": {k: [{"valeur": o, "dit": dates.dire(o, self.pack.language)} for o in v]
                                  for k, v in s.slot_options.items()},
            "recapitulatif_en_attente": self.workflows.confirmation_text(run) if s.awaiting_confirmation else None,
        }
        ctx = TurnContext(
            text=text, intent=s.intent or route.intent, rules_reply=self.pack.persona.fallback_message,
            needs_llm=True, conversational=True, workflow=run.workflow_id if run else None,
            slot_names=list(dict.fromkeys(x.name for x in tous_slots if x.type != "catalogue_item")),
            askable_slots=list(dict.fromkeys(x.name for x in tous_slots)),
            filled_slots={k: v for k, v in (run.slots if run else {}).items() if v},
            next_slot={"name": manquants[0].name, "prompt": manquants[0].prompt} if manquants else None,
            candidates=candidats, candidate_details=details, clarification=clarification,
            knowledge=fiches, knowledge_ids=[f["id"] for f in fiches], history=s.history[:-1], signals=scores,
            extra=extra)
        d = self.policy.decide(ctx)
        trace["agent"] = {"llm_used": d.llm_used, "fallback": d.fallback, "intent": d.intent,
                          "understood": d.understood, "sources": d.sources, "asks_for": d.asks_for,
                          "slots": sorted(k for k, v in d.slots.items() if v)}
        if not d.llm_used:
            log.info("LLM indisponible : le tour continue avec les règles")
            trace["llm_failure"] = d.fallback
            return None
        log.info("LLM : intention=%s compris=%s sources=%s demande=%s escalade=%s", d.intent, d.understood,
                 d.sources, d.asks_for, d.escalate)
        if d.escalate:
            return self._escalate(Escalation("agent_requested", d.escalate_reason), trace)
        s.awaiting_confirmation = False

        handler = self.pack.intent(d.intent).handler
        if handler.startswith("workflow:"):
            wid = handler.split(":", 1)[1]
            if s.run is None or s.run.workflow_id != wid:
                if s.run is not None:
                    trace["workflow_switch"] = {"from": s.run.workflow_id, "to": wid}
                s.run, s.intent = self.workflows.start(wid), d.intent
                s.resolution_context, s.candidates, s.pending_slot, s.slot_options = {}, [], None, {}
                s.failed_clarifications = 0
                if resolution is None and self.resolver and self.workflows.item_slot(s.run):
                    resolution = self.resolver.resolve(text, {})
            s.unrecognised_turns = 0
            return self._workflow_llm(text, d, resolution, ctx, trace)

        # Pas une démarche : information, salutation, hors sujet...
        if not d.understood:
            s.unrecognised_turns += 1
            if e := self.escalation_policy.from_counters(0, s.unrecognised_turns, s.audio_failures):
                return self._escalate(e, trace)
        else:
            s.unrecognised_turns = 0
        reply = self._reponse_fondee(d, ctx, trace, handler == "knowledge")
        if s.run is not None:                                   # digression : on revient à la démarche
            return self._next_step(trace, reply=reply, asks_for=d.asks_for, conversational=True, answered=True)
        return self._result(reply, trace, question=reply.rstrip().endswith("?"))

    def _fiches_pour_llm(self, text: str) -> list[dict]:
        if self.retriever is None or self.pack.knowledge is None:
            return []
        k = self.pack.knowledge
        if k.llm_context == "all":
            df = self.retriever_df()
            return [{"id": r[k.id_column], "question": r[k.question_column], "reponse": r[k.answer_column]}
                    for _, r in df.iterrows()]
        return [{"id": h.id, "question": h.question, "reponse": h.answer}
                for h in self.retriever.search(text, k=k.llm_top_k)]

    def retriever_df(self):
        r = self.retriever
        return getattr(r, "df", None) if hasattr(r, "df") else r.lexical.df

    def _reponse_fondee(self, d, ctx: TurnContext, trace: dict, question_d_information: bool) -> str:
        """La réponse du LLM n'est gardée pour une question d'information que si elle cite des
        fiches réellement fournies ; en mode verbatim, on lit la fiche citée mot pour mot."""
        sources = [x for x in d.sources if x in ctx.knowledge_ids]
        trace["knowledge"]["used"] = sources
        k = self.pack.knowledge
        if k is not None and k.answer_mode == "verbatim" and sources:
            return next(f["reponse"] for f in ctx.knowledge if f["id"] == sources[0])
        if question_d_information and not sources:
            log.info("réponse d'information sans source : message « pas d'information »")
            trace["knowledge"]["unsupported"] = True
            return self.pack.persona.no_answer_message
        return d.reply

    def _workflow_llm(self, text: str, d, resolution: Resolution | None, ctx: TurnContext, trace: dict) -> TurnResult:
        s, run = self.state, self.state.run
        slot_item = self.workflows.item_slot(run)
        if slot_item and run.item is None and self.resolver:
            if resolution is not None:
                s.resolution_context = {**s.resolution_context, **resolution.context}
                trace["resolution"] = {"status": resolution.status, "item": resolution.item_id,
                                       "candidates": resolution.candidates[:10], "confidence": resolution.confidence}
            if resolution is not None and resolution.item_id:
                self._set_item(resolution.item_id)
            elif d.item_code and d.item_code in ctx.candidates and d.item_code in self.catalogue.by_id:
                self._set_item(d.item_code)                     # revalidation D3
                trace["item_source"] = "llm"
            elif resolution is not None:
                s.candidates = resolution.candidates
                if resolution.status == "ambiguous" and s.pending_clarification:
                    s.failed_clarifications += 1
        valeurs = {k: v for k, v in d.slots.items() if v}
        for nom, v in list(valeurs.items()):                    # « la deuxième » -> option proposée
            if nom in s.slot_options and (choix := _option_choisie(v, s.slot_options[nom])) is not None:
                valeurs[nom] = choix
        erreurs = self.workflows.set_slots(run, valeurs)
        for nom in valeurs:
            if nom not in erreurs:
                s.slot_options.pop(nom, None)
        if erreurs:
            trace["slot_errors"] = erreurs
            log.info("valeurs refusées par la validation : %s", sorted(erreurs))
        if e := self.escalation_policy.from_counters(s.failed_clarifications, s.unrecognised_turns, s.audio_failures):
            return self._escalate(e, trace)
        return self._next_step(trace, reply=d.reply, resolution=resolution, asks_for=d.asks_for,
                               conversational=True, answered=bool(d.sources))

    def _dire_options(self, options: list[str]) -> str:
        dits = [dates.dire(o, self.pack.language) for o in options]
        j = self.pack.catalogue.options_joiner if self.pack.catalogue else " ou "
        return dits[0] if len(dits) == 1 else ", ".join(dits[:-1]) + j + dits[-1]

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
        return self._result(self.safety.get(s.safety_pending).question, trace, question=True)

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
        log.info("action finale réussie (%s)", s.run.workflow_id)
        s.run, s.intent, s.candidates, s.resolution_context, s.slot_options = None, None, [], {}, {}
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

    def _result(self, reply: str, trace: dict, question: bool = False) -> TurnResult:
        s = self.state
        s.history.append({"role": "agent", "text": reply})
        if question:
            s.last_question = reply
        appels = self.gateway.calls_this_turn() if self.gateway else 0
        log.info("réponse prête (%d car., %d appel(s) LLM%s)", len(reply), appels,
                 f", transfert : {s.escalation.reason}" if s.escalation else "")
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
