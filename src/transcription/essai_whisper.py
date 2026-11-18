"""
Essai rapide de la transcription avec Whisper (faster-whisper).

Usage (depuis la racine du projet) :

    # Parler au micro pendant 6 secondes, puis voir la transcription
    python src/transcription/essai_whisper.py --micro 6

    # Transcrire un fichier existant
    python src/transcription/essai_whisper.py --fichier data/audio/S04.wav

    # Choisir un autre modèle : tiny, base, small (défaut), medium
    python src/transcription/essai_whisper.py --micro 6 --modele base

Au premier lancement, le modèle est téléchargé une fois (small : environ 500 Mo).
Le mode micro demande : pip install sounddevice
"""
import argparse
import time
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 16000


def enregistrer(secondes: float, chemin: Path) -> Path:
    import sounddevice as sd

    print(f"\nParlez maintenant ({secondes:.0f} secondes)...")
    y = sd.rec(int(secondes * SR), samplerate=SR, channels=1, dtype="float32")
    sd.wait()
    y = y[:, 0]
    print("Enregistrement terminé.")
    if np.max(np.abs(y)) < 0.01:
        print("Attention : le son est presque muet. Vérifiez le micro choisi dans Windows.")
    chemin.parent.mkdir(parents=True, exist_ok=True)
    sf.write(chemin, y, SR, subtype="PCM_16")
    print(f"Audio sauvegardé : {chemin} (vous pouvez le réécouter)")
    return chemin


def transcrire(chemin: Path, nom_modele: str):
    from faster_whisper import WhisperModel

    print(f"\nChargement du modèle Whisper « {nom_modele} »...")
    t0 = time.perf_counter()
    modele = WhisperModel(nom_modele, device="cpu", compute_type="int8")
    print(f"Modèle prêt en {time.perf_counter() - t0:.1f} s")

    duree = sf.info(chemin).duration
    t0 = time.perf_counter()
    segments, _ = modele.transcribe(str(chemin), language="fr", beam_size=5, word_timestamps=True)
    segments = list(segments)  # la transcription se fait réellement ici
    latence = time.perf_counter() - t0

    texte = " ".join(s.text.strip() for s in segments)
    mots = [w for s in segments for w in (s.words or [])]
    confiance = float(np.mean([w.probability for w in mots])) if mots else 0.0

    print("\n" + "=" * 70)
    print(f"Transcription : {texte or '(rien compris)'}")
    print("=" * 70)
    print(f"Durée de l'audio : {duree:.1f} s | temps de transcription : {latence:.1f} s")
    print(f"Confiance moyenne : {confiance:.0%}")
    douteux = [f"{w.word.strip()} ({w.probability:.0%})" for w in mots if w.probability < 0.5]
    if douteux:
        print("Mots douteux (confiance < 50 %) : " + ", ".join(douteux))


def main():
    ap = argparse.ArgumentParser()
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--micro", type=float, metavar="SECONDES", help="enregistrer au micro")
    source.add_argument("--fichier", help="chemin d'un fichier audio")
    ap.add_argument("--modele", default="small", help="tiny, base, small, medium")
    args = ap.parse_args()

    if args.micro:
        chemin = enregistrer(args.micro, Path("data/audio/brut/essai_micro.wav"))
    else:
        chemin = Path(args.fichier)
        if not chemin.exists():
            raise SystemExit(f"Fichier introuvable : {chemin}")
    transcrire(chemin, args.modele)


if __name__ == "__main__":
    main()
