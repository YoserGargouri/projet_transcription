"""
Contrat de sortie de l'unique appel LLM d'un tour, généré à partir du pack (D3).

Le modèle pydantic est construit à CHAQUE tour :
    intent    ∈ intentions du pack
    slots     ∈ slots du workflow en cours (sauf l'élément du catalogue)
    item_code ∈ candidats de CE tour, ou null — jamais un code hors candidats
    tool_call ∈ outils enregistrés, ou null
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
                             tools: dict[str, list[str]] | None = None) -> type[BaseModel]:
    """tools : nom d'outil -> actions autorisées (vide = pas d'appel d'outil par le LLM)."""
    stricte = ConfigDict(extra="forbid")
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
        tool_call=(type_outil, None),
        reply=(str, Field(min_length=1)),
        sentiment=(_litteral(SENTIMENTS), "neutre"),
        escalate=(EscalateFlag, Field(default_factory=EscalateFlag)),
    )
