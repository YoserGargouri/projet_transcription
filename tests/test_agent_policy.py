"""D3 : le code d'élément proposé par le LLM n'est accepté que s'il fait partie des candidats."""
import pytest
from pydantic import ValidationError

from agentkit.agent.contract import build_agent_output_model
from agentkit.agent.policy import SingleCallPolicy, TurnContext
from agentkit.domain import load_domain
from agentkit.llm import LLMGateway
from agentkit.llm.providers import FakeLLM

BASE = {"intent": "louer", "slots": {"date": None, "nom": None}, "reply": "D'accord.", "sentiment": "neutre",
        "escalate": {"needed": False, "reason": ""}}


def test_contrat_genere_depuis_le_pack():
    m = build_agent_output_model(["louer", "info"], ["date", "nom"], ["V_VTT_L", "V_VTT_M"])
    assert m.model_validate({**BASE, "item_code": "V_VTT_M"}).item_code == "V_VTT_M"
    with pytest.raises(ValidationError):
        m.model_validate({**BASE, "item_code": "V_CARGO_L"})          # hors candidats
    with pytest.raises(ValidationError):
        m.model_validate({**BASE, "intent": "voler"})                  # intention inconnue
    with pytest.raises(ValidationError):
        m.model_validate({**BASE, "slots": {"couleur": "rouge"}})      # slot inconnu


def _ctx():
    return TurnContext(text="un vélo", intent="louer", rules_reply="Quel vélo ?", needs_llm=True,
                       slot_names=["date", "nom"], candidates=["V_VTT_L", "V_VTT_M"])


def test_code_hors_candidats_une_tentative_puis_null():
    fake = FakeLLM([{**BASE, "item_code": "V_CARGO_L"}, {**BASE, "item_code": "V_INVENTE"}])
    g = LLMGateway(fake)
    d = SingleCallPolicy(load_domain("demo_minimal"), g).decide(_ctx())
    assert d.item_code is None and d.llm_used and d.fallback == "item_code_invalide"
    assert d.reply == "D'accord."                       # le reste de la sortie est gardé
    assert g.usage.retries == 1 and g.usage.requests == 2


def test_code_corrige_a_la_nouvelle_tentative():
    fake = FakeLLM([{**BASE, "item_code": "V_CARGO_L"}, {**BASE, "item_code": "V_VTT_M"}])
    d = SingleCallPolicy(load_domain("demo_minimal"), LLMGateway(fake)).decide(_ctx())
    assert d.item_code == "V_VTT_M" and d.fallback == ""


def test_sortie_illisible_repli_sur_les_regles():
    d = SingleCallPolicy(load_domain("demo_minimal"), LLMGateway(FakeLLM(["???", "toujours pas"]))).decide(_ctx())
    assert not d.llm_used and d.reply == "Quel vélo ?" and d.fallback == "sortie_llm_invalide"


def test_pas_d_appel_si_les_regles_suffisent():
    fake = FakeLLM([])
    ctx = _ctx()
    ctx.needs_llm = False
    d = SingleCallPolicy(load_domain("demo_minimal"), LLMGateway(fake)).decide(ctx)
    assert not fake.calls and d.reply == "Quel vélo ?"
