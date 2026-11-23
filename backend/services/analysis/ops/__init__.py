"""The analysis operations, one module per op, registered in ONE table.

``pipeline.DataAnalysisService`` attaches each function as a static method, so
``run_pipeline`` (and every caller that names an op directly) keeps the same names.

The table is the operator manifests' projection: each manifest declares its handler, and
``capabilities_kernel.registry.resolve`` imports that module. A new operator is one manifest plus
its module — never an entry here.
"""

from capabilities_kernel import registry

OPS = {
    manifest.identity.id: registry.resolve(manifest.execution.handler) for manifest in registry.manifests('operator')
}
