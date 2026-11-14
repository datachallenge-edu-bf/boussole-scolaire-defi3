"""Étape 01 de Boussole Scolaire : collecte des données brutes.

Les sources sont déclarées dans ``sources.json``. Pour chacune, les lignes utiles
des CSV du Data Pack (ou les feuilles de la base principale) sont copiées sans
modification dans ``donnees/brutes/<source>.csv``, chaque ligne portant son
fichier d'origine et sa période. La collecte produit aussi :

- ``_registre.csv`` : une ligne par fichier utilisé (pages, lignes, empreintes, origine) ;
- ``_inventaire.csv`` : tous les fichiers remis par les organisateurs ;
- ``_bilan.csv`` : pour chaque fichier source, retenu (et par quelles sources) ou écarté (et pourquoi) ;
- ``_couverture.csv`` : pages trouvées par fichier pour les sources sélectives.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

from ..chemins import LIEUX
from .pages import decouper_en_pages, selecteur
from .tracabilite import original_du_csv, origine, periode, sha256

DECLARATIONS = Path(__file__).with_name("sources.json")
FORMAT_CSV = {"sep": ";", "encoding": "utf-8-sig", "index": False}


def lire_csv(chemin: Path) -> pd.DataFrame:
    return pd.read_csv(chemin, sep=";", dtype=str, encoding="utf-8-sig", keep_default_na=False)


def ecrire_csv(table: pd.DataFrame, chemin: Path) -> Path:
    chemin = LIEUX.autoriser(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(chemin, **FORMAT_CSV)
    return chemin


@dataclass
class Source:
    id: str
    intitule: str
    theme: str
    niveau: str
    depot: str
    usage: str
    fichiers: list[str] = field(default_factory=list)
    selection: dict = field(default_factory=lambda: {"type": "tout"})
    exclure_fichiers: str | None = None
    periode: str = ""
    classeur: str | None = None
    annuaires: bool = False


def charger_declarations() -> tuple[list[Source], list[dict]]:
    contenu = json.loads(DECLARATIONS.read_text(encoding="utf-8"))
    sources = []
    for brut in contenu["sources"]:
        source = Source(**{k: v for k, v in brut.items() if k in Source.__dataclass_fields__})
        if source.annuaires:
            source.fichiers = list(contenu["annuaires_primaire"])
        sources.append(source)
    return sources, contenu["ecartes"]


class Collecte:
    """Exécute la collecte et conserve ses résultats en mémoire."""

    def __init__(self) -> None:
        self.sources, self.ecartes = charger_declarations()
        self.date = date.today().isoformat()
        self.registre: list[dict] = []
        self.extraits: dict[str, pd.DataFrame] = {}
        self._documents: dict[Path, tuple[pd.DataFrame, list]] = {}

    # Fichiers d'une source.
    def _fichiers(self, source: Source) -> list[Path]:
        trouves = {p for motif in source.fichiers for p in LIEUX.csv_pack.glob(motif)}
        if source.exclure_fichiers:
            trouves = {p for p in trouves if not re.search(source.exclure_fichiers, p.name)}
        return sorted(trouves)

    def _noter(self, source: Source, original: Path | None, csv: Path | None, pages: list[int] | None,
               lignes: int, per: str) -> None:
        self.registre.append({
            "source": source.id, "intitule": source.intitule, "theme": source.theme, "niveau": source.niveau,
            "fichier_origine": original.name if original else (csv.name if csv else ""),
            "chemin_origine": original.relative_to(LIEUX.organisateurs).as_posix() if original else "",
            "csv_pack": csv.relative_to(LIEUX.csv_pack).as_posix() if csv else "",
            "periode": per,
            "selection": json.dumps(source.selection, ensure_ascii=False),
            "pages": "toutes" if pages is None else _plages(pages),
            "nb_pages": "" if pages is None else len(pages),
            "nb_lignes": lignes,
            "sha256_origine": sha256(original) if original else "",
            "sha256_csv_pack": sha256(csv) if csv else "",
            **origine(original.name if original else ""),
            "date_collecte": self.date, "usage": source.usage,
        })

    def _document(self, csv: Path):
        """CSV lu et découpé en pages une seule fois, même si plusieurs sources l'utilisent."""
        if csv not in self._documents:
            brut = lire_csv(csv)
            self._documents[csv] = (brut, decouper_en_pages(brut) if "page" in brut.columns else [])
        return self._documents[csv]

    def extraire(self, source: Source) -> pd.DataFrame:
        if source.classeur == "base_principale":
            return self._extraire_classeur(source)
        regle = selecteur(source.selection)
        morceaux = []
        for csv in self._fichiers(source):
            brut, document = self._document(csv)
            pages = None if regle is None else regle.pages(document)
            garde = brut if pages is None else brut[pd.to_numeric(brut["page"], errors="coerce").isin(pages)]
            original = original_du_csv(csv)
            per = periode(original.name if original else csv.name, source.periode)
            morceaux.append(garde.assign(origine_fichier=original.name if original else csv.name,
                                         origine_csv_pack=csv.relative_to(LIEUX.csv_pack).as_posix(),
                                         origine_periode=per))
            self._noter(source, original, csv, pages, len(garde), per)
        if not morceaux:
            return pd.DataFrame()
        table = pd.concat(morceaux, ignore_index=True, sort=False).fillna("")
        return table[_ordre(table.columns)]

    def _extraire_classeur(self, source: Source) -> pd.DataFrame:
        chemin = LIEUX.base_principale
        classeur = load_workbook(chemin, read_only=True, data_only=True)
        feuilles = []
        for feuille in classeur.worksheets:
            valeurs = [["" if v is None else str(v) for v in rang] for rang in feuille.iter_rows(values_only=True)]
            largeur = max((len(v) for v in valeurs), default=0)
            cadre = pd.DataFrame([v + [""] * (largeur - len(v)) for v in valeurs],
                                 columns=[f"col{i + 1}" for i in range(largeur)])
            cadre.insert(0, "rang", range(1, len(cadre) + 1))
            cadre.insert(0, "feuille", feuille.title)
            feuilles.append(cadre)
        classeur.close()
        table = pd.concat(feuilles, ignore_index=True).fillna("")
        table = table.assign(origine_fichier=chemin.name, origine_csv_pack="", origine_periode="2015-2025")
        self._noter(source, chemin, None, None, len(table), "2015-2025")
        self.registre[-1].update({"producteur": "DGESS / MEBAPLN",
                                  "description_source": "Base principale remise dans l'espace challenge"})
        return table[_ordre(table.columns)]

    def executer(self) -> None:
        for source in self.sources:
            self.extraits[source.id] = self.extraire(source)

    # Tables de contrôle.
    def table_registre(self) -> pd.DataFrame:
        return pd.DataFrame(self.registre)

    def inventaire(self) -> pd.DataFrame:
        lignes = []
        for chemin in LIEUX.fichiers_remis():
            dans_pack = LIEUX.csv_pack in chemin.parents
            ligne = {"chemin": chemin.relative_to(LIEUX.organisateurs).as_posix(),
                     "format": chemin.suffix.lower().lstrip("."),
                     "nature": "extraction CSV du pack" if dans_pack else "fichier source",
                     "taille_ko": round(chemin.stat().st_size / 1024, 1), "sha256": sha256(chemin),
                     **origine(chemin.name)}
            if chemin.suffix.lower() == ".csv":
                ligne["nb_lignes"], ligne["nb_colonnes"] = lire_csv(chemin).shape
            lignes.append(ligne)
        return pd.DataFrame(lignes)

    def bilan(self, inventaire: pd.DataFrame) -> pd.DataFrame:
        registre = self.table_registre()
        utilisations = registre[registre["chemin_origine"] != ""].groupby("chemin_origine")["source"].agg(
            lambda s: ", ".join(sorted(set(s))))
        lignes = []
        for fichier in inventaire[inventaire["nature"] == "fichier source"].itertuples():
            if fichier.chemin in utilisations.index:
                lignes.append({"chemin": fichier.chemin, "statut": "retenu",
                               "sources": utilisations[fichier.chemin], "motif": ""})
                continue
            motif = next((e["motif"] for e in self.ecartes if re.search(e["chemin"], fichier.chemin)), "")
            lignes.append({"chemin": fichier.chemin, "statut": "écarté" if motif else "à examiner",
                           "sources": "", "motif": motif})
        return pd.DataFrame(lignes)

    def couverture(self) -> pd.DataFrame:
        registre = self.table_registre()
        selectives = registre[registre["pages"] != "toutes"].copy()
        selectives["alerte"] = selectives["nb_lignes"].astype(int).eq(0).map(
            {True: "aucune page trouvée", False: ""})
        return selectives[["source", "fichier_origine", "periode", "pages", "nb_pages", "nb_lignes", "alerte"]]

    def ecrire(self, avec_inventaire: bool = True) -> dict[str, pd.DataFrame]:
        sortie = LIEUX.brutes
        for identifiant, table in self.extraits.items():
            if not table.empty:
                ecrire_csv(table, sortie / f"{identifiant}.csv")
        resultats = {"registre": self.table_registre(), "couverture": self.couverture()}
        ecrire_csv(resultats["registre"], sortie / "_registre.csv")
        ecrire_csv(resultats["couverture"], sortie / "_couverture.csv")
        if avec_inventaire:
            resultats["inventaire"] = self.inventaire()
            resultats["bilan"] = self.bilan(resultats["inventaire"])
            ecrire_csv(resultats["inventaire"], sortie / "_inventaire.csv")
            ecrire_csv(resultats["bilan"], sortie / "_bilan.csv")
        return resultats


def _ordre(colonnes) -> list[str]:
    colonnes = list(colonnes)
    tete = [c for c in ("origine_fichier", "origine_csv_pack", "origine_periode", "feuille", "rang",
                        "document", "page", "ligne", "methode", "nb_cellules") if c in colonnes]
    numerotees = sorted((c for c in colonnes if re.fullmatch(r"c(ol)?\d+", c)),
                        key=lambda c: (c.startswith("col"), int(re.sub(r"\D", "", c))))
    return tete + numerotees + [c for c in colonnes if c not in tete and c not in numerotees]


def _plages(pages: list[int]) -> str:
    morceaux, debut = [], None
    for i, p in enumerate(pages):
        if debut is None:
            debut = p
        if i + 1 == len(pages) or pages[i + 1] != p + 1:
            morceaux.append(str(debut) if debut == p else f"{debut}-{p}")
            debut = None
    return ", ".join(morceaux)


def collecter(avec_inventaire: bool = True) -> dict[str, pd.DataFrame]:
    """Point d'entrée : exécute la collecte et écrit ses sorties."""
    collecte = Collecte()
    collecte.executer()
    return collecte.ecrire(avec_inventaire)
