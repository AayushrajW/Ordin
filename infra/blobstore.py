"""Content-addressed blob storage.

CLAUDE.md: "Blob storage is the local filesystem behind a `BlobStore` interface."
The interface is what matters — it is the seam a real object store slots into — so it
is declared explicitly rather than left implicit in the one implementation.

**Content-addressed, and immutable.** A blob's path is derived from the SHA-256 of its
bytes, so writing the same content twice is idempotent by construction and writing
*different* content to an existing address is impossible. Originals are never
overwritten or mutated (reliability invariant); versions are append-only.

Note what content-addressing does NOT do here. It deduplicates identical bytes within
the store, which means the presence of an address leaks that *someone* stored those
bytes. That is the cross-case existence oracle in threat INS-06, and the control for
it is not in this file: docs/adr/0004 scopes the *idempotency key* to the case, so the
pipeline never asks "does this content already exist?" across a case boundary. This
store answers only what its caller asks.
"""
import hashlib
from abc import ABC, abstractmethod
from pathlib import Path

from infra.crypto import DecryptionFailed, MasterKey, is_sealed, seal, unseal


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class BlobStore(ABC):
    """The seam. `LocalBlobStore` today; an object store behind the same methods later."""

    maturity = "mvp"
    production_adapter = "an S3-compatible object store with server-side encryption"

    @abstractmethod
    def put(self, data: bytes) -> str:
        """Store bytes, return their content address. Idempotent."""

    @abstractmethod
    def get(self, address: str) -> bytes | None:
        """Return the bytes, or None if they are not present."""

    @abstractmethod
    def exists(self, address: str) -> bool: ...

    @abstractmethod
    def delete(self, address: str) -> bool:
        """Destroy the stored bytes. Returns whether anything was there to destroy.

        The one operation that contradicts "originals are never overwritten or
        mutated", and it exists for exactly one caller: a recorded, lawful disposal
        (`POST /versions/{id}/dispose`). Nothing in the pipeline may call this.

        The honest claim is bounded and worth stating in the interface itself: **this
        destroys the stored original.** Write-ahead logs, filesystem snapshots and
        backups taken before now are out of reach of any code here (threat AR-13).
        """

    @abstractmethod
    def digest_of_stored(self, address: str) -> str | None:
        """Hash what is actually on disk right now.

        Deliberately re-reads rather than trusting the address. The whole point of
        `verify()` is to detect bytes that changed underneath us, and an
        implementation that returned the address here would report VERIFIED for a
        file somebody had edited in place.
        """


class LocalBlobStore(BlobStore):
    """Filesystem implementation. Fan-out by digest prefix to keep directories small."""

    def __init__(self, root: Path | str, master: MasterKey | None = None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        # None means "write plaintext", which is what a development checkout with no
        # key configured does. `Settings.refuse_unsafe_production` is where a
        # deployment is made to configure one — the decision belongs there, not here.
        self.master = master

    @property
    def encrypted(self) -> bool:
        return self.master is not None

    def _path(self, address: str) -> Path:
        if len(address) != 64 or not all(c in "0123456789abcdef" for c in address):
            raise ValueError("address must be a sha256 hex digest")
        return self.root / address[:2] / address[2:4] / address

    def put(self, data: bytes) -> str:
        # **The address is the digest of the PLAINTEXT**, not of the envelope. Two
        # things depend on that and would both break silently otherwise: content
        # addressing stays idempotent (the same document encrypts to different bytes
        # every time, because the data key and nonces are fresh), and `verify()` keeps
        # comparing what was anchored with what is held.
        address = sha256_bytes(data)
        path = self._path(address)
        if path.exists():
            # Same address means same bytes. Rewriting would be a no-op at best and
            # a mutation at worst, and originals are never mutated.
            return address
        path.parent.mkdir(parents=True, exist_ok=True)
        stored = seal(data, self.master) if self.master else data
        # Write to a temporary name and move, so a crash mid-write cannot leave a
        # truncated file at a valid content address - which would verify as MISMATCH
        # forever and look like tampering.
        temporary = path.with_suffix(".partial")
        temporary.write_bytes(stored)
        temporary.replace(path)
        return address

    def get(self, address: str) -> bytes | None:
        """The plaintext, or None if it is not there.

        Raises `DecryptionFailed` when a blob is an envelope that will not open —
        which means the bytes changed or the key is wrong. Deliberately **not** None:
        None means "not present", which `verify()` maps to UNAVAILABLE, and a tampered
        document reported as missing would be the wrong answer to the one question this
        system exists to answer.
        """
        path = self._path(address)
        if not path.exists():
            return None
        raw = path.read_bytes()
        if not is_sealed(raw):
            # Written before encryption was configured. Readable on purpose: a store
            # that could not read what it wrote yesterday would make turning encryption
            # on a data-loss event.
            return raw
        if self.master is None:
            raise DecryptionFailed("blob is encrypted and no master key is configured")
        return unseal(raw, self.master)

    def exists(self, address: str) -> bool:
        return self._path(address).exists()

    def delete(self, address: str) -> bool:
        """Unlink the file, if it is there.

        **The caller decides whether it may.** This store is content-addressed, so one
        file can back several versions - the same document filed into two cases, or a
        version superseded by an identical re-upload. Deleting on behalf of one of them
        destroys the others, and the store cannot see them to know. `dispose_version`
        checks that no surviving version shares the address before calling this, and
        that check belongs there because it is a question about the case record.
        """
        path = self._path(address)
        if not path.exists():
            return False
        path.unlink()
        return True

    def digest_of_stored(self, address: str) -> str | None:
        """Hash what is actually held, re-reading rather than trusting the address.

        When an envelope fails to open, the digest of the raw file is returned. It
        cannot equal the address — the address is a digest of plaintext — so `verify()`
        reports **MISMATCH**, which is the truthful answer: the bytes are not the bytes
        that were stored. Returning None here would say UNAVAILABLE and turn a detected
        tamper into a missing file.
        """
        try:
            data = self.get(address)
        except DecryptionFailed:
            path = self._path(address)
            return sha256_bytes(path.read_bytes()) if path.exists() else None
        return None if data is None else sha256_bytes(data)
