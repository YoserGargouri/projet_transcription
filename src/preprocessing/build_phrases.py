
import argparse
import random

import pandas as pd

SEED = 42

# --- Comment un patient nomme les modalités et les régions -----------------------
MODALITE_ORALE = {
    "IRM": ["une IRM"],
    "Scanner": ["un scanner", "un scan"],
    "Radio": ["une radio", "une radiographie"],
    "Échographie": ["une échographie", "une écho"],
    "Mammographie": ["une mammographie", "une mammo"],
    "Densitométrie": ["une densitométrie osseuse"],
}
REGION_ORALE = {
    "genou": "du genou", "cheville": "de la cheville", "pied": "du pied",
    "hanche": "de la hanche", "cuisse": "de la cuisse", "jambe": "de la jambe",
    "épaule": "de l'épaule", "bras": "du bras", "coude": "du coude",
    "avant-bras": "de l'avant-bras", "poignet": "du poignet", "main": "de la main",
    "sein": "du sein", "thorax": "du thorax", "abdomen": "de l'abdomen",
    "abdomen-pelvis": "abdomino-pelvienne", "pelvis": "pelvienne", "bassin": "du bassin",
    "rachis cervical": "du rachis cervical", "rachis dorsal": "du dos",
    "rachis lombaire": "des lombaires", "crâne": "du crâne", "face": "de la face",
    "cou": "du cou", "thyroïde": "de la thyroïde", "reins": "des reins",
    "prostate": "de la prostate", "bourses": "des testicules", "foie": "du foie",
    "aorte": "de l'aorte", "vaisseaux du cou": "des carotides",
    "vaisseaux des jambes": "des veines des jambes", "vaisseaux des bras": "des veines des bras",
    "vaisseaux": "des vaisseaux", "glandes salivaires": "des glandes salivaires",
    "orbites": "des yeux", "oreilles": "des oreilles", "sinus": "des sinus",
}
FEMININ = {"cheville", "hanche", "épaule", "main", "cuisse", "jambe", "face"}

# --- Gabarits : (texte, groupe). Groupe "test" = formulations jamais vues à l'entraînement
GABARITS_NOUVEAU = [
    ("Bonjour, je voudrais prendre rendez-vous pour {exam}.", "train"),
    ("Bonjour, j'ai une ordonnance pour {exam}, c'est possible cette semaine ?", "train"),
    ("Oui allô, c'est pour {exam} s'il vous plaît.", "train"),
    ("Mon médecin m'a prescrit {exam}, je voudrais un créneau.", "train"),
    ("Je dois faire {exam}, vous avez de la place quand ?", "train"),
    ("Euh bonjour, c'est pour prendre un rendez-vous, euh, {exam}.", "train"),
    ("Est-ce que je peux avoir un rendez-vous pour {exam} la semaine prochaine ?", "train"),
    ("C'est pour ma mère, elle doit passer {exam}.", "train"),
    ("J'appelle pour {exam}, j'ai l'ordonnance du docteur.", "train"),
    ("Allô ? Oui, il me faudrait {exam}, vous faites ça chez vous ?", "test"),
    ("Bonsoir, je souhaiterais réserver {exam}.", "test"),
    ("On m'a dit d'appeler ici pour {exam}.", "test"),
    ("Salut, euh, je cherche un créneau pour {exam}.", "test"),
]
GABARITS_EXISTANT = [
    ("Je voudrais déplacer mon rendez-vous de {exam} prévu {jour}.", "train"),
    ("Je dois annuler mon rendez-vous de {jour}.", "train"),
    ("Je voulais confirmer mon rendez-vous pour {exam}.", "train"),
    ("À quelle heure est mon rendez-vous {jour} déjà ?", "train"),
    ("J'ai rendez-vous {jour} mais je ne pourrai pas venir.", "train"),
    ("Est-ce que mon rendez-vous pour {exam} est toujours maintenu ?", "train"),
    ("Bonjour, il faudrait décaler mon examen de {jour}, j'ai un empêchement.", "test"),
    ("Je ne me souviens plus de l'heure de mon rendez-vous {jour}.", "test"),
    ("Vous pouvez supprimer mon rendez-vous pour {exam} ?", "test"),
]
GABARITS_INFO_EXAMEN = [
    ("Il faut être à jeun pour {exam} ?", "train"),
    ("Combien de temps dure {exam} ?", "train"),
    ("Je dois apporter quoi pour {exam} ?", "test"),
]
JOURS = ["demain", "lundi", "jeudi prochain", "le 14", "vendredi matin", "cet après-midi"]

INFO_GENERALE = [
    "Vous êtes ouverts le samedi ?", "Quels sont vos horaires d'ouverture ?",
    "C'est où exactement votre centre ?", "Il y a un parking près du centre ?",
    "Qu'est-ce que je dois apporter le jour de l'examen ?", "Vous prenez la carte vitale ?",
    "Vous pratiquez le tiers payant ?", "Je reçois les résultats quand ?",
    "Le centre est accessible en fauteuil roulant ?", "Je peux venir accompagné ?",
    "Combien ça coûte sans mutuelle ?", "Comment je récupère mes images après l'examen ?",
    "Il y a un bus qui passe près de chez vous ?", "Vous êtes ouverts entre midi et deux ?",
    "Je peux payer par carte bancaire ?", "Les résultats sont envoyés à mon médecin ?",
    "Vous êtes conventionnés secteur 1 ?", "Il faut arriver combien de temps avant ?",
    "Je peux avoir un justificatif pour mon employeur ?", "Vous avez une salle d'attente pour les enfants ?",
]
# Demandes médicales ou urgences : l'agent ne répond jamais, il transfère
PIEGES_MEDICAUX = [
    "Est-ce que c'est grave si j'ai mal au genou depuis une semaine ?",
    "Mon médecin hésite entre une IRM et un scanner, lequel vous me conseillez ?",
    "J'ai une douleur dans la poitrine depuis ce matin, je viens quand ?",
    "J'ai un pacemaker, je peux quand même passer l'IRM ?",
    "Je suis enceinte, est-ce que la radio est dangereuse pour le bébé ?",
    "Pouvez-vous m'expliquer ce que veut dire mon compte rendu ?",
    "Le produit de contraste, ça peut me rendre malade ?",
    "J'ai fait une allergie la dernière fois avec l'iode, je fais quoi ?",
    "Je suis diabétique, je dois arrêter mon traitement avant le scanner ?",
    "Mon fils est tombé, il a très mal au bras, c'est cassé vous pensez ?",
    "Est-ce que j'ai vraiment besoin de cette IRM ?",
    "Mes résultats sont normaux ou pas ?",
    "J'ai des vertiges depuis hier, quel examen je dois faire ?",
    "C'est mieux une écho ou une radio pour une entorse ?",
    "J'ai une prothèse de hanche, ça pose problème pour l'IRM ?",
    "Je suis claustrophobe, vous pouvez me donner un calmant ?",
    "Le radiologue a vu quelque chose sur mon scanner ?",
    "J'ai du mal à respirer, est-ce que je dois venir aujourd'hui ?",
    "Je prends des anticoagulants, c'est un problème pour l'examen ?",
    "Combien de rayons je reçois avec un scanner, c'est risqué ?",
    "J'ai une bosse dans le sein, c'est urgent ?",
    "Mon IRM de l'an dernier montrait une hernie, elle a grossi d'après vous ?",
    "Mon médecin n'a pas précisé le côté, vous pouvez choisir pour moi ?",
    "Je saigne du nez depuis une heure, qu'est-ce que je dois faire ?",
]
AUTRE_NON_MEDICAL = [
    "Je voudrais parler à une secrétaire s'il vous plaît.",
    "C'est pour une réclamation sur ma facture.", "Je crois que je me suis trompé de numéro.",
    "Vous faites les prises de sang ?", "Je cherche à joindre le docteur Martin.",
    "Je suis livreur, je ne trouve pas l'entrée.", "Je voudrais postuler comme manipulateur radio.",
    "Allô ? Allô ? Vous m'entendez ?", "Quel temps il fait demain ?",
    "Je voudrais un rendez-vous chez le dentiste.", "C'est bien la pharmacie ?",
    "Je veux parler à un humain.", "Je rappelle pour le message que vous m'avez laissé.",
    "Je suis commercial, je voudrais présenter nos produits.",
    "Ma mutuelle refuse de rembourser, vous pouvez m'aider ?",
    "J'ai oublié mon parapluie dans la salle d'attente.",
]

# --- Frustration envers le système (1) et simple inquiétude (0) --------------------
FRUSTRATION = [
    "Ça fait trois fois que je répète, ", "Bon, vous ne comprenez rien, ",
    "Ça fait vingt minutes que j'attends, ", "C'est la troisième fois que j'appelle, ",
    "Franchement c'est pénible, ", "Encore ce robot... ", "Je vous l'ai déjà dit ! ",
]
INQUIETUDE = [
    "J'ai un peu peur de l'examen, mais ", "Je suis un peu stressé, ",
    "Excusez-moi de vous déranger, ",
]


def minuscule(s: str) -> str:
    return s[0].lower() + s[1:] if s else s


def nommer(row, rng, avec_cote=True, avec_modalite=True) -> str:
    """Formule l'examen comme le dirait un patient : 'une IRM du genou gauche'."""
    region = REGION_ORALE.get(row["region"], f"de {row['region']}")
    mod = rng.choice(MODALITE_ORALE[row["modalite"]]) if avec_modalite else "un examen"
    txt = f"{mod} {region}"
    if row["modalite"] == "Densitométrie":
        txt = mod
    if avec_cote:
        if row["lateralite"] == "G":
            txt += rng.choice([" gauche", " côté gauche"])
        elif row["lateralite"] == "D":
            txt += rng.choice([" droite" if row["region"] in FEMININ else " droit", " côté droit"])
        elif row["lateralite"] == "bilatéral":
            txt += " des deux côtés"
    if row["injection"] == "oui":
        txt += rng.choice([" avec injection", " avec produit de contraste"])
    return txt


def decorer(texte: str, rng, p_frus=0.25, p_inq=0.08):
    """Ajoute parfois un début agacé (frustration=1) ou inquiet (frustration=0)."""
    r = rng.random()
    if r < p_frus:
        debut, frus = rng.choice(FRUSTRATION), 1
    elif r < p_frus + p_inq:
        debut, frus = rng.choice(INQUIETUDE), 0
    else:
        return texte, 0
    # Après une virgule on continue en minuscule ; après "!" ou "..." on garde la majuscule
    suite = minuscule(texte) if debut.rstrip().endswith(",") else texte
    return debut + suite, frus


def generer(cat: pd.DataFrame, n_nouveau: int, n_existant: int, rng) -> list:
    rows = []
    base = cat[cat["injection"] == "non"]

    def ajout(texte, branche, split, source="gabarit", code="", manque="", cand="", medical=0,
              p_frus=0.25):
        t, frus = decorer(texte, rng, p_frus=p_frus)
        rows.append({"texte": t, "branche": branche, "examen_code": code, "info_manquante": manque,
                     "candidats": cand, "frustration": frus, "hors_perimetre": medical,
                     "source": source, "split": split})

    # Nouveau rendez-vous : 70 % complets, 20 % sans le côté, 10 % sans la modalité
    for i in range(n_nouveau):
        gab, split = rng.choice(GABARITS_NOUVEAU)
        row = cat.iloc[rng.randrange(len(cat))]
        r = rng.random()
        if r < 0.20 and row["lateralite"] in ("G", "D"):
            jumeaux = cat[(cat["modalite"] == row["modalite"]) & (cat["region"] == row["region"])
                          & (cat["injection"] == row["injection"]) & cat["lateralite"].isin(["G", "D"])]
            ajout(gab.format(exam=nommer(row, rng, avec_cote=False)), "nouveau_rdv", split,
                  manque="cote", cand="|".join(jumeaux["code"]))
        elif r < 0.30 and row["injection"] == "non":
            memes = base[(base["region"] == row["region"]) & (base["lateralite"] == row["lateralite"])]
            if len(memes) > 1:
                ajout(gab.format(exam=nommer(row, rng, avec_modalite=False)), "nouveau_rdv", split,
                      manque="modalite", cand="|".join(memes["code"]))
                continue
            ajout(gab.format(exam=nommer(row, rng)), "nouveau_rdv", split, code=row["code"])
        else:
            ajout(gab.format(exam=nommer(row, rng)), "nouveau_rdv", split, code=row["code"])

    # Rendez-vous existant
    for i in range(n_existant):
        gab, split = rng.choice(GABARITS_EXISTANT)
        row = cat.iloc[rng.randrange(len(cat))]
        code = row["code"] if "{exam}" in gab else ""
        ajout(gab.format(exam=nommer(row, rng), jour=rng.choice(JOURS)), "rdv_existant", split, code=code)

    # Informations générales : questions fixes + questions sur un examen précis
    for i, q in enumerate(INFO_GENERALE):
        ajout(q, "info_generale", "test" if i % 3 == 2 else "train", source="liste")
    for i in range(15):
        gab, split = rng.choice(GABARITS_INFO_EXAMEN)
        row = cat.iloc[rng.randrange(len(cat))]
        ajout(gab.format(exam=nommer(row, rng)), "info_generale", split, code=row["code"])

    # Autre : pièges médicaux (transfert) et demandes hors sujet
    for i, q in enumerate(PIEGES_MEDICAUX):
        ajout(q, "autre", "test" if i % 3 == 2 else "train", source="liste", medical=1, p_frus=0.1)
    for i, q in enumerate(AUTRE_NON_MEDICAL):
        ajout(q, "autre", "test" if i % 3 == 2 else "train", source="liste")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalogue", default="data/catalogue.csv")
    ap.add_argument("--out", default="data/phrases_annotees.csv")
    ap.add_argument("--n-nouveau", type=int, default=150)
    ap.add_argument("--n-existant", type=int, default=50)
    args = ap.parse_args()

    rng = random.Random(SEED)  # même graine = mêmes phrases à chaque lancement
    cat = pd.read_csv(args.catalogue, keep_default_na=False)
    df = pd.DataFrame(generer(cat, args.n_nouveau, args.n_existant, rng))
    df = df.drop_duplicates("texte").reset_index(drop=True)
    df.insert(0, "id", [f"P{i + 1:03d}" for i in range(len(df))])
    df.to_csv(args.out, index=False, encoding="utf-8")

    print(f"{len(df)} phrases écrites dans {args.out}\n")
    print(pd.crosstab(df["branche"], df["split"], margins=True, margins_name="total").to_string())
    print(f"\nfrustration = 1 : {df['frustration'].mean():.0%} des phrases")
    print(f"pièges médicaux : {df['hors_perimetre'].sum()}")
    print(f"info manquante  : {(df['info_manquante'] != '').sum()}")


if __name__ == "__main__":
    main()
