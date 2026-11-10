"""
Crée des versions dégradées des audios de test, pour mesurer la robustesse de Whisper.

Usage (depuis la racine du projet) :
    python src/preprocessing/build_noise.py

Pour chaque audio « propre » de data/audio/manifest.csv, on crée :
    <id>_snr20.wav   bruit de fond léger   (rapport signal/bruit 20 dB)
    <id>_snr10.wav   bruit de fond marqué  (10 dB)
    <id>_snr5.wav    bruit de fond fort    (5 dB)
    <id>_tel.wav     son « téléphone » : bande 300-3400 Hz, comme une vraie ligne

Les bruits viennent du corpus MUSAN (licence CC BY 4.0), téléchargés une seule fois
dans data/raw/noise/ depuis le miroir Hugging Face FluidInference/musan.
Sans Internet, ajoutez l'option --sans-telechargement : un bruit blanc est utilisé.

Les nouvelles lignes sont ajoutées à manifest.csv (colonne condition).
Relancer le script recrée les variantes sans créer de doublons.
"""
import argparse
import random
from pathlib import Path

import librosa
import numpy as np
import pandas as pd
import soundfile as sf
from scipy.signal import butter, sosfilt

SR = 16000
SEED = 42
SNRS = [20, 10, 5]
DEPOT_MUSAN = "FluidInference/musan"


def telecharger_bruits(dossier: Path, n: int) -> None:
    """Télécharge n fichiers de bruit MUSAN (sauf s'ils sont déjà là)."""
    from huggingface_hub import hf_hub_download, list_repo_files

    dossier.mkdir(parents=True, exist_ok=True)
    if len(list(dossier.glob("*.wav"))) >= n:
        return
    fichiers = [f for f in list_repo_files(DEPOT_MUSAN, repo_type="dataset")
                if f.startswith("noise/") and f.endswith(".wav")]
    for f in random.Random(SEED).sample(fichiers, min(n, len(fichiers))):
        chemin = hf_hub_download(DEPOT_MUSAN, f, repo_type="dataset")
        y, _ = librosa.load(chemin, sr=SR, mono=True)
        sf.write(dossier / Path(f).name, y, SR, subtype="PCM_16")
        print(f"bruit téléchargé : {Path(f).name}")


def charger_bruits(dossier: Path) -> list:
    bruits = [librosa.load(f, sr=SR, mono=True)[0] for f in sorted(dossier.glob("*.wav"))]
    bruits = [b for b in bruits if np.mean(b ** 2) > 1e-8]  # on écarte les fichiers silencieux
    if not bruits:
        print("Aucun bruit MUSAN disponible : utilisation d'un bruit blanc.")
        bruits = [np.random.default_rng(SEED).normal(0, 0.1, SR * 30)]
    return bruits


def ajouter_bruit(propre: np.ndarray, bruit: np.ndarray, snr_db: float, rng) -> np.ndarray:
    """Mélange le bruit au signal pour obtenir exactement le SNR demandé."""
    if len(bruit) < len(propre):
        bruit = np.tile(bruit, int(np.ceil(len(propre) / len(bruit))))
    debut = rng.integers(0, len(bruit) - len(propre) + 1)
    bruit = bruit[debut:debut + len(propre)]
    p_signal = np.mean(propre ** 2)
    p_bruit = np.mean(bruit ** 2) + 1e-12
    bruit = bruit * np.sqrt(p_signal / (p_bruit * 10 ** (snr_db / 10)))
    melange = propre + bruit
    return melange / max(1.0, np.max(np.abs(melange)) / 0.99)  # évite la saturation


def effet_telephone(y: np.ndarray) -> np.ndarray:
    """Simule une ligne téléphonique : bande 300-3400 Hz, échantillonnage 8 kHz."""
    sos = butter(6, [300, 3400], btype="bandpass", fs=SR, output="sos")
    y = sosfilt(sos, y)
    y = librosa.resample(librosa.resample(y, orig_sr=SR, target_sr=8000), orig_sr=8000, target_sr=SR)
    return 0.9 * y / (np.max(np.abs(y)) + 1e-12)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio-dir", default="data/audio")
    ap.add_argument("--noise-dir", default="data/raw/noise")
    ap.add_argument("--n-bruits", type=int, default=6)
    ap.add_argument("--sans-telechargement", action="store_true")
    args = ap.parse_args()

    audio_dir, noise_dir = Path(args.audio_dir), Path(args.noise_dir)
    if not args.sans_telechargement:
        telecharger_bruits(noise_dir, args.n_bruits)
    bruits = charger_bruits(noise_dir)

    manifest = pd.read_csv(audio_dir / "manifest.csv", keep_default_na=False)
    manifest = manifest[manifest["condition"] == "propre"]  # on repart des seuls originaux
    propres = manifest[manifest["statut"] == "ok"]
    rng = np.random.default_rng(SEED)

    nouvelles = []
    for k, (_, a) in enumerate(propres.iterrows()):
        y, _ = librosa.load(audio_dir / a["fichier"], sr=SR, mono=True)
        variantes = {f"snr{s}": ajouter_bruit(y, bruits[(k + i) % len(bruits)], s, rng)
                     for i, s in enumerate(SNRS)}
        variantes["tel"] = effet_telephone(y)
        for cond, yv in variantes.items():
            nom = f"{a['audio_id']}_{cond}"
            sf.write(audio_dir / f"{nom}.wav", yv, SR, subtype="PCM_16")
            nouvelles.append({**a.to_dict(), "audio_id": nom, "condition": cond, "fichier": f"{nom}.wav"})

    manifest = pd.concat([manifest, pd.DataFrame(nouvelles)], ignore_index=True)
    manifest.to_csv(audio_dir / "manifest.csv", index=False, encoding="utf-8")
    print(f"\n{len(propres)} audios propres -> {len(nouvelles)} variantes créées dans {audio_dir}/")
    print(manifest[manifest["statut"] == "ok"]["condition"].value_counts().to_string())


if __name__ == "__main__":
    main()
