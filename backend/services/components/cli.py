"""Command line surface for the same component core the installer and the app use.

``python -m services.components doctor`` is what the desktop launcher runs with ``--doctor --json``:
one report, one source of truth, usable from a terminal when the UI cannot start.
"""

from __future__ import annotations

import argparse
import json
import sys

from i18n import set_lang, t
from services.components.catalog import Catalog, CatalogError, load_catalog
from services.components.install import InstallError, install_component, remove_component
from services.components.manifest import Manifest, ManifestError
from services.components.paths import install_root
from services.components.probe import environment


def _doctor(args) -> int:
    report = environment(args.root, args.catalog)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    print(f'CaiXiHui environment ({report["os"]}) · {report["root"]}')
    for row in report['capabilities']:
        reason = t(row['reason_key'], **(row['reason_params'] or {}))
        print(f'  [{row["state"]:8}] {t(row["label_key"])}: {reason}')
    if report['components']:
        print('\nInstalled components:')
        for row in report['components']:
            update = ' (update available)' if row.get('update') else ''
            print(f'  {row["id"]} {row["version"]}{update} → {row["path"]}')
    return 0


def _list(args) -> int:
    catalog = Catalog(load_catalog(args.catalog))
    manifest = Manifest(install_root(args.root)).load()
    for component in catalog.components.values():
        installed = manifest.get(component.id)
        version = installed['version'] if installed else '-'
        default = '*' if component.default else ' '
        print(f'{default} {component.id:14} {component.version:24} installed={version}')
    return 0


def _install(args) -> int:
    catalog = Catalog(load_catalog(args.catalog))
    root = install_root(args.root)
    path = install_component(catalog, args.component, root)
    print(path)
    return 0


def _remove(args) -> int:
    removed = remove_component(install_root(args.root), args.component)
    print('removed' if removed else 'not installed')
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='services.components')
    parser.add_argument('--root', default='', help='installation root (default: this application)')
    parser.add_argument('--catalog', default='', help='catalogue JSON (default: the bundled one)')
    parser.add_argument('--lang', default='zh', choices=('zh', 'en'))
    sub = parser.add_subparsers(dest='command', required=True)

    doctor = sub.add_parser('doctor', help='report which features this machine can run')
    doctor.add_argument('--json', action='store_true')
    doctor.set_defaults(func=_doctor)

    listing = sub.add_parser('list', help='list catalogue and installed versions')
    listing.set_defaults(func=_list)

    install = sub.add_parser('install', help='download and install one component')
    install.add_argument('component')
    install.set_defaults(func=_install)

    remove = sub.add_parser('remove', help='delete one installed component')
    remove.add_argument('component')
    remove.set_defaults(func=_remove)

    args = parser.parse_args(argv)
    set_lang(args.lang)
    try:
        return args.func(args)
    except (CatalogError, InstallError, ManifestError, OSError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
