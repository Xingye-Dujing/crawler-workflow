"""Component catalogue, downloads, installation and the environment matrix.

The package is standard-library only: the bootstrap installer imports it before the application
exists, and the running app imports the same code so both answer “what is installed?” identically.
"""

from services.components.catalog import Catalog, CatalogError, load_catalog
from services.components.manifest import Manifest, ManifestError
from services.components.paths import components_root

__all__ = [
    'Catalog',
    'CatalogError',
    'Manifest',
    'ManifestError',
    'components_root',
    'load_catalog',
]
