"""
Contrat d'un pack de domaine (domain.yaml), validé par pydantic.

Ce schéma est LE contrat entre le moteur et le métier : tout ce que le moteur sait d'un
domaine passe par lui. Un futur générateur (« prompt client -> pack de domaine ») devra
produire un YAML valide pour ce schéma ; DomainPack.model_json_schema() fournit le schéma
JSON à lui donner. Chaque champ est documenté dans docs/architecture.md.

Règles générales :
- extra="forbid" partout : une clé inconnue (faute de frappe) est une erreur, pas un oubli silencieux ;
- les chemins de fichiers sont relatifs au dossier du pack ;
- les motifs (patterns) sont des expressions régulières appliquées au texte normalisé
  (minuscules, sans accents ni ponctuation, voir agentkit.nlu.text.normalise).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator

SCHEMA_VERSION = 1
SlotType = Literal["catalogue_item", "text", "date", "time", "datetime", "phone", "email",
                   "choice", "yes_no", "reference", "number"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _regex_valides(motifs: list[str]) -> list[str]:
    for m in motifs:
        try:
            re.compile(m)
        except re.error as e:
            raise ValueError(f"motif invalide {m!r} : {e}") from e
    return motifs


# --- Persona et périmètre -------------------------------------------------------------------
class Persona(Strict):
    name: str = Field(description="Nom sous lequel l'agent se présente")
    greeting: str = Field(description="Premier message de l'appel")
    style: str = Field("", description="Consignes de ton et de forme données au LLM")
    handoff_message: str = Field(description="Message dit avant un transfert vers un humain")
    fallback_message: str = Field(description="Message quand la demande n'est pas comprise")
    goodbye_message: str = Field("Merci, au revoir.", description="Fin de conversation")


class ScopeRule(Strict):
    """Sujet interdit à l'agent : déclenche l'action (transfert humain par défaut)."""

    id: str
    description: str
    patterns: list[str] = Field(default_factory=list, description="Déclenchent toujours")
    weak_patterns: list[str] = Field(default_factory=list,
                                     description="Déclenchent sauf si l'intention détectée est dans except_if_intents")
    except_if_intents: list[str] = Field(default_factory=list)
    action: Literal["escalate"] = "escalate"

    _v = field_validator("patterns", "weak_patterns")(_regex_valides)


class Scope(Strict):
    description: str = Field(description="Ce que fait l'agent, en une phrase (injecté dans le prompt)")
    allowed: list[str] = Field(description="Sujets autorisés (injectés dans le prompt)")
    forbidden: list[ScopeRule] = Field(default_factory=list)
    human_request_patterns: list[str] = Field(default_factory=list,
                                              description="Demande explicite de parler à un humain")

    _v = field_validator("human_request_patterns")(_regex_valides)


# --- Intentions -----------------------------------------------------------------------------
class Intent(Strict):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    description: str
    handler: str = Field(description="workflow:<id> | knowledge | escalate")
    group: str | None = Field(None, description="Regroupement (ex. branche d'évaluation) ; par défaut l'id")
    patterns: list[str] = Field(default_factory=list, description="Règles du routeur (sans LLM)")
    examples: list[str] = Field(default_factory=list, description="Exemples (prompt, futur routeur appris)")
    priority: int = Field(0, description="Les intentions de priorité haute sont testées d'abord")
    default: bool = Field(False, description="Intention retenue si aucune règle ne s'applique (une seule)")

    _v = field_validator("patterns")(_regex_valides)

    @field_validator("handler")
    @classmethod
    def _handler(cls, v):
        if v not in ("knowledge", "escalate") and not re.fullmatch(r"workflow:[a-z0-9_]+", v):
            raise ValueError("handler attendu : workflow:<id>, knowledge ou escalate")
        return v


# --- Catalogue et résolution ----------------------------------------------------------------
class AttributeSpec(Strict):
    """Attribut d'un élément du catalogue. L'ordre des attributs dans la liste est l'ordre
    des filtres du résolveur (filtre A, filtre B...)."""

    name: str
    column: str = Field(description="Colonne du fichier catalogue")
    on_missing: Literal["ask", "default"] = Field(
        "ask", description="Si l'utilisateur ne le précise pas et que plusieurs valeurs restent possibles : "
                           "demander (ask) ou prendre la valeur par défaut (default). Une valeur unique "
                           "restante est toujours déduite sans question.")
    default: str | None = None
    not_applicable: list[str] = Field(default_factory=list,
                                      description="Valeurs « sans objet » (ex. pas de côté) : jamais demandées")
    question: str | None = Field(None, description="Question de désambiguïsation ; {options} = valeurs possibles")
    option_labels: dict[str, str] = Field(default_factory=dict, description="Libellé oral de chaque valeur")
    fuzzy: bool = Field(True, description="Recherche floue autorisée pour cet attribut")
    match_values: bool = Field(True, description="Reconnaître les valeurs brutes du catalogue comme formes "
                                                 "orales (false pour des codes comme G/D ou oui/non)")

    @model_validator(mode="after")
    def _coherence(self):
        if self.on_missing == "default" and self.default is None:
            raise ValueError(f"attribut {self.name} : on_missing=default demande une valeur default")
        if self.on_missing == "ask" and not self.question:
            raise ValueError(f"attribut {self.name} : on_missing=ask demande une question")
        if self.question and "{options}" not in self.question and self.on_missing == "ask":
            raise ValueError(f"attribut {self.name} : la question doit contenir {{options}}")
        return self


class FuzzySettings(Strict):
    min_score: int = Field(82, ge=50, le=100, description="Score RapidFuzz minimal (0-100)")
    min_length: int = Field(5, ge=2, description="Longueur minimale d'un mot comparé en flou")
    exclude_words: list[str] = Field(default_factory=list,
                                     description="Vrais mots jamais corrigés (ex. « endroit » ≠ « droit »)")


class ConfusionsSpec(Strict):
    file: str
    column_a: str
    column_b: str
    column_type: str
    column_question: str | None = None


class ConfidenceSettings(Strict):
    accept: float = Field(0.75, ge=0, le=1, description="Au-dessus : élément retenu")
    confirm: float = Field(0.5, ge=0, le=1, description="Entre confirm et accept : retenu mais à faire confirmer")
    confusable_penalty: float = Field(0.7, ge=0, le=1,
                                      description="Multiplicateur si l'élément a un jumeau confondable sur un "
                                                  "attribut reconnu en flou")
    default_penalty: float = Field(0.9, ge=0, le=1,
                                   description="Multiplicateur si le jumeau confondable diffère sur un attribut "
                                               "fixé par sa valeur par défaut")


class CatalogueSpec(Strict):
    file: str
    id_column: str
    label_column: str
    attributes: list[AttributeSpec] = Field(min_length=1)
    gazetteer: str | None = Field(None, description="YAML : attribut -> valeur -> formes orales")
    synonym_columns: list[str] = Field(default_factory=list)
    synonym_separator: str = ";"
    fuzzy: FuzzySettings = Field(default_factory=FuzzySettings)
    confusions: ConfusionsSpec | None = None
    confidence: ConfidenceSettings = Field(default_factory=ConfidenceSettings)
    shortlist_size: int = Field(15, ge=2, le=50, description="Candidats max montrés au LLM")
    options_joiner: str = Field(" ou ", description="Mot placé avant la dernière option d'une question")

    @model_validator(mode="after")
    def _noms_uniques(self):
        noms = [a.name for a in self.attributes]
        if len(noms) != len(set(noms)):
            raise ValueError("noms d'attributs en double")
        return self


class KnowledgeSpec(Strict):
    file: str
    id_column: str = "id"
    question_column: str = "question"
    answer_column: str = "reponse"
    variants_column: str | None = None
    variants_separator: str = "|"
    retriever: Literal["tfidf"] = "tfidf"
    min_score: float = Field(0.35, ge=0, le=1)


# --- Workflows ------------------------------------------------------------------------------
class SlotSpec(Strict):
    name: str = Field(pattern=r"^[a-z0-9_]+$")
    type: SlotType
    required: bool = True
    prompt: str = Field(description="Question posée pour obtenir la valeur")
    pii: bool = Field(False, description="Donnée personnelle : masquée dans les journaux")
    choices: list[str] | None = None
    pattern: str | None = Field(None, description="Validation supplémentaire (regex sur la valeur)")


class ToolCallSpec(Strict):
    tool: str
    action: str
    arguments: dict[str, str] = Field(default_factory=dict,
                                      description="Argument -> modèle, ex. « {slots.nom} », « {item.duree_min} »")


class WorkflowSpec(Strict):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    description: str
    slots: list[SlotSpec] = Field(min_length=1)
    confirmation: str | None = Field(None, description="Récapitulatif avant l'action finale ({slots.x}, {item.x})")
    on_complete: ToolCallSpec | None = None
    success_message: str | None = None

    @model_validator(mode="after")
    def _slots_uniques(self):
        noms = [s.name for s in self.slots]
        if len(noms) != len(set(noms)):
            raise ValueError(f"workflow {self.id} : slots en double")
        return self


# --- Outils, signaux, escalade, scripts de sécurité -------------------------------------------
class ToolSpec(Strict):
    name: str = Field(pattern=r"^[a-z0-9_]+$")
    builtin: str | None = Field(None, description="Outil fourni par le moteur (ex. calendar)")
    entrypoint: str | None = Field(None, description="Outil propre au pack : « tools/fichier.py:Classe »")
    description: str = ""
    config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _un_seul(self):
        if (self.builtin is None) == (self.entrypoint is None):
            raise ValueError(f"outil {self.name} : renseigner builtin OU entrypoint")
        if self.entrypoint and not re.fullmatch(r"tools/[\w/]+\.py:\w+", self.entrypoint):
            raise ValueError("entrypoint attendu : tools/<fichier>.py:<Classe> (dans le pack)")
        return self


class SignalSpec(Strict):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    kind: Literal["lexicon", "model"] = "lexicon"
    description: str = ""
    patterns: list[str] = Field(default_factory=list)
    model: str | None = Field(None, description="Chemin du modèle entraîné (kind=model)")
    threshold: float = Field(0.5, ge=0, le=1)

    _v = field_validator("patterns")(_regex_valides)


class EscalationSpec(Strict):
    max_failed_clarifications: int = Field(2, ge=1)
    max_audio_failures: int = Field(2, ge=1)
    max_unrecognised_turns: int = Field(2, ge=1)
    signal_thresholds: dict[str, float] = Field(default_factory=dict,
                                                description="Signal -> score déclenchant le transfert")


class SafetyScript(Strict):
    """Question fixe posée avant l'action, selon les attributs de l'élément choisi.
    Toute réponse positive part vers un humain : l'agent ne décide jamais seul."""

    id: str
    applies_if: dict[str, list[str]] = Field(description="Attribut -> valeurs déclenchant la question")
    question: str
    on_yes: Literal["escalate"] = "escalate"
    on_unclear: Literal["ask_again_once", "escalate"] = "ask_again_once"


class YesNoSpec(Strict):
    """Reconnaissance des réponses oui / non (scripts de sécurité, confirmations).
    Clés « positive » / « negative » et non « yes » / « no » : en YAML 1.1, yes et no
    sont lus comme des booléens."""

    positive: list[str]
    negative: list[str]

    _v = field_validator("positive", "negative")(_regex_valides)


# --- Canaux ---------------------------------------------------------------------------------
class SttSpec(Strict):
    engine: str = "whisper-small"


class TtsSpec(Strict):
    engine: Literal["elevenlabs", "gtts", "piper"] = "gtts"
    voice_id: str | None = None
    model_id: str | None = None
    fallback: list[Literal["elevenlabs", "gtts", "piper"]] = Field(default_factory=list)
    settings: dict[str, float | bool] = Field(default_factory=dict, description="Réglages de voix (stabilité...)")


class QualitySpec(Strict):
    min_duration_s: float = 0.4
    min_level_db: float = -45.0
    snr_bad_db: float = 5.0
    snr_medium_db: float = 12.0
    conf_bad: float = 0.45
    conf_medium: float = 0.70


class AudioChannelSpec(Strict):
    stt: SttSpec = Field(default_factory=SttSpec)
    tts: TtsSpec = Field(default_factory=TtsSpec)
    quality: QualitySpec = Field(default_factory=QualitySpec)
    retry_message: str = "Je ne vous ai pas bien entendu, pouvez-vous répéter ?"


class ChannelsSpec(Strict):
    audio: AudioChannelSpec | None = None


class LLMSpec(Strict):
    system_prompt: str = Field(description="Texte du prompt système, ou chemin d'un fichier du pack")
    max_history_turns: int = Field(6, ge=0)


class LoggingSpec(Strict):
    extra_patterns: list[str] = Field(default_factory=list, description="Motifs à masquer en plus des génériques")

    _v = field_validator("extra_patterns")(_regex_valides)


# --- Le pack ----------------------------------------------------------------------------------
class DomainPack(Strict):
    schema_version: Literal[1] = SCHEMA_VERSION
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str
    description: str
    language: str = Field(pattern=r"^[a-z]{2}$", description="Code ISO 639-1 (STT, TTS)")
    persona: Persona
    scope: Scope
    intents: list[Intent] = Field(min_length=1)
    catalogue: CatalogueSpec | None = None
    knowledge: KnowledgeSpec | None = None
    workflows: list[WorkflowSpec] = Field(default_factory=list,
                                          description="Définitions (le chargeur remplace les chemins par leur contenu)")
    tools: list[ToolSpec] = Field(default_factory=list)
    signals: list[SignalSpec] = Field(default_factory=list)
    escalation: EscalationSpec = Field(default_factory=EscalationSpec)
    safety_scripts: list[SafetyScript] = Field(default_factory=list)
    answers: YesNoSpec
    channels: ChannelsSpec = Field(default_factory=ChannelsSpec)
    llm: LLMSpec
    logging: LoggingSpec = Field(default_factory=LoggingSpec)

    _root: Path | None = PrivateAttr(default=None)

    # --- accès pratiques -------------------------------------------------------------------
    @property
    def root(self) -> Path:
        if self._root is None:
            raise RuntimeError("pack non chargé depuis un dossier (utiliser load_domain)")
        return self._root

    def path(self, relatif: str) -> Path:
        return self.root / relatif

    def intent(self, intent_id: str) -> Intent:
        return next(i for i in self.intents if i.id == intent_id)

    def workflow(self, workflow_id: str) -> WorkflowSpec:
        return next(w for w in self.workflows if w.id == workflow_id)

    @property
    def default_intent(self) -> Intent:
        return next(i for i in self.intents if i.default)

    # --- cohérence interne -----------------------------------------------------------------
    @model_validator(mode="after")
    def _references(self):
        ids = [i.id for i in self.intents]
        if len(ids) != len(set(ids)):
            raise ValueError("identifiants d'intention en double")
        if sum(i.default for i in self.intents) != 1:
            raise ValueError("il faut exactement une intention default: true")
        workflows = {w.id for w in self.workflows}
        if len(workflows) != len(self.workflows):
            raise ValueError("identifiants de workflow en double")
        for i in self.intents:
            if i.handler.startswith("workflow:") and i.handler.split(":", 1)[1] not in workflows:
                raise ValueError(f"intention {i.id} : workflow inconnu {i.handler}")
            if i.handler == "knowledge" and self.knowledge is None:
                raise ValueError(f"intention {i.id} : handler knowledge sans section knowledge")
        for r in self.scope.forbidden:
            inconnues = set(r.except_if_intents) - set(ids)
            if inconnues:
                raise ValueError(f"règle {r.id} : intentions inconnues {inconnues}")
        outils = {t.name for t in self.tools}
        if len(outils) != len(self.tools):
            raise ValueError("noms d'outils en double")
        for w in self.workflows:
            if w.on_complete and w.on_complete.tool not in outils:
                raise ValueError(f"workflow {w.id} : outil inconnu {w.on_complete.tool}")
            if any(s.type == "catalogue_item" for s in w.slots) and self.catalogue is None:
                raise ValueError(f"workflow {w.id} : slot catalogue_item sans section catalogue")
        attributs = {a.name for a in self.catalogue.attributes} if self.catalogue else set()
        for s in self.safety_scripts:
            inconnus = set(s.applies_if) - attributs
            if inconnus:
                raise ValueError(f"script {s.id} : attributs inconnus {inconnus}")
        signaux = {s.id for s in self.signals}
        inconnus = set(self.escalation.signal_thresholds) - signaux
        if inconnus:
            raise ValueError(f"escalation.signal_thresholds : signaux inconnus {inconnus}")
        return self
