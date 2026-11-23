"""
Encodeur de phrases multilingue (sentence-transformers), chargé à la première utilisation.

Le modèle (≈ 470 Mo pour paraphrase-multilingual-MiniLM-L12-v2) est téléchargé une fois
depuis Hugging Face puis lu depuis le cache local. Les vecteurs sont normalisés : le produit
scalaire est la similarité cosinus.
"""
from __future__ import annotations

import numpy as np

_modeles: dict[str, object] = {}


class Encoder:
    def __init__(self, model_name: str):
        self.model_name = model_name

    def _modele(self):
        if self.model_name not in _modeles:
            from sentence_transformers import SentenceTransformer

            _modeles[self.model_name] = SentenceTransformer(self.model_name, device="cpu")
        return _modeles[self.model_name]

    def encode(self, textes: list[str]) -> np.ndarray:
        return self._modele().encode(list(textes), batch_size=64, normalize_embeddings=True,
                                     convert_to_numpy=True, show_progress_bar=False).astype(np.float32)
