# 04a — Storage and integrity

> Status: complete (`314406e`).

## What it does

Content-addressed immutable blob storage behind a `BlobStore` interface,
`LocalAnchorStore` (hash-chained, deliberately not called a ledger), a `disposition`
record, and `verify()` returning one of five states:
`VERIFIED | MISMATCH | DISPOSED_ANCHOR_ONLY | PENDING | UNAVAILABLE`.

## Why this design

**A state, never a boolean.** The reasoning is legal as much as technical: a lawfully
disposed document reported as MISMATCH is not a cosmetic bug, it is a claim that
evidence was tampered with.

**Decision order is the design.** Disposal is checked before the bytes, because a
disposed document has no bytes by design and checking them first reports MISMATCH for a
lawful disposal. Absence of an anchor is checked before absence of bytes, because a
document mid-pipeline has a digest and no anchor and that is normal. Both orderings
have a test that fails if they are swapped.

**`PENDING` was added and CLAUDE.md amended** (ADR 0010). The original four states
collapsed "not yet anchored" into `UNAVAILABLE`, which already meant the bytes are
gone, the store is unreachable, or you may not see it at all — so the most common
transient condition in the system shared a state with an incident.

**A version row disagreeing with its own anchor is a MISMATCH** even when the bytes
match the anchor. That is the shape of an insider edit that updates the version record
and leaves the anchor alone, hoping only the bytes get compared.

## The two questions a judge will ask

**"Is this a blockchain?"**

No, and the code refuses to imply it. The class is `LocalAnchorStore`; only a Fabric
adapter would be allowed ledger vocabulary, and the guard hook blocks the naming. What
it is: each anchor commits to its predecessor, so altering one in place breaks every
anchor after it. What it is not, stated in the module docstring rather than discovered
under questioning — the digest is unkeyed so whoever can write the table can recompute
it; truncating the tail leaves a valid prefix and is undetectable; and the anchor sits
in the same database under the same administrator as the artefact it anchors, so it is
**not an independent attestation**. That is accepted risk AR-4, and it belongs in the
pitch before a judge raises it.

**"What does `verify()` actually compare?"**

The bytes on disk, re-read and re-hashed, against the digest recorded in the anchor —
and separately the version row against the same anchor. `digest_of_stored` deliberately
re-reads rather than returning the address it was handed; an implementation that
trusted the address would report VERIFIED for a file someone had edited in place, which
is the one thing the function exists to catch.
