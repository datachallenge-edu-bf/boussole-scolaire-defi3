"""Lecture générique des tableaux provinciaux des annuaires de la DGESS.

Un tableau provincial se présente comme une suite de lignes :

    BOUCLE DU MOUHOUN                      titre de bloc (région)
    BANWA | Public | 75 | 404 | ...        province, statut éventuel, valeurs
          | Privé  | 22 | 85  | ...        même province, autre statut
    Total Région | Public | 767 | ...      total de la région

Le lecteur suit l'entité en cours (la dernière province ou région nommée) et le
contexte (dernier intertitre reconnu, par exemple « MURS » et « PUBLIC » dans les
tableaux sur l'état des salles). Il produit une table longue : une valeur par
ligne, repérée par l'édition, le contexte, l'entité, le statut et la position de
la colonne. La signification des colonnes est donnée par le tableau appelant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from .nomenclature import Nomenclature, cle

STATUTS = {"PUBLIC": "public", "PRIVE": "prive", "TOTAL": "total", "PUBLIC PRIVE": "total",
           "PUBLIC + PRIVE": "total", "COMMUNAUTAIRE": "communautaire"}
_NOMBRE = re.compile(r"^-?\d{1,3}(?:[   ]\d{3})*(?:[,.]\d+)?%?$|^-?\d+(?:[,.]\d+)?%?$")


def nombre(texte: str) -> float | None:
    texte = texte.strip()
    if texte in {"-", "--"}:
        return 0.0
    if not _NOMBRE.match(texte):
        return None
    return float(re.sub(r"[   %]", "", texte).replace(",", "."))


@dataclass
class Signalement:
    lignes: list[dict] = field(default_factory=list)

    def __call__(self, tableau: str, motif: str, fichier: str, page: str, ligne: str, texte: str) -> None:
        self.lignes.append({"tableau": tableau, "motif": motif, "fichier": fichier, "page": page,
                            "ligne": ligne, "texte": texte[:200]})


def lire(brut: pd.DataFrame, tableau: str, nomenclature: Nomenclature, nb_valeurs: int | tuple[int, ...],
         contextes: dict[str, str], signaler: Signalement, ignorer: tuple[str, ...] = (),
         etiquettes: dict[str, tuple[str, str]] | None = None) -> pd.DataFrame:
    """Table longue des valeurs d'un tableau provincial, pour toutes les éditions présentes.

    ``etiquettes`` associe un libellé de ligne (par exemple « FEMMES », parfois répété dans la même
    cellule) à une colonne et une valeur de la table produite (par exemple ``("sexe", "F")``).
    """
    etiquettes = etiquettes or {}
    cellules = sorted((c for c in brut.columns if re.fullmatch(r"c\d+", c)), key=lambda c: int(c[1:]))
    brut = brut.assign(_p=pd.to_numeric(brut["page"]), _l=pd.to_numeric(brut["ligne"]))
    sortie = []

    for (fichier, edition), document in brut.sort_values(["_p", "_l"]).groupby(["origine_fichier", "origine_periode"]):
        entite, region_en_cours, contexte = None, None, {}
        for _, rang in document.iterrows():
            morceaux = [rang[c].strip() for c in cellules if rang[c].strip()]
            if not morceaux:
                continue
            texte = " ".join(morceaux)

            # Intertitres de contexte (sous-tableaux).
            for motif, etiquette in contextes.items():
                if re.search(motif, cle(texte)) and len(morceaux) <= 2:
                    contexte[etiquette.split(":")[0]] = etiquette.split(":")[1]

            valeurs = [nombre(m) for m in morceaux]
            debut = next((i for i, v in enumerate(valeurs) if v is not None), None)
            libelles = morceaux if debut is None else morceaux[:debut]

            marques = {}
            for libelle in list(libelles):
                for prefixe, (colonne, valeur) in etiquettes.items():
                    if re.fullmatch(rf"{prefixe}( {prefixe})*", cle(libelle)):
                        marques[colonne] = valeur
                        libelles.remove(libelle)
                        break

            statut = None
            for libelle in list(libelles):
                if cle(libelle) in STATUTS:
                    statut = STATUTS[cle(libelle)]
                    libelles.remove(libelle)
            if libelles and (libelles[0].startswith("%") or cle(libelles[0]).startswith("POURCENTAGE")):
                continue  # ligne de pourcentages, recalculable
            if libelles:
                nom = " ".join(libelles)
                if cle(nom).startswith("TOTAL REGION") or cle(nom) == "TOTAL":
                    entite = region_en_cours
                elif (trouve := nomenclature.reconnaitre(nom, f"{tableau} {edition}")) is not None:
                    entite = trouve
                    if trouve[1] == "region":
                        region_en_cours = trouve
                elif debut is not None:
                    signaler(tableau, "nom non reconnu", fichier, rang["page"], rang["ligne"], texte)
                    entite = None

            if debut is None or entite is None:
                continue
            nombres = [v for v in valeurs[debut:] if v is not None]
            if not libelles and statut is None and not marques and len(nombres) == 1:
                continue  # numéro de page
            if contexte.get("element") in ignorer:
                continue  # sous-tableau non retenu
            attendus = nb_valeurs if isinstance(nb_valeurs, tuple) else (nb_valeurs,)
            if len(nombres) not in attendus:
                signaler(tableau, f"{len(nombres)} valeurs au lieu de {attendus}", fichier, rang["page"],
                         rang["ligne"], texte)
                continue
            for position, valeur in enumerate(nombres, start=1):
                sortie.append({"edition": edition, **contexte, **marques, "code": entite[0], "niveau": entite[1],
                               "statut": statut or "", "largeur": len(nombres), "colonne": position, "valeur": valeur,
                               "fichier": fichier, "page": rang["page"]})
    return pd.DataFrame(sortie)
