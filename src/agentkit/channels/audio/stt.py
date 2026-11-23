"""
Moteurs de transcription (STT) avec une interface commune.

    from agentkit.channels.audio.stt import creer_moteur
    moteur = creer_moteur("whisper-small", langue="fr")   # la langue vient du pack de domaine
    r = moteur.transcrire("audio.wav")
    r == {"texte": "...", "confiance": 0.87, "latence_s": 1.9}

Tous les moteurs renvoient le même dictionnaire, ce qui permet de les comparer
et de les échanger dans le pipeline sans rien changer d'autre.
Les audios doivent être en WAV 16 kHz mono.
"""
import json
import math
import time

import numpy as np
import soundfile as sf

from agentkit import config


def charger_16k(chemin) -> np.ndarray:
    """Audio en float32 mono 16 kHz. On décode nous-mêmes (soundfile) au lieu de laisser
    faster-whisper passer par PyAV, dont l'API a changé (av 15+ : argument metadata_errors)."""
    y, sr = sf.read(str(chemin), dtype="float32")
    if y.ndim > 1:
        y = y.mean(axis=1)
    if sr != 16000:
        import librosa

        y = librosa.resample(y, orig_sr=sr, target_sr=16000)
    return y.astype(np.float32)


class Whisper:
    """faster-whisper, exécuté sur le processeur. Modèle téléchargé au premier usage."""

    def __init__(self, taille: str = "small", langue: str | None = None, prompt: str | None = None):
        from faster_whisper import WhisperModel

        self.nom = f"whisper-{taille}"
        self.langue = langue  # None : détection automatique de la langue
        # Phrase de contexte (vocabulaire du métier, channels.audio.stt.prompt du pack) : Whisper
        # reconnaît mieux les mots qu'elle contient (noms de produits, termes du métier...)
        self.prompt = prompt or None
        self.modele = WhisperModel(taille, device="cpu", compute_type="int8")

    def transcrire(self, chemin) -> dict:
        t0 = time.perf_counter()
        segments, _ = self.modele.transcribe(charger_16k(chemin), language=self.langue, beam_size=5,
                                             word_timestamps=True, initial_prompt=self.prompt)
        segments = list(segments)  # la transcription a réellement lieu ici
        latence = time.perf_counter() - t0
        mots = [w for s in segments for w in (s.words or [])]
        return {
            "texte": " ".join(s.text.strip() for s in segments).strip(),
            "confiance": float(np.mean([w.probability for w in mots])) if mots else 0.0,
            "latence_s": latence,
        }


class Vosk:
    """Vosk (Kaldi), très léger. Petit modèle de la langue téléchargé au premier usage (≈ 40 Mo)."""

    MODELES = {"fr": "vosk-model-small-fr-0.22", "en": "vosk-model-small-en-us-0.15",
               "ar": "vosk-model-ar-mgb2-0.4", "es": "vosk-model-small-es-0.42"}

    def __init__(self, langue: str = "fr", nom_modele: str | None = None):
        from vosk import KaldiRecognizer, Model, SetLogLevel

        SetLogLevel(-1)  # coupe les messages techniques de Kaldi
        self.nom = f"vosk-{langue}"
        self.modele = Model(model_name=nom_modele or self.MODELES[langue])
        self._Recognizer = KaldiRecognizer

    def transcrire(self, chemin) -> dict:
        y, sr = sf.read(chemin, dtype="int16")
        if y.ndim > 1:
            y = y[:, 0]
        t0 = time.perf_counter()
        rec = self._Recognizer(self.modele, sr)
        rec.SetWords(True)
        donnees, textes, mots = y.tobytes(), [], []
        for i in range(0, len(donnees), 8000):  # morceaux de 0,25 s, comme un flux d'appel
            if rec.AcceptWaveform(donnees[i:i + 8000]):
                r = json.loads(rec.Result())
                textes.append(r.get("text", ""))
                mots += r.get("result", [])
        r = json.loads(rec.FinalResult())
        textes.append(r.get("text", ""))
        mots += r.get("result", [])
        return {
            "texte": " ".join(t for t in textes if t).strip(),
            "confiance": float(np.mean([m["conf"] for m in mots])) if mots else 0.0,
            "latence_s": time.perf_counter() - t0,
        }


class ElevenLabsSTT:
    """ElevenLabs Speech-to-Text (Scribe), en ligne. Consomme des crédits : jamais appelé
    par les tests ; à réserver à la comparaison des moteurs (eval_stt.py --moteurs elevenlabs)."""

    # Codes ISO 639-3 attendus par l'API
    LANGUES = {"fr": "fra", "en": "eng", "ar": "ara", "es": "spa"}

    def __init__(self, langue: str | None = None, modele: str = "scribe_v3"):
        from elevenlabs.client import ElevenLabs

        cle = config.env("ELEVENLABS_API_KEY")
        if not cle:
            raise RuntimeError("ELEVENLABS_API_KEY absente du fichier .env")
        self.client = ElevenLabs(api_key=cle)
        self.nom = f"elevenlabs-{modele}"
        self.modele = modele
        self.langue = self.LANGUES.get(langue or "", langue)

    def transcrire(self, chemin) -> dict:
        t0 = time.perf_counter()
        with open(chemin, "rb") as f:
            r = self.client.speech_to_text.convert(model_id=self.modele, file=f, language_code=self.langue,
                                                   tag_audio_events=False)
        latence = time.perf_counter() - t0
        mots = [w for w in (r.words or []) if w.type == "word" and w.logprob is not None]
        return {
            "texte": (r.text or "").strip(),
            # logprob -> probabilité : même échelle 0..1 que les autres moteurs
            "confiance": float(np.mean([math.exp(w.logprob) for w in mots])) if mots else 0.0,
            "latence_s": latence,
        }


MOTEURS = {
    "whisper-tiny": lambda langue, prompt=None: Whisper("tiny", langue, prompt),
    "whisper-base": lambda langue, prompt=None: Whisper("base", langue, prompt),
    "whisper-small": lambda langue, prompt=None: Whisper("small", langue, prompt),
    "vosk": lambda langue, prompt=None: Vosk(langue or "fr"),
    "elevenlabs": lambda langue, prompt=None: ElevenLabsSTT(langue),
}


def creer_moteur(nom: str, langue: str | None = None, prompt: str | None = None):
    """prompt : vocabulaire du métier (utilisé par Whisper, ignoré par les autres moteurs)."""
    if nom not in MOTEURS:
        raise ValueError(f"moteur STT inconnu : {nom} (disponibles : {', '.join(MOTEURS)})")
    return MOTEURS[nom](langue, prompt)
