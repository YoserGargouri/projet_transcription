"""
Appel simulé audio -> audio : chaque tour est un fichier WAV (ou un enregistrement micro).

    python -m agentkit.channels.audio --fichiers question1.wav question2.wav --jouer
    python -m agentkit.channels.audio --micro 6 --jouer          # parler 6 s par tour, au clavier : Entrée

Pour chaque tour : transcription, décision qualité, réponse de l'agent, fichier audio de la
réponse (runtime/appels/<session>/), latences par étape. Moteurs STT / TTS : ceux du pack
(--stt pour en forcer un, ex. whisper-base, plus rapide sur processeur).
"""
import argparse
import json
from pathlib import Path

from agentkit import config
from agentkit.channels.audio.channel import AudioChannel
from agentkit.channels.audio.stt import MOTEURS, creer_moteur
from agentkit.channels.audio.tts import TTSService, jouer
from agentkit.orchestrator import Orchestrator


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domaine", default=config.domaine_par_defaut())
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--fichiers", nargs="+", help="un fichier WAV par tour")
    source.add_argument("--micro", type=float, metavar="SECONDES", help="enregistrer chaque tour au micro")
    ap.add_argument("--stt", choices=list(MOTEURS), help="forcer le moteur STT")
    ap.add_argument("--tts", choices=["elevenlabs", "gtts", "piper"], help="forcer le moteur TTS")
    ap.add_argument("--sans-llm", action="store_true")
    ap.add_argument("--jouer", action="store_true", help="lire chaque réponse")
    args = ap.parse_args()

    orch = Orchestrator.from_domain(args.domaine, gateway=None if args.sans_llm else "env")
    stt = creer_moteur(args.stt or orch.pack.channels.audio.stt.engine, langue=orch.pack.language)
    canal = AudioChannel(orch, stt=stt, tts=TTSService.from_pack(orch.pack, engine=args.tts))
    orch.warmup()                                         # modèles chargés avant le premier tour
    dossier = config.runtime_dir("appels", orch.state.session_id)
    print(f"[pack {orch.pack.id} | STT {stt.nom} | LLM {orch.gateway.name if orch.gateway else 'aucun'} | "
          f"sorties : {dossier}]")
    accueil = canal.tts.synthesize(orch.start(), dossier / "00_accueil.wav")
    print(f"agent > {orch.pack.persona.greeting}")
    if args.jouer:
        jouer(accueil["file"])

    tours = args.fichiers or iter(int, 1)   # micro : tours sans fin (Ctrl+C pour arrêter)
    for n, entree in enumerate(tours, start=1):
        if args.micro:
            from agentkit.channels.audio.essai_stt import enregistrer

            if input("[Entrée pour parler, q pour quitter] ").strip().lower() == "q":
                break
            entree = enregistrer(args.micro, dossier / f"{n:02d}_vous.wav")
        r = canal.handle_audio(entree, dossier / f"{n:02d}_agent.wav")
        print(f"vous  > {r.transcript or '(rien compris)'}   [confiance {r.stt_confidence:.0%}, "
              f"qualité {r.quality_decision}, SNR {r.quality['snr_db']} dB]")
        print(f"agent > {r.reply}")
        print(f"        latences : {json.dumps(r.timings, ensure_ascii=False)}")
        if args.jouer:
            jouer(r.reply_audio)
        if r.turn.escalated:
            print(f"[transfert vers un humain : {r.turn.escalation_reason}]")
            break


if __name__ == "__main__":
    main()
