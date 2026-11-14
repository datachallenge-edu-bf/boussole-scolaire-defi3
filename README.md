# Boussole Scolaire : Data Challenge Burkina 2026, défi 3

Prévoir les besoins et répartir au plus juste les enseignants et les salles de classe, de la province à l'école.

Projet de l'équipe du défi 3, indépendant du projet du défi 1 : code, collecte, nettoyage, modèles, dépôts et documentation propres.

## Organisation

Le projet est rangé dans le dossier des données remises par les organisateurs, qu'il lit sans jamais les modifier.

```
Competition_EducationBurkina/
├── DataPack_DCB_2026/, base principale, document du challenge   (organisateurs, lecture seule)
├── defi1_sentinelle/               projet du défi 1 (autre équipe)
└── defi3_boussole/                 ce projet
```

## Contenu

| Élément | Contenu |
|---|---|
| `src/boussole/` | Code : `chemins.py` (emplacements, protection des données), `collecte/` (étape 01), `depots.py` |
| `src/boussole/collecte/sources.json` | Déclaration des sources retenues et des motifs d'exclusion |
| `notebooks/` | Un notebook par étape, enregistré avec ses résultats |
| `donnees/brutes/` | Copies brutes de la collecte, registre, inventaire, bilan, couverture |
| `donnees/base/` | Base nettoyée `boussole.db` (SQLite) et ses tables en CSV, dont les métadonnées `_tables` et `_variables` |
| `docs/methodologie/` | Méthodologie de collecte et de nettoyage (LaTeX, même gabarit que la note d'intention) |
| `docs/note_intention/`, `prototype/` | Note d'intention du défi 3 et prototype HTML |
| `depots/` | Fichiers à déposer, nommés `EQUIPE_ETAPE_D3_ROLE_description_vN` |

## Démarrer après un clonage

Le dépôt ne contient ni les données des organisateurs (réservées au concours), ni les données produites par la chaîne : elles se régénèrent en quelques minutes.

1. Récupérer dans l'espace du challenge le Data Pack (`DataPack_DCB_2026/`) et la base principale (`DONNEES_STATISTQUES_ PRESCOLAIRE ET PRIMAIRE_2016_2025_DCB.xlsx`), et les placer dans un dossier `Competition_EducationBurkina/`.
2. Cloner le dépôt dans ce même dossier :
   ```powershell
   cd Competition_EducationBurkina
   git clone https://github.com/datachallenge-edu-bf/boussole-scolaire-defi3.git defi3_boussole
   ```
3. Installer l'environnement et relancer la chaîne (section suivante). Les dossiers `donnees/`, `depots/` et `sorties/` sont recréés à l'identique.

## Relancer

```powershell
pip install -r requirements.txt
$env:BOUSSOLE_EQUIPE = "E12"        # code de l'équipe du défi 3
$env:PYTHONPATH = "src"
python -m boussole.collecte          # étape 01 : collecte et dépôt
python -m boussole.nettoyage         # étape 02 : base SQLite donnees/base/boussole.db et dépôt
```

Si les données des organisateurs sont ailleurs que dans le dossier parent, indiquer leur emplacement par `$env:BOUSSOLE_DONNEES`.

## Données utiles d'après la note d'intention

| Besoin | Source dans le Data Pack | Niveau |
|---|---|---|
| Élèves, maîtres, salles, groupes pédagogiques | Annuaires DGESS du primaire, tableau I.1 et sections V à VI | Province |
| Salles sous paillote, état des salles | Annuaires DGESS, section VI.4 ; annuaires régionaux INSD | Province, commune |
| Effectifs par niveau et redoublants, historique | Annuaires DGESS, section VIII | Province |
| Écoles, salles, élèves, enseignants par commune | Annuaires statistiques régionaux INSD 2024 (10 régions sur 13) | Commune |
| Population d'âge scolaire, horizon 2030 | Projections INSD 2020-2035 ; fichier des localités du RGPH 2019 | Région, localité |
| Écoles fermées, rouvertes, délocalisées ; enseignants touchés | Rapports mensuels ST-ESU | Région, province |
| Élèves déplacés, pression d'accueil | Situations des déplacés internes (CONASUR) | Commune |
| Localisation des écoles, distances | Écoles OpenStreetMap ; limites COD-AB | Point, commune |

Non fournis, à traiter comme hypothèses explicites : fichier des enseignants (départs, mobilité), carte scolaire par école, coûts unitaires et postes ouverts.
