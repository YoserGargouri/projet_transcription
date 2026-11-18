"""
Évalue les moteurs de transcription sur tous les audios de data/audio/manifest.csv.

Usage (depuis la racine du projet) :
    python src/evaluation/eval_stt.py                          # whisper-small + vosk
    python src/evaluation/eval_stt.py --moteurs whisper-base   # un seul moteur
    python src/evaluation/eval_stt.py --limite 5               # essai rapide sur 5 audios

Produit :
    data/results/stt_details.csv  une ligne par audio et par moteur (texte attendu / obtenu)
    data/results/stt_resume.csv   le tableau WER moteur x condition
et affiche les résultats dans le terminal.

WER (Word Error Rate) = (mots remplacés + supprimés + ajoutés) / nombre de mots attendus.
0 % = transcription parfaite. Majuscules et ponctuation sont ignorées.
"""
import argparse
import sys
from pathlib import Path

import jiwer
import librosa
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from transcription.qualite import estimer_snr  # noqa: E402
from transcription.stt import MOTEURS  # noqa: E402

NORMALISATION = jiwer.Compose([
    jiwer.SubstituteRegexes({r"[-’]": " "}),
    jiwer.ToLowerCase(),
    jiwer.RemovePunctuation(),
    jiwer.RemoveMultipleSpaces(),
    jiwer.Strip(),
    jiwer.ReduceToListOfListOfWords(),
])
ORDRE_CONDITIONS = ["propre", "snr20", "snr10", "snr5", "tel"]


def wer(refs: list, hyps: list) -> float:
    """WER global d'un groupe d'audios (pondéré par le nombre de mots)."""
    hyps = [h if h.strip() else "<vide>" for h in hyps]  # rien compris = tout faux
    return jiwer.wer(refs, hyps, reference_transform=NORMALISATION, hypothesis_transform=NORMALISATION)


def evaluer(moteur, audios: pd.DataFrame, audio_dir: Path) -> list:
    lignes = []
    for i, (_, a) in enumerate(audios.iterrows(), start=1):
        chemin = audio_dir / a["fichier"]
        r = moteur.transcrire(chemin)
        y, sr = librosa.load(chemin, sr=None)
        lignes.append({
            "moteur": moteur.nom, "audio_id": a["audio_id"], "type": a["type"],
            "condition": a["condition"], "reference": a["transcription_ref"],
            "transcription": r["texte"], "wer": wer([a["transcription_ref"]], [r["texte"]]),
            "confiance": r["confiance"], "latence_s": r["latence_s"],
            "duree_s": len(y) / sr, "snr_estime": estimer_snr(y, sr),
        })
        if i % 10 == 0 or i == len(audios):
            print(f"  {i}/{len(audios)} audios transcrits")
    return lignes


def resumer(det: pd.DataFrame) -> pd.DataFrame:
    """Tableau WER moteur x condition, plus latence et confiance moyennes."""
    resume = []
    for (moteur, cond), g in det.groupby(["moteur", "condition"]):
        resume.append({"moteur": moteur, "condition": cond,
                       "wer": wer(g["reference"].tolist(), g["transcription"].tolist()),
                       "n_audios": len(g)})
    resume = pd.DataFrame(resume)
    tableau = resume.pivot(index="moteur", columns="condition", values="wer")
    tableau = tableau[[c for c in ORDRE_CONDITIONS if c in tableau.columns]]
    par_moteur = det.groupby("moteur").agg(
        latence_moy_s=("latence_s", "mean"),
        temps_reel=("latence_s", lambda s: s.sum() / det.loc[s.index, "duree_s"].sum()),
        confiance_moy=("confiance", "mean"),
    )
    return tableau.join(par_moteur)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="data/audio/manifest.csv")
    ap.add_argument("--moteurs", nargs="+", default=["whisper-small", "vosk"], choices=list(MOTEURS))
    ap.add_argument("--limite", type=int, help="ne traiter que les N premiers audios (essai)")
    ap.add_argument("--out-dir", default="data/results")
    args = ap.parse_args()

    manifest_path = Path(args.manifest)
    audios = pd.read_csv(manifest_path, keep_default_na=False)
    audios = audios[audios["statut"] == "ok"]
    if args.limite:
        audios = audios.head(args.limite)
    print(f"{len(audios)} audios à transcrire avec : {', '.join(args.moteurs)}")

    lignes = []
    for nom in args.moteurs:
        print(f"\nChargement de {nom}...")
        try:
            moteur = MOTEURS[nom]()
        except Exception as e:  # modèle non téléchargeable, bibliothèque absente...
            print(f"  {nom} ignoré : {e}")
            continue
        lignes += evaluer(moteur, audios, manifest_path.parent)
    if not lignes:
        raise SystemExit("Aucun moteur n'a pu être chargé.")

    det = pd.DataFrame(lignes)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    det.to_csv(out / "stt_details.csv", index=False, encoding="utf-8")
    tableau = resumer(det)
    tableau.to_csv(out / "stt_resume.csv", encoding="utf-8")

    pd.set_option("display.width", 200)
    print("\n=== WER par moteur et par condition (plus bas = mieux) ===")
    affiche = tableau.copy()
    for c in affiche.columns:
        if c in ORDRE_CONDITIONS or c == "confiance_moy":
            affiche[c] = affiche[c].map(lambda v: f"{v:.0%}")
        else:
            affiche[c] = affiche[c].map(lambda v: f"{v:.2f}")
    print(affiche.to_string())
    print("temps_reel = temps de calcul / durée de l'audio (< 1 : plus rapide que la parole)")

    print("\n=== La confiance prévient-elle des erreurs ? (corrélation confiance / WER) ===")
    for moteur, g in det.groupby("moteur"):
        if g["wer"].nunique() < 2 or g["confiance"].nunique() < 2:
            print(f"{moteur:<15} pas assez de variation pour conclure")
            continue
        corr = g["confiance"].corr(g["wer"], method="spearman")
        print(f"{moteur:<15} {corr:+.2f}   (proche de -1 : confiance basse = beaucoup d'erreurs, c'est ce qu'on veut)")

    print("\n=== SNR estimé sans référence, par condition (médiane, dB) ===")
    snr = det.groupby("condition")["snr_estime"].median().reindex(ORDRE_CONDITIONS).dropna()
    print(snr.round(1).to_string() if not snr.empty else "(aucun silence exploitable dans les audios)")

    print("\n=== Les 3 pires transcriptions par moteur (pour l'analyse d'erreurs) ===")
    for moteur, g in det.groupby("moteur"):
        for _, r in g.nlargest(3, "wer").iterrows():
            print(f"[{moteur} | {r['audio_id']} | WER {r['wer']:.0%}]")
            print(f"   attendu : {r['reference']}")
            print(f"   obtenu  : {r['transcription'] or '(rien)'}")
    print(f"\nRésultats complets : {out / 'stt_details.csv'} et {out / 'stt_resume.csv'}")


if __name__ == "__main__":
    main()
