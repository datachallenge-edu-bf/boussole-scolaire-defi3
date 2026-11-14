"""Nomenclature des territoires et reconnaissance des noms.

Les annuaires de la DGESS suivent l'ancien découpage (13 régions, 45 provinces).
Le référentiel COD-AB donne, pour chacune des 351 communes, son code actuel et son
ancien code ; les noms des anciennes provinces et régions viennent du fichier des
écoles OpenStreetMap, qui suit l'ancien découpage.

Un nom lu dans un tableau est rapproché d'un code en trois temps : égalité exacte
après normalisation, égalité après retrait d'un article en tête (« LES BALE »),
puis plus proche orthographe si la similarité dépasse un seuil. Chaque
rapprochement non exact est conservé pour le journal.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import pandas as pd

from ..chemins import LIEUX

SEUIL_SIMILARITE = 0.85
TOTAUX_NATIONAUX = {"NATIONAL", "BURKINA FASO", "TOTAL NATIONAL", "ENSEMBLE", "TOTAL GENERAL"}


def cle(texte: str) -> str:
    """Majuscules sans accent ; tirets, apostrophes et espaces multiples ramenés à une espace."""
    texte = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode().upper()
    return " ".join(re.findall(r"[A-Z0-9]+", texte))


def _lire_brut(nom: str) -> pd.DataFrame:
    return pd.read_csv(LIEUX.brutes / f"{nom}.csv", sep=";", dtype=str, encoding="utf-8-sig", keep_default_na=False)


def _en_tete_dans_premiere_ligne(table: pd.DataFrame) -> pd.DataFrame:
    colonnes = [c for c in table.columns if re.fullmatch(r"col\d+", c)]
    corps = table.iloc[1:][colonnes].copy()
    corps.columns = [table.iloc[0][c] for c in colonnes]
    return corps.loc[:, [c for c in corps.columns if c]]


@dataclass
class Nomenclature:
    communes: pd.DataFrame
    provinces: pd.DataFrame
    regions: pd.DataFrame
    rapprochements: list[dict] = field(default_factory=list)

    @classmethod
    def construire(cls) -> "Nomenclature":
        codab = _en_tete_dans_premiere_ligne(_lire_brut("codab_communes"))
        osm = _lire_brut("ecoles_osm")
        noms_provinces = (osm.loc[osm["adm2_pcode"] != "", ["adm2_pcode", "adm2_name"]]
                          .drop_duplicates("adm2_pcode").set_index("adm2_pcode")["adm2_name"])
        noms_regions = (osm.loc[osm["adm1_pcode"] != "", ["adm1_pcode", "adm1_name"]]
                        .drop_duplicates("adm1_pcode").set_index("adm1_pcode")["adm1_name"])

        communes = pd.DataFrame({
            "commune_code": codab["adm3_pcode"], "commune": codab["adm3_name"],
            "province_code": codab["adm2_pcode"], "province": codab["adm2_name"],
            "region_code": codab["adm1_pcode"], "region": codab["adm1_name"],
            "commune_code_ancien": codab["adm3_pcode_old"],
            "province_code_ancien": codab["adm3_pcode_old"].str[:6],
            "region_code_ancien": codab["adm3_pcode_old"].str[:4],
            "superficie_km2": pd.to_numeric(codab["area_sqkm"], errors="coerce"),
        })
        communes["province_ancienne"] = communes["province_code_ancien"].map(noms_provinces)
        communes["region_ancienne"] = communes["region_code_ancien"].map(noms_regions)

        provinces = (communes.groupby(["province_code_ancien", "province_ancienne", "region_code_ancien",
                                       "region_ancienne"], as_index=False)
                     .agg(communes=("commune_code", "count"), superficie_km2=("superficie_km2", "sum"),
                          provinces_2025=("province_code", lambda s: ", ".join(sorted(set(s))))))
        regions = (communes.groupby(["region_code_ancien", "region_ancienne"], as_index=False)
                   .agg(provinces=("province_code_ancien", "nunique"), communes=("commune_code", "count")))
        return cls(communes, provinces, regions)

    def _candidats(self) -> dict[str, tuple[str, str]]:
        table = {cle(n): (c, "province") for c, n in zip(self.provinces["province_code_ancien"],
                                                       self.provinces["province_ancienne"])}
        table.update({cle(n): (c, "region") for c, n in zip(self.regions["region_code_ancien"],
                                                          self.regions["region_ancienne"])})
        return table

    def reconnaitre(self, nom: str, contexte: str = "") -> tuple[str, str] | None:
        """Code et niveau (province, region, pays) d'un nom de l'ancien découpage, ou None."""
        k = cle(nom)
        if not k:
            return None
        if k in TOTAUX_NATIONAUX:
            return ("BF", "pays")
        candidats = self._candidats()
        if k in candidats:
            return candidats[k]
        sans_article = re.sub(r"^(LES|LE|LA|L) ", "", k)
        if sans_article in candidats:
            self._noter(nom, candidats[sans_article], "article retiré", 1.0, contexte)
            return candidats[sans_article]
        meilleur, score = max(((c, SequenceMatcher(None, sans_article, c).ratio()) for c in candidats),
                              key=lambda x: x[1])
        if score >= SEUIL_SIMILARITE:
            self._noter(nom, candidats[meilleur], f"orthographe voisine de « {meilleur} »", score, contexte)
            return candidats[meilleur]
        return None

    def _noter(self, nom: str, resultat: tuple[str, str], regle: str, score: float, contexte: str) -> None:
        self.rapprochements.append({"nom_lu": nom, "code": resultat[0], "niveau": resultat[1], "regle": regle,
                                    "similarite": round(score, 3), "contexte": contexte})
