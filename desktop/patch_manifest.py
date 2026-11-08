"""Make an Inno Setup executable request elevation before its loader runs.

Inno's SetupLdr is deliberately built with an ``asInvoker`` manifest; Setup asks for UAC only
after the loader has extracted the real setup into the user's %TEMP%. On a locked-down machine
that write is denied before the prompt can appear, and the user sees

    Setup was unable to create the directory "...\\is-XXXX.tmp". Error 5: 拒绝访问。

Replacing the outer manifest's ``requestedExecutionLevel`` with ``requireAdministrator`` makes
Windows elevate the whole executable at launch, so the loader's extraction runs with the admin
token and the wizard can appear. Only the manifest bytes are rewritten; the file length and every
other resource are untouched, because the replacement is padded to the original size.

    python desktop/patch_manifest.py dist/CaiXiHui-Setup.exe
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pefile

#: Kept deliberately small and dependency-compatible with Inno's own manifest. Trailing spaces
#: are appended after </assembly> to keep the resource's byte size unchanged.
MANIFEST = b"""<?xml version="1.0" encoding="utf-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <assemblyIdentity type="win32" name="CaiXiHui.Setup" version="1.0.0.0" processorArchitecture="x86"/>
  <description>CaiXiHui Setup</description>
  <dependency>
    <dependentAssembly>
      <assemblyIdentity type="win32" name="Microsoft.Windows.Common-Controls" version="6.0.0.0"
        processorArchitecture="*" publicKeyToken="6595b64144ccf1df" language="*"/>
    </dependentAssembly>
  </dependency>
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
    <security>
      <requestedPrivileges>
        <requestedExecutionLevel level="requireAdministrator" uiAccess="false"/>
      </requestedPrivileges>
    </security>
  </trustInfo>
  <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1">
    <application>
      <supportedOS Id="{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}"/>
    </application>
  </compatibility>
</assembly>"""


def _manifest_entry(pe: pefile.PE):
    """The RT_MANIFEST resource data entry, or ``None``."""
    for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if entry.id != 24:  # RT_MANIFEST
            continue
        for item in entry.directory.entries:
            for language in item.directory.entries:
                return language.data.struct
    return None


def patch(path: Path) -> None:
    pe = pefile.PE(str(path))
    data = _manifest_entry(pe)
    if data is None:
        raise SystemExit(f'{path}: no RT_MANIFEST resource found')
    original = pe.get_data(data.OffsetToData, data.Size)
    if len(MANIFEST) > len(original):
        raise SystemExit(f'{path}: existing manifest is only {len(original)} bytes, replacement is longer')
    padded = MANIFEST + b' ' * (len(original) - len(MANIFEST))
    # Same length on purpose: the resource's IMAGE_RESOURCE_DATA_ENTRY keeps its size, so no
    # directory rewrite (and no PE section resize) is needed. OffsetToData is an RVA; the writer
    # needs the file offset.
    pe.set_bytes_at_offset(pe.get_offset_from_rva(data.OffsetToData), padded)
    pe.write(str(path))
    print(f'patched manifest: {path} ({len(original)} bytes, requireAdministrator)')


def verify(path: Path) -> str:
    pe = pefile.PE(str(path))
    data = _manifest_entry(pe)
    if data is None:
        return 'missing'
    text = pe.get_data(data.OffsetToData, data.Size).decode('utf-8', errors='replace')
    match = re.search(r'<requestedExecutionLevel[^>]*level="([^"]+)"', text)
    return match.group(1) if match else 'missing'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('file', nargs='+')
    parser.add_argument('--check', action='store_true', help='only report the level')
    args = parser.parse_args(argv)
    failed = 0
    for raw in args.file:
        target = Path(raw)
        if not target.is_file():
            print(f'not found: {target}', file=sys.stderr)
            failed += 1
            continue
        if args.check:
            print(f'{target}: {verify(target)}')
            continue
        patch(target)
        level = verify(target)
        print(f'{target}: {level}')
        if level != 'requireAdministrator':
            failed += 1
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
