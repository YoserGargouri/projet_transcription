"""
Chargement et validation d'un pack de domaine.

    from agentkit.domain.loader import load_domain
    pack = load_domain("imagerie_medicale")      # nom (dans DOMAINS_DIR) ou chemin d'un dossier

Étapes :
1. lecture de domain.yaml, avec substitution ${VAR} / ${VAR:-défaut} depuis l'environnement
   (les secrets restent dans .env, jamais dans le pack) ;
2. les workflows donnés par chemin et le prompt système donné par fichier sont inlinés ;
3. validation pydantic du contrat (schema.DomainPack) ;
4. vérification des fichiers référencés : existence, colonnes du catalogue, clés du gazetteer.
Toutes les erreurs sont regroupées dans une seule DomainPackError, lisible.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pandas as pd
import yaml
from pydantic import ValidationError

from agentkit import config
from agentkit.domain.schema import DomainPack

_VAR = re.compile(r"\$\{(\w+)(?::-([^}]*))?\}")
_cache: dict[Path, DomainPack] = {}


class DomainPackError(ValueError):
    """Pack invalide : le message liste toutes les erreurs trouvées."""


def interpoler(texte: str) -> str:
    return _VAR.sub(lambda m: os.environ.get(m.group(1)) or (m.group(2) or ""), texte)


def trouver_dossier(nom_ou_chemin: str | Path) -> Path:
    chemin = Path(nom_ou_chemin)
    if not (chemin / "domain.yaml").exists():
        chemin = config.domains_dir() / str(nom_ou_chemin)
    if not (chemin / "domain.yaml").exists():
        raise DomainPackError(f"pack introuvable : {nom_ou_chemin} (cherché dans {config.domains_dir()})")
    return chemin.resolve()


def _lire_yaml(chemin: Path):
    return yaml.safe_load(interpoler(chemin.read_text(encoding="utf-8")))


def load_domain(nom_ou_chemin: str | Path, recharger: bool = False) -> DomainPack:
    dossier = trouver_dossier(nom_ou_chemin)
    if dossier in _cache and not recharger:
        return _cache[dossier]
    data = _lire_yaml(dossier / "domain.yaml") or {}

    erreurs = []
    workflows = []
    for w in data.get("workflows", []) or []:
        if isinstance(w, str):
            if not (dossier / w).exists():
                erreurs.append(f"workflow introuvable : {w}")
                continue
            w = _lire_yaml(dossier / w)
        workflows.append(w)
    data["workflows"] = workflows
    prompt = (data.get("llm") or {}).get("system_prompt", "")
    if isinstance(prompt, str) and re.fullmatch(r"[\w./-]+\.(md|txt)", prompt):
        if (dossier / prompt).exists():
            data["llm"]["system_prompt"] = (dossier / prompt).read_text(encoding="utf-8")
        else:
            erreurs.append(f"prompt introuvable : {prompt}")

    try:
        pack = DomainPack(**data)
    except ValidationError as e:
        erreurs += [f"{'.'.join(map(str, err['loc']))} : {err['msg']}" for err in e.errors()]
        raise DomainPackError(f"pack {dossier.name} invalide :\n- " + "\n- ".join(erreurs)) from None
    pack._root = dossier
    erreurs += verifier_fichiers(pack)
    if erreurs:
        raise DomainPackError(f"pack {dossier.name} invalide :\n- " + "\n- ".join(erreurs))
    _cache[dossier] = pack
    return pack


def _colonnes(chemin: Path) -> list[str]:
    return list(pd.read_csv(chemin, nrows=0).columns)


def verifier_fichiers(pack: DomainPack) -> list[str]:
    """Contrôles qui demandent de lire les fichiers du pack."""
    err = []
    c = pack.catalogue
    if c:
        fichier = pack.path(c.file)
        if not fichier.exists():
            return [f"catalogue introuvable : {c.file}"]
        cat = pd.read_csv(fichier, keep_default_na=False, dtype=str)
        attendues = [c.id_column, c.label_column, *c.synonym_columns, *(a.column for a in c.attributes)]
        err += [f"catalogue : colonne absente {col}" for col in attendues if col not in cat.columns]
        if not err and cat[c.id_column].duplicated().any():
            err.append("catalogue : identifiants en double")
        if c.gazetteer:
            if not pack.path(c.gazetteer).exists():
                err.append(f"gazetteer introuvable : {c.gazetteer}")
            elif not err:
                gaz = yaml.safe_load(pack.path(c.gazetteer).read_text(encoding="utf-8")) or {}
                colonnes = {a.name: a.column for a in c.attributes}
                for attr, valeurs in gaz.items():
                    if attr not in colonnes:
                        err.append(f"gazetteer : attribut inconnu {attr}")
                        continue
                    connues = set(cat[colonnes[attr]])
                    err += [f"gazetteer : {attr}={v!r} absent du catalogue" for v in valeurs if v not in connues]
        if c.confusions:
            f = pack.path(c.confusions.file)
            if not f.exists():
                err.append(f"confusions introuvables : {c.confusions.file}")
            else:
                cols = _colonnes(f)
                err += [f"confusions : colonne absente {col}" for col in
                        (c.confusions.column_a, c.confusions.column_b, c.confusions.column_type) if col not in cols]
    k = pack.knowledge
    if k:
        f = pack.path(k.file)
        if not f.exists():
            err.append(f"base de connaissances introuvable : {k.file}")
        else:
            cols = _colonnes(f)
            err += [f"connaissances : colonne absente {col}" for col in
                    (k.id_column, k.question_column, k.answer_column, k.variants_column) if col and col not in cols]
    jeux = [(d.id, d.file, [d.text_column, d.label_column, d.split_column, d.out_of_scope_column])
            for d in pack.evaluation.intents]
    jeux += [(d.id, d.file, [d.text_column, d.expected_column]) for d in pack.evaluation.knowledge]
    for jid, fichier, colonnes in jeux:
        if not pack.path(fichier).exists():
            err.append(f"évaluation {jid} : fichier introuvable {fichier}")
        else:
            cols = _colonnes(pack.path(fichier))
            err += [f"évaluation {jid} : colonne absente {c}" for c in colonnes if c and c not in cols]
    for t in pack.tools:
        if t.entrypoint and not pack.path(t.entrypoint.split(":")[0]).exists():
            err.append(f"outil {t.name} : fichier introuvable {t.entrypoint}")
    for s in pack.signals:
        if s.kind == "model" and s.model and not pack.path(s.model).exists():
            err.append(f"signal {s.id} : modèle introuvable {s.model}")
    return err
