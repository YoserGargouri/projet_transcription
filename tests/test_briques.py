"""Briques génériques : résolveur, routeur, FAQ, agenda, anonymisation (sur les deux packs)."""
from datetime import datetime

import pytest

from agentkit.domain import load_domain
from agentkit.knowledge.retriever import build_retriever
from agentkit.logging.redaction import Redactor
from agentkit.nlu.resolver import CatalogueResolver
from agentkit.nlu.router import RuleRouter
from agentkit.nlu.text import normalise
from agentkit.tools.base import ToolError
from agentkit.tools.registry import ToolRegistry


def test_normalisation():
    assert normalise("L'É.C.G. du pied-gauche !") == "l ecg du pied gauche"


@pytest.mark.parametrize("texte, attendu", [
    ("je voudrais louer un vtt grand", "V_VTT_L"),
    ("un vélo cargo", "V_CARGO_L"),               # une seule taille : rien à demander
    ("un vtt petitte", "V_VTT_S"),                # faute : recherche floue
])
def test_resolveur_demo(texte, attendu):
    r = CatalogueResolver(load_domain("demo_minimal")).resolve(texte)
    assert r.item_id == attendu


def test_resolveur_question_et_contexte():
    res = CatalogueResolver(load_domain("demo_minimal"))
    r = res.resolve("un vélo électrique")
    assert r.status == "ambiguous" and r.question == "Quelle taille, moyenne ou grande ?"
    assert res.resolve("moyenne", r.context).item_id == "V_ELEC_M"


def test_resolveur_combinaison_absente():
    assert CatalogueResolver(load_domain("demo_minimal")).resolve("un vélo enfant grand").status == "infeasible"


@pytest.mark.parametrize("texte, attendu", [
    ("une IRM du genou gauche", "IRM_GEN_G"),
    ("un doppler des carotides", "ECH_VCO"),
    ("on m'a dit d'appeler pour une radio du thorax", "RX_THO"),   # « dit d » n'est pas le côté droit
    ("oui, une échographie des reins", "ECH_REI"),                 # « oui » n'est pas « avec injection »
])
def test_resolveur_imagerie(texte, attendu):
    assert CatalogueResolver(load_domain("imagerie_medicale")).resolve(texte).item_id == attendu


def test_routeur():
    r = RuleRouter(load_domain("demo_minimal"))
    assert r.route("quels sont vos horaires").intent == "info"
    assert r.route("je veux louer").intent == "louer"
    assert r.route("bla bla").intent == "autre" and not r.route("bla bla").matched


def test_faq():
    hit = build_retriever(load_domain("demo_minimal")).answer("il faut une caution ?")
    assert hit and hit.id == "Q3"
    assert build_retriever(load_domain("demo_minimal")).answer("quel temps fait-il à Tokyo") is None


def test_agenda_generique():
    outils = ToolRegistry.from_pack(load_domain("imagerie_medicale"))
    apres = datetime(2026, 11, 23, 7, 0)                              # un lundi
    libres = outils.call("agenda", "free_slots", {"resource": "IRM", "item_id": "IRM_GEN_G", "after": apres})
    assert libres["slots"][0] == "2026-11-23T08:00"
    rdv = outils.call("agenda", "book", {"resource": "IRM", "start": libres["slots"][0], "item_id": "IRM_GEN_G"})
    assert rdv["end"] == "2026-11-23T08:30"                           # durée = colonne duree_min (30)
    with pytest.raises(ToolError, match="déjà pris"):
        outils.call("agenda", "book", {"resource": "IRM", "start": "2026-11-23T08:10", "item_id": "IRM_GEN_G"})
    assert outils.call("agenda", "find", {"reference": rdv["reference"]})["status"] == "booked"
    assert outils.call("agenda", "move", {"reference": rdv["reference"], "new_start": "2026-11-24T10:00"})["start"] \
        == "2026-11-24T10:00"
    assert outils.call("agenda", "cancel", {"reference": rdv["reference"]})["status"] == "cancelled"
    with pytest.raises(ToolError, match="horaires"):
        outils.call("agenda", "book", {"resource": "IRM", "start": "2026-11-29T10:00"})   # dimanche


def test_anonymisation():
    red = Redactor(load_domain("imagerie_medicale"))
    texte = red.redact("C'est Paul Martin, 06 12 34 56 78, paul@mail.fr, né le 12/03/1980",
                       {"nom": "Paul Martin"})
    assert texte == "C'est [NOM], [TELEPHONE], [EMAIL], né le [DATE]"
