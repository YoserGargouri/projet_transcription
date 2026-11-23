"""
Base de connaissances (WP3, « RAG simple ») : on retrouve la fiche dont la question
ressemble le plus à celle de l'utilisateur, et on lit SA réponse, mot pour mot.
Rien n'est généré : l'agent ne peut pas inventer une information.

Chaque fiche est indexée par sa question, ses variantes et « question + réponse » ; le
score d'une fiche est le meilleur de ses textes. Trois méthodes (knowledge.retriever) :
    tfidf       n-grammes de caractères : robuste aux fautes, aveugle aux synonymes
    embeddings  sens de la phrase (modèle multilingue) : synonymes, mais confond
                « samedi » et « dimanche »
    hybrid      (1 - lexical_weight) × embeddings + lexical_weight × tfidf
Si le modèle d'embeddings ne peut pas être chargé (hors ligne au premier lancement...),
on se replie sur tfidf avec un avertissement : la conversation continue.
"""
from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
import pandas as pd

from agentkit.domain.schema import DomainPack, KnowledgeSpec
from agentkit.nlu.text import normalise

log = logging.getLogger(__name__)


@dataclass
class Hit:
    id: str
    question: str
    answer: str
    score: float


@dataclass
class KnowledgeDecision:
    zone: str            # "direct" (lecture sans LLM) | "grey" (le LLM choisit parmi hits) | "none"
    hits: list[Hit]

    @property
    def best(self) -> Hit | None:
        return self.hits[0] if self.hits else None


def zone_de(hits: list[Hit], spec: KnowledgeSpec) -> str:
    """Lecture directe seulement si la 1re fiche est assez sûre ET nettement devant la 2e."""
    if not hits:
        return "none"
    s1 = hits[0].score
    ecart = s1 - hits[1].score if len(hits) > 1 else 1.0
    if s1 >= spec.min_score and ecart >= spec.min_gap:
        return "direct"
    if s1 >= spec.min_score - spec.llm_margin:
        return "grey"
    return "none"


class Retriever(ABC):
    min_score: float = 0.0
    spec: KnowledgeSpec

    @abstractmethod
    def search(self, query: str, k: int = 3) -> list[Hit]: ...

    def decide(self, query: str) -> KnowledgeDecision:
        hits = self.search(query, k=max(2, self.spec.llm_top_k))
        return KnowledgeDecision(zone_de(hits, self.spec), hits[: self.spec.llm_top_k])

    def answer(self, query: str) -> Hit | None:
        """Fiche lue directement (zone « direct »), sinon None."""
        d = self.decide(query)
        return d.best if d.zone == "direct" else None


class _BaseFiches(Retriever):
    """Index commun : textes indexés et fiche correspondante."""

    def __init__(self, pack: DomainPack, spec: KnowledgeSpec | None = None):
        k = spec or pack.knowledge
        self.spec, self.min_score = k, k.min_score
        self.df = pd.read_csv(pack.path(k.file), dtype=str, keep_default_na=False)
        textes, fiches = [], []
        for i, f in self.df.iterrows():
            variantes = ([v for v in f.get(k.variants_column, "").split(k.variants_separator) if v]
                         if k.variants_column else [])
            for t in [f[k.question_column], *variantes, f"{f[k.question_column]} {f[k.answer_column]}"]:
                textes.append(t)
                fiches.append(i)
        self.textes, self._fiches = textes, np.array(fiches)

    @abstractmethod
    def _scores_textes(self, query: str) -> np.ndarray: ...

    def search(self, query: str, k: int = 3) -> list[Hit]:
        s = self._scores_textes(query)
        par_fiche = np.full(len(self.df), -1.0)
        np.maximum.at(par_fiche, self._fiches, s)
        ordre = np.argsort(-par_fiche)[:k]
        c = self.spec
        return [Hit(id=self.df.iloc[i][c.id_column], question=self.df.iloc[i][c.question_column],
                    answer=self.df.iloc[i][c.answer_column], score=round(float(par_fiche[i]), 3)) for i in ordre]


class TfidfRetriever(_BaseFiches):
    def __init__(self, pack, spec=None):
        super().__init__(pack, spec)
        from sklearn.feature_extraction.text import TfidfVectorizer

        self._vect = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5))
        self._index = self._vect.fit_transform([normalise(t) for t in self.textes])

    def _scores_textes(self, query):
        return (self._index @ self._vect.transform([normalise(query)]).T).toarray().ravel()


def _leger(t: str) -> str:
    """Normalisation légère pour les embeddings : minuscules, sans ponctuation, MAIS avec les
    accents (utiles au modèle). Sans elle, un simple « ? » déplaçait le score d'une fiche."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s'’-]", " ", t.lower())).strip()


class EmbeddingRetriever(_BaseFiches):
    def __init__(self, pack, spec=None, encoder=None):
        super().__init__(pack, spec)
        from agentkit.knowledge.embeddings import Encoder

        self.encoder = encoder or Encoder(self.spec.embeddings_model)
        self._vecteurs = None   # calculés à la première question (chargement du modèle différé)

    def _scores_textes(self, query):
        if self._vecteurs is None:
            self._vecteurs = self.encoder.encode([_leger(t) for t in self.textes])
        return self._vecteurs @ self.encoder.encode([_leger(query)])[0]


class HybridRetriever(Retriever):
    def __init__(self, pack, spec=None, encoder=None):
        self.lexical = TfidfRetriever(pack, spec)
        self.semantique = EmbeddingRetriever(pack, spec, encoder)
        self.spec, self.min_score = self.lexical.spec, self.lexical.spec.min_score
        self.degrade = False   # True si les embeddings sont indisponibles

    def search(self, query, k=3):
        lex = self.lexical._scores_textes(query)
        if not self.degrade:
            try:
                sem = self.semantique._scores_textes(query)
            except Exception as e:  # modèle absent hors ligne, mémoire... : on continue en lexical
                log.warning("embeddings indisponibles (%s) : repli sur la recherche lexicale", type(e).__name__)
                self.degrade = True
        w = self.spec.lexical_weight
        scores = lex if self.degrade else (1 - w) * sem + w * lex
        base = self.lexical
        par_fiche = np.full(len(base.df), -1.0)
        np.maximum.at(par_fiche, base._fiches, scores)
        ordre = np.argsort(-par_fiche)[:k]
        c = self.spec
        return [Hit(id=base.df.iloc[i][c.id_column], question=base.df.iloc[i][c.question_column],
                    answer=base.df.iloc[i][c.answer_column], score=round(float(par_fiche[i]), 3)) for i in ordre]


def build_retriever(pack: DomainPack, methode: str | None = None, encoder=None) -> Retriever | None:
    if pack.knowledge is None:
        return None
    methode = methode or pack.knowledge.retriever
    if methode == "tfidf":
        return TfidfRetriever(pack)
    if methode == "embeddings":
        return EmbeddingRetriever(pack, encoder=encoder)
    return HybridRetriever(pack, encoder=encoder)
