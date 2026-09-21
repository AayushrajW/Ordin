"""Encryption at rest (ADR 0028).

The deck said documents stay encrypted off-chain. Until this existed they did not:
`LocalBlobStore` wrote plaintext, so a victim's name sat readable in `var/blobs` for
anyone with a shell on the host.

Four properties are load-bearing, and three of them are about *not* breaking something:

1. The bytes on disk are unreadable.
2. **The content address is still the digest of the plaintext.** Encryption produces
   different bytes every time — fresh data key, fresh nonces — so addressing by the
   ciphertext would make `put` non-idempotent and break `verify()` at the same time.
3. **A tampered blob reports MISMATCH, not UNAVAILABLE and not a crash.** GCM makes the
   failure loud; the store turns it into the digest of what is actually held, which
   cannot equal the address. "Missing" and "altered" are different answers and an
   evidence system must not confuse them.
4. **Blobs written before encryption was turned on still open.** A store that could not
   read what it wrote yesterday would make enabling encryption a data-loss event.
"""
import pathlib
import tempfile

import pytest

from infra.blobstore import LocalBlobStore, sha256_bytes
from infra.crypto import (
    DecryptionFailed,
    EnvironmentMasterKey,
    generate_master_key,
    is_sealed,
    seal,
    unseal,
)

SPECIMEN = b"Victim Name: Rukmini Deshmukh\nVictim Phone: 0900000111\n"


@pytest.fixture
def key() -> EnvironmentMasterKey:
    return EnvironmentMasterKey.from_setting(generate_master_key())


@pytest.fixture
def store(key) -> LocalBlobStore:
    return LocalBlobStore(pathlib.Path(tempfile.mkdtemp()), master=key)


def _file_for(store: LocalBlobStore, address: str) -> pathlib.Path:
    return store.root / address[:2] / address[2:4] / address


# --- the envelope itself ---------------------------------------------------------


def test_a_sealed_blob_does_not_contain_the_plaintext(key):
    sealed = seal(SPECIMEN, key)
    assert b"Rukmini" not in sealed
    assert b"0900000111" not in sealed
    assert is_sealed(sealed)


def test_it_round_trips(key):
    assert unseal(seal(SPECIMEN, key), key) == SPECIMEN


def test_the_same_plaintext_seals_differently_every_time(key):
    """Fresh data key and fresh nonces per blob.

    Identical ciphertexts would leak that two documents are the same document, across
    cases the reader may not both be able to open.
    """
    assert seal(SPECIMEN, key) != seal(SPECIMEN, key)


def test_a_different_master_key_cannot_open_it(key):
    other = EnvironmentMasterKey.from_setting(generate_master_key())
    with pytest.raises(DecryptionFailed):
        unseal(seal(SPECIMEN, key), other)


@pytest.mark.parametrize("position", [-1, 20, 40])
def test_a_single_flipped_bit_fails_loudly(key, position):
    """GCM authenticates: a modified blob fails rather than returning wrong bytes."""
    sealed = bytearray(seal(SPECIMEN, key))
    sealed[position] ^= 0x01
    with pytest.raises(DecryptionFailed):
        unseal(bytes(sealed), key)


def test_a_truncated_envelope_is_refused(key):
    with pytest.raises(DecryptionFailed):
        unseal(seal(SPECIMEN, key)[:20], key)


def test_a_master_key_of_the_wrong_length_is_refused():
    with pytest.raises(ValueError, match="32 bytes"):
        EnvironmentMasterKey(b"too short")


def test_no_key_configured_is_a_real_answer_not_an_error():
    """A development checkout with no key writes plaintext, exactly as before."""
    assert EnvironmentMasterKey.from_setting("") is None
    assert EnvironmentMasterKey.from_setting(None) is None


# --- the store -------------------------------------------------------------------


def test_the_name_is_not_readable_on_disk(store):
    address = store.put(SPECIMEN)
    raw = _file_for(store, address).read_bytes()
    assert b"Rukmini" not in raw, "the victim's name is in cleartext on disk"
    assert is_sealed(raw)


def test_the_address_is_still_the_digest_of_the_plaintext(store):
    """Content addressing and verify() both depend on this and would break silently."""
    assert store.put(SPECIMEN) == sha256_bytes(SPECIMEN)


def test_putting_the_same_document_twice_is_still_idempotent(store):
    """Encryption is non-deterministic; addressing must not be."""
    first = store.put(SPECIMEN)
    second = store.put(SPECIMEN)
    assert first == second
    assert store.get(first) == SPECIMEN


def test_it_reads_back(store):
    assert store.get(store.put(SPECIMEN)) == SPECIMEN


def test_verify_still_matches_an_untouched_blob(store):
    address = store.put(SPECIMEN)
    assert store.digest_of_stored(address) == address


def test_a_tampered_blob_reports_mismatch_rather_than_missing(store):
    """The distinction the five-state verify() exists for.

    None here would mean UNAVAILABLE — "the bytes are gone" — for a document that is
    present and altered. That is the wrong answer to the one question this system
    exists to answer.
    """
    address = store.put(SPECIMEN)
    path = _file_for(store, address)
    raw = bytearray(path.read_bytes())
    raw[-1] ^= 0x01
    path.write_bytes(bytes(raw))

    digest = store.digest_of_stored(address)
    assert digest is not None, "a tampered blob reported as missing"
    assert digest != address, "a tampered blob reported as matching"


def test_reading_a_tampered_blob_raises_rather_than_returning_bytes(store):
    address = store.put(SPECIMEN)
    path = _file_for(store, address)
    raw = bytearray(path.read_bytes())
    raw[-1] ^= 0x01
    path.write_bytes(bytes(raw))
    with pytest.raises(DecryptionFailed):
        store.get(address)


def test_a_missing_blob_is_still_none_not_an_error(store):
    assert store.get("0" * 64) is None
    assert store.digest_of_stored("0" * 64) is None


# --- turning it on must not lose yesterday's data --------------------------------


def test_a_plaintext_blob_written_before_encryption_still_opens(key):
    """Enabling encryption must not be a data-loss event."""
    root = pathlib.Path(tempfile.mkdtemp())
    before = LocalBlobStore(root)            # no key: writes plaintext
    address = before.put(SPECIMEN)
    assert not before.encrypted

    after = LocalBlobStore(root, master=key)  # key configured later
    assert after.encrypted
    assert after.get(address) == SPECIMEN, "an older plaintext blob became unreadable"
    assert after.digest_of_stored(address) == address


def test_an_encrypted_blob_without_a_key_refuses_rather_than_returning_garbage(store):
    address = store.put(SPECIMEN)
    keyless = LocalBlobStore(store.root)
    with pytest.raises(DecryptionFailed):
        keyless.get(address)
