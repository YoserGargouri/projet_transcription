"""Base de connaissances : zones direct / grise / aucune, choix du LLM en zone grise, repli lexical."""
import numpy as np
import pytest

from agentkit.domain import load_domain
from agentkit.knowledge.retriever import Hit, HybridRetriever, zone_de
from agentkit.llm import LLMGateway
from agentkit.llm.providers import FakeLLM
from agentkit.orchestrator import Orchestrator


def _hits(*scores):
    return [Hit(id=f"Q{i}", question="", answer="", score=s) for i, s in enumerate(scores)]


def test_zones():
    k = load_domain("imagerie_medicale").knowledge                  # min_score 0.45, min_gap 0.13, marge 0.15
    assert zone_de(_hits(0.80, 0.50), k) == "direct"
    assert zone_de(_hits(0.80, 0.75), k) == "grey"                   # deux fiches presque à égalité
    assert zone_de(_hits(0.35, 0.10), k) == "grey"                   # pas assez sûre, mais proche du seuil
    assert zone_de(_hits(0.20, 0.10), k) == "none"


class EncodeurEnPanne:
    def encode(self, textes):
        raise OSError("modèle absent (hors ligne)")


def test_repli_lexical_si_embeddings_indisponibles():
    r = HybridRetriever(load_domain("imagerie_medicale"), encoder=EncodeurEnPanne())
    assert r.search("vous prenez la carte vitale ?", k=1)[0].id == "F14" and r.degrade


class EncodeurFactice:
    """Encodeur déterministe (sac de mots) : teste l'hybride sans modèle téléchargé."""

    def encode(self, textes):
        v = np.array([[hash(m) % 97 in {hash(x) % 97 for x in t.lower().split()} for m in range(97)]
                      for t in textes], dtype=np.float32)
        return v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)


def test_hybride_avec_encodeur_injecte():
    r = HybridRetriever(load_domain("imagerie_medicale"), encoder=EncodeurFactice())
    assert r.search("vous prenez la carte vitale", k=1)[0].id == "F14" and not r.degrade


def _orch_zone_grise(reponse_llm):
    """Imagerie, FAQ forcée en zone grise ; le LLM simulé choisit (ou non) une fiche."""
    pack = load_domain("imagerie_medicale")
    fake = FakeLLM([reponse_llm] if not callable(reponse_llm) else reponse_llm)
    o = Orchestrator(pack, gateway=LLMGateway(fake))
    o.retriever = HybridRetriever(pack, encoder=EncodeurEnPanne())   # lexical, déterministe
    o.retriever.spec = pack.knowledge.model_copy(update={"min_score": 1.01, "llm_margin": 1.01})  # tout en zone grise
    return o, fake


BASE = {"intent": "info_generale", "slots": {}, "item_code": None, "reply": "x", "sentiment": "neutre",
        "escalate": {"needed": False, "reason": ""}}


def test_zone_grise_le_llm_choisit_une_fiche_lue_mot_pour_mot():
    o, fake = _orch_zone_grise(lambda msgs, schema: {**BASE, "knowledge_id": schema["properties"]["knowledge_id"]
                                                     ["anyOf"][0]["enum"][0], "reply": "texte inventé"})
    r = o.handle_text("Vous êtes ouverts le samedi ?")
    assert r.llm_calls == 1 and r.trace["knowledge"]["zone"] == "grey"
    fiche = o.retriever.lexical.df.set_index("id").loc[r.trace["agent"]["knowledge_id"], "reponse"]
    assert r.reply == fiche and "inventé" not in r.reply            # jamais le texte du LLM


def test_zone_grise_aucune_fiche_ne_convient():
    o, _ = _orch_zone_grise({**BASE, "knowledge_id": None})
    r = o.handle_text("Vous êtes ouverts le samedi ?")
    assert r.reply == o.pack.persona.fallback_message


def test_zone_grise_fiche_hors_liste_refusee():
    o, _ = _orch_zone_grise({**BASE, "knowledge_id": "F99"})
    r = o.handle_text("Vous êtes ouverts le samedi ?")
    assert r.reply == o.pack.persona.fallback_message and r.trace["agent"]["knowledge_id"] is None
