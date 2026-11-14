"""Population projetée 2020-2035 par région et par province (RGPH 2019, volume 4, chapitre 2).

Chaque entité occupe trois pages. Une page commence par le nom de l'entité
(« Région du Centre-Nord », « Kossi »), puis donne des blocs de trois années côte
à côte : une ligne d'années, une ligne d'en-têtes (Homme, Femme, Ensemble) et une
ligne par groupe d'âges. Le groupe « 6-11 ans » correspond à l'âge officiel du
primaire. Le scénario est celui retenu par l'INSD pour les projections
régionales et provinciales.
"""

from __future__ import annotations

import re

import pandas as pd

from .nomenclature import Nomenclature, cle
from .tableaux import Signalement, nombre

_TITRE_REGION = re.compile(r"^R[ée]gion\s+(?:de\s+la\s+|de\s+l['’]\s*|du\s+|des\s+|de\s+)", re.IGNORECASE)
_GROUPE = re.compile(r"^(\d+)\s*(?:an|ans)?\s*(?:-\s*(\d+)\s*ans?|et\s*\+)?$|^Total$", re.IGNORECASE)


def _groupe_age(libelle: str) -> str | None:
    texte = libelle.strip()
    if cle(texte) == "TOTAL":
        return "total"
    m = re.match(r"^(\d+)\s*-\s*(\d+)\s*ans?$", texte)
    if m:
        return f"{int(m[1])}-{int(m[2])}"
    m = re.match(r"^(\d+)\s*ans?\s*et\s*\+$", texte)
    if m:
        return f"{int(m[1])}+"
    m = re.match(r"^(\d+)\s*ans?$", texte)  # « 0 an » ou « 0 ans » selon les pages
    if m:
        return m[1]
    return None


def lire_projections(brut: pd.DataFrame, nomenclature: Nomenclature, signaler: Signalement) -> pd.DataFrame:
    volume = brut[brut["origine_fichier"].str.startswith("INSD_RGPH2019_Vol4")]
    cellules = sorted((c for c in volume.columns if re.fullmatch(r"c\d+", c)), key=lambda c: int(c[1:]))
    volume = volume.assign(_p=pd.to_numeric(volume["page"]), _l=pd.to_numeric(volume["ligne"]))
    sortie = []
    for page, lignes in volume.sort_values(["_p", "_l"]).groupby("_p"):
        rangs = [[r[c].strip() for c in cellules if r[c].strip()] for _, r in lignes.iterrows()]
        rangs = [r for r in rangs if r]
        if not rangs or not any(_groupe_age(r[0]) == "6-11" for r in rangs if r):
            continue
        titre = _TITRE_REGION.sub("", rangs[0][0]) if len(rangs[0]) == 1 else ""
        entite = nomenclature.reconnaitre(titre, f"projections page {page}")
        if entite is None:
            signaler("projections", "entité non reconnue", lignes["origine_fichier"].iloc[0], str(page), "1",
                     " ".join(rangs[0]))
            continue

        annees: list[int] = []
        for rang in rangs[1:]:
            entiers = [m for m in rang if re.fullmatch(r"20\d{2}", m)]
            if entiers and len(entiers) == len([m for m in rang if re.search(r"\d", m)]):
                annees = [int(a) for a in entiers]
                continue
            groupe = _groupe_age(rang[0])
            if groupe is None or not annees:
                continue
            valeurs = [nombre(m) for m in rang[1:]]
            if len(valeurs) != 3 * len(annees) or any(v is None for v in valeurs):
                signaler("projections", f"{len(valeurs)} valeurs pour {len(annees)} années", lignes["origine_fichier"].iloc[0],
                         str(page), "", " ".join(rang))
                continue
            for k, annee in enumerate(annees):
                hommes, femmes, ensemble = valeurs[3 * k: 3 * k + 3]
                sortie.append({"annee": annee, "code": entite[0], "niveau": entite[1], "groupe_age": groupe,
                               "hommes": hommes, "femmes": femmes, "ensemble": ensemble,
                               "fichier": lignes["origine_fichier"].iloc[0], "page": str(page)})
    table = pd.DataFrame(sortie)
    if table.empty:
        return table
    table = table.drop_duplicates(["annee", "code", "groupe_age"]).sort_values(["code", "groupe_age", "annee"])
    return _reparer_colonnes_decalees(table.reset_index(drop=True), signaler)


def _reparer_colonnes_decalees(table: pd.DataFrame, signaler: Signalement) -> pd.DataFrame:
    """Lignes où hommes + femmes diffère de l'ensemble : colonnes décalées à l'extraction.

    Leurs valeurs sont remplacées par une interpolation linéaire entre l'année
    précédente et l'année suivante de la même entité et du même groupe d'âges.
    """
    decalees = (table["hommes"] + table["femmes"] - table["ensemble"]).abs() > 1
    table["valeur_interpolee"] = decalees
    for ligne in table[decalees].itertuples():
        signaler("projections", "hommes + femmes différent de l'ensemble (colonnes décalées) : valeurs "
                 "interpolées entre les années voisines", ligne.fichier, ligne.page, "",
                 f"{ligne.code} {ligne.annee} {ligne.groupe_age}")
    colonnes = ["hommes", "femmes", "ensemble"]
    table.loc[decalees, colonnes] = float("nan")
    table[colonnes] = (table.groupby(["code", "groupe_age"])[colonnes]
                       .transform(lambda s: s.interpolate(limit_area="inside")).round())
    return table
