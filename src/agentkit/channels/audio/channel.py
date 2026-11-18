"""
Canal audio -> audio : un fichier (ou un enregistrement micro) par tour.

    canal = AudioChannel.from_domain("imagerie_medicale")
    r = canal.handle_audio("question.wav", "reponse.wav")
    r.transcript, r.reply, r.reply_audio, r.timings   # latence par étape et totale

Étapes : filtrage + qualité -> STT + confiance -> décision qualité -> orchestrateur (texte)
-> TTS. La langue du STT et la voix du TTS viennent du pack. Le canal ne connaît rien du
dialogue : il convertit l'audio en texte et inversement.
TODO(WP2) : en qualité moyenne (« confirmer »), faire répéter ce qui a été compris avant
d'agir. TODO(WP7) : démonstrateur Gradio (micro + lecteur) au-dessus de ce canal.
"""
from __future__ import annotations

import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import soundfile as sf

from agentkit.channels.audio.quality import decision, diagnostic, pretraiter
from agentkit.channels.audio.stt import creer_moteur
from agentkit.channels.audio.tts import TTSService
from agentkit.orchestrator import Orchestrator, TurnResult


@dataclass
class AudioTurnResult:
    transcript: str
    stt_confidence: float
    quality: dict
    quality_decision: str
    turn: TurnResult
    reply_audio: str | None
    timings: dict = field(default_factory=dict)

    @property
    def reply(self) -> str:
        return self.turn.reply


class AudioChannel:
    def __init__(self, orchestrator: Orchestrator, stt=None, tts: TTSService | None = None):
        self.orch = orchestrator
        audio = orchestrator.pack.channels.audio
        if audio is None:
            raise ValueError(f"le pack {orchestrator.pack.id} ne déclare pas de canal audio")
        self.spec = audio
        self.stt = stt or creer_moteur(audio.stt.engine, langue=orchestrator.pack.language)
        self.tts = tts or TTSService.from_pack(orchestrator.pack)

    @classmethod
    def from_domain(cls, domain: str, **kw) -> AudioChannel:
        return cls(Orchestrator.from_domain(domain), **kw)

    def handle_audio(self, audio_path: str | Path, reply_path: str | Path) -> AudioTurnResult:
        t0 = time.perf_counter()
        y, sr = sf.read(audio_path, dtype="float32")
        diag = diagnostic(y.mean(axis=1) if y.ndim > 1 else y, sr, self.spec.quality.min_duration_s)
        texte, confiance = "", 0.0
        t_stt = time.perf_counter()
        if decision(diag, self.spec.quality) != "redemander":
            y16, _ = pretraiter(y, sr)
            with tempfile.TemporaryDirectory() as tmp:
                propre = Path(tmp) / "entree.wav"
                sf.write(propre, y16, 16000, subtype="PCM_16")
                r = self.stt.transcrire(propre)
            texte, confiance = r["texte"], r["confiance"]
        t_nlu = time.perf_counter()
        choix = decision(diag, self.spec.quality, confiance, texte)
        if choix == "redemander":
            tour = self.orch.handle_unusable_input(self.spec.retry_message)
        else:
            tour = self.orch.handle_text(texte)
            tour.trace["audio_quality"] = choix
        t_tts = time.perf_counter()
        sortie = self.tts.synthesize(tour.reply, reply_path)
        fin = time.perf_counter()
        return AudioTurnResult(
            transcript=texte, stt_confidence=confiance, quality=diag, quality_decision=choix, turn=tour,
            reply_audio=sortie["file"],
            timings={"stt_s": round(t_nlu - t_stt, 3), "agent_s": round(t_tts - t_nlu, 3),
                     "tts_s": round(fin - t_tts, 3), "total_s": round(fin - t0, 3), "tts_engine": sortie["engine"],
                     "tts_cached": sortie["cached"]})
