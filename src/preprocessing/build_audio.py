"""
Prépare les audios de test pour la transcription (Whisper).

Deux commandes, à lancer depuis la racine du projet :

1) Voix synthétiques + fiche d'enregistrement des voix réelles
    python src/preprocessing/build_audio.py synth

   - choisit 20 phrases du jeu de TEST (toutes les branches, des phrases agacées,
     des pièges médicaux, des phrases incomplètes) ;
   - les lit avec une voix de synthèse (gTTS, accents France et Canada) ;
   - écrit data/audio/<id>.wav en 16 kHz mono ;
   - écrit data/audio/manifest.csv : la liste de tous les audios et leur texte exact.
   Il faut une connexion Internet (gTTS utilise le service de Google).

2) Voix réelles : après avoir enregistré les phrases (voir manifest.csv, lignes
   type = reel), placez les fichiers WAV dans data/audio/brut/ en les nommant avec
   leur audio_id (ex. R01.wav), puis :
    python src/preprocessing/build_audio.py normaliser

   Chaque fichier est converti en 16 kHz mono, volume normalisé, dans data/audio/.

Format commun de tous les audios : WAV, 16 kHz, mono, 16 bits (format attendu par Whisper).
"""
import argparse
import random
import tempfile
from pathlib import Path

import librosa
import numpy as np
import pandas as pd
import soundfile as sf

SR = 16000
SEED = 42
# Accents disponibles dans gTTS pour le français (domaine Google utilisé)
VOIX_SYNTH = [("gtts-fr", "fr"), ("gtts-ca", "ca")]


def choisir_phrases(phrases: pd.DataFrame, n: int) -> pd.DataFrame:
    """Échantillon varié du jeu de test : quotas par cas difficile, puis complément."""
    test = phrases[phrases["split"] == "test"].copy()
    rng = random.Random(SEED)
    quotas = [
        ("pièges médicaux", test["hors_perimetre"] == 1, 3),
        ("info manquante", test["info_manquante"] != "", 3),
        ("frustration", test["frustration"] == 1, 4),
        ("rdv existant", test["branche"] == "rdv_existant", 3),
        ("info générale", test["branche"] == "info_generale", 3),
    ]
    choisis = []
    for _, masque, k in quotas:
        dispo = [i for i in test[masque].index if i not in choisis]
        choisis += rng.sample(dispo, min(k, len(dispo)))
    reste = [i for i in test.index if i not in choisis]
    choisis += rng.sample(reste, max(0, n - len(choisis)))
    return test.loc[choisis[:n]]


def ecrire_wav(y: np.ndarray, sr: int, chemin: Path):
    """Convertit en mono 16 kHz, normalise le volume et écrit en WAV 16 bits."""
    if y.ndim > 1:
        y = y.mean(axis=1)
    if sr != SR:
        y = librosa.resample(y, orig_sr=sr, target_sr=SR)
    pic = np.max(np.abs(y))
    if pic > 0:
        y = 0.9 * y / pic
    sf.write(chemin, y, SR, subtype="PCM_16")


def synth(args):
    from gtts import gTTS  # importé ici : inutile pour la commande "normaliser"

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    phrases = pd.read_csv(args.phrases, keep_default_na=False)
    choix = choisir_phrases(phrases, args.n)

    lignes = []
    for k, (_, p) in enumerate(choix.iterrows(), start=1):
        voix, tld = VOIX_SYNTH[k % len(VOIX_SYNTH)]
        audio_id = f"S{k:02d}"
        with tempfile.TemporaryDirectory() as tmp:
            mp3 = Path(tmp) / "tts.mp3"
            gTTS(p["texte"], lang="fr", tld=tld).save(str(mp3))
            y, sr = sf.read(mp3)
        ecrire_wav(y, sr, out / f"{audio_id}.wav")
        print(f"{audio_id}.wav  ({voix})  {p['texte'][:70]}")
        lignes.append({"audio_id": audio_id, "phrase_id": p["id"], "transcription_ref": p["texte"],
                       "type": "synth", "locuteur": voix, "condition": "propre",
                       "fichier": f"{audio_id}.wav", "statut": "ok"})

    # Mêmes phrases à enregistrer par de vraies voix : on pourra comparer synthèse / réel
    for k, (_, p) in enumerate(choix.iterrows(), start=1):
        lignes.append({"audio_id": f"R{k:02d}", "phrase_id": p["id"], "transcription_ref": p["texte"],
                       "type": "reel", "locuteur": "", "condition": "propre",
                       "fichier": f"R{k:02d}.wav", "statut": "a_enregistrer"})

    manifest = pd.DataFrame(lignes)
    manifest.to_csv(out / "manifest.csv", index=False, encoding="utf-8")
    print(f"\n{args.n} audios synthétiques écrits dans {out}/")
    print(f"{args.n} phrases à enregistrer avec de vraies voix : lignes type = reel de manifest.csv")


def normaliser(args):
    out = Path(args.out_dir)
    brut = out / "brut"
    manifest = pd.read_csv(out / "manifest.csv", keep_default_na=False)
    faits = 0
    for i, ligne in manifest[manifest["type"] == "reel"].iterrows():
        src = brut / ligne["fichier"]
        if not src.exists():
            continue
        y, sr = sf.read(src)
        ecrire_wav(y, sr, out / ligne["fichier"])
        manifest.loc[i, "statut"] = "ok"
        faits += 1
    manifest.to_csv(out / "manifest.csv", index=False, encoding="utf-8")
    restants = (manifest["statut"] == "a_enregistrer").sum()
    print(f"{faits} enregistrements convertis en 16 kHz mono. Encore à enregistrer : {restants}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="commande", required=True)
    s = sub.add_parser("synth", help="voix synthétiques + fiche d'enregistrement")
    s.add_argument("--phrases", default="data/phrases_annotees.csv")
    s.add_argument("--n", type=int, default=20)
    s.add_argument("--out-dir", default="data/audio")
    s.set_defaults(func=synth)
    n = sub.add_parser("normaliser", help="convertit les enregistrements de data/audio/brut/")
    n.add_argument("--out-dir", default="data/audio")
    n.set_defaults(func=normaliser)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
