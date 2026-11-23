"""
Évaluation de la recherche dans la base de connaissances (WP3), sur les jeux déclarés par
le pack (evaluation.knowledge : reformulations + fiche attendue, vide = hors base).

Usage (depuis la racine du projet) :
    python -m agentkit.evaluation.eval_knowledge
    python -m agentkit.evaluation.eval_knowledge --domaine demo_minimal --methodes tfidf

Pour chaque méthode (tfidf, embeddings, hybrid), sans seuil :
    top-1  la meilleure fiche est la bonne        top-k  la bonne fiche est dans les k premières
Pour la méthode du pack, avec ses réglages (min_score, min_gap, llm_margin) — ce que vit
l'utilisateur :
    direct-juste   lue directement, bonne fiche        direct-FAUSSE  lue directement, mauvaise fiche
    zone grise     l'appel LLM du tour choisira parmi les k premières (ou aucune)
    sans réponse   question hors base bien refusée, ou question de la base manquée
Une réponse FAUSSE est pire qu'une absence de réponse (on peut toujours passer la main) :
c'est la métrique à garder à 0. Le balayage des réglages n'est fait que sur un jeu de MISE
AU POINT, jamais sur un jeu aveugle.
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

from agentkit import config
from agentkit.domain.loader import load_domain
from agentkit.knowledge.retriever import build_retriever, zone_de


def classer(hits, attendu: str, spec) -> str:
    zone = zone_de(hits, spec)
    if zone == "direct":
        return "direct-juste" if attendu and hits[0].id == attendu else "direct-FAUSSE"
    return {"grey": "zone grise", "none": "sans réponse"}[zone]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domaine", default=config.domaine_par_defaut())
    ap.add_argument("--methodes", nargs="+", default=["tfidf", "embeddings", "hybrid"])
    args = ap.parse_args()
    pack = load_domain(args.domaine)
    k = pack.knowledge
    if k is None or not pack.evaluation.knowledge:
        raise SystemExit(f"le pack {pack.id} n'a pas de base de connaissances ou de jeu d'évaluation")
    sortie = config.REPO_ROOT / "results" / pack.id
    sortie.mkdir(parents=True, exist_ok=True)
    n_hits = max(2, k.llm_top_k)
    methodes = list(dict.fromkeys([*args.methodes, k.retriever]))
    retrievers = {m: build_retriever(pack, m) for m in methodes}

    for jeu in pack.evaluation.knowledge:
        df = pd.read_csv(pack.path(jeu.file), keep_default_na=False, dtype=str)
        attendus = df[jeu.expected_column].tolist()
        dans = np.array([a != "" for a in attendus])
        print(f"\n=== Base de connaissances : pack {pack.id}, jeu {jeu.id} "
              f"({'AVEUGLE' if jeu.blind else 'mise au point'}) : {dans.sum()} questions de la base, "
              f"{(~dans).sum()} hors base ===")
        lignes, resume, hits_par_methode = [], {}, {}
        for m, r in retrievers.items():
            hits = [r.search(q, k=n_hits) for q in df[jeu.text_column]]
            hits_par_methode[m] = hits
            top1 = np.array([h[0].id == a for h, a in zip(hits, attendus)])
            topk = np.array([a in {x.id for x in h[: k.llm_top_k]} for h, a in zip(hits, attendus)])
            resume[m] = {"top1": round(float(top1[dans].mean()), 4),
                         f"top{k.llm_top_k}": round(float(topk[dans].mean()), 4)}
            if getattr(r, "degrade", False):
                resume[m]["remarque"] = "embeddings indisponibles : lexical seul"
            for q, a, h in zip(df[jeu.text_column], attendus, hits):
                lignes.append({"methode": m, "question": q, "attendu": a, "obtenu": h[0].id, "score": h[0].score,
                               "ecart": round(h[0].score - h[1].score, 3), "zone": classer(h, a, k),
                               f"top{k.llm_top_k}": "|".join(x.id for x in h[: k.llm_top_k])})
        print(f"{'méthode':<12}{'top-1':>8}{'top-' + str(k.llm_top_k):>8}   (questions de la base, sans seuil)")
        for m in args.methodes:
            v = resume[m]
            print(f"{m:<12}{v['top1']:>8.0%}{v[f'top{k.llm_top_k}']:>8.0%}   {v.get('remarque', '')}")

        det = pd.DataFrame(lignes)
        mp = det[det["methode"] == k.retriever]
        print(f"\nMéthode du pack ({k.retriever}) : min_score {k.min_score}, min_gap {k.min_gap}, "
              f"zone grise dès {k.min_score - k.llm_margin:.2f}")
        zones = mp.groupby([np.where(mp["attendu"] != "", "dans la base", "hors base"), "zone"]).size()
        print(zones.to_string())
        resume["pack"] = {"reglages": {"min_score": k.min_score, "min_gap": k.min_gap, "llm_margin": k.llm_margin},
                          "zones": mp["zone"].value_counts().to_dict()}
        for _, e in mp[mp["zone"] == "direct-FAUSSE"].iterrows():
            print(f"  RÉPONSE FAUSSE : « {e['question']} » -> {e['obtenu']} (attendu {e['attendu'] or 'aucune'})")
        if not jeu.blind:
            print("\nBalayage (mise au point) : direct-juste / direct-FAUSSE / zone grise")
            for gap in (0.0, 0.10, 0.13, 0.15):
                for s in np.arange(0.35, 0.66, 0.05):
                    essai = k.model_copy(update={"min_score": float(s), "min_gap": gap})
                    z = [classer(h, a, essai) for h, a in zip(hits_par_methode[k.retriever], attendus)]
                    print(f"  min_score {s:.2f} min_gap {gap:.2f} : {z.count('direct-juste'):>3} / "
                          f"{z.count('direct-FAUSSE'):>2} / {z.count('zone grise'):>2}")
        det.to_csv(sortie / f"knowledge_{jeu.id}.csv", index=False, encoding="utf-8")
        (sortie / f"knowledge_{jeu.id}.json").write_text(json.dumps(resume, indent=1, ensure_ascii=False),
                                                         encoding="utf-8")


if __name__ == "__main__":
    main()
