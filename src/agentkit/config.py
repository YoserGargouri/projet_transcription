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


def configurer_journal(verbose: bool) -> None:
    """--verbose : affiche les étapes du traitement (STT, appel LLM, repli, TTS...) via le module
    logging. Ces messages ne contiennent ni le texte de l'utilisateur ni les clés d'API."""
    import logging

    logging.basicConfig(level=logging.WARNING, format="        · %(name)s : %(message)s")
    logging.getLogger("agentkit").setLevel(logging.INFO if verbose else logging.WARNING)


def resume_agent(trace: dict) -> str:
    """Une ligne lisible : le LLM a-t-il été utilisé pour ce tour, et pour quoi."""
    a = trace.get("agent")
    if trace.get("llm_failure"):
        return f"LLM : échec -> règles ({trace['llm_failure'][:90]})"
    if not a:
        return "LLM : non appelé (règles : " + ", ".join(k for k in ("safety", "confirmation", "escalation",
                                                                     "precheck") if k in trace) + ")"
    if not a.get("llm_used"):
        return f"LLM : échec -> règles ({a.get('fallback', '')[:80]})"
    infos = [f"intention {a.get('intent')}"] if a.get("intent") else []
    if (k := trace.get("knowledge", {})).get("used"):
        infos.append(f"sources {k['used']}")
    if a.get("slots"):
        infos.append(f"infos {a['slots']}")
    if a.get("asks_for"):
        infos.append(f"demande {a['asks_for']}")
    return "LLM : utilisé (" + ", ".join(infos) + ")"
