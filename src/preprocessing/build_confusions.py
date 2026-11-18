import argparse
from itertools import combinations

import pandas as pd

# Modalités que les patients confondent souvent entre elles
MODALITES_PROCHES = [
    ("IRM", "Scanner"),
    ("Radio", "Scanner"),
    ("Radio", "Échographie"),
    ("Mammographie", "Échographie"),
]

# Régions voisines, faciles à confondre à l'oral
REGIONS_VOISINES = [
    ("genou", "jambe"), ("genou", "cuisse"), ("cheville", "pied"), ("cheville", "jambe"),
    ("hanche", "bassin"), ("hanche", "cuisse"), ("poignet", "main"), ("poignet", "avant-bras"),
    ("coude", "avant-bras"), ("coude", "bras"), ("épaule", "bras"),
    ("rachis cervical", "rachis dorsal"), ("rachis dorsal", "rachis lombaire"),
    ("rachis cervical", "cou"), ("rachis lombaire", "bassin"),
    ("abdomen", "abdomen-pelvis"), ("pelvis", "abdomen-pelvis"), ("abdomen", "foie"),
    ("crâne", "face"), ("face", "sinus"), ("cou", "thyroïde"),
]

# Pour des questions naturelles : "une IRM ou un scanner ?"
ARTICLE = {"IRM": "une IRM", "Scanner": "un scanner", "Radio": "une radio",
           "Échographie": "une échographie", "Mammographie": "une mammographie",
           "Densitométrie": "une densitométrie"}


def question(type_conf: str, a: pd.Series, b: pd.Series) -> str:
    if type_conf == "lateralite":
        return "Votre ordonnance précise-t-elle le côté : gauche ou droit ?"
    if type_conf == "injection":
        return "Votre ordonnance mentionne-t-elle une injection de produit de contraste ?"
    if type_conf == "modalite":
        return f"Votre ordonnance indique-t-elle {ARTICLE[a['modalite']]} ou {ARTICLE[b['modalite']]} ?"
    return f"Sur votre ordonnance, est-il écrit {a['region']} ou {b['region']} ?"


def paires(cat: pd.DataFrame):
    # Clé « examen sans côté ni injection » pour comparer les lignes entre elles
    cat = cat.assign(cle_lat=cat["code"].str.replace(r"_(G|D)(?=_|$)", "", regex=True),
                     cle_inj=cat["code"].str.replace("_INJ", "", regex=False))

    # 1. Latéralité : X_G / X_D
    for _, grp in cat[cat["lateralite"].isin(["G", "D"])].groupby("cle_lat"):
        if len(grp) == 2:
            yield "lateralite", grp.iloc[0], grp.iloc[1]

    # 2. Injection : X / X_INJ
    for _, grp in cat.groupby("cle_inj"):
        if len(grp) == 2:
            yield "injection", grp.iloc[0], grp.iloc[1]

    # 3. Modalité : même région, même côté, sans injection
    base = cat[cat["injection"] == "non"]
    for (region, lat), grp in base.groupby(["region", "lateralite"]):
        for (_, a), (_, b) in combinations(grp.iterrows(), 2):
            if (a["modalite"], b["modalite"]) in MODALITES_PROCHES or \
               (b["modalite"], a["modalite"]) in MODALITES_PROCHES:
                yield "modalite", a, b

    # 4. Région voisine : même modalité, même côté, sans injection
    voisins = {frozenset(p) for p in REGIONS_VOISINES}
    for (mod, lat), grp in base.groupby(["modalite", "lateralite"]):
        for (_, a), (_, b) in combinations(grp.iterrows(), 2):
            if frozenset((a["region"], b["region"])) in voisins:
                yield "region", a, b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalogue", default="data/catalogue.csv")
    ap.add_argument("--out", default="data/confusions.csv")
    args = ap.parse_args()

    # keep_default_na=False : sinon pandas lit la latéralité "aucune"... et d'autres valeurs comme vides
    cat = pd.read_csv(args.catalogue, keep_default_na=False)
    rows = [{
        "exam_a": a["code"], "libelle_a": a["libelle"],
        "exam_b": b["code"], "libelle_b": b["libelle"],
        "type_confusion": t,
        "question_desambiguisation": question(t, a, b),
    } for t, a, b in paires(cat)]

    out = pd.DataFrame(rows).drop_duplicates(subset=["exam_a", "exam_b"])
    out.to_csv(args.out, index=False, encoding="utf-8")
    print(f"{len(out)} paires écrites dans {args.out}")
    print(out["type_confusion"].value_counts().to_string())


if __name__ == "__main__":
    main()
