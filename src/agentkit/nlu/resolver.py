"""
Résolveur de catalogue (WP4, bot niveau 1) : texte -> élément du catalogue, ou question.

    normalisation -> filtres par attribut, dans l'ordre déclaré par le pack (filtre A, B...)
    -> gazetteer (formes exactes) puis RapidFuzz (fautes de transcription)
    -> score de confiance (abaissé si l'élément a un « jumeau » confondable)
    -> candidats + question de clarification si plusieurs restent possibles

Le LLM n'intervient PAS ici en conversation : les candidats sont transmis à l'unique appel
LLM du tour (agent.policy.SingleCallPolicy). Pour mesurer le bot seul (« gazetteer seul vs
gazetteer + LLM »), l'évaluation hors ligne utilise llm_fallback().
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

from rapidfuzz import fuzz, process

from agentkit.domain.catalogue import Catalogue, Item
from agentkit.domain.schema import DomainPack
from agentkit.nlu.disambiguation import build_clarification
from agentkit.nlu.text import normalise

Status = Literal["resolved", "confirm", "ambiguous", "unknown", "infeasible"]


@dataclass
class Resolution:
    status: Status
    item_id: str | None = None
    candidates: list[str] = field(default_factory=list)
    confidence: float = 0.0
    question: str | None = None                 # clarification à poser (status ambiguous)
    ask_attribute: str | None = None
    detected: dict[str, dict[str, float]] = field(default_factory=dict)   # attribut -> valeur -> score
    context: dict[str, str] = field(default_factory=dict)   # valeurs acquises, réutilisées au tour suivant
    defaulted: list[str] = field(default_factory=list)       # attributs fixés par leur valeur par défaut


class Resolver(ABC):
    @abstractmethod
    def resolve(self, text: str, context: dict[str, str] | None = None) -> Resolution: ...


class CatalogueResolver(Resolver):
    def __init__(self, pack: DomainPack, catalogue: Catalogue | None = None, fuzzy: bool = True):
        self.pack = pack
        self.cat = catalogue or Catalogue(pack)
        self.spec = pack.catalogue
        self.fuzzy = fuzzy
        # Mots appartenant à une forme connue : jamais « corrigés » vers un autre attribut
        self._mots_connus = {m for formes in self.cat.forms.values() for f in formes for m in f.split()}
        self._exclus = {normalise(w) for w in self.spec.fuzzy.exclude_words}

    # ------------------------------------------------------------------ détection ---------
    def _detecter_attribut(self, mots: list[str], formes: dict[str, str], flou: bool) -> dict[str, float]:
        trouves: dict[str, float] = {}
        mots = list(mots)
        multi = sorted((f for f in formes if " " in f), key=len, reverse=True)
        for f in multi:                                            # 1. expressions exactes
            n, cible = len(f.split()), f.split()
            for i in range(len(mots) - n + 1):
                if mots[i:i + n] == cible:
                    trouves.setdefault(formes[f], 1.0)
                    mots[i:i + n] = ["#"] * n
        if flou:                                                   # 2. expressions floues
            for f in multi:
                n = len(f.split())
                for i in range(len(mots) - n + 1):
                    fenetre = mots[i:i + n]
                    if "#" in fenetre:
                        continue
                    score = fuzz.ratio(" ".join(fenetre), f)
                    if score >= max(self.spec.fuzzy.min_score, 88):
                        trouves[formes[f]] = max(trouves.get(formes[f], 0), score / 100)
                        mots[i:i + n] = ["#"] * n
        for i, m in enumerate(mots):                               # 3. mots exacts
            if m in formes:
                trouves.setdefault(formes[m], 1.0)
                mots[i] = "#"
        if flou and not trouves:                                   # 4. mots flous
            simples = [f for f in formes if " " not in f and len(f) >= self.spec.fuzzy.min_length]
            for m in set(mots):
                if len(m) < self.spec.fuzzy.min_length or m in self._mots_connus or m in self._exclus:
                    continue
                r = process.extractOne(m, simples, scorer=fuzz.ratio, score_cutoff=self.spec.fuzzy.min_score)
                if r:
                    v = formes[r[0]]
                    trouves[v] = max(trouves.get(v, 0), r[1] / 100)
        return trouves

    def detect(self, text: str) -> dict[str, dict[str, float]]:
        mots = normalise(text).split()
        return {a.name: d for a in self.spec.attributes
                if (d := self._detecter_attribut(mots, self.cat.forms[a.name], self.fuzzy and a.fuzzy))}

    # ------------------------------------------------------------------ résolution --------
    def resolve(self, text: str, context: dict[str, str] | None = None) -> Resolution:
        detecte = self.detect(text)
        ctx = dict(context or {})
        for attr, valeur in ctx.items():               # « le gauche » complète le tour précédent
            detecte.setdefault(attr, {valeur: 1.0})
        if not detecte:
            return Resolution(status="unknown", candidates=self.shortlist(text))

        items: list[Item] = self.cat.items
        for spec in self.spec.attributes:              # filtres dans l'ordre du pack
            valeurs = detecte.get(spec.name)
            if valeurs:
                sel = [i for i in items if i.attributes[spec.name] in valeurs]
                if not sel:                            # combinaison absente du catalogue
                    return Resolution(status="infeasible", detected=detecte,
                                      candidates=[i.id for i in items][: self.spec.shortlist_size])
                items = sel
        defauts = []
        for spec in self.spec.attributes:              # attributs non dits
            if spec.name in detecte:
                continue
            valeurs = {i.attributes[spec.name] for i in items}
            if len(valeurs) > 1 and spec.on_missing == "default" and spec.default in valeurs:
                items = [i for i in items if i.attributes[spec.name] == spec.default]
                defauts.append(spec.name)

        acquis = {a.name: items[0].attributes[a.name] for a in self.spec.attributes
                  if len({i.attributes[a.name] for i in items}) == 1}
        if len(items) > 1:
            q = build_clarification(items, self.spec.attributes, self.spec.options_joiner)
            return Resolution(status="ambiguous", candidates=[i.id for i in items], detected=detecte,
                              question=q.question if q else None, ask_attribute=q.attribute if q else None,
                              context=acquis, defaulted=defauts, confidence=0.0)

        item = items[0]
        confiance = 1.0
        for attr, valeurs in detecte.items():
            confiance *= max(valeurs.values())
        types = self.cat.confusable.get(item.id, set())
        if any(max(v.values()) < 1 for a, v in detecte.items() if a in types):
            confiance *= self.spec.confidence.confusable_penalty
        if set(defauts) & types:
            confiance *= self.spec.confidence.default_penalty
        confiance = round(confiance, 3)
        statut: Status = "resolved" if confiance >= self.spec.confidence.accept else "confirm"
        if confiance < self.spec.confidence.confirm:
            statut = "ambiguous"
        return Resolution(status=statut, item_id=item.id if statut != "ambiguous" else None,
                          candidates=[item.id], confidence=confiance, detected=detecte, context=acquis,
                          defaulted=defauts)

    # ------------------------------------------------------------------ liste courte / LLM --
    def shortlist(self, text: str, k: int | None = None) -> list[str]:
        """Éléments dont le libellé et les synonymes ressemblent le plus au texte."""
        k = k or self.spec.shortlist_size
        res = process.extract(normalise(text), self.cat.search_text, scorer=fuzz.token_set_ratio, limit=k)
        return [cle for _, _, cle in res]

    def candidates_for_llm(self, resolution: Resolution, text: str) -> list[str]:
        """Candidats montrés au LLM : ceux du résolveur, complétés par la liste courte."""
        cands = list(resolution.candidates)
        for c in self.shortlist(text):
            if len(cands) >= self.spec.shortlist_size:
                break
            if c not in cands:
                cands.append(c)
        return cands[: self.spec.shortlist_size]

    def llm_fallback(self, text: str, resolution: Resolution, gateway) -> Resolution:
        """Évaluation hors ligne SEULEMENT (WP4 : « gazetteer seul vs gazetteer + LLM »).
        En conversation, le secours est fusionné dans l'unique appel LLM de l'agent."""
        raise NotImplementedError("TODO(WP4) : appel LLM sur les candidats, pour l'évaluation du bot seul")
