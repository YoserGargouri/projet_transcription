"""
Garde-fous communs à tous les tests (moteur et packs) :
- aucune clé d'API n'est visible (le .env local est ignoré) ;
- aucun accès réseau (requests bloqué) et ElevenLabs ne peut pas être instancié :
  un test qui voudrait consommer des crédits échoue au lieu de payer ;
- les fichiers d'exécution (caches, agendas, journaux) vont dans un dossier temporaire.
"""
import pytest

CLES = ["ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID", "ELEVENLABS_MODEL_ID", "LLM_BASE_URL", "LLM_API_KEY",
        "LLM_MODEL", "LLM_MAX_CALLS", "LLM_MAX_TOKENS"]


@pytest.fixture(autouse=True)
def environnement_isole(monkeypatch, tmp_path):
    for cle in CLES:
        monkeypatch.delenv(cle, raising=False)
    monkeypatch.setenv("AGENTKIT_RUNTIME", str(tmp_path / "runtime"))

    def reseau_interdit(*a, **k):
        raise RuntimeError("accès réseau interdit pendant les tests")

    monkeypatch.setattr("requests.sessions.Session.request", reseau_interdit)
    try:
        import elevenlabs.client

        def elevenlabs_interdit(*a, **k):
            raise RuntimeError("ElevenLabs ne doit jamais être appelé par les tests (crédits)")

        monkeypatch.setattr(elevenlabs.client.ElevenLabs, "__init__", elevenlabs_interdit)
    except ImportError:
        pass
