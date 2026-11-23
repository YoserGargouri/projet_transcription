"""
Évaluation du routage du premier tour (WP3) : sans LLM, sur les jeux déclarés par le pack
(evaluation.intents dans domain.yaml).

Usage (depuis la racine du projet) :
    python -m agentkit.evaluation.eval_router                       # pack de .env, split test
    python -m agentkit.evaluation.eval_router --split tout
    python -m agentkit.evaluation.eval_router --domaine demo_minimal

Prédiction pour une phrase, comme au premier tour de l'orchestrateur :
    demande d'un humain, ou sujet interdit (garde-fou)  -> escalate_label du jeu
    sinon intention du routeur ; handler « escalate »    -> escalate_label
    sinon                                                -> group (ou id) de l'intention
Mesures : accuracy, précision / rappel / F1 par étiquette, matrice de confusion, rappel des
phrases hors périmètre (doivent toutes partir vers un humain), fausses alertes, temps moyen.
Sorties : results/<pack>/router_<jeu>_<split>.csv et .json
"""
from __future__ import annotations

import argparse
import json
import time

import pandas as pd
from sklearn.metrics import classification_report, confusion_matrix

from agentkit import config
from agentkit.domain.loader import load_domain
from agentkit.domain.schema import DomainPack, IntentDatasetSpec
from agentkit.nlu.router import RuleRouter
from agentkit.policy.guardrails import ScopeGuard


class PremierTour:
    """Reproduit la décision du premier tour (sans LLM ni état)."""

    def __init__(self, pack: DomainPack, escalate_label: str):
        self.pack, self.label_humain = pack, escalate_label
        self.router, self.guard = RuleRouter(pack), ScopeGuard(pack)
        self.groupe = {i.id: (i.group or i.id) for i in pack.intents}

    def predire(self, texte: str) -> tuple[str, str]:
        """(étiquette prédite, raison)"""
        if self.guard.wants_human(texte):
            return self.label_humain, "humain demandé"
        route = self.router.route(texte)
        if v := self.guard.check(texte, route.intent):
            return self.label_humain, f"hors périmètre ({v.pattern})"
        if self.pack.intent(route.intent).handler == "escalate":
            return self.label_humain, f"intention {route.intent} ({route.rule or 'par défaut'})"
        return self.groupe[route.intent], f"intention {route.intent} ({route.rule})"


def evaluer(pack: DomainPack, jeu: IntentDatasetSpec, split: str) -> dict:
    df = pd.read_csv(pack.path(jeu.file), keep_default_na=False, dtype=str)
    if split != "tout" and jeu.split_column:
        df = df[df[jeu.split_column] == split]
    modele = PremierTour(pack, jeu.escalate_label)
    t0 = time.perf_counter()
    sorties = [modele.predire(t) for t in df[jeu.text_column]]
    duree_ms = 1000 * (time.perf_counter() - t0) / max(len(df), 1)
    df = df.assign(predit=[p for p, _ in sorties], raison=[r for _, r in sorties])
    vrai, predit = df[jeu.label_column], df["predit"]
    etiquettes = sorted(set(vrai) | set(predit))

    resume = {"pack": pack.id, "jeu": jeu.id, "split": split, "n": len(df),
              "accuracy": round(float((vrai == predit).mean()), 4), "ms_par_phrase": round(duree_ms, 2),
              "par_etiquette": classification_report(vrai, predit, labels=etiquettes, output_dict=True,
                                                     zero_division=0)}
    if jeu.out_of_scope_column:
        hors = df[df[jeu.out_of_scope_column] == "1"]
        dans = df[df[jeu.out_of_scope_column] != "1"]
        resume["hors_perimetre"] = {
            "n": len(hors),
            "rappel": round(float((hors["predit"] == jeu.escalate_label).mean()), 4) if len(hors) else None,
            "fausses_alertes": int(dans["raison"].str.startswith("hors périmètre").sum()),
        }
    sortie = config.REPO_ROOT / "results" / pack.id
    sortie.mkdir(parents=True, exist_ok=True)
    df.to_csv(sortie / f"router_{jeu.id}_{split}.csv", index=False, encoding="utf-8")
    (sortie / f"router_{jeu.id}_{split}.json").write_text(json.dumps(resume, indent=1, ensure_ascii=False),
                                                          encoding="utf-8")

    print(f"\n=== Routage du premier tour : pack {pack.id}, jeu {jeu.id}, split {split} ({len(df)} phrases) ===")
    print(classification_report(vrai, predit, labels=etiquettes, digits=3, zero_division=0))
    cm = pd.DataFrame(confusion_matrix(vrai, predit, labels=etiquettes),
                      index=[f"vrai {e}" for e in etiquettes], columns=etiquettes)
    print(cm.to_string())
    if "hors_perimetre" in resume:
        h = resume["hors_perimetre"]
        print(f"\nHors périmètre transférés : {h['rappel']:.0%} sur {h['n']} | fausses alertes : {h['fausses_alertes']}")
    print(f"Temps moyen : {duree_ms:.2f} ms par phrase (aucun appel LLM)")
    erreurs = df[vrai != predit]
    if len(erreurs):
        print(f"\n{len(erreurs)} erreurs :")
        for _, e in erreurs.iterrows():
            print(f"  {e[jeu.label_column]:>14} -> {e['predit']:<14} [{e['raison']}] {e[jeu.text_column]}")
    return resume


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domaine", default=config.domaine_par_defaut())
    ap.add_argument("--jeu", help="id du jeu (par défaut : tous les jeux d'intentions du pack)")
    ap.add_argument("--split", default="test", help="test | train | tout")
    args = ap.parse_args()
    pack = load_domain(args.domaine)
    jeux = [j for j in pack.evaluation.intents if not args.jeu or j.id == args.jeu]
    if not jeux:
        raise SystemExit(f"le pack {pack.id} ne déclare aucun jeu d'évaluation d'intentions")
    for jeu in jeux:
        evaluer(pack, jeu, args.split)


if __name__ == "__main__":
    main()
