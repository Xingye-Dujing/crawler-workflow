"""Every platform's declaration, projected from the capability tree.

The declarations live in ``capabilities_kernel/platforms/<id>/manifest.py`` — one file per platform,
which is also the panel's order (``identity.order``). ``Capability`` here is the same kind of object
the crawl matrix has always served; ``registry`` re-exports it, so a caller that asks either spelling
gets the same tuple. ``tests/unit/foundation/test_capabilities_layout.py`` pins the order.
"""

from capabilities_kernel import registry
from capabilities_kernel.platform import PlatformManifest

CAPABILITIES: tuple[PlatformManifest, ...] = tuple(registry.manifests('platform'))
