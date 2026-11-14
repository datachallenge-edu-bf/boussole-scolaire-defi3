"""Effectifs et redoublants par niveau, à partir de l'historique des annuaires (section VIII.3).

Pour chaque province, l'annuaire donne une dizaine d'années, de la plus récente à la
plus ancienne, trois lignes par année (garçons, filles, total) de quatorze valeurs
(effectif et dont redoublants, pour le CP1 au CM2 puis le total).

Principe retenu : chaque année est lue dans sa propre édition. Seul le premier
bloc de chaque province est conservé ; c'est toujours l'année de l'édition, quelle
que soit l'étiquette imprimée, qui est parfois absente ou erronée dans les PDF.
L'étiquette et les libellés de sexe servent de contrôle et leurs écarts sont
signalés. Les huit éditions donnent ainsi huit années contemporaines de leur
publication, de 2017-2018 à 2024-2025.
"""

from __future__ import annotations

import re

import pandas as pd

from .nomenclature import Nomenclature, cle
from .tableaux import Signalement, nombre

NIVEAUX = ["CP1", "CP2", "CE1", "CE2", "CM1", "CM2", "Total"]
SEXES = ["G", "F", "T"]
LIBELLES_SEXE = {"GARCONS": "G", "FILLES": "F", "TOTAL": "T"}
_ANNEE = re.compile(r"^\s*(\d{4})\s*/\s*(\d{4})\s*$")


def lire_effectifs(brut: pd.DataFrame, nomenclature: Nomenclature, signaler: Signalement) -> pd.DataFrame:
    cellules = sorted((c for c in brut.columns if re.fullmatch(r"c\d+", c)), key=lambda c: int(c[1:]))
    brut = brut.assign(_p=pd.to_numeric(brut["page"]), _l=pd.to_numeric(brut["ligne"]))
    sortie = []

    for (fichier, edition), document in brut.sort_values(["_p", "_l"]).groupby(["origine_fichier", "origine_periode"]):
        entite, attente, bloc, etiquette = None, False, {}, None
        for _, rang in document.iterrows():
            morceaux = [rang[c].strip() for c in cellules if rang[c].strip()]
            if not morceaux:
                continue

            if len(morceaux) == 1:
                texte = morceaux[0]
                if _ANNEE.match(texte) or re.fullmatch(r"\d{8,9}", texte):
                    if attente and bloc:
                        sortie.extend(_completer(bloc, edition, entite, etiquette, fichier, signaler, rang))
                        attente, bloc = False, {}  # le bloc suivant commence
                    elif attente:
                        etiquette = texte.replace(" ", "")
                    continue
                trouve = nomenclature.reconnaitre(texte, f"effectifs {edition}")
                if trouve is not None:
                    entite, attente, bloc, etiquette = trouve, True, {}, None
                continue

            if not attente or entite is None:
                continue
            valeurs = [nombre(m) for m in morceaux[1:]]
            if len(valeurs) != 14 or any(v is None for v in valeurs):
                signaler("effectifs_niveau", f"{len(valeurs)} valeurs au lieu de 14", fichier, rang["page"],
                         rang["ligne"], " ".join(morceaux))
                continue
            # Le libellé fait foi s'il est lisible ; sinon le sexe se déduit de la position dans le bloc.
            sexe = LIBELLES_SEXE.get(cle(morceaux[0]))
            if sexe is None or sexe in bloc:
                deduit = next(s for s in SEXES if s not in bloc)
                signaler("effectifs_niveau", f"libellé « {morceaux[0]} » : sexe déduit de la position ({deduit})",
                         fichier, rang["page"], rang["ligne"], " ".join(morceaux))
                sexe = deduit
            bloc[sexe] = (valeurs, rang["page"])
            if len(bloc) == 3:
                sortie.extend(_emettre(bloc, edition, entite, etiquette, fichier, signaler, rang))
                attente, bloc = False, {}
    return pd.DataFrame(sortie)


def _emettre(bloc: dict, edition: str, entite: tuple[str, str], etiquette: str | None, fichier: str,
             signaler: Signalement, rang) -> list[dict]:
    attendue = edition.replace("-", "/")
    if etiquette and etiquette != attendue:
        signaler("effectifs_niveau", f"étiquette « {etiquette} » en tête du bloc de l'édition {edition} : "
                 "année de l'édition retenue", fichier, rang["page"], rang["ligne"], entite[0])
    lignes = []
    for sexe, (valeurs, page) in bloc.items():
        for k, niveau in enumerate(NIVEAUX):
            lignes.append({"annee": edition, "code": entite[0], "niveau": entite[1], "sexe": sexe, "classe": niveau,
                           "effectif": valeurs[2 * k], "redoublants": valeurs[2 * k + 1], "fichier": fichier,
                           "page": page})
    return lignes


def _completer(bloc: dict, edition: str, entite: tuple[str, str], etiquette: str | None, fichier: str,
               signaler: Signalement, rang) -> list[dict]:
    """Bloc interrompu avec deux lignes sur trois : la troisième se déduit des deux autres."""
    if len(bloc) != 2:
        return []
    manquant = next(s for s in SEXES if s not in bloc)
    page = next(iter(bloc.values()))[1]
    if manquant == "T":
        valeurs = [g + f for g, f in zip(bloc["G"][0], bloc["F"][0])]
    else:
        autre = "F" if manquant == "G" else "G"
        valeurs = [t - a for t, a in zip(bloc["T"][0], bloc[autre][0])]
    bloc[manquant] = (valeurs, page)
    signaler("effectifs_niveau", f"ligne {manquant} illisible : déduite des deux autres lignes du bloc",
             fichier, rang["page"], rang["ligne"], entite[0])
    return _emettre(bloc, edition, entite, etiquette, fichier, signaler, rang)
