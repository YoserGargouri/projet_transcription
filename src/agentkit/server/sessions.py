"""
Conversations en direct de la plateforme (Playground texte et voix).

Une session = l'Orchestrator existant, construit sur le pack effectif de l'agent
(agents.build_pack), avec sa propre passerelle LLM (compteurs de jetons par conversation).
La voix réutilise AudioChannel tel quel : STT partagé entre les sessions (le modèle Whisper
n'est chargé qu'une fois), TTS du pack (ElevenLabs, repli gTTS). Aucune intégration n'est
dupliquée ici : ce module ne fait que créer, retrouver, faire vivre et clore les sessions.

Budget ElevenLabs : au-delà de la limite mensuelle de caractères fixée dans les réglages de
l'espace de travail, la voix passe automatiquement sur gTTS (gratuit).
"""
from __future__ import annotations

import logging
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import soundfile as sf

from agentkit import config
from agentkit.domain.schema import DomainPack
from agentkit.llm.gateway import LLMGateway, gateway_from_env
from agentkit.orchestrator import Orchestrator
from agentkit.server.agents import build_pack, effective_settings
from agentkit.server.db import Database, loads, new_id, now_iso
from agentkit.server.recorder import Anonymiser, Recorder

log = logging.getLogger("agentkit.platform")

IDLE_TIMEOUT_S = 30 * 60
DEFAULT_TTS_MONTHLY_LIMIT = 3000


def audio_dir(conv_id: str) -> Path:
    return config.runtime_dir("platform", "audio", conv_id)


class SessionError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass
class LiveSession:
    id: str
    workspace_id: str
    agent_id: str
    pack: DomainPack
    orch: Orchestrator
    anonymise: Anonymiser
    lock: threading.Lock = field(default_factory=threading.Lock)
    last_active: float = field(default_factory=time.monotonic)
    audio: object | None = None          # AudioChannel, créé au premier tour vocal
    voice_enabled: bool = True           # canal voix activé dans les réglages de l'agent

    @property
    def gateway(self) -> LLMGateway | None:
        return self.orch.gateway


_stt_cache: dict[tuple, object] = {}
_stt_lock = threading.Lock()


def shared_stt(engine: str, language: str, prompt: str):
    """Un seul moteur STT par (moteur, langue, prompt) pour tout le serveur."""
    from agentkit.channels.audio.stt import creer_moteur

    cle = (engine, language, prompt)
    with _stt_lock:
        if cle not in _stt_cache:
            _stt_cache[cle] = _VerrouSTT(creer_moteur(engine, langue=language, prompt=prompt))
        return _stt_cache[cle]


class _VerrouSTT:
    """Le modèle Whisper partagé transcrit une requête à la fois."""

    def __init__(self, moteur):
        self.moteur, self.nom, self._lock = moteur, getattr(moteur, "nom", "stt"), threading.Lock()

    def transcrire(self, chemin):
        with self._lock:
            return self.moteur.transcrire(chemin)


class SessionManager:
    def __init__(self, db: Database, gateway_factory=gateway_from_env, preload_stt: bool = False):
        self.db = db
        self.preload_stt = preload_stt          # vrai en service (python -m agentkit.server), faux en test
        self.recorder = Recorder(db)
        self.gateway_factory = gateway_factory
        self._sessions: dict[str, LiveSession] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ cycle de vie ------------
    def start(self, workspace_id: str, agent: dict, source: str = "playground") -> tuple[LiveSession, str]:
        self.expire_idle()
        pack = build_pack(self.db, agent)
        conv_id = new_id("conv_")
        orch = Orchestrator(pack, gateway=self.gateway_factory(), session_id=conv_id, log=False)
        greeting = orch.start()
        live = LiveSession(id=conv_id, workspace_id=workspace_id, agent_id=agent["id"], pack=pack, orch=orch,
                           anonymise=Anonymiser(pack),
                           voice_enabled=bool(pack.channels.audio) and effective_settings(agent, pack)["channels"]["voice"])
        t = now_iso()
        self.recorder.open_conversation({
            "id": conv_id, "workspace_id": workspace_id, "agent_id": agent["id"], "agent_name": agent["name"],
            "channel": "chat", "source": source, "customer_ref": "CUST-" + new_id()[:6].upper(),
            "started_at": t, "last_activity_at": t, "status": "active", "outcome": "in_progress"}, greeting)
        with self._lock:
            self._sessions[conv_id] = live
        if live.voice_enabled and self.preload_stt:   # le modèle STT se charge pendant que l'on lit l'accueil
            spec = pack.channels.audio
            threading.Thread(target=self._precharger_stt, args=(spec.stt.engine, pack.language, spec.stt.prompt),
                             daemon=True).start()
        log.info("conversation ouverte (agent %s, mode %s, LLM %s)", agent["id"], pack.llm.mode,
                 "oui" if orch.gateway else "non")
        return live, greeting

    @staticmethod
    def _precharger_stt(engine: str, language: str, prompt: str) -> None:
        try:
            shared_stt(engine, language, prompt)
        except Exception as e:  # modèle absent hors ligne... : l'erreur ressortira au premier tour vocal
            log.warning("préchargement STT impossible (%s)", type(e).__name__)

    def get(self, workspace_id: str, conv_id: str) -> LiveSession:
        with self._lock:
            live = self._sessions.get(conv_id)
        if live is None or live.workspace_id != workspace_id:      # isolation : jamais la session d'un autre
            raise SessionError("This conversation is no longer active. Start a new one.", 404)
        live.last_active = time.monotonic()
        return live

    def end(self, workspace_id: str, conv_id: str) -> None:
        with self._lock:
            live = self._sessions.get(conv_id)
            if live is not None and live.workspace_id == workspace_id:
                del self._sessions[conv_id]
        if live is not None and live.workspace_id == workspace_id:
            self.recorder.close_conversation(conv_id, workspace_id)
            if not self.db.one("SELECT 1 FROM conversations WHERE id = ?", (conv_id,)):
                import shutil

                shutil.rmtree(config.runtime_dir("platform", "audio") / conv_id, ignore_errors=True)

    def end_for_agent(self, workspace_id: str, agent_id: str) -> None:
        with self._lock:
            ids = [s.id for s in self._sessions.values() if s.workspace_id == workspace_id and s.agent_id == agent_id]
        for i in ids:
            self.end(workspace_id, i)

    def expire_idle(self) -> None:
        limite = time.monotonic() - IDLE_TIMEOUT_S
        with self._lock:
            vieilles = [s for s in self._sessions.values() if s.last_active < limite]
        for s in vieilles:
            self.end(s.workspace_id, s.id)

    def close_all(self) -> None:
        with self._lock:
            toutes = list(self._sessions.values())
        for s in toutes:
            self.end(s.workspace_id, s.id)

    # ------------------------------------------------------------------ tours ------------------
    def _usage(self, live: LiveSession) -> dict:
        return live.gateway.usage.snapshot() if live.gateway else {}

    @staticmethod
    def _delta(avant: dict, apres: dict) -> dict:
        return {k: apres.get(k, 0) - avant.get(k, 0) for k in ("prompt_tokens", "completion_tokens", "logical_calls")}

    def text_turn(self, live: LiveSession, text: str) -> dict:
        with live.lock:
            avant = self._usage(live)
            t0 = time.perf_counter()
            r = live.orch.handle_text(text)
            latence = (time.perf_counter() - t0) * 1000
            return self._record(live, r, text, "chat", latence, self._delta(avant, self._usage(live)))

    def voice_turn(self, live: LiveSession, wav_bytes: bytes) -> dict:
        if live.pack.channels.audio is None or not live.voice_enabled:
            raise SessionError("Voice is not enabled for this agent.")
        with live.lock:
            canal = self._audio(live)
            n = live.orch.state.turn + 1
            dossier = audio_dir(live.id)
            reponse = dossier / f"turn_{n:02d}.wav"
            with tempfile.TemporaryDirectory() as tmp:        # l'audio de l'appelant n'est pas conservé
                entree = Path(tmp) / "input.wav"
                entree.write_bytes(wav_bytes)
                try:
                    duree = sf.info(str(entree)).duration
                except RuntimeError as e:
                    raise SessionError("Unreadable audio: send a WAV recording.") from e
                avant = self._usage(live)
                t0 = time.perf_counter()
                r = canal.handle_audio(entree, reponse)
                latence = (time.perf_counter() - t0) * 1000
            tts = r.timings.get("tts_engine")
            chars = 0 if r.timings.get("tts_cached") or tts != "elevenlabs" else len(r.reply)
            tour = self._record(live, r.turn, r.transcript or "[inaudible]", "voice", latence,
                                self._delta(avant, self._usage(live)), tts_chars=chars, stt_seconds=duree,
                                audio_file=reponse.name, timings={**r.timings, "stt_confidence": round(r.stt_confidence, 2),
                                                                  "quality": r.quality_decision})
            return {**tour, "transcript": r.transcript, "audio_url": f"/api/conversations/{live.id}/audio/{reponse.name}"}

    def greeting_audio(self, live: LiveSession) -> str | None:
        """Accueil dit à voix haute au début d'une conversation vocale."""
        if live.pack.channels.audio is None:
            return None
        with live.lock:
            canal = self._audio(live)
            chemin = audio_dir(live.id) / "turn_00.wav"
            if not chemin.exists():
                sortie = canal.tts.synthesize(live.pack.persona.greeting, chemin)
                chars = sortie["chars_billed"] if sortie["engine"] == "elevenlabs" else 0
                self.recorder.record_greeting_audio(live.id, live.workspace_id, chemin.name, chars)
            return f"/api/conversations/{live.id}/audio/{chemin.name}"

    def _audio(self, live: LiveSession):
        from agentkit.channels.audio.channel import AudioChannel
        from agentkit.channels.audio.tts import TTSService

        moteur = None if self._tts_budget_ok(live.workspace_id) else "gtts"
        if live.audio is None or getattr(live.audio, "_moteur_force", None) != moteur:
            spec = live.pack.channels.audio
            stt = shared_stt(spec.stt.engine, live.pack.language, spec.stt.prompt)
            canal = AudioChannel(live.orch, stt=stt, tts=TTSService.from_pack(live.pack, engine=moteur))
            canal._moteur_force = moteur
            live.audio = canal
        return live.audio

    def _tts_budget_ok(self, workspace_id: str) -> bool:
        ws = self.db.one("SELECT settings FROM workspaces WHERE id = ?", (workspace_id,))
        limite = loads(ws["settings"] if ws else None).get("tts_monthly_char_limit", DEFAULT_TTS_MONTHLY_LIMIT)
        if not limite:
            return True
        mois = time.strftime("%Y-%m")
        utilise = self.db.one("SELECT COALESCE(SUM(tts_chars), 0) AS n FROM conversations WHERE workspace_id = ? "
                              "AND substr(started_at, 1, 7) = ?", (workspace_id, mois))["n"]
        return utilise < int(limite)

    def _record(self, live: LiveSession, r, user_text: str, channel: str, latency_ms: float, usage: dict,
                **kw) -> dict:
        run = live.orch.state.run
        live.anonymise.observe(run.slots if run else None)
        tour = self.recorder.record_turn(
            conv_id=live.id, workspace_id=live.workspace_id, agent_id=live.agent_id, pack=live.pack,
            anonymise=live.anonymise, result=r, user_text=user_text, channel=channel, latency_ms=latency_ms,
            usage=usage, awaiting_confirmation=live.orch.state.awaiting_confirmation,
            run_workflow=run.workflow_id if run else None, run_item=(run.item or {}).get("id") if run else None, **kw)
        return {"idx": tour["idx"], "reply": r.reply, "user_text": tour["user_text"], "intent": r.intent,
                "llm_used": bool(tour["llm_used"]), "llm_failed": bool(tour["llm_failed"]),
                "escalated": r.escalated, "escalation_reason": r.escalation_reason,
                "latency_ms": tour["latency_ms"], "tokens": usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0),
                "details": tour["details"], "created_at": tour["created_at"]}
