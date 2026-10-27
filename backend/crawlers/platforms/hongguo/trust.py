"""Trusting mitmproxy's CA on this machine: read it, check it, install it without hanging.

The harvest intercepts the player's HTTPS traffic, which only works if the OS trusts the proxy's
certificate. Everything in this file exists because of two measurements:

* the store **read** is instant and silent through crypt32, but every ``restype``/``argtype`` has to
  be pinned or a 64-bit handle loses its high half;
* the store **write** hangs this machine forever (2026-10-19, both ``Import-Certificate`` and the raw
  crypt32 call, with no window anywhere — an antivirus or the store provider blocking). So the write
  runs in a child process with a hard timeout, which is killable, and the caller refuses by name with
  the command a human can run themselves.

Split out of ``harvest.py`` because it is a different question (what this machine trusts) from what the
harness asks (how to reach one drama's comments), and because its Windows-ness is now contained in one
file rather than sprinkled through the harness.
"""

import base64
import contextlib
import ctypes
import hashlib
import logging
import os
import subprocess
import sys

from config import Config

logger = logging.getLogger(__name__)


def read_der(cer: str) -> bytes | None:
    """The CA file's DER bytes, or ``None``.

    mitmproxy's ``.cer`` is PEM-armored (measured — ``-----BEGIN CERTIFICATE-----``),
    and crypt32's X509_ASN_ENCODING reader refuses the armor
    (``CertAddEncodedCertificateToStore`` fails on it), so the base64 body is
    unwrapped here once, at the boundary.
    """
    try:
        with open(cer, 'rb') as handle:
            raw = handle.read()
    except OSError:
        return None
    if raw.lstrip().startswith(b'-----BEGIN'):
        try:
            body = raw.split(b'-----BEGIN CERTIFICATE-----', 1)[1].split(b'-----END CERTIFICATE-----', 1)[0]
            return base64.b64decode(body)
        except (ValueError, IndexError):
            return None
    return raw


def manual_command(cer: str) -> str:
    return f'Import-Certificate -FilePath "{cer}" -CertStoreLocation Cert:\\CurrentUser\\Root'


class _Crypt32:
    """Reading the CURRENT USER's ROOT store through crypt32 — silent, instant.

    Every restype/argtype is pinned because the default ``c_int`` would truncate a
    64-bit ``HCERTSTORE``/``PCCERT_CONTEXT`` pointer (the measured classic: it
    "works" until the handle's high half is non-zero). Writing the store lives in
    :func:`install` instead — the write hangs this machine in-process.
    """

    def __init__(self):
        from ctypes import wintypes

        self._ctypes = ctypes
        self._wintypes = wintypes

        class _CertContext(ctypes.Structure):
            _fields_ = [
                ('dwCertEncodingType', wintypes.DWORD),
                ('pbCertEncoded', ctypes.POINTER(ctypes.c_char)),
                ('cbCertEncoded', wintypes.DWORD),
                ('pCertInfo', ctypes.c_void_p),
                ('hCertStore', ctypes.c_void_p),
            ]

        self._CERT_CONTEXT = _CertContext
        crypt32 = ctypes.windll.crypt32
        crypt32.CertOpenSystemStoreW.restype = ctypes.c_void_p
        crypt32.CertOpenSystemStoreW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        crypt32.CertCloseStore.restype = wintypes.BOOL
        crypt32.CertCloseStore.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        crypt32.CertEnumCertificatesInStore.restype = ctypes.c_void_p
        crypt32.CertEnumCertificatesInStore.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        crypt32.CertAddEncodedCertificateToStore.restype = wintypes.BOOL
        crypt32.CertAddEncodedCertificateToStore.argtypes = [
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.c_char_p,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
        ]

    def _root(self):
        return self._ctypes.windll.crypt32.CertOpenSystemStoreW(None, 'ROOT')

    def thumbprints(self) -> set:
        """SHA-1 of the DER of every certificate in the user ROOT store.

        The DER is read off the CERT_CONTEXT itself: the ``CERT_HASH_PROP_ID``
        property is only cached for certificates the provider has already hashed
        (measured — one hit out of 79, and a probe that sees one cert calls every
        CA untrusted).
        """
        # The module this instance was built with, read back from ``self``: ``_CERT_CONTEXT``
        # declared its fields through it, so casting into ``POINTER(that structure)`` has to come
        # from the same module or ctypes refuses the type.
        ct = self._ctypes
        crypt32 = ct.windll.crypt32
        store = self._root()
        if not store:
            return set()
        found = set()
        try:
            ctx = crypt32.CertEnumCertificatesInStore(store, None)
            while ctx:
                cc = ct.cast(ctx, ct.POINTER(self._CERT_CONTEXT)).contents
                der = ct.string_at(cc.pbCertEncoded, cc.cbCertEncoded)
                found.add(hashlib.sha1(der).digest())
                ctx = crypt32.CertEnumCertificatesInStore(store, ctx)
        finally:
            crypt32.CertCloseStore(store, 0)
        return found


_crypt32 = None


def crypt32_api() -> _Crypt32:
    """The one crypt32 handle set this process needs; built lazily, on first trust question.

    Named ``_api`` because every method below binds a local ``crypt32`` to the DLL itself (that is
    the original code, moved verbatim); an accessor spelled ``crypt32`` would be shadowed by those
    locals — and pylint's W0621 caught it before it could read as two different things.
    """
    global _crypt32
    if _crypt32 is None:
        _crypt32 = _Crypt32()
    return _crypt32


#: The child-process installer: DER on stdin, exit 0 on success. Kept as source
#: bytes so the parent never executes it in-process (see :func:`install`).
_INSTALL_SNIPPET = b"""
import ctypes, sys
from ctypes import wintypes
der = sys.stdin.buffer.read()
c = ctypes.windll.crypt32
c.CertOpenSystemStoreW.restype = ctypes.c_void_p
c.CertOpenSystemStoreW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
c.CertAddEncodedCertificateToStore.restype = wintypes.BOOL
c.CertAddEncodedCertificateToStore.argtypes = [
    ctypes.c_void_p, wintypes.DWORD, ctypes.c_char_p, wintypes.DWORD, wintypes.DWORD,
    ctypes.POINTER(ctypes.c_void_p),
]
c.CertCloseStore.argtypes = [ctypes.c_void_p, wintypes.DWORD]
store = c.CertOpenSystemStoreW(None, "ROOT")
if not store:
    sys.exit(2)
ok = c.CertAddEncodedCertificateToStore(store, 0x00000001, der, len(der), 2, None)
c.CertCloseStore(store, 0)
sys.exit(0 if ok else 1)
"""


def is_trusted(der: bytes) -> bool:
    if sys.platform != 'win32':
        return False
    try:
        return hashlib.sha1(der).digest() in crypt32_api().thumbprints()
    except Exception as exc:
        logger.debug('hongguo harvest: trust probe failed: %s', exc)
        return False


def install(der: bytes, timeout: float = 20.0) -> bool:
    """Add the CA to the user ROOT store — in a CHILD PROCESS with a hard timeout.

    Reading the store is instant; WRITING it was measured to hang this machine
    forever (2026-10-19, both ``Import-Certificate`` and the raw crypt32 call, no
    window anywhere — an antivirus or the store provider itself blocking). An
    in-process call would therefore freeze the whole server on one harvest, and a
    daemon thread that never returns keeps the store lock for the process life.
    A child is killable: on timeout it is terminated, its handle dies with it, and
    the caller refuses by name with the manual command.
    """
    if sys.platform != 'win32':
        return False
    script = os.path.join(Config.HARVEST_DIR, 'hg_ca_install_tmp.py')
    try:
        os.makedirs(Config.HARVEST_DIR, exist_ok=True)
        with open(script, 'wb') as handle:
            handle.write(_INSTALL_SNIPPET)
            handle.write(b'\n')
        done = subprocess.run(
            [sys.executable, script],
            input=der,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return done.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        with contextlib.suppress(OSError):
            os.remove(script)
