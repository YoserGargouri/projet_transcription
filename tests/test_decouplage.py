"""
Test d'acceptation de l'architecture : le moteur (src/agentkit) ne connaît aucun domaine.

1. aucun module du moteur n'importe un pack (ni « domains », ni un pack par son nom) ;
2. aucun mot du métier « imagerie » dans le moteur, code ET commentaires.
   Comparaison par MOT ENTIER (insensible à la casse et aux accents) : une recherche de
   sous-chaîne signalerait « confirmer » (qui contient « irm ») ou « impatient ».
"""
import ast
import re
import unicodedata
from pathlib import Path

MOTEUR = Path(__file__).resolve().parents[1] / "src" / "agentkit"
DOMAINES = Path(__file__).resolve().parents[1] / "domains"
MOTS_INTERDITS = ["irm", "scanner", "radiolog", "imagerie", "examen", "patient", "medical", "rendez-vous",
                  "ordonnance"]
# Formes autorisées pour chaque racine (le mot entier, ses pluriels et dérivés)
MOTIFS = {m: re.compile(rf"\b{re.escape(m)}(s|e|es|ux|ale|ales|aux|ie|ies|ue|ues|ique|iques|iste|istes)?\b")
          for m in MOTS_INTERDITS}
MOTIFS["radiolog"] = re.compile(r"\bradiolog\w*")


def _sans_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _fichiers():
    return [f for f in MOTEUR.rglob("*.py") if "__pycache__" not in f.parts]


def test_le_moteur_n_importe_aucun_pack():
    packs = {p.name for p in DOMAINES.iterdir() if p.is_dir()}
    fautes = []
    for f in _fichiers():
        for noeud in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            modules = []
            if isinstance(noeud, ast.Import):
                modules = [a.name for a in noeud.names]
            elif isinstance(noeud, ast.ImportFrom) and noeud.module:
                modules = [noeud.module]
            for m in modules:
                racine = m.split(".")[0]
                if racine == "domains" or racine in packs:
                    fautes.append(f"{f.relative_to(MOTEUR)} importe {m}")
    assert not fautes, fautes


def test_aucun_vocabulaire_metier_dans_le_moteur():
    fautes = []
    for f in _fichiers():
        for n, ligne in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            texte = _sans_accents(ligne.lower())
            for mot, motif in MOTIFS.items():
                if motif.search(texte):
                    fautes.append(f"{f.relative_to(MOTEUR)}:{n} « {mot} » : {ligne.strip()[:80]}")
    assert not fautes, "\n".join(fautes)


def test_le_detecteur_de_mots_fonctionne():
    """Garde-fou du test lui-même : il doit voir les mots interdits, mais pas « confirmer »."""
    def trouve(t):
        return any(m.search(_sans_accents(t.lower())) for m in MOTIFS.values())
    assert trouve("une IRM du genou") and trouve("le Médical") and trouve("prendre rendez-vous")
    assert trouve("les examens") and trouve("un radiologue")
    assert not trouve("confirmer la réservation") and not trouve("impatient") and not trouve("firmware")
