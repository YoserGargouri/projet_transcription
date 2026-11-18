"""
Réglages d'exécution du moteur, lus dans l'environnement (fichier .env à la racine).

Rien de métier ici : seulement où trouver les packs, où écrire les fichiers d'exécution,
et comment joindre les services externes (LLM, ElevenLabs). Modèle : .env.example.
"""
import os
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")  # Windows sans liens symboliques

REPO_ROOT = Path(__file__).resolve().parents[2]

try:  # python-dotenv : facultatif, sinon on lit seulement les variables d'environnement
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass


def env(nom: str, defaut: str = "") -> str:
    return os.environ.get(nom, defaut).strip()


def env_int(nom: str, defaut: int = 0) -> int:
    try:
        return int(env(nom, str(defaut)) or defaut)
    except ValueError:
        return defaut


def domains_dir() -> Path:
    """Dossier contenant les packs de domaine (DOMAINS_DIR, sinon domains/ à la racine)."""
    return Path(env("DOMAINS_DIR") or REPO_ROOT / "domains")


def runtime_dir(*parties: str) -> Path:
    """Fichiers produits à l'exécution (caches, agendas simulés, journaux), hors du dépôt Git."""
    chemin = Path(env("AGENTKIT_RUNTIME") or REPO_ROOT / "runtime").joinpath(*parties)
    chemin.mkdir(parents=True, exist_ok=True)
    return chemin


def domaine_par_defaut() -> str:
    return env("DOMAIN", "imagerie_medicale")
