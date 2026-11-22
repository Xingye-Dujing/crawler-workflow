"""Built-in node plugins: one behavior module per node type.

Every type is declared by ``capabilities_kernel/nodes/<id>/manifest.py``, whose
``execution.handler`` names that module's ``run(node, call)``. ``nodes.registry`` resolves the
handler when it registers the type, so this package holds no registration table and a new type
adds no line here.
"""
