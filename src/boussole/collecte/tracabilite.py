"""Identité des fichiers : empreinte, origine d'après le manifeste, période couverte."""

from __future__ import annotations

import hashlib
import re
from functools import cache
from pathlib import Path

import pandas as pd

from ..chemins import LIEUX

_MOIS = ["janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout", "septembre",
         "octobre", "novembre", "decembre"]


@cache
def sha256(chemin: Path) -> str:
    condensat = hashlib.sha256()
    with Path(chemin).open("rb") as flux:
        for morceau in iter(lambda: flux.read(1 << 20), b""):
            condensat.update(morceau)
    return condensat.hexdigest()


@cache
def _manifeste() -> dict[str, dict[str, str]]:
    table = pd.read_csv(LIEUX.manifeste, sep=";", dtype=str, encoding="utf-8-sig", keep_default_na=False)
    return {ligne["fichier"]: ligne for ligne in table.to_dict("records")}


def origine(nom_fichier: str) -> dict[str, str]:
    """Producteur, description et adresse de téléchargement d'un fichier, d'après le manifeste du pack."""
    ligne = _manifeste().get(nom_fichier, {})
    return {"producteur": ligne.get("source", ""), "description_source": ligne.get("description", ""),
            "url": ligne.get("url", "")}


def original_du_csv(csv: Path) -> Path | None:
    """Fichier remis par les organisateurs (PDF, classeur...) dont le CSV du pack est tiré."""
    dossier = LIEUX.data_pack / csv.parent.relative_to(LIEUX.csv_pack)
    racine = csv.stem.split("__")[0]
    candidats = [c for c in dossier.glob(f"{racine}.*")] if dossier.is_dir() else []
    # Un même nom peut exister en plusieurs formats (classeur et archives cartographiques) :
    # le document tabulaire dont le CSV est tiré passe en premier.
    preference = {".pdf": 0, ".xlsx": 1, ".xls": 2, ".csv": 3}
    candidats.sort(key=lambda c: (preference.get(c.suffix.lower(), 9), c.name))
    return candidats[0] if candidats else None


def _sans_accent(texte: str) -> str:
    return texte.lower().translate(str.maketrans("éèêëûùôàç", "eeeeuuoac"))


# Motifs de date rencontrés dans les noms de fichiers, du plus précis au moins précis.
_MOTIFS = [
    (r"(20\d{2})[_-](20\d{2})", lambda m: f"{m[1]}-{m[2]}"),
    (r"(?<!\d)(\d{1,2})[-_](\d{1,2})[-_](20\d{2})(?!\d)", lambda m: f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}"),
    (r"(?<!\d)(\d{1,2})[-_](" + "|".join(_MOIS) + r")[-_](20\d{2})",
     lambda m: f"{m[3]}-{_MOIS.index(m[2]) + 1:02d}-{int(m[1]):02d}"),
    (r"(?:^|[^a-z])d?(" + "|".join(_MOIS) + r")[^a-z0-9]*(20\d{2})",
     lambda m: f"{m[2]}-{_MOIS.index(m[1]) + 1:02d}"),
    (r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)", lambda m: f"{m[1]}-{m[2]}-{m[3]}"),
    (r"(?<!\d)(\d{2})(\d{2})(20\d{2})(?!\d)", lambda m: f"{m[3]}-{m[2]}-{m[1]}"),
    (r"(?<!\d)(\d{2})_(\d{2})_(20\d{2})(?!\d)", lambda m: f"{m[3]}-{m[2]}-{m[1]}"),
    (r"(?<!\d)(\d{2})(\d{2})(\d{2})(?!\d)", lambda m: f"20{m[3]}-{m[2]}-{m[1]}"),
    (r"(?<!\d)(20\d{2})(?!\d)", lambda m: m[1]),
]

# Fichiers dont le nom ne donne pas la période : relevée dans le document.
PERIODES_RELEVEES = {
    "RAPPORT_STATISTIQUE_Mensuel_ESU_Novembre.pdf": "2024-11",
    "idps4.xlsx": "plusieurs dates (colonne date)",
}


def periode(nom_fichier: str, defaut: str = "") -> str:
    if nom_fichier in PERIODES_RELEVEES:
        return PERIODES_RELEVEES[nom_fichier]
    texte = _sans_accent(nom_fichier)
    for motif, mise_en_forme in _MOTIFS:
        if (trouve := re.search(motif, texte)) is not None:
            return mise_en_forme(trouve)
    return defaut
