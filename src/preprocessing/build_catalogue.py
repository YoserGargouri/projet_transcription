
import argparse
import re
import unicodedata
import pandas as pd

# --- Modalités : mot de tête du libellé CCAM -> (modalité, préfixe de code) ---
MODALITES = [
    (r"^remnographie", "IRM", "IRM"),
    (r"^scanographie", "Scanner", "TDM"),
    (r"^mammographie", "Mammographie", "MAM"),
    (r"^osteodensitometrie", "Densitométrie", "DMO"),
    (r"^echographie", "Échographie", "ECH"),
    (r"^radiographie", "Radio", "RX"),
]

# Actes hors champ d'un centre d'imagerie de ville : interventionnel, dentaire,
# obstétrique, cardiologie
EXCLUSIONS = (r"guid|biopsie|ponction|drainage|infiltration|embolisation|peroperatoire"
              r"|endoscopi|foetal|foetus|obstetric|grossesse|dent|intrabuccal|panoramique"
              r"|cephalometr|\bcoeur|cardiaque|transoesophag|peniscopie|arthrographie|hysterosalping"
              r"|[23] segments|plusieurs|territoires|en totalite|tridimensionnelle|stereotax"
              r"|dosimetr|muscle|tendon|peau|tissus mous du membre|tube digestif|transit"
              r"|piece operatoire|exerese|gravide|transfontanell")

# --- Vaisseaux (échographie-doppler, angio) : testés en premier ---
VAISSEAUX = [
    (r"cervicocephal|carotid|cervic", "vaisseaux du cou", "VCO"),
    (r"membres? inferieurs?", "vaisseaux des jambes", "VMI"),
    (r"membres? superieurs?", "vaisseaux des bras", "VMS"),
    (r"aort", "aorte", "AOR"),
    (r"", "vaisseaux", "VAS"),
]

# --- Régions : (motif dans le libellé normalisé, nom, abréviation, latéralisable) ---
# Ordre important : combinaisons et régions précises d'abord, régions larges ensuite.
REGIONS = [
    (r"thorax.*abdomen|thoraco-?abdomin", "thorax-abdomen-pelvis", "TAP", False),
    (r"abdomen.*(petit bassin|pelvis)", "abdomen-pelvis", "ABP", False),
    (r"segment cervical|rachis cervical|colonne vertebrale cervicale", "rachis cervical", "RCE", False),
    (r"segment thoracique|rachis thoracique|rachis dorsal", "rachis dorsal", "RDO", False),
    (r"segment lombal|rachis lombal|rachis lombaire|lombosacr", "rachis lombaire", "RLO", False),
    (r"colonne vertebrale|rachis", "rachis", "RAC", False),
    (r"sacro-?iliaque", "sacro-iliaques", "SIL", False),
    (r"\bgenou", "genou", "GEN", True),
    (r"cheville", "cheville", "CHE", True),
    (r"\bpied|orteil", "pied", "PIE", True),
    (r"hanche|coxofemorale", "hanche", "HAN", True),
    (r"epaule|ceinture scapulaire", "épaule", "EPA", True),
    (r"coude", "coude", "CDE", True),
    (r"poignet", "poignet", "POI", True),
    (r"\bmain\b|doigt", "main", "MAI", True),
    (r"avant-bras", "avant-bras", "ABR", True),
    (r"cuisse|femur", "cuisse", "CUI", True),
    (r"jambe", "jambe", "JAM", True),
    (r"\bbras\b|humerus", "bras", "BRA", True),
    (r"\bsein?s?\b|mammaire", "sein", "SEI", True),  # libellés parfois tronqués ("du sei")
    (r"thyroid", "thyroïde", "THY", False),
    (r"salivaire|parotid", "glandes salivaires", "GSA", False),
    (r"orbite", "orbites", "ORB", False),
    (r"sinus", "sinus", "SIN", False),
    (r"rocher|oreille", "oreilles", "ORE", False),
    (r"\breins?\b|renal|voies urinaires", "reins", "REI", False),
    (r"prostate", "prostate", "PRO", False),
    (r"bourse|testicul|scrot", "bourses", "BOU", False),
    (r"ceinture pelvienne", "bassin", "BAS", False),
    (r"uterus|ovaire|petit bassin|pelvis|pelvien", "pelvis", "PEL", False),
    (r"bassin", "bassin", "BAS", False),
    (r"\bfoie\b|hepat|voies biliaires", "foie", "FOI", False),
    (r"abdom", "abdomen", "ABD", False),
    (r"thorax|thoracique|poumon", "thorax", "THO", False),
    (r"encephale|crane|cerveau|\btete\b", "crâne", "CRA", False),
    (r"massif facial|\bface\b|mandibul|machoire", "face", "FAC", False),
    (r"\bcou\b|cervical", "cou", "COU", False),
    (r"squelette|corps entier", "squelette", "SQU", False),
]

# La CCAM ne distingue pas toujours la région précise demandée par le patient :
# "IRM de segment du membre inférieur" couvre genou, cheville, hanche...
# On développe ces actes génériques en examens « patient ».
MEMBRE_INF = [("hanche", "HAN"), ("cuisse", "CUI"), ("genou", "GEN"),
              ("jambe", "JAM"), ("cheville", "CHE"), ("pied", "PIE")]
MEMBRE_SUP = [("épaule", "EPA"), ("bras", "BRA"), ("coude", "CDE"),
              ("avant-bras", "ABR"), ("poignet", "POI"), ("main", "MAI")]
ARTICULATIONS = [("épaule", "EPA"), ("coude", "CDE"), ("poignet", "POI"), ("main", "MAI"),
                 ("hanche", "HAN"), ("genou", "GEN"), ("cheville", "CHE"), ("pied", "PIE")]
RACHIS = [("rachis cervical", "RCE"), ("rachis dorsal", "RDO"), ("rachis lombaire", "RLO")]
GENERIQUES = [
    (r"segment du membre inferieur", MEMBRE_INF, True),
    (r"segment du membre superieur", MEMBRE_SUP, True),
    (r"(un ou de deux segments|d'un segment) de la colonne", RACHIS, False),
]
# Testé seulement si aucune région précise n'est trouvée (ex. "Échographie d'une articulation")
ARTICULATION_GENERIQUE = r"d'une articulation|de l'articulation"

# Région par défaut quand le libellé CCAM n'en cite pas (ex. "Mammographie bilatérale")
REGION_DEFAUT = {
    "Mammographie": ("sein", "SEI", True),
    "Densitométrie": ("squelette", "SQU", False),
}

# Régions de genre féminin, pour accorder "gauche/droite"
FEMININ = {"cheville", "hanche", "épaule", "main", "cuisse", "jambe", "face"}

SYNONYMES_MODALITE = {
    "IRM": ["IRM", "résonance magnétique"],
    "Scanner": ["scanner", "scanographie", "TDM"],
    "Radio": ["radio", "radiographie"],
    "Échographie": ["écho", "échographie"],
    "Mammographie": ["mammographie", "mammo"],
    "Densitométrie": ["densitométrie", "ostéodensitométrie"],
}

DUREE_BASE = {"Radio": 10, "Échographie": 20, "Scanner": 15, "IRM": 30,
              "Mammographie": 20, "Densitométrie": 15}


def norm(s: str) -> str:
    """Minuscules sans accents, pour le filtrage par motifs."""
    s = unicodedata.normalize("NFD", str(s).lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def load_ccam(path: str) -> pd.DataFrame:
    """Charge le fichier CCAM et repère les colonnes code / libellé (et, si elles
    existent, quantité d'actes et catégorie), sur n'importe quelle feuille et même
    si l'en-tête n'est pas sur la première ligne."""
    if path.lower().endswith((".xls", ".xlsx")):
        feuilles = pd.read_excel(path, header=None, dtype=str, sheet_name=None)
    else:
        feuilles = {"csv": pd.read_csv(path, header=None, dtype=str, sep=None, engine="python")}
    for raw in feuilles.values():
        for i in range(min(30, len(raw))):
            row = [norm(x) for x in raw.iloc[i].fillna("")]
            code_idx = next((j for j, v in enumerate(row) if v.startswith("code acte") or v == "code"), None)
            lib_idx = next((j for j, v in enumerate(row) if "libelle" in v), None)
            if code_idx is None or lib_idx is None:
                continue
            qte_idx = next((j for j, v in enumerate(row) if v.startswith("quantite")), None)
            cat_idx = next((j for j, v in enumerate(row) if v.startswith("categorie")), None)
            df = pd.DataFrame({
                "ccam_code": raw.iloc[i + 1:, code_idx],
                "libelle_ccam": raw.iloc[i + 1:, lib_idx],
                "nb": pd.to_numeric(raw.iloc[i + 1:, qte_idx], errors="coerce") if qte_idx is not None else 0,
                "categorie": raw.iloc[i + 1:, cat_idx] if cat_idx is not None else "",
            }).dropna(subset=["ccam_code", "libelle_ccam"])
            df = df[df["ccam_code"].str.match(r"^[A-Z]{4}\d{3}$")]
            # Un même acte apparaît sur plusieurs lignes (activité / phase) : on somme
            df = (df.groupby(["ccam_code", "libelle_ccam", "categorie"], as_index=False)["nb"].sum())
            return df.drop_duplicates("ccam_code").reset_index(drop=True)
    raise ValueError("Colonnes 'code' et 'libellé' introuvables : vérifiez le fichier.")


def classify(lib: str):
    """Renvoie la modalité, l'injection et la liste des régions « patient » d'un acte,
    ou None si l'acte n'est pas un examen d'imagerie diagnostique de ville."""
    n = norm(lib)
    if re.search(EXCLUSIONS, n):
        return None
    mod = next(((m, p) for rx, m, p in MODALITES if re.search(rx, n)), None)
    if mod is None:
        return None
    # "intraveineuse" (voie d'injection) ne doit pas faire classer l'examen en vasculaire
    if re.search(r"doppler|arter|\bvein|\bveineu|angio", n.replace("intraveineuse", "")):
        regions = [next((r, a, False) for rx, r, a in VAISSEAUX if re.search(rx, n))]
    else:
        gen = next(((liste, lat) for rx, liste, lat in GENERIQUES if re.search(rx, n)), None)
        reg = None if gen else next(((r, a, lat) for rx, r, a, lat in REGIONS if re.search(rx, n)), None)
        if gen:
            regions = [(r, a, gen[1]) for r, a in gen[0]]
        elif reg:
            regions = [reg]
        elif re.search(ARTICULATION_GENERIQUE, n):
            regions = [(r, a, True) for r, a in ARTICULATIONS]
        elif mod[0] in REGION_DEFAUT:
            regions = [REGION_DEFAUT[mod[0]]]
        else:
            return None
    inj = "oui" if re.search(r"avec injection|apres injection", n) else "non"
    les_deux = bool(re.search(r"unilaterale? ou bilaterale?", n))
    bilat = "bilateral" in n and not les_deux
    unilat = "unilateral" in n and not les_deux
    if mod[0] == "Mammographie" and not unilat:
        bilat = True  # une mammographie est bilatérale sauf mention contraire
    return {"modalite": mod[0], "prefixe": mod[1], "injection": inj, "bilateral": bilat,
            "regions": [{"region": r, "abr": a, "lateralisable": lat and not bilat}
                        for r, a, lat in regions]}


def preparation(modalite: str, region: str, injection: str) -> str:
    """Règles FICTIVES de logistique (données simulées)."""
    if modalite == "Échographie" and region == "abdomen":
        return "à jeun 6 h"
    if modalite == "Échographie" and region == "pelvis":
        return "vessie pleine"
    if injection == "oui":
        return "à jeun 3 h"
    return "aucune"


def expand(act: pd.Series, info: dict) -> list:
    """Une ligne par région et par côté (gauche / droit) pour les régions paires."""
    rows = []
    for reg in info["regions"]:
        lats = ["G", "D"] if reg["lateralisable"] else ["bilatéral" if info["bilateral"] else "aucune"]
        for lat in lats:
            region = reg["region"]
            droit = " droite" if region in FEMININ else " droit"
            cote = {"G": " gauche", "D": droit, "bilatéral": " des deux côtés"}.get(lat, "")
            libelle = f"{info['modalite']} {region}{cote}"
            if info["injection"] == "oui":
                libelle += " avec injection"
            syns = [f"{s} {region}" for s in SYNONYMES_MODALITE[info["modalite"]]]
            duree = DUREE_BASE[info["modalite"]] + (10 if info["injection"] == "oui" else 0)
            rows.append({
                "code": f"{info['prefixe']}_{reg['abr']}"
                        + {"G": "_G", "D": "_D", "bilatéral": "_BIL"}.get(lat, "")
                        + ("_INJ" if info["injection"] == "oui" else ""),
                "libelle": libelle,
                "modalite": info["modalite"],
                "region": region,
                "lateralite": lat,
                "injection": info["injection"],
                "mots_cles": ";".join([region] + SYNONYMES_MODALITE[info["modalite"]][:1]),
                "synonymes": ";".join(syns),
                "preparation": preparation(info["modalite"], region, info["injection"]),
                "duree_min": duree,
                "ccam_code": act["ccam_code"],
                "libelle_ccam": act["libelle_ccam"],
            })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ccam", required=True, help="Fichier CCAM (xlsx/xls/csv)")
    ap.add_argument("--freq", help="Open CCAM (csv) pour trier par fréquence")
    ap.add_argument("--freq-code-col", help="Colonne du code acte dans Open CCAM")
    ap.add_argument("--freq-count-col", help="Colonne du nombre de réalisations")
    ap.add_argument("--n", type=int, default=180)
    ap.add_argument("--out", default="data/catalogue.csv")
    args = ap.parse_args()

    acts = load_ccam(args.ccam)
    infos = acts["libelle_ccam"].map(classify)
    acts = acts[infos.notna()].assign(info=infos[infos.notna()])
    print(f"{len(acts)} actes d'imagerie diagnostique retenus après filtrage")

    if args.freq:
        freq = pd.read_csv(args.freq, sep=None, engine="python", dtype=str)
        freq = freq[[args.freq_code_col, args.freq_count_col]]
        freq.columns = ["ccam_code", "nb"]
        freq["nb"] = pd.to_numeric(freq["nb"], errors="coerce").fillna(0)
        freq = freq.groupby("ccam_code", as_index=False)["nb"].sum()
        acts = acts.drop(columns="nb").merge(freq, on="ccam_code", how="left").fillna({"nb": 0})
        acts = acts.sort_values("nb", ascending=False)
    elif acts["nb"].fillna(0).sum() > 0:
        # Le fichier contient déjà la quantité d'actes réalisés : on trie dessus
        acts = acts.sort_values("nb", ascending=False)
    else:
        # Sans fréquences : tirage alterné entre modalités pour un catalogue équilibré
        acts["mod"] = acts["info"].map(lambda d: d["modalite"])
        acts["rang"] = acts.groupby("mod").cumcount()
        acts = acts.sort_values(["rang", "mod"])

    rows, seen = [], set()
    for _, act in acts.iterrows():
        for r in expand(act, act["info"]):
            if r["code"] in seen:  # deux actes CCAM -> même examen patient : on garde le premier
                continue
            seen.add(r["code"])
            rows.append(r)
        if len(rows) >= args.n:
            break

    out = pd.DataFrame(rows[: args.n])
    out.to_csv(args.out, index=False, encoding="utf-8")
    print(f"{len(out)} examens écrits dans {args.out}")
    print(out["modalite"].value_counts().to_string())


if __name__ == "__main__":
    main()
