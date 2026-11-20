"""The model catalogue: one manifest per model, one adapter per family.

This package answers *which* models exist and *whether this machine can run them*. It never imports
torch, transformers or onnxruntime on the boot path; the family adapters under ``analyzers.backends``
do that lazily, after the catalogue has refused an unknown id by name.
"""

from services.models.catalog import (
    all_models,
    default_for,
    get,
    legacy_rows,
    public_rows,
)
from services.models.catalog import (
    for_task as models_for_task,
)

__all__ = [
    'all_models',
    'default_for',
    'get',
    'legacy_rows',
    'models_for_task',
    'public_rows',
]
