"""Passerelle LLM : validation pydantic, nouvelle tentative, cache, budget, un appel par tour."""
from typing import Literal

import pytest
from pydantic import BaseModel

from agentkit.llm import BudgetExceeded, InvalidOutput, LLMGateway, TurnCallLimit
from agentkit.llm.cache import ResponseCache
from agentkit.llm.providers import FakeLLM


class Sortie(BaseModel):
    choix: Literal["A", "B"] | None
    texte: str


MSG = [{"role": "user", "content": "bonjour"}]


def test_sortie_valide():
    g = LLMGateway(FakeLLM([{"choix": "A", "texte": "ok"}]))
    assert g.complete_json(MSG, Sortie).choix == "A"
    assert g.usage.logical_calls == 1 and g.usage.requests == 1 and g.usage.retries == 0


def test_json_entoure_de_balises():
    g = LLMGateway(FakeLLM(['```json\n{"choix": "B", "texte": "ok"}\n```']))
    assert g.complete_json(MSG, Sortie).choix == "B"


def test_une_nouvelle_tentative_avec_l_erreur():
    fake = FakeLLM([{"choix": "Z", "texte": "x"}, {"choix": "B", "texte": "corrigé"}])
    g = LLMGateway(fake)
    assert g.complete_json(MSG, Sortie).choix == "B"
    assert g.usage.retries == 1 and g.usage.requests == 2 and g.usage.logical_calls == 1
    assert "pas valide" in fake.calls[1][-1]["content"]   # l'erreur est renvoyée au LLM


def test_invalide_deux_fois():
    g = LLMGateway(FakeLLM([{"choix": "Z", "texte": "x"}, "pas du json"]))
    with pytest.raises(InvalidOutput):
        g.complete_json(MSG, Sortie)
    assert g.usage.invalid_outputs == 1


def test_cache(tmp_path):
    cache = ResponseCache(tmp_path / "c.sqlite")
    g1 = LLMGateway(FakeLLM([{"choix": "A", "texte": "ok"}]), cache)
    g1.complete_json(MSG, Sortie)
    g2 = LLMGateway(FakeLLM([]), cache)          # aucune réponse scriptée : seul le cache répond
    assert g2.complete_json(MSG, Sortie).texte == "ok"
    assert g2.usage.cache_hits == 1 and g2.usage.requests == 0


def test_un_seul_appel_par_tour():
    g = LLMGateway(FakeLLM([{"choix": "A", "texte": "1"}, {"choix": "A", "texte": "2"}]))
    g.begin_turn("t1")
    g.complete_json(MSG, Sortie)
    with pytest.raises(TurnCallLimit):
        g.complete_json(MSG, Sortie)
    g.begin_turn("t2")
    g.complete_json(MSG, Sortie)
    assert g.usage.per_turn == {"t1": 1, "t2": 1}


def test_plafond_de_budget():
    g = LLMGateway(FakeLLM([{"choix": "A", "texte": "1"}] * 3), max_calls=2)
    g.complete_json(MSG, Sortie)
    g.complete_json(MSG, Sortie)
    with pytest.raises(BudgetExceeded):
        g.complete_json(MSG, Sortie)
