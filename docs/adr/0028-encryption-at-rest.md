# 0028 — Envelope encryption at rest, without breaking content addressing

## Context
The deck said documents stay encrypted off-chain. They did not. `LocalBlobStore` wrote
plaintext, so a victim's name sat readable in `var/blobs` for anybody with a shell on
the host, a copy of a backup, or a stolen disk. The deck-vs-build audit listed this as
one of three claims with **nothing behind them**.

The obvious implementation breaks two things quietly. Encryption is non-deterministic —
fresh key, fresh nonce — so addressing a blob by the digest of its stored bytes would
make `put` non-idempotent *and* make `verify()` compare a digest against something that
changes on every write. Both failures look like flakiness rather than like a mistake.

## Decision

**Envelope encryption.** A master key from the environment wraps a per-blob data key of
32 random bytes, which encrypts the document with AES-256-GCM. Two keys rather than
one, because rotating the master then rewraps a small key per blob instead of
re-encrypting every document in the store — and that is the seam a KMS slots into.

**No cryptography is implemented.** `infra/crypto.py` composes the `cryptography`
library's AEAD and nothing else: no hand-rolled mode, no home-made KDF, no clever nonce
scheme. CLAUDE.md forbids custom cryptography by name.

**The content address stays the digest of the plaintext.** Addressing, idempotency and
`verify()` are therefore unchanged, and a test asserts each of them rather than trusting
that they still hold.

**A tampered blob reports MISMATCH, not UNAVAILABLE.** GCM authenticates, so a flipped
bit makes decryption fail loudly instead of returning plausible wrong bytes.
`digest_of_stored` catches that failure and returns the digest of what is *actually*
held, which cannot equal the address. Returning `None` would have said "the bytes are
gone" about a document that is present and altered — the wrong answer to the one
question this system exists to answer.

**A blob written before encryption was configured still opens.** Envelopes carry a
magic header; anything without it is read as plaintext. A store that could not read what
it wrote yesterday would make enabling encryption a data-loss event.

**Production refuses to start without a key.** `ORDIN_MASTER_KEY` joins the session
secret and the database passwords in `refuse_unsafe_production`, because a deployment
silently writing plaintext looks exactly like one that is not.

## Consequences
- **What this defends against:** a stolen disk, a copied backup, an operator browsing
  the filesystem. **What it does not:** anybody who can read the master key, which here
  is anybody who can read the process environment. AR-3 already says a privileged
  insider defeats every control in the threat model; this does not change that. The
  honest claim is "encrypted at rest", never "encrypted from the operator".
- **Losing the master key destroys the store.** `tasks.py newkey` says so in its own
  output, and prints rather than writes, so the key does not land in shell history.
- **Turning encryption on does not encrypt what is already stored.** The store is
  content-addressed, so `put` returns early when the address exists and never rewrites
  it — a blob written before the key was configured stays plaintext for ever, and
  nothing in the application looks wrong. Sentinel CRYPT-03 found this by reporting the
  pipeline as broken when what it had actually found was a pre-existing plaintext blob;
  the scenario now writes unique bytes so it watches the write path, and this paragraph
  exists so the caveat is not lost with it.

  There is no re-encryption command. `tasks.py demo` destroys and regenerates the
  store, which covers the demo; a deployment migrating an existing store needs a pass
  that reads every blob and rewrites it, and that is unbuilt.
- **The derived text is still plaintext in Postgres.** `ocr_text` and `extracted_field`
  hold the same names this encrypts on disk. Field-level encryption is a separate
  decision with a real cost — an encrypted column cannot be searched, and search is
  ADR 0026 — so it is named here as the remaining gap rather than implied to be closed.
- The api, the worker and `demo.py` all build the store from the same setting. A worker
  writing plaintext while the api wrote envelopes would leave half the store readable
  and nothing would look wrong until somebody copied the disk.
