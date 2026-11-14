"""Étape 02 de Boussole Scolaire : nettoyage et construction de la base.

La base est un fichier SQLite unique (``donnees/base/boussole.db``) : tables de
référence des territoires, tables de faits en format large par province, édition
et statut, journal et contrôles, et deux tables de métadonnées (``_tables`` et
``_variables``). Chaque table est aussi exportée en CSV.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from ..chemins import LIEUX
from . import dictionnaire
from .communes import LecteurCommunal
from .crise import lire_deplaces, lire_esu
from .effectifs import lire_effectifs
from .nomenclature import Nomenclature
from .projections import lire_projections
from .tableaux import Signalement, lire

COLONNES_OFFRE = {1: "ecoles", 2: "salles", 3: "groupes_pedagogiques", 4: "maitres", 5: "eleves",
                  6: "eleves_par_maitre_publie"}
COLONNES_MURS = {1: "murs_dur", 2: "murs_semi_dur", 3: "murs_paille_banco", 4: "murs_indetermine",
                 5: "murs_bon_etat", 6: "murs_mauvais_etat", 7: "murs_etat_indetermine", 8: "salles"}
COLONNES_TOITS = {1: "toit_tole", 2: "toit_tuiles_ciment", 3: "toit_banco", 4: "toit_paille", 5: "toit_absent",
                  6: "toit_bon_etat", 7: "toit_mauvais_etat", 8: "toit_etat_indetermine", 9: "salles"}
COLONNES_ENSEIGNANTS = {1: "corps_ip", 2: "corps_ic", 3: "corps_iac", 4: "corps_ia", 5: "corps_autre",
                        6: "corps_pce", 7: "corps_pe", 8: "enseignants", 9: "tenant_classe", 10: "directeurs",
                        11: "titulaires", 12: "suppleants", 13: "classes_simples", 14: "classes_multigrades",
                        15: "classes_double_flux"}
CONTEXTES_STATUT = {
    r"^[IVX ]*[0-9 ]+PUBLIC$": "statut_tableau:public",
    r"^[IVX ]*[0-9 ]+PRIVE$": "statut_tableau:prive",
    r"^[IVX ]*[0-9 ]+PUBLIC PRIVE$": "statut_tableau:total",
}
ETIQUETTES_SEXE = {"FEMMES?": ("sexe", "F"), "HOMMES?": ("sexe", "H"), "TOTAL": ("sexe", "T")}
CONTEXTES_SALLES = {
    r"NATURE ET ETAT DES MURS": "element:murs",
    r"NATURE ET ETAT DES TOITURES": "element:toits",
    r"ORIGINE DU FINANCEMENT": "element:financement",
    r"^[IVX ]*[0-9 ]+PUBLIC$": "statut_tableau:public",
    r"^[IVX ]*[0-9 ]+PRIVE$": "statut_tableau:prive",
    r"^[IVX ]*[0-9 ]+PUBLIC PRIVE$": "statut_tableau:total",
}


def _brut(nom: str) -> pd.DataFrame:
    return pd.read_csv(LIEUX.brutes / f"{nom}.csv", sep=";", dtype=str, encoding="utf-8-sig", keep_default_na=False)


def _elargir(long: pd.DataFrame, colonnes: dict[int, str], cles: list[str]) -> pd.DataFrame:
    """Passe d'une valeur par ligne à une ligne par entité, avec une colonne par variable."""
    long = long.assign(variable=long["colonne"].map(colonnes))
    large = long.pivot_table(index=cles, columns="variable", values="valeur", aggfunc="first").reset_index()
    large.columns.name = None
    source = long.groupby(cles)[["fichier", "page"]].first().reset_index()
    return large.merge(source, on=cles)[cles + list(dict.fromkeys(colonnes.values())) + ["fichier", "page"]]


class Chantier:
    def __init__(self) -> None:
        self.nomenclature = Nomenclature.construire()
        self.signalements = Signalement()
        self.tables: dict[str, pd.DataFrame] = {}
        self.controles: list[dict] = []

    # Tables de faits.
    def offre(self) -> pd.DataFrame:
        long = lire(_brut("dgess_principaux_chiffres"), "principaux_chiffres", self.nomenclature, 6, {},
                    self.signalements)
        large = _elargir(long, COLONNES_OFFRE, ["edition", "code", "niveau", "statut"])
        large["eleves_par_maitre"] = (large["eleves"] / large["maitres"]).round(2)
        large["eleves_par_salle"] = (large["eleves"] / large["salles"]).round(2)
        large["eleves_par_groupe"] = (large["eleves"] / large["groupes_pedagogiques"]).round(2)
        return large

    def etat_salles(self) -> pd.DataFrame:
        long = lire(_brut("dgess_etat_salles"), "etat_salles", self.nomenclature, (8, 9), CONTEXTES_SALLES,
                    self.signalements, ignorer=("financement",))
        long = long[long["element"].isin(["murs", "toits"])]
        cles = ["edition", "statut_tableau", "code", "niveau"]
        murs = _elargir(long[(long["element"] == "murs") & (long["largeur"] == 8)], COLONNES_MURS, cles)
        toits = _elargir(long[(long["element"] == "toits") & (long["largeur"] == 9)], COLONNES_TOITS, cles)
        etat = murs.drop(columns=["fichier", "page"]).merge(
            toits.drop(columns=["salles"]), on=cles, how="outer", suffixes=("", "_toits"))
        etat = etat.rename(columns={"statut_tableau": "statut"})
        etat["part_salles_precaires"] = ((etat["murs_paille_banco"] + etat["murs_semi_dur"]) / etat["salles"]).round(4)
        etat["part_toits_precaires"] = ((etat["toit_paille"] + etat["toit_banco"] + etat["toit_absent"])
                                        / etat["salles"]).round(4)
        return etat

    def effectifs_niveau(self) -> pd.DataFrame:
        return lire_effectifs(_brut("dgess_effectifs_niveau"), self.nomenclature, self.signalements)

    def enseignants(self) -> pd.DataFrame:
        long = lire(_brut("dgess_enseignants_corps"), "enseignants_corps", self.nomenclature, (13, 15),
                    CONTEXTES_STATUT, self.signalements, etiquettes=ETIQUETTES_SEXE)
        # Jusqu'en 2022-2023, l'annuaire compte 5 corps ; les corps P.C.E. et P.E. apparaissent ensuite.
        # Les tableaux à 13 colonnes sont ramenés au schéma à 15, ces deux corps restant vides.
        ancien = long["largeur"] == 13
        long.loc[ancien & (long["colonne"] >= 6), "colonne"] += 2
        cles = ["edition", "statut_tableau", "code", "niveau", "sexe"]
        large = _elargir(long, COLONNES_ENSEIGNANTS, cles).rename(columns={"statut_tableau": "statut"})
        return large

    def population(self) -> pd.DataFrame:
        return lire_projections(_brut("insd_projections"), self.nomenclature, self.signalements)

    def communes(self) -> pd.DataFrame:
        lecteur = LecteurCommunal(self.nomenclature, self.signalements)
        table = lecteur.lire(_brut("insd_communes_primaire"))
        self.nomenclature.rapprochements.extend(lecteur.rapprochements)
        return table

    def ecoles_crise(self) -> pd.DataFrame:
        return lire_esu(_brut("esu_rapports"), self.nomenclature, self.signalements)

    def deplaces(self) -> pd.DataFrame:
        return lire_deplaces(_brut("deplaces_internes"), self.nomenclature, self.signalements)

    # Contrôles.
    def _controle(self, nom: str, conforme: bool, detail: str) -> None:
        self.controles.append({"controle": nom, "conforme": bool(conforme), "detail": detail})

    def controler(self) -> None:
        offre, etat = self.tables["offre_province"], self.tables["etat_salles_province"]
        provinces = offre[offre["niveau"] == "province"]
        n = provinces.groupby("edition")["code"].nunique()
        manquants = {e: sorted(set(self.nomenclature.provinces["province_code_ancien"])
                               - set(provinces.loc[provinces["edition"] == e, "code"])) for e in n.index}
        # Une province sans aucune école ouverte une année donnée n'apparaît pas dans l'annuaire :
        # absence réelle (fermetures pour insécurité), signalée mais pas comptée comme erreur.
        sans_ecole = {"2022-2023": {"BF5203"}}
        explique = all(set(manquants[e]) <= sans_ecole.get(e, set()) for e in n.index)
        self._controle("offre_45_provinces_par_edition", explique,
                       "; ".join(f"{e} : {v}" + (f" (manque {', '.join(manquants[e])}, aucune école ouverte)"
                                                     if manquants[e] else "") for e, v in n.items()))

        variables = ["ecoles", "salles", "groupes_pedagogiques", "maitres", "eleves"]
        large = offre.pivot_table(index=["edition", "code", "niveau"], columns="statut", values=variables)
        ecart = sum((large[(v, "public")] + large[(v, "prive")] - large[(v, "total")]).abs().sum() for v in variables)
        self._controle("offre_public_plus_prive_egal_total", ecart == 0,
                       f"somme des écarts absolus sur les cinq variables : {ecart:.0f}")

        region_de = self.nomenclature.provinces.set_index("province_code_ancien")["region_code_ancien"]
        somme = (provinces.assign(region=provinces["code"].map(region_de))
                 .groupby(["edition", "region", "statut"])[variables].sum())
        publie = offre[offre["niveau"] == "region"].rename(columns={"code": "region"}).set_index(
            ["edition", "region", "statut"])[variables]
        comparaison = (somme - publie).dropna(how="all")
        hors = int((comparaison.abs() > 0).any(axis=1).sum())
        self._controle("offre_somme_provinces_egal_total_regional", hors == 0,
                       f"{hors} combinaisons édition × région × statut avec écart sur {len(comparaison)}")

        ecart_ratio = (provinces["eleves_par_maitre"] - provinces["eleves_par_maitre_publie"]).abs()
        self._controle("ratio_eleves_maitre_recalcule_egal_publie", (ecart_ratio <= 0.1).mean() > 0.99,
                       f"écart médian {ecart_ratio.median():.2f} ; {int((ecart_ratio > 0.1).sum())} lignes "
                       f"au-delà de 0,1 sur {ecart_ratio.notna().sum()}")

        salles = provinces.set_index(["edition", "code", "statut"])["salles"]
        salles_etat = etat[etat["niveau"] == "province"].set_index(["edition", "code", "statut"])["salles"]
        commun = salles.index.intersection(salles_etat.index)
        diff = (salles.loc[commun] - salles_etat.loc[commun]).abs()
        self._controle("salles_tableau_etat_egal_tableau_principal", (diff == 0).mean() > 0.9,
                       f"{int((diff == 0).sum())} provinces × éditions × statuts identiques sur {len(diff)} ; "
                       f"écart médian des autres : {diff[diff > 0].median():.0f} salles (incohérence de l'annuaire)")

        eff = self.tables["effectifs_niveau_province"]
        eff_prov = eff[eff["niveau"] == "province"]
        n_eff = eff_prov.groupby("annee")["code"].nunique()
        self._controle("effectifs_45_provinces_par_annee", (n_eff >= 44).all(),
                       "; ".join(f"{a} : {v}" for a, v in n_eff.items()))
        large = eff_prov.pivot_table(index=["annee", "code", "classe"], columns="sexe", values="effectif")
        ecart_sexe = (large["G"] + large["F"] - large["T"]).abs()
        self._controle("effectifs_garcons_plus_filles_egal_total", (ecart_sexe == 0).mean() > 0.99,
                       f"{int((ecart_sexe > 0).sum())} lignes en écart sur {ecart_sexe.notna().sum()}")
        totaux = eff_prov[(eff_prov["sexe"] == "T") & (eff_prov["classe"] == "Total")].set_index(["annee", "code"])["effectif"]
        offre_t = provinces[provinces["statut"] == "total"].set_index(["edition", "code"])["eleves"]
        offre_t.index = offre_t.index.set_names(["annee", "code"])
        commun = totaux.index.intersection(offre_t.index)
        diff_eff = (totaux.loc[commun] - offre_t.loc[commun]).abs()
        self._controle("effectifs_par_niveau_egal_eleves_tableau_principal", (diff_eff == 0).mean() > 0.95,
                       f"{int((diff_eff == 0).sum())} provinces × années identiques sur {len(diff_eff)}")

        ens = self.tables["enseignants_province"]
        corps = [c for c in ens.columns if c.startswith("corps_")]
        ecart_corps = (ens[corps].sum(axis=1) - ens["enseignants"]).abs()
        ecart_fonctions = (ens[["directeurs", "titulaires", "suppleants"]].sum(axis=1) - ens["enseignants"]).abs()
        self._controle("enseignants_somme_corps_et_fonctions_egal_total",
                       (ecart_corps == 0).mean() > 0.99 and (ecart_fonctions == 0).mean() > 0.99,
                       f"corps : {int((ecart_corps > 0).sum())} écarts ; fonctions : "
                       f"{int((ecart_fonctions > 0).sum())} écarts, sur {len(ens)} lignes")
        tenant = ens[(ens["niveau"] == "province") & (ens["sexe"] == "T")].set_index(
            ["edition", "code", "statut"])["tenant_classe"]
        maitres = provinces.set_index(["edition", "code", "statut"])["maitres"]
        commun = tenant.index.intersection(maitres.index)
        diff_m = (tenant.loc[commun] - maitres.loc[commun]).abs()
        self._controle("enseignants_tenant_classe_egal_maitres_tableau_principal", (diff_m == 0).mean() > 0.9,
                       f"{int((diff_m == 0).sum())} identiques sur {len(diff_m)} ; écart médian des autres : "
                       f"{diff_m[diff_m > 0].median() if (diff_m > 0).any() else 0:.0f}")

        pop = self.tables["population_projetee"]
        couverture = pop.groupby("niveau")["code"].nunique()
        self._controle("population_45_provinces_13_regions_16_annees",
                       couverture.get("province") == 45 and couverture.get("region") == 13
                       and pop["annee"].nunique() == 16,
                       f"{couverture.get('province', 0)} provinces, {couverture.get('region', 0)} régions, "
                       f"années {pop['annee'].min()} à {pop['annee'].max()}")
        ecart_sexes = (pop["hommes"] + pop["femmes"] - pop["ensemble"]).abs()
        self._controle("population_hommes_plus_femmes_egal_ensemble", (ecart_sexes <= 1).mean() > 0.999,
                       f"{int((ecart_sexes > 1).sum())} lignes en écart sur {len(pop)}")
        region_de = self.nomenclature.provinces.set_index("province_code_ancien")["region_code_ancien"]
        prov = pop[pop["niveau"] == "province"].assign(region=lambda t: t["code"].map(region_de))
        somme = prov.groupby(["annee", "region", "groupe_age"])["ensemble"].sum()
        reg = pop[pop["niveau"] == "region"].set_index(["annee", "code", "groupe_age"])["ensemble"]
        reg.index = reg.index.set_names(["annee", "region", "groupe_age"])
        commun = somme.index.intersection(reg.index)
        ecart_regions = (somme.loc[commun] - reg.loc[commun]).abs()
        self._controle("population_somme_provinces_egal_region", (ecart_regions <= 5).mean() > 0.99,
                       f"{int((ecart_regions > 5).sum())} écarts de plus de 5 personnes sur {len(ecart_regions)}")

        com = self.tables["communes_primaire"]
        attendues = self.nomenclature.communes.groupby("region_code_ancien")["commune_code"].nunique()
        lues = com[com["indicateur"] == "eleves_par_sexe"].groupby("region_code_ancien")["commune_code"].nunique()
        part = (lues / attendues.reindex(lues.index)).round(2)
        self._controle("communes_couverture_par_region", len(lues) == 10 and (part >= 0.6).all(),
                       f"{len(lues)} régions sur 10 publiées ; communes lues / attendues : "
                       + ", ".join(f"{r} {v:.0%}" for r, v in part.items()))
        province_de = self.nomenclature.communes.set_index("commune_code")["province_code_ancien"]
        eleves = com[(com["indicateur"] == "eleves_par_sexe") & (com["modalite"] == "ensemble")]
        somme = eleves.assign(code=eleves["commune_code"].map(province_de)).groupby(["annee", "code"])["valeur"].agg(
            ["sum", "count"])
        dgess = provinces[provinces["statut"] == "total"].set_index(["edition", "code"])["eleves"]
        dgess.index = dgess.index.set_names(["annee", "code"])
        communes_par_province = self.nomenclature.communes.groupby("province_code_ancien")["commune_code"].nunique()
        complet = somme[somme["count"] == somme.index.get_level_values("code").map(communes_par_province)]
        commun = complet.index.intersection(dgess.index)
        ecart = ((complet.loc[commun, "sum"] - dgess.loc[commun]) / dgess.loc[commun]).abs()
        self._controle("communes_somme_eleves_proche_dgess_province", ecart.median() < 0.02,
                       f"{len(ecart)} provinces × années complètes comparées ; écart relatif médian "
                       f"{ecart.median():.1%}, {int((ecart > 0.05).sum())} au-delà de 5 % (sources différentes : "
                       "INSD et DGESS)")

        esu = self.tables["ecoles_crise_province"]
        fiables = esu[esu["tableau_fiable"]].groupby(["mois", "situation"]).size()
        self._controle("esu_tableaux_fiables", len(fiables) > 0,
                       f"{len(fiables)} tableaux (mois × situation) dont la somme des provinces retrouve le total "
                       f"primaire publié à 5 % près, sur {esu.groupby(['mois', 'situation']).ngroups} ; mois fiables : "
                       + ", ".join(sorted({m for m, _ in fiables.index})))
        self._controle("esu_eleves_filles_plus_garcons_egal_total", esu["coherence_eleves"].mean() > 0.9,
                       f"{int((~esu['coherence_eleves']).sum())} lignes incohérentes sur {len(esu)}, "
                       "toutes dans des rapports lus par reconnaissance de caractères"
                       if (~esu.loc[esu['tableau_fiable'], 'coherence_eleves']).sum() == 0
                       else f"{int((~esu['coherence_eleves']).sum())} lignes incohérentes sur {len(esu)}")
        dep = self.tables["deplaces_commune"]
        perdus = [l for l in self.signalements.lignes if l["tableau"] == "deplaces"]
        self._controle("deplaces_aucune_date_perdue_faute_de_p_code", not perdus,
                       f"{dep['commune_code'].nunique()} communes, {dep['date_situation'].nunique()} dates "
                       f"({dep['date_situation'].min()} à {dep['date_situation'].max()}) ; les situations données "
                       "seulement par commune sans P-code sont toutes couvertes par un autre fichier doté de P-codes"
                       if not perdus else f"{len(perdus)} dates absentes faute de P-code")

        n_etat = etat[etat["niveau"] == "province"].groupby("edition")["code"].nunique()
        self._controle("etat_salles_45_provinces_par_edition", (n_etat >= 44).all() and explique,
                       "; ".join(f"{e} : {v}" for e, v in n_etat.items()))

    # Exécution et écriture.
    def executer(self) -> dict[str, pd.DataFrame]:
        nom = self.nomenclature
        self.tables["territoire_commune"] = nom.communes
        self.tables["territoire_province_ancienne"] = nom.provinces
        self.tables["territoire_region_ancienne"] = nom.regions
        self.tables["offre_province"] = self.offre()
        self.tables["etat_salles_province"] = self.etat_salles()
        self.tables["effectifs_niveau_province"] = self.effectifs_niveau()
        self.tables["enseignants_province"] = self.enseignants()
        self.tables["population_projetee"] = self.population()
        self.tables["communes_primaire"] = self.communes()
        self.tables["ecoles_crise_province"] = self.ecoles_crise()
        self.tables["deplaces_commune"] = self.deplaces()
        self.controler()
        self.tables["journal_rapprochements"] = pd.DataFrame(
            nom.rapprochements, columns=["nom_lu", "code", "niveau", "regle", "similarite", "contexte"]
        ).drop_duplicates(["nom_lu", "code"])
        self.tables["journal_signalements"] = pd.DataFrame(
            self.signalements.lignes, columns=["tableau", "motif", "fichier", "page", "ligne", "texte"])
        # Le contrôle des métadonnées porte aussi sur sa propre table : une place lui est réservée.
        self._controle("metadonnees_completes", False, "")
        self.tables["controles"] = pd.DataFrame(self.controles)
        tables_meta, variables_meta = dictionnaire.decrire(self.tables)
        manques = dictionnaire.lacunes(tables_meta, variables_meta)
        self.tables["controles"].iloc[-1, 1:] = [not manques, "toutes les tables et variables sont décrites"
                                                 if not manques else "sans description : " + ", ".join(manques)]
        self.tables["_tables"], self.tables["_variables"] = tables_meta, variables_meta
        self.ecrire()
        return self.tables

    def ecrire(self) -> Path:
        dossier = LIEUX.autoriser(LIEUX.projet / "donnees" / "base")
        dossier.mkdir(parents=True, exist_ok=True)
        base = dossier / "boussole.db"
        base.unlink(missing_ok=True)
        with sqlite3.connect(base) as connexion:
            for nom, table in self.tables.items():
                table.replace({np.nan: None}).to_sql(nom, connexion, index=False)
        for nom, table in self.tables.items():
            table.to_csv(dossier / f"{nom}.csv", sep=";", encoding="utf-8-sig", index=False)
        return base


def nettoyer() -> dict[str, pd.DataFrame]:
    return Chantier().executer()
