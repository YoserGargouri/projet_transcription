"""
Mode llm_first (pack imagerie_medicale) avec un LLM simulé : aucun réseau, aucun crédit.

Ce qu'on vérifie : le LLM comprend le tour (y compris une transcription fautive), sa réponse est
dite à l'utilisateur, les réponses d'information doivent citer des fiches réellement fournies,
les garde-fous restent hors LLM, le repli sur les règles fonctionne, et une démarche va jusqu'à
l'agenda (créer, déplacer, annuler) avec les dates en ISO.
"""
from datetime import date, datetime, timedelta

import pytest

from agentkit.domain import load_domain
from agentkit.llm import LLMGateway
from agentkit.llm.providers import FakeLLM
from agentkit.nlu import dates
from agentkit.orchestrator import Orchestrator


def sortie(intent, reply, **kw):
    return {"intent": intent, "understood": kw.pop("understood", True), "slots": kw.pop("slots", {}),
            "item_code": kw.pop("item_code", None), "sources": kw.pop("sources", []),
            "asks_for": kw.pop("asks_for", None), "reply": reply, "sentiment": "neutre",
            "escalate": kw.pop("escalate", {"needed": False, "reason": ""}), **kw}


def orch(reponses):
    fake = FakeLLM(reponses)
    o = Orchestrator(load_domain("imagerie_medicale"), gateway=LLMGateway(fake))
    o.start()
    return o, fake


def prochain_mardi(heure="10:00") -> str:
    j = date.today() + timedelta(days=1)
    while j.weekday() != 1:
        j += timedelta(days=1)
    return f"{j.isoformat()}T{heure}"


def contexte_envoye(fake, i=-1) -> str:
    return fake.calls[i][-1]["content"]


# --------------------------------------------------------------------------- compréhension
def test_transcription_fautive_comprise_par_le_llm():
    """« ronds des vous » : aucune règle ne le reconnaît, le LLM si."""
    o, fake = orch([sortie("nouveau_rdv", "Bien sûr ! Quel examen devez-vous passer ?", asks_for="examen")])
    r = o.handle_text("Bonjour, je voudrais prendre un ronds des vous")
    assert r.trace["route"]["matched"] is False                     # les règles seules auraient échoué
    assert r.llm_calls == 1 and r.reply == "Bien sûr ! Quel examen devez-vous passer ?"
    assert o.state.run.workflow_id == "booking" and o.state.pending_slot == "examen"
    assert "TRANSCRIPTION" in fake.calls[0][0]["content"]          # le prompt prévient des erreurs de STT
    assert "date_et_heure_actuelles" in contexte_envoye(fake)


def test_salutation_comprise_ne_compte_pas_comme_incomprise():
    o, _ = orch([sortie("autre", "Bonjour ! Que puis-je faire pour vous ?")] * 3)
    for _ in range(3):
        r = o.handle_text("allô bonjou")
    assert not r.escalated and r.reply == "Bonjour ! Que puis-je faire pour vous ?"


def test_deux_tours_incompris_transfert():
    o, _ = orch([sortie("autre", "Pardon, pouvez-vous reformuler ?", understood=False)] * 2)
    o.handle_text("hmm euh bla")
    r = o.handle_text("brrr")
    assert r.escalated and r.escalation_reason == "unrecognised"


# --------------------------------------------------------------------------- connaissances
def test_reponse_redigee_a_partir_de_la_faq_avec_source():
    o, fake = orch([sortie("info_generale", "Oui, le samedi matin, de 8 heures à 12 heures 30.", sources=["F02"])])
    r = o.handle_text("vous bossez le samedi ?")
    assert r.reply == "Oui, le samedi matin, de 8 heures à 12 heures 30."   # texte du LLM, pas la fiche
    assert r.trace["knowledge"]["used"] == ["F02"]
    assert "12 heures 30" in contexte_envoye(fake)                 # la FAQ est bien fournie au LLM
    assert len(r.trace["knowledge"]["provided"]) == 24             # llm_context: all


def test_reponse_d_information_sans_source_refusee():
    """Le LLM ne peut pas répondre à une question pratique sans s'appuyer sur la base."""
    o, _ = orch([sortie("info_generale", "Le parking coûte 5 euros.")])
    r = o.handle_text("le parking est payant ?")
    assert r.reply == o.pack.persona.no_answer_message and r.trace["knowledge"]["unsupported"]


def test_source_inventee_refusee():
    o, _ = orch([sortie("info_generale", "Réponse.", sources=["F99"])] * 2)
    r = o.handle_text("une question")
    assert r.trace["agent"]["fallback"] == "item_code_invalide" and r.reply == o.pack.persona.no_answer_message


def test_question_pratique_pendant_une_demarche_puis_retour():
    o, _ = orch([sortie("nouveau_rdv", "Quel examen ?", asks_for="examen"),
                 sortie("info_generale", "Oui, le centre est accessible en fauteuil.", sources=["F07"])])
    o.handle_text("je voudrais un rendez-vous")
    r = o.handle_text("au fait c'est accessible en fauteuil ?")
    assert r.reply.startswith("Oui, le centre est accessible en fauteuil.") and "Quel examen" in r.reply
    assert o.state.run.workflow_id == "booking"                    # la démarche continue


# --------------------------------------------------------------------------- garde-fous
def test_motif_fort_transfert_sans_appel_llm():
    o, fake = orch([])
    r = o.handle_text("est-ce que c'est grave docteur ?")
    assert r.escalated and r.escalation_reason == "out_of_scope" and fake.calls == []


def test_motif_faible_alerte_donnee_au_llm_qui_decide():
    o, fake = orch([sortie("autre", "Je vous passe le secrétariat.",
                           escalate={"needed": True, "reason": "hors_perimetre"})])
    r = o.handle_text("j'ai mal au dos depuis hier")
    assert "alerte_perimetre" in contexte_envoye(fake)
    assert r.escalated and r.escalation_reason == "agent_requested"


def test_code_hors_candidats_jamais_accepte():
    o, _ = orch([sortie("nouveau_rdv", "Quel côté ?", item_code="INVENTE")] * 2)
    o.handle_text("une IRM du genou")
    assert o.state.run.item is None                               # D3 : remis à null


def test_llm_indisponible_repli_sur_les_regles():
    def panne(messages, schema):
        raise ConnectionError("503")

    o, _ = orch(panne)
    r = o.handle_text("je voudrais un rendez-vous pour une IRM du genou")
    assert "llm_indisponible" in r.trace["llm_failure"]
    assert "côté" in r.reply                                       # question des règles


# --------------------------------------------------------------------------- démarches
def test_prise_de_rendez_vous_complete_puis_deplacement_et_annulation():
    creneau = prochain_mardi("10:00")
    o, _ = orch([
        sortie("nouveau_rdv", "C'est noté.", slots={"creneau": creneau, "nom": "Paul Martin",
                                                     "telephone": "0612345678"}),
    ])
    r = o.handle_text("une écho du genou gauche mardi à 10 heures pour Paul Martin au 06 12 34 56 78")
    assert r.item_id == "ECH_GEN_G" and r.reply.startswith("Je récapitule : Échographie genou gauche, mardi")
    assert "à 10 heures" in r.reply                                # date ISO relue en toutes lettres
    r = o.handle_text("oui")                                       # confirmation : règles, 0 appel
    assert r.llm_calls == 0 and "RDV-" in r.reply
    ref = r.trace["tool_result"]["reference"]

    nouveau = prochain_mardi("15:00")
    o2, _ = orch([sortie("deplacer_rdv", "D'accord.", slots={"reference": ref, "nouveau_creneau": nouveau})])
    r = o2.handle_text(f"je dois décaler mon ronds des vous {ref} à mardi 15 heures")
    assert r.reply.startswith(f"Je déplace le rendez-vous {ref}") and "15 heures" in r.reply
    assert "RDV" in o2.handle_text("oui").reply

    # référence dictée lettre par lettre : retrouvée malgré les espaces
    dictee = " ".join(ref.replace("-", ""))
    o3, _ = orch([sortie("annuler_rdv", "D'accord.", slots={"reference": dictee})])
    r = o3.handle_text("annuler mon rendez-vous")
    assert "Vous confirmez" in r.reply
    assert "annulé" in o3.handle_text("oui").reply


def test_creneau_pris_alternatives_puis_choix():
    creneau = prochain_mardi("11:00")
    o0 = Orchestrator(load_domain("imagerie_medicale"))
    o0.tools.call("agenda", "book", {"resource": "Échographie", "start": creneau, "item_id": "ECH_GEN_G"})

    o, _ = orch([sortie("nouveau_rdv", "Noté.", slots={"creneau": creneau, "nom": "Ana", "telephone": "0611223344"}),
                 sortie("nouveau_rdv", "Parfait.", slots={"creneau": "la deuxième"})])
    r = o.handle_text("échographie du genou droit mardi 11 heures, Ana, 06 11 22 33 44")
    assert r.trace["precheck"]["reason"] == "ce créneau est déjà pris"
    options = o.state.slot_options["creneau"]
    assert len(options) == 3 and "Je peux vous proposer" in r.reply
    r = o.handle_text("la deuxième")
    assert o.state.run.slots["creneau"] == options[1] and r.reply.startswith("Je récapitule")


def test_date_passee_refusee():
    hier = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT10:00")
    o, _ = orch([sortie("nouveau_rdv", "Noté.", slots={"creneau": hier, "nom": "Ana", "telephone": "0611223344"})])
    r = o.handle_text("échographie du genou droit hier, Ana, 0611223344")
    assert r.trace["precheck"]["reason"] == "ce moment est déjà passé"


# --------------------------------------------------------------------------- dates
@pytest.mark.parametrize("texte,attendu", [
    ("demain matin", (1, "09:00")),
    ("après-demain à 14h30", (2, "14:30")),
    ("demain vers 3 heures de l'après-midi", (1, "15:00")),
])
def test_analyse_des_dates_de_secours(texte, attendu):
    now = datetime(2026, 11, 23, 16, 0)                            # un lundi
    jours, heure = attendu
    assert dates.analyser(texte, "datetime", now) == f"{(now + timedelta(days=jours)).date()}T{heure}"


def test_jour_de_la_semaine_et_lecture():
    now = datetime(2026, 11, 23, 16, 0)                            # lundi
    assert dates.analyser("jeudi matin", "datetime", now) == "2026-11-26T09:00"
    assert dates.dire("2026-11-26T09:30", "fr") == "jeudi 26 novembre à 9 heures 30"
    assert dates.dire("2026-12-01T12:00", "fr") == "mardi 1er décembre à midi"
    assert dates.option_choisie("la deuxième", ["2026-11-26T09:00", "2026-11-26T11:00"]) == "2026-11-26T11:00"


def test_reference_transcrite_avec_confusions():
    """Transcriptions réelles de Whisper : « RDV-M8ZI3I » dicté -> « CRDV-M8Z13I » (c'est + I/1)."""
    from agentkit.tools.builtin.calendar import ALPHABET_REF

    o = Orchestrator(load_domain("imagerie_medicale"))
    ref = o.tools.call("agenda", "book", {"resource": "Échographie", "start": prochain_mardi("16:00")})["reference"]
    assert all(c in ALPHABET_REF for c in ref.split("-")[1])          # ni I, L, O, 0, 1
    agenda = o.tools.get("agenda")
    corps = ref.split("-")[1]
    assert agenda._ligne("C" + ref)["reference"] == ref                # « c'est RDV... »
    assert agenda._ligne(" ".join(ref))["reference"] == ref            # lettre par lettre
    with pytest.raises(Exception):
        agenda._ligne("RDV-ZZZZZZ")
    assert agenda._ligne("rdv " + corps.lower())["reference"] == ref

    o2, _ = orch([sortie("annuler_rdv", "D'accord.", slots={"reference": "C" + ref})])
    r = o2.handle_text("je veux annuler")
    assert r.reply == f"J'annule le rendez-vous {ref}. Vous confirmez ?"     # la vraie référence est relue
