"""Données communales du primaire tirées des annuaires statistiques régionaux 2024 de l'INSD.

Dix régions sur treize ont publié un annuaire (Centre-Est, Centre-Nord et Est manquent).
La mise en page varie d'une région à l'autre, mais suit le même principe :

    Tableau 02.04.012 : Effectifs des élèves du primaire par commune et par sexe
    2014/2015 | 2015/2016 | ... | 2018/2019          années en colonnes
    Bagassi                                          commune
    Filles   | 3 186 | 3 307 | ...                   une ligne par modalité
    Garçons  | 3 070 | ...
    Ensemble | 6 256 | ...

Le type de tableau se déduit des mots de son titre ; les années de la dernière
ligne d'années rencontrée ; la commune est reconnue parmi celles de la région du
fichier, par égalité puis par orthographe voisine. Le résultat est une table longue :
une valeur par commune, indicateur, modalité et année.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

import pandas as pd

from .nomenclature import Nomenclature, cle
from .tableaux import Signalement, nombre

# Type de tableau d'après les mots de son titre, du plus précis au plus général.
TYPES = [
    ("ecoles_fermees", ["FERM", "INSECURITE"]),
    ("salles_paillote", ["SALLES", "PAILLOT"]),
    ("salles", ["SALLES DE CLASSE"]),
    ("ecoles", ["ECOLES"]),
    ("enseignants", ["ENSEIGNANTS"]),
    ("eleves", ["ELEVES"]),
]
MODALITES = {"FILLES": "filles", "GARCONS": "garcons", "FEMMES": "femmes", "HOMMES": "hommes",
             "PUBLIC": "public", "PRIVE": "prive", "ENSEMBLE": "ensemble", "TOTAL": "ensemble",
             "COMMUNAUTAIRE": "communautaire"}
_ANNEE = re.compile(r"^(?:20)?(\d{2})\s*[/-]\s*(?:20)?(\d{2})$")
SEUIL = 0.85
NON_DISPONIBLE = float("nan")


def _type_tableau(titre: str) -> str | None:
    t = cle(titre)
    if "PRIMAIRE" not in t or "COMMUNE" not in t:
        return None
    for nom, mots in TYPES:
        if all(m in t for m in mots):
            if nom in ("eleves", "enseignants"):
                return f"{nom}_par_sexe" if "SEXE" in t else f"{nom}_par_statut"
            return nom
    return None


def _region_du_fichier(fichier: str, nomenclature: Nomenclature) -> str | None:
    morceau = re.sub(r"(?i)^annuaire_statistique_2024_|_?\d*\.pdf$", "", fichier)
    morceau = re.sub(r"(?i)^(de_la_)?(r[ée]gion_)?(de_la_|du_|des_|de_l_|de_)?", "", morceau)
    trouve = nomenclature.reconnaitre(morceau.replace("_", " "), "annuaire régional")
    return trouve[0] if trouve and trouve[1] == "region" else None


class LecteurCommunal:
    def __init__(self, nomenclature: Nomenclature, signaler: Signalement):
        self.nomenclature = nomenclature
        self.signaler = signaler
        self.rapprochements: list[dict] = []

    def _commune(self, nom: str, region: str) -> str | None:
        communes = self.nomenclature.communes
        candidats = communes[communes["region_code_ancien"] == region]
        k = cle(re.sub(r"(?i)^commune\s+(de|d')\s*", "", nom))
        provinces = {cle(n) for n in self.nomenclature.provinces["province_ancienne"]}
        if k in provinces or re.sub(r"^(PROVINCE|TOTAL) (DU |DE LA |DES |DE L |DE )?", "", k) in provinces \
                or k.startswith(("TOTAL", "PROVINCE", "REGION")):
            return None
        exacts = candidats[candidats["commune"].map(cle) == k]
        if len(exacts) == 1:
            return exacts["commune_code"].iloc[0]
        scores = candidats["commune"].map(lambda n: SequenceMatcher(None, k, cle(n)).ratio())
        if len(scores) and scores.max() >= SEUIL:
            meilleur = candidats.loc[scores.idxmax()]
            self.rapprochements.append({"nom_lu": nom, "code": meilleur["commune_code"], "niveau": "commune",
                                        "regle": f"orthographe voisine de « {meilleur['commune']} »",
                                        "similarite": round(scores.max(), 3), "contexte": f"annuaire régional {region}"})
            return meilleur["commune_code"]
        return None

    def lire(self, brut: pd.DataFrame) -> pd.DataFrame:
        cellules = sorted((c for c in brut.columns if re.fullmatch(r"c\d+", c)), key=lambda c: int(c[1:]))
        brut = brut.assign(_p=pd.to_numeric(brut["page"]), _l=pd.to_numeric(brut["ligne"]))
        sortie = []
        for fichier, document in brut.sort_values(["_p", "_l"]).groupby("origine_fichier"):
            region = _region_du_fichier(fichier, self.nomenclature)
            if region is None:
                self.signaler("communes", "région du fichier non reconnue", fichier, "", "", fichier)
                continue
            tableau, annees, commune = None, [], None
            for _, rang in document.iterrows():
                morceaux = [rang[c].strip() for c in cellules if rang[c].strip()]
                if not morceaux:
                    continue
                texte = " ".join(morceaux)
                if re.match(r"(?i)^\s*tableau", texte):
                    if "...." in texte or "…" in texte:
                        continue  # table des matières
                    tableau, annees, commune = _type_tableau(texte), [], None
                    continue
                if tableau is None:
                    continue
                if all(_ANNEE.match(m.replace(" ", "")) for m in morceaux):
                    annees = [f"20{_ANNEE.match(m.replace(' ', '')).group(1)}-20{_ANNEE.match(m.replace(' ', '')).group(2)}"
                              for m in morceaux]
                    continue
                valeurs = [NON_DISPONIBLE if cle(m) in {"ND", "NP"} else nombre(m) for m in morceaux]
                debut = next((i for i, v in enumerate(valeurs) if v is not None), None)
                libelles = morceaux if debut is None else morceaux[:debut]
                modalite = MODALITES.get(cle(libelles[-1])) if libelles else None
                nom = " ".join(libelles[:-1] if modalite else libelles)
                if nom:
                    trouvee = self._commune(nom, region)
                    if trouvee is not None:
                        commune = trouvee
                    elif debut is None:
                        commune = None  # titre de province ou ligne de total : la commune en cours s'arrête
                if debut is None or commune is None or not annees:
                    continue
                nombres = [v for v in valeurs[debut:] if v is not None]  # NaN (« nd ») conservé
                if len(nombres) != len(annees):
                    self.signaler("communes", f"{len(nombres)} valeurs pour {len(annees)} années", fichier,
                                  rang["page"], rang["ligne"], texte)
                    continue
                for annee, valeur in zip(annees, nombres):
                    sortie.append({"annee": annee, "commune_code": commune, "region_code_ancien": region,
                                   "indicateur": tableau, "modalite": modalite or "ensemble", "valeur": valeur,
                                   "fichier": fichier, "page": rang["page"]})
        table = pd.DataFrame(sortie)
        if table.empty:
            return table
        cles = ["annee", "commune_code", "indicateur", "modalite"]
        nb_valeurs = table.groupby(cles)["valeur"].transform(lambda v: v.nunique(dropna=False))
        contradictoires = nb_valeurs > 1
        for _, ligne in table[contradictoires].drop_duplicates(cles).iterrows():
            self.signaler("communes", "valeurs contradictoires pour une même commune, année et modalité : "
                          "écartées", ligne["fichier"], ligne["page"], "",
                          f"{ligne['commune_code']} {ligne['annee']} {ligne['indicateur']} {ligne['modalite']}")
        return table[~contradictoires].drop_duplicates(cles).reset_index(drop=True)
