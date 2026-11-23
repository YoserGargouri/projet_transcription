"""
Contrat de sortie de l'unique appel LLM d'un tour, généré à partir du pack (D3).

Le modèle pydantic est construit à CHAQUE tour :
    intent    ∈ intentions du pack
    slots     ∈ slots du workflow en cours (sauf l'élément du catalogue)
    item_code ∈ candidats de CE tour, ou null — jamais un code hors candidats
    knowledge_id ∈ fiches proposées ce tour (zone grise de la FAQ), ou null
    tool_call ∈ outils enregistrés, ou null
    (mode llm_first : understood, sources ⊆ fiches fournies, asks_for ∈ slots ; voir plus bas)
    reply, sentiment, escalate {needed, reason}

On ne compte pas sur le fournisseur pour respecter l'énumération : la passerelle valide avec
pydantic, redemande une fois, puis la politique remet item_code à null (voir agent.policy).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

SENTIMENTS = ("positif", "neutre", "negatif")


class EscalateFlag(BaseModel):
    model_config = ConfigDict(extra="forbid")
    needed: bool = False
    reason: str = ""


def _litteral(valeurs):
    return Literal[tuple(valeurs)]  # type: ignore[valid-type]


def build_agent_output_model(intents: list[str], slot_names: list[str], candidates: list[str],
                             tools: dict[str, list[str]] | None = None,
                             knowledge_ids: list[str] | None = None, *, conversational: bool = False,
                             askable_slots: list[str] | None = None) -> type[BaseModel]:
    """tools : nom d'outil -> actions autorisées (vide = pas d'appel d'outil par le LLM).

    conversational (mode llm_first) : le LLM comprend tout le tour. Au lieu de knowledge_id
    (choix d'UNE fiche lue mot pour mot), il renvoie :
        understood  false s'il n'a pas compris la demande (compte pour le transfert)
        sources     fiches de la base sur lesquelles s'appuie sa réponse (∈ fiches fournies)
        asks_for    l'information que sa réponse demande (∈ slots), pour que le système
                    sache à quoi correspondra la réponse suivante
    """
    stricte = ConfigDict(extra="forbid")
    if conversational:
        return _modele_conversationnel(intents, slot_names, candidates, knowledge_ids or [], askable_slots or [])
    Slots = create_model("Slots", __config__=stricte, **{n: (str | None, None) for n in slot_names})
    type_item = (_litteral(candidates) | None) if candidates else type(None)
    if tools:
        ToolCall = create_model("ToolCall", __config__=stricte, tool=(_litteral(list(tools)), ...),
                                action=(_litteral(sorted({a for acts in tools.values() for a in acts})), ...),
                                arguments=(dict[str, Any], Field(default_factory=dict)))
        type_outil = ToolCall | None
    else:
        type_outil = type(None)
    return create_model(
        "AgentOutput", __config__=stricte,
        intent=(_litteral(intents), ...),
        slots=(Slots, Field(default_factory=Slots)),
        item_code=(type_item, None),
        knowledge_id=((_litteral(knowledge_ids) | None) if knowledge_ids else type(None), None),
        tool_call=(type_outil, None),
        reply=(str, Field(min_length=1)),
        sentiment=(_litteral(SENTIMENTS), "neutre"),
        escalate=(EscalateFlag, Field(default_factory=EscalateFlag)),
    )


def _modele_conversationnel(intents, slot_names, candidates, knowledge_ids, askable_slots):
    stricte = ConfigDict(extra="forbid")
    Slots = create_model("Slots", __config__=stricte, **{n: (str | None, None) for n in slot_names})
    champs: dict[str, Any] = {
        "intent": (_litteral(intents), ...),
        "understood": (bool, True),
        "slots": (Slots, Field(default_factory=Slots)),
        "item_code": ((_litteral(candidates) | None) if candidates else type(None), None),
    }
    if knowledge_ids:
        champs["sources"] = (list[_litteral(knowledge_ids)], Field(default_factory=list))
    champs["asks_for"] = ((_litteral(askable_slots) | None) if askable_slots else type(None), None)
    # Écrite AVANT reply (les champs sont générés dans l'ordre) : le modèle pose les faits avant de
    # répondre, ce qui évite les réponses contradictoires des petits modèles. Jamais dite à l'utilisateur.
    champs["analysis"] = (str, Field("", max_length=400))
    champs["reply"] = (str, Field(min_length=1))
    champs["sentiment"] = (_litteral(SENTIMENTS), "neutre")
    champs["escalate"] = (EscalateFlag, Field(default_factory=EscalateFlag))
    return create_model("AgentOutput", __config__=stricte, **champs)
