"""
Moteurs de transcription (STT) avec une interface commune.

    from transcription.stt import Whisper, Vosk
    moteur = Whisper("small")
    r = moteur.transcrire("data/audio/S01.wav")
    r == {"texte": "...", "confiance": 0.87, "latence_s": 1.9}

Tous les moteurs renvoient le même dictionnaire, ce qui permet de les comparer
et de les échanger dans le pipeline sans rien changer d'autre.
Les audios doivent être en WAV 16 kHz mono (format produit par build_audio.py).
"""
import json
import time

import numpy as np
import soundfile as sf


class Whisper:
    """faster-whisper, exécuté sur le processeur. Modèle téléchargé au premier usage."""

    def __init__(self, taille: str = "small"):
        from faster_whisper import WhisperModel

        self.nom = f"whisper-{taille}"
        self.modele = WhisperModel(taille, device="cpu", compute_type="int8")

    def transcrire(self, chemin) -> dict:
        t0 = time.perf_counter()
        segments, _ = self.modele.transcribe(str(chemin), language="fr", beam_size=5,
                                             word_timestamps=True)
        segments = list(segments)  # la transcription a réellement lieu ici
        latence = time.perf_counter() - t0
        mots = [w for s in segments for w in (s.words or [])]
        return {
            "texte": " ".join(s.text.strip() for s in segments).strip(),
            "confiance": float(np.mean([w.probability for w in mots])) if mots else 0.0,
            "latence_s": latence,
        }


class Vosk:
    """Vosk (Kaldi), très léger. Modèle français téléchargé au premier usage (environ 40 Mo)."""

    def __init__(self, nom_modele: str = "vosk-model-small-fr-0.22"):
        from vosk import KaldiRecognizer, Model, SetLogLevel

        SetLogLevel(-1)  # coupe les messages techniques de Kaldi
        self.nom = "vosk-fr"
        self.modele = Model(model_name=nom_modele)
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


MOTEURS = {
    "whisper-tiny": lambda: Whisper("tiny"),
    "whisper-base": lambda: Whisper("base"),
    "whisper-small": lambda: Whisper("small"),
    "vosk": Vosk,
}
