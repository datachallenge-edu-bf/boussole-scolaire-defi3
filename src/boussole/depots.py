"""Mise en forme des dépôts selon la convention du challenge.

Nom d'un fichier déposé : EQUIPE_ETAPE_DEFI_ROLE_description_vN.extension,
sans espace ni accent. Chaque dépôt est accompagné d'un LISEZ-MOI.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from shutil import copy2

import pandas as pd

from .chemins import CODE_DEFI, CODE_EQUIPE, LIEUX

NOMS_ETAPES = {1: "01-collecte", 2: "02-nettoyage", 3: "03-transformation", 4: "04-analyse", 5: "05-interpretation"}
ROLES = ("engineer", "architect", "analyst", "scientist")


def en_minuscules_simples(texte: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode().lower()
    return "-".join(re.findall(r"[a-z0-9]+", ascii_))


@dataclass(frozen=True)
class Piece:
    """Un fichier à déposer."""

    chemin: Path
    role: str
    description: str
    contenu: str

    def nom(self, etape: int, version: int) -> str:
        if self.role not in ROLES:
            raise ValueError(f"Rôle inconnu : {self.role}")
        extension = self.chemin.suffix.lstrip(".")
        return (f"{CODE_EQUIPE}_{NOMS_ETAPES[etape]}_{CODE_DEFI}_{self.role}_"
                f"{en_minuscules_simples(self.description)}_v{version}.{extension}")


def deposer(etape: int, pieces: list[Piece], presentation: list[str], version: int = 1) -> pd.DataFrame:
    """Copie les pièces dans depots/<étape>, remplace les fichiers précédents et écrit le LISEZ-MOI."""
    dossier = LIEUX.autoriser(LIEUX.depots / NOMS_ETAPES[etape])
    dossier.mkdir(parents=True, exist_ok=True)
    for ancien in dossier.iterdir():
        if ancien.is_file():
            ancien.unlink()

    lignes = []
    for piece in pieces:
        if piece.chemin.exists():
            nom = piece.nom(etape, version)
            copy2(piece.chemin, dossier / nom)
            lignes.append({"fichier": nom, "role": piece.role, "contenu": piece.contenu})
    table = pd.DataFrame(lignes)

    lisez_moi = Piece(Path("lisez-moi.txt"), "engineer", "lisez-moi", "")
    texte = presentation + ["", "FICHIERS DÉPOSÉS", ""]
    texte += [f"{l.fichier}\n    {l.contenu}" for l in table.itertuples()]
    (dossier / lisez_moi.nom(etape, version)).write_text("\n".join(texte) + "\n", encoding="utf-8")
    return table


def deposer_collecte(version: int = 1) -> pd.DataFrame:
    """Dépôt de l'étape 01 de Boussole Scolaire."""
    brutes = LIEUX.brutes
    declarations = json.loads((Path(__file__).parent / "collecte" / "sources.json").read_text(encoding="utf-8"))
    pieces = [
        Piece(brutes / "_registre.csv", "engineer", "registre-des-sources",
              "Une ligne par fichier utilisé : pages extraites, nombre de lignes, empreintes SHA-256, producteur, "
              "adresse d'origine, date de collecte."),
        Piece(brutes / "_bilan.csv", "engineer", "bilan-sources-retenues-ecartees",
              "Chaque fichier remis par les organisateurs : retenu (par quelles sources) ou écarté (avec le motif)."),
        Piece(brutes / "_inventaire.csv", "engineer", "inventaire-fichiers-organisateurs",
              "Tous les fichiers remis : format, taille, empreinte, dimensions des CSV, origine."),
        Piece(brutes / "_couverture.csv", "engineer", "controle-couverture-pages",
              "Pages trouvées par fichier pour chaque source sélective, avec alerte si aucune page n'est trouvée."),
    ]
    for source in declarations["sources"]:
        pieces.append(Piece(brutes / f"{source['id']}.csv", "engineer", source["depot"],
                            f"{source['intitule']}. Usage : {source['usage']}."))
    presentation = [
        "BOUSSOLE SCOLAIRE - DÉPÔT 01 : COLLECTE",
        "Défi 3 : optimisation de la répartition des infrastructures et du personnel enseignant",
        "",
        "Ces fichiers sont des copies brutes des données remises par les organisateurs (base principale",
        "DGESS et Data Pack DCB 2026) : aucune valeur n'est modifiée à ce stade. Chaque ligne indique son",
        "fichier d'origine (origine_fichier), son extraction CSV dans le pack (origine_csv_pack), sa",
        "période (origine_periode) et, pour les PDF, sa page et sa ligne.",
        "",
        "Les sources sont choisies pour le défi 3 : offre (enseignants, écoles, salles, état des salles,",
        "équipements, logements de maître), demande (effectifs, nouveaux entrants, projections de",
        "population, localités), contexte sécuritaire (écoles fermées et rouvertes, déplacés internes)",
        "et référentiels géographiques.",
        "",
        "Séparateur « ; », encodage UTF-8 ; les nombres gardent leur forme d'origine.",
        "Relancer : python -m boussole.collecte (dossier src dans le PYTHONPATH) ou notebooks/01_collecte.ipynb.",
    ]
    return deposer(1, pieces, presentation, version)


def deposer_nettoyage(version: int = 1) -> pd.DataFrame:
    """Dépôt de l'étape 02 de Boussole Scolaire : base SQLite, tables propres, métadonnées, contrôles."""
    base = LIEUX.projet / "donnees" / "base"
    pieces = [
        Piece(base / "boussole.db", "architect", "base-boussole-sqlite",
              "Base complète au format SQLite : territoires, offre scolaire, état des salles, journal, "
              "contrôles et métadonnées."),
        Piece(base / "_tables.csv", "architect", "metadonnees-tables",
              "Une ligne par table : description, grain, clé, sources, nombre de lignes et de colonnes."),
        Piece(base / "_variables.csv", "architect", "metadonnees-dictionnaire-variables",
              "Chaque variable de chaque table : type, unité, description."),
        Piece(base / "territoire_commune.csv", "engineer", "territoires-communes-deux-decoupages",
              "351 communes avec leurs codes et rattachements dans le découpage 2025 et l'ancien."),
        Piece(base / "territoire_province_ancienne.csv", "engineer", "territoires-provinces-ancien-decoupage",
              "45 provinces de l'ancien découpage, avec les provinces de 2025 qui en sont issues."),
        Piece(base / "territoire_region_ancienne.csv", "engineer", "territoires-regions-ancien-decoupage",
              "13 régions de l'ancien découpage."),
        Piece(base / "offre_province.csv", "engineer", "offre-ecoles-salles-maitres-eleves-province-2017-2025",
              "Écoles, salles, groupes pédagogiques, maîtres et élèves par province, édition et statut, avec "
              "les élèves par maître, par salle et par groupe pédagogique."),
        Piece(base / "etat_salles_province.csv", "engineer", "etat-murs-toitures-salles-province-2017-2025",
              "Nature et état des murs et des toitures des salles de classe, part des salles et des toitures "
              "précaires, par province, édition et statut."),
        Piece(base / "effectifs_niveau_province.csv", "engineer", "effectifs-redoublants-classe-sexe-province-2017-2025",
              "Élèves et redoublants par province, classe (CP1 à CM2) et sexe ; chaque année est lue dans sa "
              "propre édition de l'annuaire."),
        Piece(base / "enseignants_province.csv", "engineer", "enseignants-corps-fonction-province-2017-2025",
              "Enseignants par province, édition, statut et sexe : corps, fonction (directeur, titulaire, "
              "suppléant), enseignants tenant une classe, classes simples, multigrades et à double flux."),
        Piece(base / "population_projetee.csv", "engineer", "population-projetee-age-sexe-province-region-2020-2035",
              "Population projetée par groupe d'âges et sexe, par région et province, 2020 à 2035 ; le groupe "
              "6-11 ans donne la population d'âge scolaire du primaire."),
        Piece(base / "communes_primaire.csv", "engineer", "ecoles-salles-paillotes-eleves-enseignants-commune-2014-2024",
              "Indicateurs du primaire par commune (10 régions sur 13), d'après les annuaires régionaux de l'INSD : "
              "écoles, salles, salles sous paillote, élèves et enseignants par sexe et par statut."),
        Piece(base / "ecoles_crise_province.csv", "engineer", "ecoles-fermees-rouvertes-delocalisees-province-esu",
              "Écoles primaires fermées, rouvertes ou délocalisées, élèves et enseignants touchés, par province et "
              "rapport mensuel ; tableau_fiable indique les tableaux dont la somme retrouve le total publié."),
        Piece(base / "deplaces_commune.csv", "engineer", "deplaces-internes-commune-2019-2023",
              "Personnes déplacées internes et enfants déplacés par commune et date de situation, 2019 à 2023."),
        Piece(base / "controles.csv", "engineer", "controles-automatiques",
              "Contrôles : complétude, public + privé = total, somme des provinces = total régional, ratios "
              "recalculés = ratios publiés, cohérence entre tableaux, métadonnées."),
        Piece(base / "journal_rapprochements.csv", "engineer", "journal-rapprochements-noms",
              "Noms lus dans les tableaux et rapprochés d'un code autrement que par égalité exacte."),
        Piece(base / "journal_signalements.csv", "engineer", "journal-lignes-signalees",
              "Lignes de tableau écartées ou à vérifier, avec leur motif."),
    ]
    presentation = [
        "BOUSSOLE SCOLAIRE - DÉPÔT 02 : NETTOYAGE",
        "Défi 3 : optimisation de la répartition des infrastructures et du personnel enseignant",
        "",
        "Base Boussole construite à partir des copies brutes de l'étape 01. Les annuaires de la DGESS",
        "suivent l'ancien découpage (13 régions, 45 provinces) ; la table des communes relie ce découpage",
        "à celui de juillet 2025 (17 régions, 47 provinces).",
        "",
        "Contrôles satisfaits : 45 provinces par édition (la Komandjari, sans aucune école ouverte, est",
        "absente en 2022-2023) ; public + privé = total ; somme des provinces = total régional publié ;",
        "élèves par maître recalculés = valeurs publiées ; élèves par niveau = élèves du tableau principal ;",
        "somme des corps et des fonctions = total des enseignants ; enseignants tenant une classe = maîtres",
        "du tableau principal ; toutes les variables sont décrites.",
        "",
        "Séparateur « ; », encodage UTF-8, point décimal.",
        "Relancer : python -m boussole.nettoyage (dossier src dans le PYTHONPATH) ou notebooks/02_nettoyage.ipynb.",
    ]
    return deposer(2, pieces, presentation, version)
