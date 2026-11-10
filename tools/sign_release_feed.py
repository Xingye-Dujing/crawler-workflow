"""Sign (or check) the release feed so a client can tell a real ``version.json`` from an edited one.

The feed's own SHA-256 only proves "the bytes match what the manifest says", and the manifest is the
first thing an attacker with write access to the mirror rewrites — it could point at another URL and
another digest with no contradiction. A detached Ed25519 signature over the document, verified with
a public key the client was given out of band, is the trust root the digest cannot be.

    python tools/sign_release_feed.py version.json --key release-private.pem
    python tools/sign_release_feed.py version.json --verify --key release-public.pem

The signature covers the document WITHOUT its ``signature`` field, re-serialised with sorted keys and
compact separators (see ``backend/services/update.py::_canonical_feed``). Both sides must agree on
that canonical form, so it is defined once there and imported here rather than copied.

``cryptography`` is imported inside the functions: the application only needs it when a public key is
configured, and the release job should get a sentence naming the missing package instead of a
traceback during import.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_side():
    """The canonical haystack and the serialization module, or a refusal naming the missing piece."""
    sys.path.insert(0, str(ROOT / 'backend'))
    try:
        from cryptography.hazmat.primitives import serialization
    except ImportError as exc:  # pragma: no cover - exercised only on a machine without the package
        raise SystemExit(f'sign_release_feed needs the "cryptography" package: {exc}') from exc
    from services.update import canonical_feed

    return canonical_feed, serialization


def _document(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise SystemExit(f'{path} is not readable JSON: {exc}') from exc
    if not isinstance(payload, dict):
        raise SystemExit(f'{path} must hold a JSON object')
    return payload


def _order(payload: dict) -> dict:
    """The feed with ``signature`` LAST, so a re-signed or unsigned document still reads the same."""
    body = {key: value for key, value in payload.items() if key != 'signature'}
    if 'signature' in payload:
        body['signature'] = payload['signature']
    return body


def sign(path: Path, key_path: Path) -> str:
    """Sign ``path`` in place and return the base64 signature that was written."""
    canonical_feed, serialization = _load_side()
    try:
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    except (OSError, ValueError) as exc:
        raise SystemExit(f'{key_path} is not a readable private key: {exc}') from exc
    if not hasattr(key, 'sign'):
        raise SystemExit(f'{key_path} is not an Ed25519 private key')
    payload = _document(path)
    signature = base64.b64encode(key.sign(canonical_feed(payload))).decode('ascii')
    payload['signature'] = signature
    path.write_text(json.dumps(_order(payload), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return signature


def verify(path: Path, key_path: Path) -> None:
    """Raise ``SystemExit`` unless ``path`` carries a signature ``key_path`` accepts."""
    canonical_feed, serialization = _load_side()
    payload = _document(path)
    signature = str(payload.get('signature') or '').strip()
    if not signature:
        raise SystemExit(f'{path} has no signature field')
    try:
        key = serialization.load_pem_public_key(key_path.read_bytes())
    except (OSError, ValueError) as exc:
        raise SystemExit(f'{key_path} is not a readable public key: {exc}') from exc
    try:
        key.verify(base64.b64decode(signature), canonical_feed(payload))
    except Exception as exc:  # InvalidSignature and anything a malformed blob raises
        raise SystemExit(f'{path}: signature does not match {key_path.name}: {exc}') from exc
    print(f'{path}: signature verified')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Sign or verify a release version.json.')
    parser.add_argument('feed', type=Path, help='path to version.json')
    parser.add_argument('--key', type=Path, required=True, help='private key to sign, public key to verify')
    parser.add_argument('--verify', action='store_true', help='check an existing signature instead of writing one')
    args = parser.parse_args(argv)
    if not args.feed.is_file():
        raise SystemExit(f'{args.feed} does not exist')
    if not args.key.is_file():
        raise SystemExit(f'{args.key} does not exist')
    if args.verify:
        verify(args.feed, args.key)
        return 0
    signature = sign(args.feed, args.key)
    print(f'{args.feed}: signed ({len(signature)} base64 chars)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
