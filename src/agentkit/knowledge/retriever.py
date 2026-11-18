"""
Base de connaissances (WP3, « RAG simple ») : on retrouve la fiche dont la question
ressemble le plus à celle de l'utilisateur, et on lit SA réponse, mot pour mot.
Rien n'est généré : l'agent ne peut pas inventer une information.

Baseline : TF-IDF sur n-grammes de caractères (robuste aux fautes et aux variantes), chaque
fiche indexée par sa question, ses variantes et « question + réponse » ; le score d'une
fiche est le meilleur de ses textes. TODO(WP3) : retriever par embeddings + score hybride.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
import pandas as pd

from agentkit.domain.schema import DomainPack
from agentkit.nlu.text import normalise


@dataclass
class Hit:
    id: str
    question: str
    answer: str
    score: float


class Retriever(ABC):
    min_score: float = 0.0

    @abstractmethod
    def search(self, query: str, k: int = 3) -> list[Hit]: ...

    def answer(self, query: str) -> Hit | None:
        """Meilleure fiche si elle dépasse le seuil du pack, sinon None (on ne répond pas)."""
        hits = self.search(query, k=1)
        return hits[0] if hits and hits[0].score >= self.min_score else None


class TfidfRetriever(Retriever):
    def __init__(self, pack: DomainPack):
        from sklearn.feature_extraction.text import TfidfVectorizer

        k = pack.knowledge
        self.min_score = k.min_score
        self.df = pd.read_csv(pack.path(k.file), dtype=str, keep_default_na=False)
        self._q, self._a, self._id = k.question_column, k.answer_column, k.id_column
        textes, fiches = [], []
        for i, f in self.df.iterrows():
            variantes = [v for v in f.get(k.variants_column, "").split(k.variants_separator) if v] if k.variants_column else []
            for t in [f[self._q], *variantes, f"{f[self._q]} {f[self._a]}"]:
                textes.append(normalise(t))
                fiches.append(i)
        self._fiches = np.array(fiches)
        self._vect = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5))
        self._index = self._vect.fit_transform(textes)

    def search(self, query: str, k: int = 3) -> list[Hit]:
        s = (self._index @ self._vect.transform([normalise(query)]).T).toarray().ravel()
        par_fiche = np.full(len(self.df), -1.0)
        np.maximum.at(par_fiche, self._fiches, s)
        ordre = np.argsort(-par_fiche)[:k]
        return [Hit(id=self.df.iloc[i][self._id], question=self.df.iloc[i][self._q],
                    answer=self.df.iloc[i][self._a], score=round(float(par_fiche[i]), 3)) for i in ordre]


def build_retriever(pack: DomainPack) -> Retriever | None:
    if pack.knowledge is None:
        return None
    return {"tfidf": TfidfRetriever}[pack.knowledge.retriever](pack)
