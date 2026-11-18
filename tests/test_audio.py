"""
Canal audio sans réseau : TTS ElevenLabs simulé (jamais appelé pour de vrai), cache,
journal des caractères, sortie 16 kHz mono, décision qualité, canal audio -> audio.
"""
import json

import numpy as np
import pytest
import soundfile as sf

from agentkit.channels.audio.quality import decision, diagnostic
from agentkit.channels.audio.tts import ElevenLabsTTS, GTTSEngine, TTSService
from agentkit.domain import load_domain
from agentkit.domain.schema import QualitySpec


class FauxClientElevenLabs:
    """Imite elevenlabs.client.ElevenLabs : renvoie 0,5 s de PCM 16 kHz."""

    def __init__(self):
        self.appels = []
        self.text_to_speech = self
        self.voices = self

    def convert(self, voice_id, **kw):
        self.appels.append({"voice_id": voice_id, **kw})
        t = np.arange(8000) / 16000
        yield (0.3 * np.sin(2 * np.pi * 220 * t) * 32767).astype("<i2").tobytes()

    def search(self, **kw):
        class V:
            voice_id = "voix-par-defaut"

        class R:
            voices = [V()]
        return R()


def _parole_avec_pauses(secondes=2.0):
    """Signal qui ressemble à de la parole pour l'estimateur de SNR : des « mots » séparés
    de silences (un son continu n'a pas de pause, donc pas de bruit de fond mesurable)."""
    t = np.arange(int(16000 * secondes)) / 16000
    mots = (np.sin(2 * np.pi * 2 * t) > 0).astype(np.float32)
    bruit = 0.001 * np.random.default_rng(0).standard_normal(len(t))
    return (0.3 * np.sin(2 * np.pi * 200 * t) * mots + bruit).astype(np.float32)


@pytest.fixture
def faux_client():
    return FauxClientElevenLabs()


def _service(tmp_path, moteur):
    return TTSService([moteur], cache_dir=tmp_path / "cache", usage_log=tmp_path / "usage.jsonl")


def test_elevenlabs_simule_cache_et_journal(tmp_path, faux_client):
    moteur = ElevenLabsTTS("voix-1", "eleven_flash_v2_5", {"stability": 0.5}, "fr", client=faux_client)
    tts = _service(tmp_path, moteur)
    r1 = tts.synthesize("Bonjour, je vous écoute.", tmp_path / "a.wav")
    r2 = tts.synthesize("Bonjour, je vous écoute.", tmp_path / "b.wav")
    assert not r1["cached"] and r1["chars_billed"] == 24
    assert r2["cached"] and r2["chars_billed"] == 0 and len(faux_client.appels) == 1   # 2e fois : 0 crédit
    assert faux_client.appels[0]["output_format"] == "pcm_16000" and faux_client.appels[0]["language_code"] == "fr"
    info = sf.info(tmp_path / "b.wav")
    assert info.samplerate == 16000 and info.channels == 1
    journal = [json.loads(l) for l in (tmp_path / "usage.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(journal) == 1 and journal[0]["chars"] == 24 and journal[0]["model"] == "eleven_flash_v2_5"


def test_cle_de_cache_depend_de_la_voix(tmp_path, faux_client):
    a = _service(tmp_path, ElevenLabsTTS("voix-1", "m", {}, "fr", client=faux_client))
    b = _service(tmp_path, ElevenLabsTTS("voix-2", "m", {}, "fr", client=faux_client))
    a.synthesize("même texte", tmp_path / "a.wav")
    assert not b.synthesize("même texte", tmp_path / "b.wav")["cached"]


def test_voix_par_defaut_du_compte(tmp_path, faux_client):
    _service(tmp_path, ElevenLabsTTS(None, "m", {}, "fr", client=faux_client)).synthesize("x y", tmp_path / "a.wav")
    assert faux_client.appels[0]["voice_id"] == "voix-par-defaut"


def test_vraie_cle_jamais_utilisee_en_test(tmp_path):
    """Sans client simulé, le moteur ElevenLabs échoue (pas de clé, client interdit) et la
    chaîne passe au moteur suivant : aucun crédit ne peut être consommé par les tests."""
    class Secours(GTTSEngine):
        def synthesize(self, text):
            return np.zeros(1600, dtype=np.float32) + 0.1, 16000

    tts = TTSService([ElevenLabsTTS("v", "m", {}, "fr"), Secours("fr")], tmp_path / "c", tmp_path / "u.jsonl")
    r = tts.synthesize("bonjour", tmp_path / "a.wav")
    assert r["engine"] == "gtts" and "elevenlabs" in r["fallback_errors"][0]


def test_tts_configure_par_le_pack():
    tts = TTSService.from_pack(load_domain("imagerie_medicale", recharger=True))
    assert [e.name for e in tts.engines] == ["elevenlabs", "gtts", "piper"]
    assert tts.engines[0].model_id == "eleven_flash_v2_5" and tts.engines[0].language == "fr"


def test_decision_qualite():
    q = QualitySpec()
    d = diagnostic(_parole_avec_pauses(), 16000)
    assert decision(d, q, 0.9, "bonjour") == "ok"
    assert decision(d, q, 0.6, "bonjour") == "confirmer"
    assert decision(d, q, 0.3, "bonjour") == "redemander"
    assert decision(diagnostic(np.zeros(16000, dtype=np.float32), 16000), q) == "redemander"   # silence


def test_canal_audio_bout_en_bout(tmp_path, faux_client):
    """audio -> qualité -> STT (simulé) -> orchestrateur -> TTS (simulé) -> audio."""
    from agentkit.channels.audio.channel import AudioChannel
    from agentkit.orchestrator import Orchestrator

    class FauxSTT:
        nom = "faux"

        def transcrire(self, chemin):
            return {"texte": "Bonjour, je voudrais une IRM du genou", "confiance": 0.95, "latence_s": 0.0}

    pack = load_domain("imagerie_medicale")
    tts = _service(tmp_path, ElevenLabsTTS("v", "eleven_flash_v2_5", {}, "fr", client=faux_client))
    canal = AudioChannel(Orchestrator(pack), stt=FauxSTT(), tts=tts)
    sf.write(tmp_path / "in.wav", _parole_avec_pauses(), 16000)
    r = canal.handle_audio(tmp_path / "in.wav", tmp_path / "out.wav")
    assert "côté" in r.reply and sf.info(r.reply_audio).samplerate == 16000
    assert faux_client.appels[0]["text"] == r.reply and r.timings["total_s"] < 5

    sf.write(tmp_path / "vide.wav", np.zeros(4000), 16000)                  # audio vide : on redemande
    r = canal.handle_audio(tmp_path / "vide.wav", tmp_path / "out2.wav")
    assert r.quality_decision == "redemander" and r.reply == pack.channels.audio.retry_message
    r = canal.handle_audio(tmp_path / "vide.wav", tmp_path / "out3.wav")    # 2e échec : humain
    assert r.turn.escalated and r.turn.escalation_reason == "audio_unusable"
