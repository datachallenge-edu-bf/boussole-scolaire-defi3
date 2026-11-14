"""Emplacements du projet et des données des organisateurs.

Les données des organisateurs se trouvent dans un dossier voisin du projet
(``Competition_EducationBurkina``) ou à l'emplacement indiqué par la variable
d'environnement ``BOUSSOLE_DONNEES``. Elles ne sont jamais modifiées.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Emplacements:
    projet: Path = field(default_factory=lambda: Path(__file__).resolve().parents[2])

    @property
    def organisateurs(self) -> Path:
        """Dossier qui contient les données remises (et, à côté, les projets des équipes)."""
        return Path(os.environ.get("BOUSSOLE_DONNEES", self.projet.parent)).resolve()

    @property
    def data_pack(self) -> Path:
        return self.organisateurs / "DataPack_DCB_2026"

    @property
    def csv_pack(self) -> Path:
        return self.data_pack / "data"

    @property
    def manifeste(self) -> Path:
        return self.data_pack / "00_Documentation_et_Referentiels" / "manifeste_telechargements.csv"

    @property
    def base_principale(self) -> Path:
        return self.organisateurs / "DONNEES_STATISTQUES_ PRESCOLAIRE ET PRIMAIRE_2016_2025_DCB.xlsx"

    @property
    def brutes(self) -> Path:
        return self.projet / "donnees" / "brutes"

    @property
    def depots(self) -> Path:
        return self.projet / "depots"

    @property
    def document_challenge(self) -> Path:
        return self.organisateurs / "Document_du_challenge_Data_Challenge_Burkina.pdf"

    @property
    def remis(self) -> tuple[Path, ...]:
        """Les trois éléments remis par les organisateurs."""
        return (self.data_pack, self.base_principale, self.document_challenge)

    def fichiers_remis(self) -> list[Path]:
        fichiers = []
        for element in self.remis:
            fichiers += [p for p in element.rglob("*") if p.is_file()] if element.is_dir() else [element]
        return sorted(fichiers)

    def autoriser(self, cible: Path) -> Path:
        """Renvoie le chemin s'il ne touche aucun élément remis par les organisateurs, sinon lève une erreur."""
        cible = Path(cible).resolve()
        for protege in (p.resolve() for p in self.remis):
            if cible == protege or protege in cible.parents:
                raise PermissionError(f"Données des organisateurs en lecture seule : {cible}")
        return cible


LIEUX = Emplacements()

# Convention de nommage des dépôts du challenge.
CODE_EQUIPE = os.environ.get("BOUSSOLE_EQUIPE", "EXX")
CODE_DEFI = "D3"
