"""The release feed's signature is the trust root the SHA-256 chain cannot be.

``version.json`` carries both the download URL and the digest that "verifies" it, so a manifest the
mirror was tricked into serving is self-consistent: it simply names another program. An Ed25519
signature over the document, checked against a public key the machine was given out of band, is the
only part of that chain an attacker with write access to the mirror cannot forge.

The four cases pinned here are the four answers the client can give: a valid signature passes, an
edited document is refused, a configured key makes a MISSING signature a refusal too (failure
closed), and a machine with no key keeps updating (the product cannot require a key it never
shipped). The signing tool is exercised as a real subprocess, because the canonical bytes it signs
must be the same bytes the client hashes — a test that called ``canonical_feed`` on both sides would
pass even if the tool encoded them differently.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SIGN_TOOL = REPO / 'tools' / 'sign_release_feed.py'

pytestmark = pytest.mark.unit


@pytest.fixture
def keypair(tmp_path):
    serialization = pytest.importorskip('cryptography.hazmat.primitives.serialization')
    ed25519 = pytest.importorskip('cryptography.hazmat.primitives.asymmetric.ed25519')
    private = ed25519.Ed25519PrivateKey.generate()
    private_path = tmp_path / 'private.pem'
    public_path = tmp_path / 'public.pem'
    private_path.write_bytes(
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        private.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return private_path, public_path


@pytest.fixture
def feed(tmp_path):
    payload = {
        'schema': 1,
        'version': '2026.12.1.1',
        'platforms': {'win32': {'sha256': 'a' * 64, 'size': 10}},
    }
    path = tmp_path / 'version.json'
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return path


def _run_tool(feed: Path, key: Path, *, verify: bool = False):
    command = [sys.executable, str(SIGN_TOOL), str(feed), '--key', str(key)]
    if verify:
        command.append('--verify')
    return subprocess.run(command, capture_output=True, text=True, check=False)


def _client_verify(payload: dict, public_key: Path, monkeypatch):
    monkeypatch.setenv('CIXI_UPDATE_PUBKEY', str(public_key))
    sys.path.insert(0, str(REPO / 'backend'))
    from services import update

    update.verify_feed_signature(payload)


class TestTheSignedFeed:
    def test_a_signed_feed_is_accepted_and_re_verifies(self, feed, keypair, monkeypatch):
        private_key, public_key = keypair
        assert _run_tool(feed, private_key).returncode == 0
        signed = json.loads(feed.read_text(encoding='utf-8'))
        assert signed.get('signature'), 'the tool wrote no signature'

        _client_verify(signed, public_key, monkeypatch)
        assert _run_tool(feed, public_key, verify=True).returncode == 0

    def test_editing_the_document_after_signing_is_refused(self, feed, keypair, monkeypatch):
        private_key, public_key = keypair
        assert _run_tool(feed, private_key).returncode == 0
        signed = json.loads(feed.read_text(encoding='utf-8'))
        signed['platforms']['win32']['sha256'] = 'b' * 64

        with pytest.raises(ValueError):
            _client_verify(signed, public_key, monkeypatch)

    def test_a_configured_key_makes_a_missing_signature_a_refusal(self, feed, keypair, monkeypatch):
        """Failure closed: "no signature" must not read as "nothing to check" once a key exists."""
        _private_key, public_key = keypair
        payload = json.loads(feed.read_text(encoding='utf-8'))
        with pytest.raises(ValueError):
            _client_verify(payload, public_key, monkeypatch)

    def test_without_a_key_the_update_still_works(self, feed, monkeypatch):
        """The fallback the product cannot do without: nothing is gained by refusing every update."""
        monkeypatch.delenv('CIXI_UPDATE_PUBKEY', raising=False)
        monkeypatch.setattr('core.config.Config.DATA_DIR', str(feed.parent), raising=False)
        sys.path.insert(0, str(REPO / 'backend'))
        from services import update

        update.verify_feed_signature(json.loads(feed.read_text(encoding='utf-8')))
