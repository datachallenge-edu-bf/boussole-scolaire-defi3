"""python -m boussole.nettoyage : construction de la base et dépôt de l'étape 02."""

from ..depots import deposer_nettoyage
from .chantier import nettoyer


def main() -> None:
    tables = nettoyer()
    print(tables["controles"].to_string(index=False))
    print(f"{len(deposer_nettoyage())} fichiers déposés dans depots/02-nettoyage.")


if __name__ == "__main__":
    main()
