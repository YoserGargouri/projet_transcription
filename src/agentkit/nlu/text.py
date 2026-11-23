"""Normalisation du texte (transcrit ou tapé), commune au routeur, au résolveur et aux règles."""
import re
import unicodedata


def sans_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def normalise(s: str) -> str:
    """« L'É.C.G. du pied-gauche ! » -> « l ecg du pied gauche »

    Minuscules, sans accents ni ponctuation ; apostrophes et tirets deviennent des espaces ;
    les sigles pointés sont recollés. Les moteurs STT ne ponctuent pas tous pareil : on
    ramène tout à une forme commune avant d'appliquer les motifs des packs.
    """
    s = sans_accents(str(s).lower()).replace("œ", "oe").replace("æ", "ae")
    s = re.sub(r"\b((?:[a-z]\.){2,})", lambda m: m.group(1).replace(".", ""), s)   # sigles pointés
    s = re.sub(r"[’'`\-_/]", " ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()
