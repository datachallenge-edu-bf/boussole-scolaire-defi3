"""Métadonnées de la base Boussole : tables ``_tables`` et ``_variables``.

Les descriptions sont rédigées dans ``dictionnaire.json`` ; ce module les associe
aux tables réellement produites (colonnes, types, nombre de lignes). Une variable
absente du dictionnaire reçoit une description vide, que signale le contrôle
``metadonnees_completes``.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

_DICTIONNAIRE = json.loads(Path(__file__).with_name("dictionnaire.json").read_text(encoding="utf-8"))


def _type(serie: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(serie):
        return "booléen"
    if pd.api.types.is_integer_dtype(serie):
        return "entier"
    if pd.api.types.is_numeric_dtype(serie):
        return "décimal"
    return "texte"


def decrire(tables: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    variables_connues, tables_connues = _DICTIONNAIRE["variables"], _DICTIONNAIRE["tables"]
    colonnes_meta = {"_tables": ["table", "description", "grain", "cle", "sources", "lignes", "colonnes",
                                 "produite_le"],
                     "_variables": ["table", "variable", "type", "unite", "description"]}

    lignes_variables = [
        {"table": nom, "variable": colonne, "type": _type(table[colonne]),
         "unite": variables_connues.get(colonne, ["", ""])[1], "description": variables_connues.get(colonne, ["", ""])[0]}
        for nom, table in tables.items() for colonne in table.columns
    ]
    lignes_variables += [
        {"table": nom, "variable": colonne, "type": "entier" if colonne in ("lignes", "colonnes") else "texte",
         "unite": variables_connues[colonne][1], "description": variables_connues[colonne][0]}
        for nom, colonnes in colonnes_meta.items() for colonne in colonnes
    ]
    variables = pd.DataFrame(lignes_variables)

    effectifs = {nom: table.shape for nom, table in tables.items()}
    effectifs["_variables"] = variables.shape
    effectifs["_tables"] = (len(effectifs) + 1, len(colonnes_meta["_tables"]))
    lignes_tables = []
    for nom, (n_lignes, n_colonnes) in effectifs.items():
        description, grain, cle, sources = tables_connues.get(nom, ["", "", "", ""])
        lignes_tables.append({"table": nom, "description": description, "grain": grain, "cle": cle,
                              "sources": sources, "lignes": n_lignes, "colonnes": n_colonnes,
                              "produite_le": date.today().isoformat()})
    return pd.DataFrame(lignes_tables), variables


def lacunes(tables_meta: pd.DataFrame, variables_meta: pd.DataFrame) -> list[str]:
    return ([f"{r.table}.{r.variable}" for r in variables_meta.itertuples() if not r.description]
            + [r.table for r in tables_meta.itertuples() if not r.description])
