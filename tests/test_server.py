"""
Plateforme web (API) avec un LLM simulé : aucun réseau, aucun crédit.

Vérifie : comptes et sessions, protection CSRF, isolation des locataires, agents créés depuis un
modèle avec LEUR base de connaissances, conversation du Playground jusqu'à l'action exécutée,
anonymisation de ce qui est stocké, actions et indicateurs calculés sur les données réelles.
"""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from agentkit.llm import LLMGateway
from agentkit.llm.providers import FakeLLM
from agentkit.server.app import create_app
from agentkit.server.db import Database

H = {"X-Requested-With": "fetch"}


def sortie(intent, reply, **kw):
    return {"intent": intent, "understood": kw.pop("understood", True), "slots": kw.pop("slots", {}),
            "item_code": kw.pop("item_code", None), "sources": kw.pop("sources", []),
            "asks_for": kw.pop("asks_for", None), "reply": reply, "sentiment": "neutre",
            "escalate": kw.pop("escalate", {"needed": False, "reason": ""}), **kw}


class Script:
    """Réponses du faux LLM, partagées par toutes les sessions du test."""

    def __init__(self):
        self.reponses, self.appels = [], []

    def __call__(self, messages, schema):
        self.appels.append(messages)
        return self.reponses.pop(0)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTKIT_RUNTIME", str(tmp_path / "runtime"))
    script = Script()
    app = create_app(Database(tmp_path / "p.sqlite"), gateway_factory=lambda: LLMGateway(FakeLLM(script)),
                     serve_web=False)
    return app, script


def client(app, email="a@example.com", business="Centre A"):
    c = TestClient(app)
    r = c.post("/api/auth/register", json={"name": "Alice", "email": email, "password": "motdepasse1",
                                            "business_name": business}, headers=H)
    assert r.status_code == 201, r.text
    return c


def agent(c, **kw):
    r = c.post("/api/agents", json={"name": "Réception", "template": "imagerie_medicale", **kw}, headers=H)
    assert r.status_code == 201, r.text
    return r.json()


def prochain_mardi(heure):
    j = date.today() + timedelta(days=1)
    while j.weekday() != 1:
        j += timedelta(days=1)
    return f"{j.isoformat()}T{heure}"


# --------------------------------------------------------------------------- comptes
def test_inscription_connexion_deconnexion(env):
    app, _ = env
    c = client(app)
    me = c.get("/api/auth/me").json()
    assert me["user"]["email"] == "a@example.com" and me["workspace"]["name"] == "Centre A"
    assert "password_hash" not in str(me)
    c.post("/api/auth/logout", headers=H)
    assert c.get("/api/auth/me").status_code == 401
    assert c.post("/api/auth/login", json={"email": "a@example.com", "password": "faux-mot-de-passe"},
                  headers=H).status_code == 401
    assert c.post("/api/auth/login", json={"email": "A@example.com", "password": "motdepasse1"},
                  headers=H).status_code == 200
    assert c.get("/api/auth/me").status_code == 200


def test_csrf_en_tete_obligatoire(env):
    app, _ = env
    c = TestClient(app)
    r = c.post("/api/auth/register", json={"name": "x", "email": "x@example.com", "password": "motdepasse1",
                                            "business_name": "x"})
    assert r.status_code == 403


def test_reinitialisation_mot_de_passe_reponse_identique(env):
    app, _ = env
    client(app)
    c = TestClient(app)
    a = c.post("/api/auth/forgot-password", json={"email": "a@example.com"}, headers=H).json()
    b = c.post("/api/auth/forgot-password", json={"email": "inconnu@example.com"}, headers=H).json()
    assert a == b                                                   # n'indique pas si le compte existe
    assert c.post("/api/auth/reset-password", json={"token": "x" * 20, "password": "nouveau123"},
                  headers=H).status_code == 400


# --------------------------------------------------------------------------- locataires
def test_isolation_entre_espaces_de_travail(env):
    app, script = env
    a, b = client(app), client(app, "b@example.com", "Centre B")
    ag = agent(a)
    script.reponses = [sortie("autre", "Bonjour !")]
    conv = a.post("/api/playground/sessions", json={"agent_id": ag["id"]}, headers=H).json()["conversation_id"]
    a.post(f"/api/playground/sessions/{conv}/messages", json={"text": "bonjour"}, headers=H)

    assert b.get(f"/api/agents/{ag['id']}").status_code == 404
    assert b.get(f"/api/agents/{ag['id']}/knowledge").status_code == 404
    assert b.get(f"/api/conversations/{conv}").status_code == 404
    assert b.post(f"/api/playground/sessions/{conv}/messages", json={"text": "x"}, headers=H).status_code == 404
    assert b.get("/api/conversations").json()["total"] == 0
    assert b.get("/api/analytics").json()["totals"]["conversations"] == 0
    assert a.get("/api/conversations").json()["total"] == 1


# --------------------------------------------------------------------------- agents et connaissances
def test_agent_cree_depuis_un_modele_avec_sa_propre_faq(env):
    app, script = env
    c = client(app)
    modeles = {m["id"]: m for m in c.get("/api/templates").json()}
    assert "imagerie_medicale" in modeles and modeles["imagerie_medicale"]["workflows"]
    ag = agent(c, settings={"greeting": "Bonjour, ici Réception.", "llm_mode": "llm_first"})
    assert ag["knowledge_entries"] == modeles["imagerie_medicale"]["knowledge_entries"] > 0
    assert ag["settings"]["greeting"] == "Bonjour, ici Réception."

    r = c.post(f"/api/agents/{ag['id']}/knowledge", json={"question": "Avez-vous un parking ?",
                                                          "answer": "Oui, un parking gratuit de 40 places.",
                                                          "category": "accès"}, headers=H)
    fiche = r.json()
    assert r.status_code == 201 and fiche["entry_id"] == "K001"

    script.reponses = [sortie("info_generale", "Oui, il y a un parking gratuit de 40 places.", sources=["K001"])]
    s = c.post("/api/playground/sessions", json={"agent_id": ag["id"]}, headers=H).json()
    assert s["greeting"] == "Bonjour, ici Réception."
    t = c.post(f"/api/playground/sessions/{s['conversation_id']}/messages", json={"text": "il y a un parking ?"},
               headers=H).json()
    assert "40 places" in script.appels[-1][-1]["content"]          # la fiche de CET agent est fournie au LLM
    assert t["reply"] == "Oui, il y a un parking gratuit de 40 places." and t["llm_used"]
    assert t["details"]["knowledge_used"] == ["K001"]

    c2 = client(app, "c@example.com", "Autre")
    ag2 = agent(c2)
    assert all(f["entry_id"] != "K001" for f in c2.get(f"/api/agents/{ag2['id']}/knowledge").json())


# --------------------------------------------------------------------------- démarche complète
def test_playground_prise_de_rendez_vous_action_enregistree_et_anonymisee(env):
    app, script = env
    c = client(app)
    ag = agent(c)
    conv = c.post("/api/playground/sessions", json={"agent_id": ag["id"]}, headers=H).json()["conversation_id"]
    script.reponses = [sortie("nouveau_rdv", "C'est noté.", slots={"creneau": prochain_mardi("10:00"),
                                                                    "nom": "Paul Martin", "telephone": "0612345678"})]
    t = c.post(f"/api/playground/sessions/{conv}/messages",
               json={"text": "une écho du genou gauche mardi 10h pour Paul Martin au 06 12 34 56 78"}, headers=H).json()
    assert t["reply"].startswith("Je récapitule") and t["state"]["awaiting_confirmation"]
    assert c.get("/api/actions?status=pending").json()["total"] == 1

    t = c.post(f"/api/playground/sessions/{conv}/messages", json={"text": "oui"}, headers=H).json()
    assert "RDV-" in t["reply"] and t["llm_used"] is False

    acts = c.get("/api/actions").json()
    assert acts["total"] == 1                                       # l'action en attente est devenue réussie
    a = acts["items"][0]
    assert a["status"] == "succeeded" and a["type"] == "appointment.created" and a["duration_ms"] is not None
    assert a["details"]["result"]["reference"].startswith("RDV-")
    assert "contact" not in a["details"]["result"]

    d = c.get(f"/api/conversations/{conv}").json()
    stocke = str(d)
    assert "Paul Martin" not in stocke and "0612345678" not in stocke and "06 12 34 56 78" not in stocke
    assert d["outcome"] == "action_completed" and d["turns"] == 2
    assert d["turns_list"][0]["agent_text"] and d["turns_list"][0]["idx"] == 0     # accueil

    an = c.get("/api/analytics").json()["totals"]
    assert an["conversations"] == 1 and an["actions_succeeded"] == 1 and an["action_success_rate"] == 1.0
    assert an["total_tokens"] > 0 and an["llm_turns"] == 1 and an["turns"] == 2


def test_transfert_humain_enregistre(env):
    app, script = env
    c = client(app)
    ag = agent(c)
    conv = c.post("/api/playground/sessions", json={"agent_id": ag["id"]}, headers=H).json()["conversation_id"]
    t = c.post(f"/api/playground/sessions/{conv}/messages", json={"text": "est-ce que c'est grave docteur ?"},
               headers=H).json()
    assert t["escalated"] and script.appels == []                   # motif fort : aucun appel LLM
    a = c.get("/api/actions?status=requires_human").json()
    assert a["total"] == 1 and a["items"][0]["type"] == "handoff.human"
    assert c.get(f"/api/conversations/{conv}").json()["outcome"] == "escalated"
    assert c.get("/api/dashboard").json()["attention"]


def test_fin_de_conversation_et_suppression(env):
    app, script = env
    c = client(app)
    ag = agent(c)
    vide = c.post("/api/playground/sessions", json={"agent_id": ag["id"]}, headers=H).json()["conversation_id"]
    c.post(f"/api/playground/sessions/{vide}/end", headers=H)
    assert c.get(f"/api/conversations/{vide}").status_code == 404     # aucun message : pas une conversation

    script.reponses = [sortie("autre", "Bonjour !")]
    conv = c.post("/api/playground/sessions", json={"agent_id": ag["id"]}, headers=H).json()["conversation_id"]
    c.post(f"/api/playground/sessions/{conv}/messages", json={"text": "bonjour"}, headers=H)
    c.post(f"/api/playground/sessions/{conv}/end", headers=H)
    assert c.get(f"/api/conversations/{conv}").json()["status"] == "ended"
    assert c.post(f"/api/playground/sessions/{conv}/messages", json={"text": "x"}, headers=H).status_code == 404
    assert c.delete(f"/api/conversations/{conv}", headers=H).status_code == 200
    assert c.get(f"/api/conversations/{conv}").status_code == 404


def test_integrations_ne_revelent_aucune_cle(env, monkeypatch):
    app, _ = env
    monkeypatch.setenv("LLM_API_KEY", "cle-secrete-123")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "cle-secrete-456")
    c = client(app)
    texte = c.get("/api/integrations").text
    assert "cle-secrete" not in texte and '"configured":true' in texte.replace(" ", "")
