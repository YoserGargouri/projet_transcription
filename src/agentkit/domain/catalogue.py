"""
Données du catalogue d'un pack : éléments, attributs, gazetteer, paires confondables.

Le moteur ne connaît que des « éléments » ayant un identifiant, un libellé et des attributs
(colonnes déclarées dans domain.yaml). Ce que sont ces éléments (examens, vélos, voyages...)
ne regarde que le pack.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
import yaml

from agentkit.domain.schema import DomainPack
from agentkit.nlu.text import normalise


@dataclass
class Item:
    id: str
    label: str
    attributes: dict[str, str]                       # nom d'attribut -> valeur
    row: dict[str, str] = field(default_factory=dict)  # ligne complète du fichier (pour les modèles de texte)

    def as_context(self) -> dict[str, str]:
        """Champs utilisables dans les modèles de texte : {item.colonne}, {item.id}, {item.label}."""
        return {**self.row, "id": self.id, "label": self.label}


class Catalogue:
    def __init__(self, pack: DomainPack):
        if pack.catalogue is None:
            raise ValueError(f"le pack {pack.id} n'a pas de catalogue")
        self.spec = spec = pack.catalogue
        df = pd.read_csv(pack.path(spec.file), dtype=str, keep_default_na=False)
        self.items: list[Item] = [
            Item(id=r[spec.id_column], label=r[spec.label_column],
                 attributes={a.name: r[a.column] for a in spec.attributes}, row=dict(r))
            for r in df.to_dict("records")]
        self.by_id = {i.id: i for i in self.items}
        self.attributes = spec.attributes

        # Formes reconnues : formes orales du gazetteer + libellés d'options + (si match_values)
        # la valeur brute du catalogue
        gaz = yaml.safe_load(pack.path(spec.gazetteer).read_text(encoding="utf-8")) if spec.gazetteer else {}
        self.forms: dict[str, dict[str, str]] = {}      # attribut -> forme normalisée -> valeur
        for a in spec.attributes:
            formes = {}
            for valeur in dict.fromkeys(i.attributes[a.name] for i in self.items):
                if valeur in a.not_applicable:
                    continue
                orales = list((gaz.get(a.name) or {}).get(valeur) or [])
                if a.option_labels.get(valeur):
                    orales.append(a.option_labels[valeur])
                if a.match_values:
                    orales.append(valeur)
                for f in orales:
                    if normalise(f):
                        formes.setdefault(normalise(f), valeur)
            self.forms[a.name] = formes

        # Synonymes au niveau des éléments (pour la liste courte montrée au LLM)
        self.search_text = {
            i.id: normalise(" ".join([i.label, *(i.row.get(c, "").replace(spec.synonym_separator, " ")
                                                 for c in spec.synonym_columns)]))
            for i in self.items}

        # Paires confondables : le type de confusion est le nom de l'attribut qui diffère
        self.confusable: dict[str, set[str]] = {}       # id -> types de confusion
        if spec.confusions:
            c = spec.confusions
            conf = pd.read_csv(pack.path(c.file), dtype=str, keep_default_na=False)
            for a, b, t in conf[[c.column_a, c.column_b, c.column_type]].itertuples(index=False):
                self.confusable.setdefault(a, set()).add(t)
                self.confusable.setdefault(b, set()).add(t)

    def __len__(self):
        return len(self.items)
