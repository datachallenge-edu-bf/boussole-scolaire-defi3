"""Repérage des pages utiles dans les CSV extraits des PDF.

Chaque page d'un CSV issu d'un PDF est réduite à son texte en majuscules et sans
accent. Deux sélecteurs en tirent les pages à retenir :

- ``SelecteurSection`` (annuaires DGESS) : le titre de section d'une page est la
  ligne de tête numérotée en chiffres romains (« V.2 REPARTITION DES ECOLES… »)
  et écrite en majuscules, ce qui écarte la table des matières, rédigée en
  minuscules. La page est retenue si ce titre contient tous les mots-clés.
- ``SelecteurTableaux`` (annuaires INSD et autres) : la page est retenue si un
  titre de tableau (« Tableau … ») contient les mots-clés demandés ; les pages de
  suite sans titre peuvent être rattachées au tableau qui précède.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

import pandas as pd

_NUMERO_SECTION = re.compile(r"^[IVX]+\s?\.\s?\d")


def majuscules_sans_accent(texte: str) -> str:
    sans_accent = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", " ", sans_accent.upper()).strip()


@dataclass
class Page:
    numero: int
    lignes: list[tuple[int, str]]  # (numéro de ligne, texte brut)

    def titre_section(self, lignes_de_tete: int = 5) -> str:
        for numero, texte in self.lignes:
            if numero > lignes_de_tete:
                break
            lettres = [c for c in texte if c.isalpha()]
            # Seuil à 0,5 : certains titres mêlent majuscules et minuscules (« V.3 TAILLE DES écoles »),
            # alors que les entrées de la table des matières sont presque entièrement en minuscules.
            en_majuscules = lettres and sum(c.isupper() for c in lettres) / len(lettres) > 0.5
            if _NUMERO_SECTION.match(texte) and en_majuscules:
                return majuscules_sans_accent(texte)
        return ""

    def titres_tableaux(self) -> list[str]:
        return [majuscules_sans_accent(t) for _, t in self.lignes
                if re.match(r"^\s*Tableau\b", t, flags=re.IGNORECASE) and "...." not in t and "…" not in t]

    def tete(self, lignes_de_tete: int = 5) -> str:
        return majuscules_sans_accent(" ".join(t for n, t in self.lignes if n <= lignes_de_tete))


def decouper_en_pages(extrait: pd.DataFrame) -> list[Page]:
    cellules = sorted((c for c in extrait.columns if re.fullmatch(r"c\d+", c)), key=lambda c: int(c[1:]))
    textes = extrait[cellules].fillna("").agg(" ".join, axis=1).str.replace(r"\s+", " ", regex=True).str.strip()
    cadre = pd.DataFrame({"page": pd.to_numeric(extrait["page"], errors="coerce"),
                          "ligne": pd.to_numeric(extrait["ligne"], errors="coerce"), "texte": textes})
    cadre = cadre.dropna(subset=["page"]).sort_values(["page", "ligne"])
    return [Page(int(p), list(zip(g["ligne"].astype(int), g["texte"]))) for p, g in cadre.groupby("page")]


@dataclass
class SelecteurSection:
    cles: list[str]
    exclure: list[str] = field(default_factory=list)

    def pages(self, document: list[Page]) -> list[int]:
        retenues = []
        for page in document:
            titre = page.titre_section()
            if titre and all(cle in titre for cle in self.cles) \
                    and not any(mot in page.tete() for mot in self.exclure):
                retenues.append(page.numero)
        return retenues


@dataclass
class SelecteurTableaux:
    tous: list[str] = field(default_factory=list)
    un_de: list[str] = field(default_factory=list)
    exclure: list[str] = field(default_factory=list)
    suite: bool = False

    def _convient(self, titre: str) -> bool:
        return (all(m in titre for m in self.tous)
                and (not self.un_de or any(m in titre for m in self.un_de))
                and not any(m in titre for m in self.exclure))

    def pages(self, document: list[Page]) -> list[int]:
        retenues, en_cours = [], False
        for page in document:
            titres = page.titres_tableaux()
            if titres:
                en_cours = any(self._convient(t) for t in titres)
                if en_cours:
                    retenues.append(page.numero)
            elif en_cours and self.suite:
                retenues.append(page.numero)
        return retenues


def selecteur(regle: dict):
    if regle["type"] == "section":
        return SelecteurSection(regle["cles"], regle.get("exclure", []))
    if regle["type"] == "tableaux":
        return SelecteurTableaux(regle.get("tous", []), regle.get("un_de", []), regle.get("exclure", []),
                                 regle.get("suite", False))
    return None  # le fichier entier
