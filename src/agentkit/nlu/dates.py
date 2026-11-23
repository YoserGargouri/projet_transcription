"""
Dates et heures : format pivot ISO (« 2026-11-26T09:00 ») entre le LLM, les slots et les outils.

    dire("2026-11-26T09:00", "fr")        -> « jeudi 26 novembre à 9 heures »   (lu à voix haute)
    analyser("jeudi matin", "fr", now)    -> "2026-11-26T09:00"                  (repli sans LLM)
    normaliser(valeur, "datetime", "fr")  -> ISO, ou None si la valeur n'est pas comprise

Avec un LLM, c'est lui qui convertit « demain vers 10 h » en ISO (il reçoit la date du jour).
L'analyseur ci-dessous ne sert qu'au repli sur les règles (LLM absent ou en panne) : il couvre
les formes courantes, pas toutes. Données de langue uniquement (noms de jours et de mois).
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from agentkit.nlu.text import normalise

LANGUES = {
    "fr": {"jours": ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"],
           "mois": ["janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout", "septembre",
                    "octobre", "novembre", "decembre"],
           "mois_dits": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
                         "octobre", "novembre", "décembre"]},
    "en": {"jours": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"],
           "mois": ["january", "february", "march", "april", "may", "june", "july", "august", "september",
                    "october", "november", "december"]},
}
ISO_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?$")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HEURE = re.compile(r"^\d{1,2}:\d{2}$")
# Moment de la journée sans heure précise -> heure proposée (le récapitulatif la fait confirmer)
MOMENTS_FR = {"matin": 9, "midi": 12, "apres midi": 14, "fin d apres midi": 17, "soir": 17}


def dire(valeur: str, langue: str = "fr") -> str:
    """Date ISO -> forme orale ; toute autre valeur est rendue telle quelle."""
    v = str(valeur).strip()
    try:
        if ISO_DATETIME.match(v):
            d = datetime.fromisoformat(v.replace(" ", "T"))
            return f"{_jour(d.date(), langue)} {_heure(d, langue)}"
        if ISO_DATE.match(v):
            return _jour(date.fromisoformat(v), langue)
    except ValueError:
        pass
    return v


def _jour(d: date, langue: str) -> str:
    if langue == "fr":
        L = LANGUES["fr"]
        return f"{L['jours'][d.weekday()]} {'1er' if d.day == 1 else d.day} {L['mois_dits'][d.month - 1]}"
    L = LANGUES["en"]
    return f"{L['jours'][d.weekday()].capitalize()} {d.day} {L['mois'][d.month - 1].capitalize()}"


def _heure(d: datetime, langue: str) -> str:
    if langue == "fr":
        h = "midi" if d.hour == 12 and not d.minute else f"{d.hour} heure{'s' if d.hour > 1 else ''}"
        return f"à {h}" + (f" {d.minute}" if d.minute else "")
    return f"at {d.hour}:{d.minute:02d}"


def maintenant_pour_llm(now: datetime | None = None) -> str:
    """Date du jour donnée au LLM pour résoudre « demain », « jeudi prochain »..."""
    now = now or datetime.now()
    return f"{now:%Y-%m-%dT%H:%M} ({LANGUES['en']['jours'][now.weekday()]})"


def normaliser(valeur: str, type_slot: str, langue: str = "fr", now: datetime | None = None) -> str | None:
    """Valeur d'un slot date / time / datetime -> ISO, ou None si elle n'est pas comprise."""
    v = str(valeur).strip()
    if type_slot == "datetime" and ISO_DATETIME.match(v):
        return _valide(v.replace(" ", "T")[:16], datetime.fromisoformat)
    if type_slot == "date" and ISO_DATE.match(v):
        return _valide(v, date.fromisoformat)
    if type_slot == "time" and HEURE.match(v):
        h, m = map(int, v.split(":"))
        return f"{h:02d}:{m:02d}" if h < 24 and m < 60 else None
    if langue != "fr":
        return None
    return analyser(v, type_slot, now)


def _valide(v, conv):
    try:
        conv(v)
        return v
    except ValueError:
        return None


def analyser(texte: str, type_slot: str = "datetime", now: datetime | None = None) -> str | None:
    """Analyse simple du français parlé (repli sans LLM)."""
    now = now or datetime.now()
    t = normalise(texte)
    jour, heure = _analyser_jour(t, now.date()), _analyser_heure(t)
    if type_slot == "date":
        return jour.isoformat() if jour else None
    if type_slot == "time":
        return f"{heure[0]:02d}:{heure[1]:02d}" if heure else None
    if jour is None or heure is None:
        return None
    return f"{jour.isoformat()}T{heure[0]:02d}:{heure[1]:02d}"


def _analyser_jour(t: str, aujourd_hui: date) -> date | None:
    if re.search(r"\bapres demain\b", t):
        return aujourd_hui + timedelta(days=2)
    if re.search(r"\bdemain\b", t):
        return aujourd_hui + timedelta(days=1)
    if re.search(r"\baujourd hui\b|\bce (matin|soir|midi)\b|\bcet apres midi\b", t):
        return aujourd_hui
    L = LANGUES["fr"]
    m = re.search(r"\b(\d{1,2}|1er|premier) (" + "|".join(L["mois"]) + r")\b(?: (\d{4}))?", t)
    if m:
        j = 1 if m.group(1) in ("1er", "premier") else int(m.group(1))
        mois = L["mois"].index(m.group(2)) + 1
        an = int(m.group(3)) if m.group(3) else aujourd_hui.year
        try:
            d = date(an, mois, j)
        except ValueError:
            return None
        return d if m.group(3) or d >= aujourd_hui else date(an + 1, mois, j)
    for i, nom in enumerate(L["jours"]):
        if re.search(rf"\b{nom}\b", t):
            ecart = (i - aujourd_hui.weekday()) % 7 or 7     # « jeudi » = le prochain jeudi
            if re.search(rf"\b{nom} (en )?(huit|d apres)\b|\b{nom} de la semaine prochaine\b", t):
                ecart += 7 if ecart < 7 else 0
            return aujourd_hui + timedelta(days=ecart)
    m = re.search(r"\b(?:le )(\d{1,2})\b(?! ?h)", t)
    if m and 1 <= int(m.group(1)) <= 31:
        j, d = int(m.group(1)), aujourd_hui
        for _ in range(2):
            try:
                cand = d.replace(day=j)
                if cand >= aujourd_hui:
                    return cand
            except ValueError:
                pass
            d = (d.replace(day=1) + timedelta(days=32)).replace(day=1)
    return None


def _analyser_heure(t: str) -> tuple[int, int] | None:
    m = re.search(r"\b(\d{1,2}) ?(?:h|heures?)(?: ?(\d{2}))?\b", t)
    if m and int(m.group(1)) < 24:
        h, mn = int(m.group(1)), int(m.group(2) or 0)
        if re.search(r"\b(apres midi|soir)\b", t) and h < 12:
            h += 12
        return (h, mn) if mn < 60 else None
    if re.search(r"\bmidi\b", t) and not re.search(r"\bapres midi\b", t):
        return (12, 0)
    for moment, h in sorted(MOMENTS_FR.items(), key=lambda x: -len(x[0])):
        if re.search(rf"\b{moment}\b", t):
            return (h, 0)
    return None


ORDINAUX_FR = [r"premier|premiere|1er|1re|la 1|le 1", r"deuxieme|second|seconde|2e|la 2|le 2",
               r"troisieme|3e|la 3|le 3"]


def option_choisie(texte: str, options: list[str], langue: str = "fr") -> str | None:
    """Parmi des options ISO proposées, celle que désigne la réponse (valeur exacte, rang,
    « la dernière », ou heure citée). None si la réponse ne désigne pas une option."""
    v = str(texte).strip()
    if v in options:
        return v
    if not options or langue != "fr":
        return None
    t = normalise(v)
    if re.search(r"\b(derniere|dernier)\b", t):
        return options[-1]
    for i, motif in enumerate(ORDINAUX_FR[: len(options)]):
        if re.search(rf"\b({motif})\b", t):
            return options[i]
    if h := _analyser_heure(t):
        memes = [o for o in options if ISO_DATETIME.match(o) and datetime.fromisoformat(o).hour == h[0]
                 and datetime.fromisoformat(o).minute == h[1]]
        if len(memes) == 1:
            return memes[0]
    return None
