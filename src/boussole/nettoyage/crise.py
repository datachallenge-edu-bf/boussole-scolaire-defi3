"""Contexte sécuritaire : écoles fermées, rouvertes et délocalisées (ST-ESU) ; déplacés internes (CONASUR).

Rapports ST-ESU. Les tableaux « Situation des établissements fermés / rouverts /
délocalisés » sont découpés par ordre d'enseignement ; seul le primaire est retenu.
Une ligne donne, après le nom de la province (parfois précédé de celui de la région),
sept valeurs : établissements, élèves (filles, garçons, total), enseignants (femmes,
hommes, total). La ligne « TOTAL PRIMAIRE » de chaque tableau sert de contrôle : un
tableau n'est jugé fiable que si la somme de ses provinces la retrouve à 5 % près.

Déplacés internes. Seuls les fichiers qui donnent le P-code de la commune d'accueil
sont utilisés : aucune commune n'est rapprochée par son nom. Les fichiers détaillés
par site d'accueil sont additionnés par commune et par date de situation.
"""

from __future__ import annotations

import re

import pandas as pd

from .nomenclature import Nomenclature, cle
from .tableaux import Signalement, nombre

_SITUATION = re.compile(r"TABLEAU\s*\d+.*?(FERME|ROUVERT|REOUVERT|DELOCALIS)")
_ORDRES = {"PRESCOLAIRE": "prescolaire", "PRIMAIRE": "primaire", "POST PRIMAIRE": "post_primaire",
           "POST PRIMAIRE ET SECONDAIRE": "post_primaire", "SECONDAIRE": "secondaire"}
COLONNES_ESU = ["etablissements", "eleves_filles", "eleves_garcons", "eleves", "enseignants_femmes",
                "enseignants_hommes", "enseignants"]
SEUIL_FIABILITE = 0.05


def lire_esu(brut: pd.DataFrame, nomenclature: Nomenclature, signaler: Signalement) -> pd.DataFrame:
    cellules = sorted((c for c in brut.columns if re.fullmatch(r"c\d+", c)), key=lambda c: int(c[1:]))
    brut = brut.assign(_p=pd.to_numeric(brut["page"]), _l=pd.to_numeric(brut["ligne"]))
    provinces = set(nomenclature.provinces["province_code_ancien"])
    lignes, totaux = [], []

    for (fichier, mois), rapport in brut.sort_values(["_p", "_l"]).groupby(["origine_fichier", "origine_periode"]):
        situation, ordre = None, None
        for _, rang in rapport.iterrows():
            morceaux = [rang[c].strip() for c in cellules if rang[c].strip()]
            if not morceaux:
                continue
            k = cle(" ".join(morceaux))
            if (m := _SITUATION.search(k)) is not None:
                situation = {"FERME": "fermees", "ROUVERT": "rouvertes", "REOUVERT": "rouvertes",
                             "DELOCALIS": "delocalisees"}[m.group(1)]
                ordre = None
                continue
            if k in _ORDRES:
                ordre = _ORDRES[k]
                continue
            if situation is None or ordre != "primaire":
                continue

            valeurs = [float("nan") if cle(m) in {"NP", "ND"} else nombre(m) for m in morceaux]
            debut = next((i for i, v in enumerate(valeurs) if v is not None), None)
            if debut is None:
                continue
            libelles, chiffres = morceaux[:debut], valeurs[debut:]
            if k.startswith("TOTAL PRIMAIRE"):
                totaux.append({"mois": mois, "situation": situation, "fichier": fichier,
                               "etablissements_publie": chiffres[0] if chiffres else None,
                               "eleves_publie": chiffres[3] if len(chiffres) > 3 else None})
                ordre = None
                continue
            # L'entité est le dernier libellé reconnu comme province (le précédent est souvent la région).
            code = None
            for libelle in reversed(libelles):
                trouve = nomenclature.reconnaitre(libelle, f"ESU {mois}")
                if trouve and trouve[0] in provinces:
                    code = trouve[0]
                    break
            if code is None:
                continue
            if len(chiffres) != 7 or any(v is None for v in chiffres):
                signaler("esu", f"{len(chiffres)} valeurs au lieu de 7", fichier, rang["page"], rang["ligne"],
                         " ".join(morceaux))
                continue
            lignes.append({"mois": mois, "situation": situation, "code": code,
                           **dict(zip(COLONNES_ESU, chiffres)), "fichier": fichier, "page": rang["page"],
                           "lecture": rapport["methode"].iloc[0] if "methode" in rapport and rapport["methode"].iloc[0]
                           else "texte natif"})

    table = pd.DataFrame(lignes)
    if table.empty:
        return table
    table = table.drop_duplicates(["mois", "situation", "code", "fichier"])
    controle = table.groupby(["fichier", "mois", "situation"])[["etablissements", "eleves"]].sum().reset_index()
    controle = controle.merge(pd.DataFrame(totaux).drop_duplicates(["fichier", "situation"]),
                              on=["fichier", "mois", "situation"], how="left")
    ecart = pd.concat([
        (controle["etablissements"] / controle["etablissements_publie"] - 1).abs(),
        (controle["eleves"] / controle["eleves_publie"] - 1).abs(),
    ], axis=1).max(axis=1)
    controle["tableau_fiable"] = ecart.le(SEUIL_FIABILITE)
    table = table.merge(controle[["fichier", "situation", "tableau_fiable"]], on=["fichier", "situation"], how="left")
    table["tableau_fiable"] = table["tableau_fiable"].fillna(False).astype(bool)
    table["coherence_eleves"] = (table["eleves_filles"] + table["eleves_garcons"] - table["eleves"]).abs().le(1)
    return table


def lire_deplaces(brut: pd.DataFrame, nomenclature: Nomenclature, signaler: Signalement) -> pd.DataFrame:
    colonnes = sorted((c for c in brut.columns if re.fullmatch(r"col\d+", c)), key=lambda c: int(c[3:]))
    anciens = dict(zip(nomenclature.communes["commune_code_ancien"], nomenclature.communes["commune_code"]))
    actuels = set(nomenclature.communes["commune_code"])
    morceaux, dates_sans_code = [], set()

    for fichier, bloc in brut.groupby("origine_csv_pack", sort=False):
        bloc = bloc.reset_index(drop=True)
        entete = next((i for i in range(min(12, len(bloc)))
                       if any(re.search(r"(?i)admin\s*3\s*p?code|^admin3", bloc.at[i, c]) for c in colonnes)), None)
        if entete is None:
            continue  # fichier sans P-code de commune : écarté par construction
        noms = {c: cle(bloc.at[entete, c]) for c in colonnes}
        col_pcode = next(c for c, n in noms.items() if re.search(r"ADMIN 3 P ?CODE|^ADMIN3", n))
        col_total = next((c for c, n in noms.items() if re.search(r"TOTAL INDIVIDUS|NOMBRE TOTAL DE PDI|TOTAL PDI", n)), None)
        col_enfants = next((c for c, n in noms.items() if n == "TOTAL ENFANTS"), None)
        col_date = next((c for c, n in noms.items() if n.startswith("DATE")), None)
        if col_total is None:
            continue
        donnees = bloc.iloc[entete + 1:]
        donnees = donnees[~donnees[col_pcode].str.startswith("#")]
        codes = donnees[col_pcode].str.strip().map(lambda p: p if p in actuels else anciens.get(p))
        table = pd.DataFrame({
            "date_situation": (donnees[col_date].str[:10] if col_date else bloc["origine_periode"].iloc[0]),
            "commune_code": codes,
            "deplaces": donnees[col_total].map(nombre),
            "enfants_deplaces": donnees[col_enfants].map(nombre) if col_enfants else None,
            "fichier": fichier,
        })
        # Lignes sans P-code : lignes modèles vides, blocs récapitulatifs sans date, ou situations anciennes
        # données seulement par commune. Leurs dates sont retenues pour vérifier plus bas qu'un autre fichier,
        # doté de P-codes, les couvre.
        datees = table["date_situation"].astype(str).str.match(r"20\d{2}-\d{2}-\d{2}")
        sans_code = table["commune_code"].isna() & table["deplaces"].fillna(0).gt(0) & datees
        dates_sans_code.update(table.loc[sans_code, "date_situation"])
        morceaux.append(table[table["commune_code"].notna() & table["deplaces"].notna() & datees])

    detail = pd.concat(morceaux, ignore_index=True)
    for date in sorted(dates_sans_code - set(detail["date_situation"])):
        signaler("deplaces", "situation donnée seulement sans P-code de commune : date absente de la série",
                 "", "", "", date)
    # Une même date peut figurer dans plusieurs fichiers : la version « après nettoyage » du CONASUR est préférée.
    detail["rang_fichier"] = (~detail["fichier"].str.contains("nettoyage")).astype(int)
    retenu = detail.sort_values("rang_fichier").groupby("date_situation")["fichier"].first()
    detail = detail[detail["fichier"] == detail["date_situation"].map(retenu)]
    return (detail.groupby(["date_situation", "commune_code"], as_index=False)
            .agg(deplaces=("deplaces", "sum"), enfants_deplaces=("enfants_deplaces", lambda v: v.sum(min_count=1)),
                 fichier=("fichier", "first")))
