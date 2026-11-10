"""
Tests automatiques des données de la S1.

Usage (depuis la racine du projet) :
    pip install pytest
    pytest tests/ -v

Chaque test vérifie une règle précise ; en cas d'échec, le message dit quoi corriger.
Les tests audio sont ignorés (SKIPPED) tant que data/audio/manifest.csv n'existe pas.
"""
import re
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

MODALITES = {"IRM", "Scanner", "Radio", "Échographie", "Mammographie", "Densitométrie"}
BRANCHES = {"nouveau_rdv", "rdv_existant", "info_generale", "autre"}


def lire(nom):
    chemin = DATA / nom
    if not chemin.exists():
        pytest.fail(f"{chemin} introuvable : lancez d'abord le script qui le crée.")
    return pd.read_csv(chemin, keep_default_na=False)


@pytest.fixture(scope="module")
def catalogue():
    return lire("catalogue.csv")


@pytest.fixture(scope="module")
def confusions():
    return lire("confusions.csv")


@pytest.fixture(scope="module")
def phrases():
    return lire("phrases_annotees.csv")


@pytest.fixture(scope="module")
def manifest():
    chemin = DATA / "audio" / "manifest.csv"
    if not chemin.exists():
        pytest.skip("pas encore d'audios (data/audio/manifest.csv absent)")
    return pd.read_csv(chemin, keep_default_na=False)


# --- Étape 1 : catalogue -------------------------------------------------------------
class TestCatalogue:
    def test_taille(self, catalogue):
        assert len(catalogue) >= 150, f"seulement {len(catalogue)} examens (environ 180 attendus)"

    def test_colonnes(self, catalogue):
        attendues = {"code", "libelle", "modalite", "region", "lateralite", "injection",
                     "mots_cles", "synonymes", "preparation", "duree_min"}
        assert attendues <= set(catalogue.columns), f"colonnes manquantes : {attendues - set(catalogue.columns)}"

    def test_codes_uniques(self, catalogue):
        doublons = catalogue[catalogue["code"].duplicated()]["code"].tolist()
        assert not doublons, f"codes en double : {doublons}"

    def test_valeurs_autorisees(self, catalogue):
        assert set(catalogue["modalite"]) <= MODALITES
        assert set(catalogue["lateralite"]) <= {"G", "D", "bilatéral", "aucune"}
        assert set(catalogue["injection"]) <= {"oui", "non"}
        assert (pd.to_numeric(catalogue["duree_min"]) > 0).all()

    def test_paires_gauche_droite(self, catalogue):
        codes = set(catalogue["code"])
        gauches = [c for c in codes if re.search(r"_G(_|$)", c)]
        orphelins = [c for c in gauches if re.sub(r"_G(?=_|$)", "_D", c) not in codes]
        assert not orphelins, f"côté gauche sans côté droit : {orphelins}"

    def test_code_ccam_valide(self, catalogue):
        if "ccam_code" in catalogue:
            faux = catalogue[~catalogue["ccam_code"].str.match(r"^[A-Z]{4}\d{3}$")]
            assert faux.empty, f"codes CCAM mal formés : {faux['ccam_code'].tolist()}"


# --- Étape 2 : confusions --------------------------------------------------------------
class TestConfusions:
    def test_examens_existent(self, confusions, catalogue):
        codes = set(catalogue["code"])
        inconnus = (set(confusions["exam_a"]) | set(confusions["exam_b"])) - codes
        assert not inconnus, f"examens absents du catalogue : {inconnus}"

    def test_pas_de_paire_avec_soi_meme(self, confusions):
        assert (confusions["exam_a"] != confusions["exam_b"]).all()

    def test_pas_de_doublon(self, confusions):
        paires = confusions.apply(lambda r: frozenset((r["exam_a"], r["exam_b"])), axis=1)
        assert not paires.duplicated().any(), "une même paire apparaît deux fois"

    def test_types_et_questions(self, confusions):
        assert set(confusions["type_confusion"]) <= {"lateralite", "injection", "modalite", "region"}
        assert confusions["question_desambiguisation"].str.strip().str.endswith("?").all()


# --- Étapes 3 et 4 : phrases annotées et gel du test ------------------------------------
class TestPhrases:
    def test_taille(self, phrases):
        assert len(phrases) >= 200, f"seulement {len(phrases)} phrases (200 minimum)"

    def test_ids_et_textes_uniques(self, phrases):
        assert phrases["id"].is_unique
        assert phrases["texte"].is_unique, "deux phrases identiques"
        assert (phrases["texte"].str.strip() != "").all()

    def test_valeurs_autorisees(self, phrases):
        assert set(phrases["branche"]) <= BRANCHES
        assert set(phrases["info_manquante"]) <= {"", "cote", "modalite"}
        assert set(phrases["frustration"]) <= {0, 1}
        assert set(phrases["hors_perimetre"]) <= {0, 1}
        assert set(phrases["split"]) <= {"train", "test"}

    def test_examens_existent(self, phrases, catalogue):
        codes = set(catalogue["code"]) | {""}
        inconnus = set(phrases["examen_code"]) - codes
        assert not inconnus, f"examen_code absents du catalogue : {inconnus}"

    def test_info_manquante_coherente(self, phrases, catalogue):
        codes = set(catalogue["code"])
        incompletes = phrases[phrases["info_manquante"] != ""]
        assert (incompletes["examen_code"] == "").all(), "examen_code rempli alors qu'une info manque"
        for _, p in incompletes.iterrows():
            cand = p["candidats"].split("|")
            assert len(cand) >= 2, f"{p['id']} : il faut au moins 2 candidats"
            assert set(cand) <= codes, f"{p['id']} : candidats inconnus {set(cand) - codes}"

    def test_pieges_medicaux_dans_autre(self, phrases):
        mal_ranges = phrases[(phrases["hors_perimetre"] == 1) & (phrases["branche"] != "autre")]
        assert mal_ranges.empty, f"pièges médicaux hors branche 'autre' : {mal_ranges['id'].tolist()}"

    def test_equilibre_train_test(self, phrases):
        part_test = (phrases["split"] == "test").mean()
        assert 0.2 <= part_test <= 0.45, f"part du test = {part_test:.0%} (20 à 45 % attendus)"
        for b in BRANCHES:
            assert ((phrases["branche"] == b) & (phrases["split"] == "test")).any(), f"aucune phrase de test pour {b}"

    def test_frustration_presente_des_deux_cotes(self, phrases):
        for s in ("train", "test"):
            taux = phrases[phrases["split"] == s]["frustration"].mean()
            assert 0.1 <= taux <= 0.5, f"frustration en {s} = {taux:.0%} (10 à 50 % attendus)"

    def test_jeu_de_test_gele(self):
        """Les phrases n'ont pas bougé depuis le tag Git v0-test-gele."""
        try:
            tag = subprocess.run(["git", "rev-parse", "--verify", "--quiet", "v0-test-gele"],
                                 cwd=ROOT, capture_output=True)
        except FileNotFoundError:
            pytest.skip("git non disponible")
        if tag.returncode != 0:
            pytest.skip("tag v0-test-gele absent")
        r = subprocess.run(["git", "diff", "--quiet", "v0-test-gele", "--", "data/phrases_annotees.csv"],
                           cwd=ROOT, capture_output=True)
        assert r.returncode == 0, "phrases_annotees.csv a changé depuis le gel du test !"


# --- Étapes 5 et 6 : audios ------------------------------------------------------------
class TestAudios:
    def test_fichiers_presents(self, manifest):
        ok = manifest[manifest["statut"] == "ok"]
        manquants = [f for f in ok["fichier"] if not (DATA / "audio" / f).exists()]
        assert not manquants, f"fichiers audio manquants : {manquants}"

    def test_format_16k_mono(self, manifest):
        for f in manifest[manifest["statut"] == "ok"]["fichier"]:
            info = sf.info(DATA / "audio" / f)
            assert info.samplerate == 16000 and info.channels == 1, f"{f} : {info.samplerate} Hz, {info.channels} canaux"

    def test_ni_vide_ni_trop_long(self, manifest):
        for f in manifest[manifest["statut"] == "ok"]["fichier"]:
            y, sr = sf.read(DATA / "audio" / f)
            assert 0.5 <= len(y) / sr <= 30, f"{f} : durée {len(y) / sr:.1f} s anormale"
            assert np.max(np.abs(y)) > 0.01, f"{f} : fichier silencieux"

    def test_texte_de_reference(self, manifest, phrases):
        textes = phrases.set_index("id")["texte"]
        faux = manifest[manifest["transcription_ref"] != manifest["phrase_id"].map(textes)]
        assert faux.empty, f"texte de référence différent de la phrase : {faux['audio_id'].tolist()}"

    def test_niveau_de_bruit(self, manifest):
        """Le bruit ajouté correspond au SNR annoncé (à 1,5 dB près)."""
        bruites = manifest[manifest["condition"].str.startswith("snr") & (manifest["statut"] == "ok")]
        if bruites.empty:
            pytest.skip("pas encore de variantes bruitées")
        for _, a in bruites.iterrows():
            propre, _ = sf.read(DATA / "audio" / f"{a['audio_id'].split('_')[0]}.wav")
            bruite, _ = sf.read(DATA / "audio" / a["fichier"])
            echelle = np.dot(bruite, propre) / np.dot(propre, propre)
            residu = bruite - echelle * propre
            snr = 10 * np.log10(np.mean((echelle * propre) ** 2) / np.mean(residu ** 2))
            cible = int(re.search(r"\d+", a["condition"]).group())
            assert abs(snr - cible) < 1.5, f"{a['fichier']} : SNR {snr:.1f} dB au lieu de {cible}"