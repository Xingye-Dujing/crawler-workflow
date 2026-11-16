"""The extension spine: typed contribution points, manifests and permissions.

The AI workspace is built from plugins rather than a fixed module list. Built-in providers, tools,
skills and UI commands register here at import; a declarative user plugin can add a skill pack, a
provider or a constrained HTTP tool; a local code plugin can call the same registry from Python.
Cloud mode refuses code plugins by name, and every install carries the permissions the user
approved.
"""

from extensions.manifest import API_VERSION, Manifest, validate_manifest
from extensions.registry import HOST, ExtensionRegistry

__all__ = ['API_VERSION', 'HOST', 'ExtensionRegistry', 'Manifest', 'validate_manifest']
