"""
Synthèse vocale (TTS, WP2) : texte -> fichier WAV 16 kHz mono, moteurs interchangeables.

    tts = TTSService.from_pack(pack)                 # moteur, voix, modèle et repli : domain.yaml
    r = tts.synthesize("Bonjour, je vous écoute.", "reponse.wav")
    r == {"file": ..., "engine": "elevenlabs", "cached": False, "chars_billed": 24, "latency_s": 0.4, ...}

Moteurs : elevenlabs (principal, clé ELEVENLABS_API_KEY), gtts (gratuit, en ligne),
piper (gratuit, hors ligne, extra facultatif). En cas d'échec, on passe au suivant.

Crédits ElevenLabs protégés :
- chaque synthèse est mise en cache, clé = hash(moteur, texte, voix, modèle, réglages, langue) ;
- chaque appel réellement facturé est journalisé (runtime/logs/tts_usage.jsonl, caractères) ;
- les tests n'appellent jamais ElevenLabs (client simulé, voir conftest.py).

Essai manuel :
    python -m agentkit.channels.audio.tts --texte "Bonjour, je vous écoute." --out sortie.wav --jouer
"""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import time
from abc import ABC, abstractmethod
from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf

from agentkit import config
from agentkit.domain.schema import DomainPack, TtsSpec

SR = 16000


def _vers_16k(y: np.ndarray, sr: int) -> np.ndarray:
    y = np.asarray(y, dtype=np.float32)
    if y.ndim > 1:
        y = y.mean(axis=1)
    if sr != SR:
        from scipy.signal import resample_poly

        g = gcd(SR, sr)
        y = resample_poly(y, SR // g, sr // g).astype(np.float32)
    pic = float(np.max(np.abs(y))) if len(y) else 0.0
    return 0.9 * y / pic if pic > 1e-6 else y


class TTSEngine(ABC):
    name = "?"

    @abstractmethod
    def synthesize(self, text: str) -> tuple[np.ndarray, int]: ...

    def cache_identity(self) -> dict:
        """Ce qui change le son produit (entre dans la clé du cache)."""
        return {"engine": self.name}

    def billed_chars(self, text: str) -> int:
        return 0


class ElevenLabsTTS(TTSEngine):
    name = "elevenlabs"
    # Modèles qui acceptent language_code (forçage de la langue)
    AVEC_LANGUE = {"eleven_flash_v2_5", "eleven_turbo_v2_5"}

    def __init__(self, voice_id: str | None, model_id: str | None, settings: dict | None, language: str,
                 client=None):
        self.voice_id = voice_id or config.env("ELEVENLABS_VOICE_ID") or None
        self.model_id = model_id or config.env("ELEVENLABS_MODEL_ID") or "eleven_flash_v2_5"
        self.settings = settings or {}
        self.language = language
        self._client = client

    @property
    def client(self):
        if self._client is None:
            cle = config.env("ELEVENLABS_API_KEY")
            if not cle:
                raise RuntimeError("ELEVENLABS_API_KEY absente du fichier .env")
            from elevenlabs.client import ElevenLabs

            self._client = ElevenLabs(api_key=cle)
        return self._client

    def _voix(self) -> str:
        if not self.voice_id:
            # Pas de voix choisie : la première voix « premade » du compte. Les voix de la
            # bibliothèque (professional, ...) sont refusées par l'API sur l'offre gratuite (402).
            voix = self.client.voices.search(page_size=100).voices
            premade = [v for v in voix if getattr(v, "category", "") == "premade"]
            if not (premade or voix):
                raise RuntimeError("aucune voix sur le compte ElevenLabs")
            self.voice_id = (premade or voix)[0].voice_id
        return self.voice_id

    def cache_identity(self) -> dict:
        return {"engine": self.name, "voice": self.voice_id or "(première voix)", "model": self.model_id,
                "settings": self.settings, "language": self.language}

    def billed_chars(self, text: str) -> int:
        return len(text)

    def synthesize(self, text: str):
        options = {"output_format": "pcm_16000", "model_id": self.model_id}
        if self.model_id in self.AVEC_LANGUE:
            options["language_code"] = self.language
        if self.settings:
            from elevenlabs.types import VoiceSettings

            options["voice_settings"] = VoiceSettings(**self.settings)
        flux = self.client.text_to_speech.convert(self._voix(), text=text, **options)
        pcm = b"".join(flux)
        return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0, 16000


class GTTSEngine(TTSEngine):
    name = "gtts"

    def __init__(self, language: str):
        self.language = language

    def cache_identity(self) -> dict:
        return {"engine": self.name, "language": self.language}

    def synthesize(self, text: str):
        from gtts import gTTS

        tampon = io.BytesIO()
        gTTS(text, lang=self.language).write_to_fp(tampon)
        tampon.seek(0)
        return sf.read(tampon, dtype="float32")


class PiperTTS(TTSEngine):
    """Hors ligne. Extra facultatif : pip install -e .[piper]"""

    name = "piper"
    VOIX = {"fr": "fr/fr_FR/siwis/medium/fr_FR-siwis-medium", "en": "en/en_US/lessac/medium/en_US-lessac-medium"}

    def __init__(self, language: str):
        self.language = language
        self._voix = None

    def cache_identity(self) -> dict:
        return {"engine": self.name, "voice": self.VOIX.get(self.language)}

    def synthesize(self, text: str):
        if self._voix is None:
            from huggingface_hub import hf_hub_download
            from piper import PiperVoice

            chemin = self.VOIX[self.language]
            onnx = hf_hub_download("rhasspy/piper-voices", f"{chemin}.onnx")
            hf_hub_download("rhasspy/piper-voices", f"{chemin}.onnx.json")
            self._voix = PiperVoice.load(onnx)
        morceaux = list(self._voix.synthesize(text))
        return np.concatenate([m.audio_float_array for m in morceaux]), morceaux[0].sample_rate


def build_engine(nom: str, spec: TtsSpec, language: str) -> TTSEngine:
    if nom == "elevenlabs":
        return ElevenLabsTTS(spec.voice_id, spec.model_id, dict(spec.settings), language)
    if nom == "gtts":
        return GTTSEngine(language)
    if nom == "piper":
        return PiperTTS(language)
    raise ValueError(f"moteur TTS inconnu : {nom}")


class TTSService:
    """Chaîne de moteurs (principal + repli), cache disque et journal d'usage."""

    def __init__(self, engines: list[TTSEngine], cache_dir: Path | None = None, usage_log: Path | None = None):
        self.engines = engines
        self.cache_dir = Path(cache_dir) if cache_dir else config.runtime_dir("cache", "tts")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.usage_log = Path(usage_log) if usage_log else config.runtime_dir("logs") / "tts_usage.jsonl"
        self.usage_log.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_pack(cls, pack: DomainPack, engine: str | None = None) -> TTSService:
        spec = pack.channels.audio.tts if pack.channels.audio else TtsSpec()
        noms = [engine] if engine else [spec.engine, *[f for f in spec.fallback if f != spec.engine]]
        return cls([build_engine(n, spec, pack.language) for n in noms])

    def _cle(self, engine: TTSEngine, text: str) -> str:
        brut = json.dumps({**engine.cache_identity(), "text": text}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(brut.encode("utf-8")).hexdigest()[:24]

    def synthesize(self, text: str, out_path: str | Path) -> dict:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        erreurs = []
        for engine in self.engines:
            cache = self.cache_dir / f"{engine.name}_{self._cle(engine, text)}.wav"
            if cache.exists():
                shutil.copy(cache, out_path)
                return self._resultat(out_path, engine, cached=True, chars=0, latence=0.0, erreurs=erreurs)
            t0 = time.perf_counter()
            try:
                y, sr = engine.synthesize(text)
            except Exception as e:  # quota, réseau, clé absente : moteur suivant
                erreurs.append(f"{engine.name} : {type(e).__name__} {str(e)[:150]}")
                continue
            latence = time.perf_counter() - t0
            sf.write(cache, _vers_16k(y, sr), SR, subtype="PCM_16")
            shutil.copy(cache, out_path)
            chars = engine.billed_chars(text)
            with open(self.usage_log, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **engine.cache_identity(),
                                    "chars": chars, "latency_s": round(latence, 3)}, ensure_ascii=False) + "\n")
            return self._resultat(out_path, engine, cached=False, chars=chars, latence=latence, erreurs=erreurs)
        raise RuntimeError("aucun moteur TTS n'a fonctionné : " + " | ".join(erreurs))

    @staticmethod
    def _resultat(path, engine, cached, chars, latence, erreurs=None) -> dict:
        info = sf.info(path)
        return {"file": str(path), "engine": engine.name, "cached": cached, "chars_billed": chars,
                "latency_s": round(latence, 3), "sample_rate": info.samplerate, "channels": info.channels,
                "duration_s": round(info.duration, 2), "fallback_errors": erreurs or []}


def jouer(chemin: str | Path) -> None:
    try:
        import winsound

        winsound.PlaySound(str(chemin), winsound.SND_FILENAME)
    except ImportError:
        import sounddevice as sd

        y, sr = sf.read(chemin)
        sd.play(y, sr)
        sd.wait()


def main():
    import argparse

    from agentkit.domain.loader import load_domain

    ap = argparse.ArgumentParser(description="Synthèse d'une phrase avec le TTS du pack (cache disque)")
    ap.add_argument("--domaine", default=config.domaine_par_defaut())
    ap.add_argument("--texte", default="Bonjour, je vous écoute. Que puis-je faire pour vous ?")
    ap.add_argument("--out", default="sortie_tts.wav")
    ap.add_argument("--moteur", choices=["elevenlabs", "gtts", "piper"], help="forcer un moteur (sans repli)")
    ap.add_argument("--jouer", action="store_true", help="lire le fichier produit")
    args = ap.parse_args()

    r = TTSService.from_pack(load_domain(args.domaine), engine=args.moteur).synthesize(args.texte, args.out)
    for erreur in r["fallback_errors"]:
        print(f"[repli] {erreur}")
    origine = "cache (0 crédit)" if r["cached"] else f"{r['chars_billed']} caractères facturés"
    print(f"{r['file']} | moteur {r['engine']} | {origine} | {r['sample_rate']} Hz, {r['channels']} canal, "
          f"{r['duration_s']} s | synthèse {r['latency_s']} s")
    if args.jouer:
        jouer(r["file"])


if __name__ == "__main__":
    main()
