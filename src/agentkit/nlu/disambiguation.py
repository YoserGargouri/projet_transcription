"""
Construction de la question de clarification quand plusieurs éléments restent possibles.

On cherche, dans l'ordre déclaré par le pack, le premier attribut « à demander » sur lequel
les candidats diffèrent, et on remplit son modèle de question avec les valeurs possibles :
    candidats = [X_gauche, X_droit]  ->  « Votre document précise-t-il le côté, gauche ou droit ? »
"""
from __future__ import annotations

from dataclasses import dataclass

from agentkit.domain.catalogue import Item
from agentkit.domain.schema import AttributeSpec


@dataclass
class Clarification:
    attribute: str
    question: str
    options: list[str]          # valeurs possibles (dans l'ordre du catalogue)


def differing_attributes(items: list[Item], specs: list[AttributeSpec]) -> list[AttributeSpec]:
    """Attributs « ask » sur lesquels les candidats diffèrent (hors valeurs sans objet)."""
    out = []
    for spec in specs:
        valeurs = {i.attributes[spec.name] for i in items} - set(spec.not_applicable)
        if spec.on_missing == "ask" and len(valeurs) > 1:
            out.append(spec)
    return out


def joindre(options: list[str], joiner: str) -> str:
    if len(options) == 1:
        return options[0]
    return ", ".join(options[:-1]) + joiner + options[-1]


def build_clarification(items: list[Item], specs: list[AttributeSpec], joiner: str = " ou ") -> Clarification | None:
    attributs = differing_attributes(items, specs)
    if not attributs:
        return None
    spec = attributs[0]
    valeurs = [v for v in dict.fromkeys(i.attributes[spec.name] for i in items) if v not in spec.not_applicable]
    libelles = [spec.option_labels.get(v, v) for v in valeurs]
    return Clarification(attribute=spec.name, question=spec.question.format(options=joindre(libelles, joiner)),
                         options=valeurs)
