"""python -m boussole.collecte : collecte des données brutes et dépôt de l'étape 01."""

from ..depots import deposer_collecte
from .pipeline import collecter


def main() -> None:
    resultats = collecter()
    registre, bilan = resultats["registre"], resultats["bilan"]
    print(f"{registre['source'].nunique()} sources, {len(registre)} fichiers, "
          f"{registre['nb_lignes'].astype(int).sum()} lignes copiées.")
    print(bilan["statut"].value_counts().to_string())
    alertes = resultats["couverture"].query("alerte != ''")
    if not alertes.empty:
        print(alertes.to_string(index=False))
    print(f"{len(deposer_collecte())} fichiers déposés dans depots/01-collecte.")


if __name__ == "__main__":
    main()
