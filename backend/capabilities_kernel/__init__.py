"""The capability kernel: one manifest per capability, everything else derived from it.

The kernel replaces the habit of describing one capability in a dozen places. A capability (a node
type today; an analysis operator, chart, platform or AI skill later) declares its identity,
parameters, ports, executor, validation rules, UI hints, AI knowledge, tests and documentation in a
single manifest. The registry discovers those manifests by directory name, refuses duplicates and
loads executors lazily; the generator and doctor (``tools/gen_capabilities.py`` / ``tools/doctor.py``)
read the same declarations instead of keeping their own lists.

The package is deliberately a leaf: manifests may import the standard library and this package only,
so ``nodes.catalog`` can read them while parsing a DAG without pulling pandas, Selenium or Flask into
the boot path. Behavior stays in the executor a manifest names — a manifest declares a contract, it
does not run anything.
"""

from capabilities_kernel.manifest import API_VERSION, KINDS, Manifest

__all__ = ['API_VERSION', 'KINDS', 'Manifest']
