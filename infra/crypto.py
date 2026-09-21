"""Envelope encryption for stored document bytes.

The deck says documents stay encrypted off-chain. Until this existed they did not:
`LocalBlobStore` wrote plaintext, and a victim's name sat in cleartext in `var/blobs`
for anyone with a shell on the host.

**No cryptography is implemented here.** CLAUDE.md: "never implements custom
cryptography - use established libraries only." This module composes `cryptography`'s
AES-GCM and nothing else. There is no hand-rolled mode, no home-made KDF, no clever
nonce scheme.

## The envelope

    master key (from the environment)
        wraps
    a per-blob data key (32 random bytes, one per blob)
        encrypts
    the document bytes, with AES-256-GCM

Two keys rather than one, for a reason that matters when this becomes real: rotating
the master key rewraps a small key per blob instead of re-encrypting every document in
the store. That is the seam a KMS slots into — `MasterKey` is the interface, and
`EnvironmentMasterKey` declares itself `mvp` and names what replaces it.

## What this does and does not defend against

**Does:** a stolen disk, a backup tarball, a copied `var/blobs`, an operator browsing
the filesystem. The bytes are unreadable without the master key.

**Does not:** anybody who can read the master key, which on this deployment is anybody
who can read the environment of the running process. AR-3 already says a privileged
insider defeats every control in the threat model, and this does not change that. The
honest claim is "encrypted at rest", never "encrypted from the operator".

## Tamper detection

GCM authenticates. A single flipped bit in the ciphertext makes decryption **fail**
rather than return wrong plaintext, which is what an evidence system wants: the failure
is loud. `LocalBlobStore.digest_of_stored` turns that failure into a digest that cannot
match the address, so the five-state `verify()` reports MISMATCH — a tampered document
refused, not a 500.
"""
import os
from abc import ABC, abstractmethod

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Marks a blob as an envelope. Blobs written before encryption existed have no header
# and are still readable: a store that could not read what it wrote yesterday would
# make turning encryption on a data-loss event.
MAGIC = b"ORDIN-ENV1"
KEY_BYTES = 32          # AES-256
NONCE_BYTES = 12        # GCM standard; never reused, one per encryption
WRAPPED_KEY_BYTES = KEY_BYTES + 16  # ciphertext plus GCM tag


class DecryptionFailed(Exception):
    """The bytes are not what was written, or the key is wrong.

    Deliberately one exception for both. Distinguishing "wrong key" from "tampered
    ciphertext" to a caller would be an oracle, and neither answer changes what the
    caller must do: refuse.
    """


class MasterKey(ABC):
    """The seam a key-management service slots into."""

    maturity = "mvp"
    production_adapter = "a KMS or HSM holding the master key off-host"

    @abstractmethod
    def key(self) -> bytes:
        """32 raw bytes."""


class EnvironmentMasterKey(MasterKey):
    """The master key, read from the environment.

    Named for what it is. The key lives in the process environment, so it is readable
    by anybody who can read that environment — which is why `production_adapter` names
    a KMS and why the claim is "encrypted at rest" rather than "encrypted from the
    operator" (AR-3).
    """

    maturity = "mvp"
    production_adapter = "a KMS or HSM holding the master key off-host"

    def __init__(self, material: bytes) -> None:
        if len(material) != KEY_BYTES:
            raise ValueError(
                f"master key must be {KEY_BYTES} bytes, got {len(material)}"
            )
        self._material = material

    @classmethod
    def from_setting(cls, value: str | None) -> "EnvironmentMasterKey | None":
        """Build from the configured value, or None when encryption is not configured.

        None is a real answer, not a failure: a development checkout with no key writes
        plaintext exactly as it did before, and `Settings.refuse_unsafe_production`
        is where a deployment is made to configure one.
        """
        if not value:
            return None
        import base64

        raw = value.strip()
        try:
            material = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        except Exception as exc:  # noqa: BLE001
            raise ValueError("ORDIN_MASTER_KEY is not valid base64") from exc
        return cls(material)

    def key(self) -> bytes:
        return self._material


def generate_master_key() -> str:
    """A new master key, base64 for an environment variable."""
    import base64

    return base64.urlsafe_b64encode(os.urandom(KEY_BYTES)).decode("ascii").rstrip("=")


def seal(plaintext: bytes, master: MasterKey) -> bytes:
    """Wrap a fresh data key and encrypt the bytes with it.

    Layout, fixed width so parsing needs no length fields:

        MAGIC | wrap nonce (12) | wrapped data key (48) | data nonce (12) | ciphertext
    """
    data_key = os.urandom(KEY_BYTES)
    wrap_nonce = os.urandom(NONCE_BYTES)
    data_nonce = os.urandom(NONCE_BYTES)

    wrapped = AESGCM(master.key()).encrypt(wrap_nonce, data_key, MAGIC)
    ciphertext = AESGCM(data_key).encrypt(data_nonce, plaintext, MAGIC)
    return MAGIC + wrap_nonce + wrapped + data_nonce + ciphertext


def is_sealed(blob: bytes) -> bool:
    return blob.startswith(MAGIC)


def unseal(blob: bytes, master: MasterKey) -> bytes:
    """Recover the plaintext. Raises `DecryptionFailed` for anything wrong.

    Anything wrong includes a flipped bit: GCM authenticates, so a modified blob fails
    here rather than returning plausible-looking wrong bytes. For an evidence store
    that is the desired behaviour — the failure is loud and the caller refuses.
    """
    if not is_sealed(blob):
        raise DecryptionFailed("not an envelope")

    head = len(MAGIC)
    wrap_nonce = blob[head:head + NONCE_BYTES]
    wrapped = blob[head + NONCE_BYTES:head + NONCE_BYTES + WRAPPED_KEY_BYTES]
    rest = blob[head + NONCE_BYTES + WRAPPED_KEY_BYTES:]
    data_nonce, ciphertext = rest[:NONCE_BYTES], rest[NONCE_BYTES:]

    if len(wrap_nonce) != NONCE_BYTES or len(wrapped) != WRAPPED_KEY_BYTES:
        raise DecryptionFailed("envelope is truncated")

    try:
        data_key = AESGCM(master.key()).decrypt(wrap_nonce, wrapped, MAGIC)
        return AESGCM(data_key).decrypt(data_nonce, ciphertext, MAGIC)
    except InvalidTag as exc:
        raise DecryptionFailed("authentication failed") from exc
    except Exception as exc:  # noqa: BLE001
        raise DecryptionFailed("envelope could not be opened") from exc
