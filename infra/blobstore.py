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
    def digest_of_stored(self, address: str) -> str | None:
        """Hash what is actually on disk right now.

        Deliberately re-reads rather than trusting the address. The whole point of
        `verify()` is to detect bytes that changed underneath us, and an
        implementation that returned the address here would report VERIFIED for a
        file somebody had edited in place.
        """


class LocalBlobStore(BlobStore):
    """Filesystem implementation. Fan-out by digest prefix to keep directories small."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, address: str) -> Path:
        if len(address) != 64 or not all(c in "0123456789abcdef" for c in address):
            raise ValueError("address must be a sha256 hex digest")
        return self.root / address[:2] / address[2:4] / address

    def put(self, data: bytes) -> str:
        address = sha256_bytes(data)
        path = self._path(address)
        if path.exists():
            # Same address means same bytes. Rewriting would be a no-op at best and
            # a mutation at worst, and originals are never mutated.
            return address
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temporary name and move, so a crash mid-write cannot leave a
        # truncated file at a valid content address - which would verify as MISMATCH
        # forever and look like tampering.
        temporary = path.with_suffix(".partial")
        temporary.write_bytes(data)
        temporary.replace(path)
        return address

    def get(self, address: str) -> bytes | None:
        path = self._path(address)
        return path.read_bytes() if path.exists() else None

    def exists(self, address: str) -> bool:
        return self._path(address).exists()

    def digest_of_stored(self, address: str) -> str | None:
        data = self.get(address)
        return None if data is None else sha256_bytes(data)
