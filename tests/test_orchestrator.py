"""
L'orchestrateur sur le pack demo_minimal : un tour avec FakeLLM, règles seules, garde-fous.
Le même code tourne sur imagerie_medicale : aucune ligne du moteur ne dépend du pack.
"""
import pytest

from agentkit.domain import load_domain
from agentkit.llm import LLMGateway
from agentkit.llm.providers import FakeLLM
from agentkit.orchestrator import Orchestrator

REPONSE_LLM = {"intent": "louer", "slots": {"date": "samedi", "nom": "Alice Martin"}, "item_code": "V_VTT_L",
               "reply": "Très bien.", "sentiment": "neutre", "escalate": {"needed": False, "reason": ""}}


@pytest.fixture
def demo():
    return load_domain("demo_minimal")


def test_un_tour_avec_fake_llm(demo):
    fake = FakeLLM([REPONSE_LLM])
    o = Orchestrator(demo, gateway=LLMGateway(fake))
    o.start()
    r = o.handle_text("Je voudrais louer un VTT grand pour samedi, au nom d'Alice Martin")
    assert r.llm_calls == 1 and r.item_id == "V_VTT_L"
    # « samedi » est enregistré comme une vraie date (ISO) et relu en toutes lettres
    assert r.reply.startswith("Je réserve : VTT taille L, samedi ") and "au nom de Alice Martin" in r.reply
    assert o.state.run.slots["date"].count("-") == 2
    # le LLM n'a vu que les candidats autorisés, et le contexte du tour
    assert "V_VTT_L" in fake.calls[0][-1]["content"]
    r = o.handle_text("oui")                           # confirmation : règles seules (D1)
    assert r.llm_calls == 0 and r.reply == "Réservation LOC-001 enregistrée."


def test_regles_seules_sans_llm(demo):
    o = Orchestrator(demo)
    assert o.handle_text("je voudrais louer un vélo de ville").reply == "Quelle taille, petite, moyenne ou grande ?"
    assert o.handle_text("grande").reply == "Pour quelle date ?"     # contexte gardé d'un tour à l'autre
    assert o.state.run.item["id"] == "V_VILLE_L"


def test_clarification_sans_appel_llm(demo):
    """D1 : la règle a une question précise -> pas d'appel LLM, même si un LLM est configuré."""
    o = Orchestrator(demo, gateway=LLMGateway(FakeLLM([])))
    r = o.handle_text("je voudrais louer un vélo de ville")
    assert r.llm_calls == 0 and "taille" in r.reply


def test_faq_sans_llm(demo):
    o = Orchestrator(demo, gateway=LLMGateway(FakeLLM([])))
    r = o.handle_text("quels sont vos horaires ?")
    assert r.llm_calls == 0 and "9 heures" in r.reply


@pytest.mark.parametrize("texte, raison", [
    ("je voudrais parler à un vendeur", "explicit_request"),
    ("mon vélo est en panne, vous pouvez réparer ?", "out_of_scope"),
    ("j'en ai marre, c'est nul", "signal:frustration"),
])
def test_transferts(demo, texte, raison):
    r = Orchestrator(demo).handle_text(texte)
    assert r.escalated and r.escalation_reason == raison and r.reply == demo.persona.handoff_message


def test_script_de_securite(demo):
    o = Orchestrator(demo)
    r = o.handle_text("je voudrais louer un vélo électrique grand")
    assert r.reply == demo.safety_scripts[0].question
    assert o.handle_text("euh je sais pas").reply == demo.safety_scripts[0].question   # flou : reposée une fois
    r = o.handle_text("oui")                                                           # positif : humain
    assert r.escalated and r.escalation_reason == "safety_positive"


def test_script_de_securite_negatif(demo):
    o = Orchestrator(demo)
    o.handle_text("je voudrais louer un vélo électrique grand")
    assert o.handle_text("non").reply == "Pour quelle date ?"


def test_meme_moteur_autre_pack():
    o = Orchestrator(load_domain("imagerie_medicale"))
    r = o.handle_text("Bonjour, je voudrais une IRM du genou")
    assert "côté" in r.reply and set(r.candidates) == {"IRM_GEN_G", "IRM_GEN_D"}


def test_question_reposee_apres_une_digression(demo):
    """Une question pratique au milieu d'un workflow : on répond, puis on repose la question en cours."""
    o = Orchestrator(demo)
    q = o.handle_text("je voudrais louer un vélo de ville").reply
    r = o.handle_text("quels sont vos horaires ?")
    assert r.reply.endswith(q) and "9 heures" in r.reply
