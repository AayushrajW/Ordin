# 0021 — Verify on read, watermark and audit every view, rate-limit, harden headers

## Context
The build verified integrity only when asked, rendered pages identically for everyone,
recorded no reads, had no rate limiting (accepted risk AR-8), and relied on the web tier
for response headers the API itself should carry.

## Decision
- **Verify on every read.** The page renderer re-hashes the stored bytes against the
  version's digest before drawing a pixel and refuses with `integrity_mismatch` on any
  difference. `GET /versions/{id}/integrity` returns the full five-state verdict from the
  pure `verify_version`, assembled from the version row, the anchor, the disposition record
  and a fresh hash of the bytes. Sentinel INTEG-01 flips a bit on disk and expects both.
- **Watermark every rendered page** with the viewer's name, post and the UTC time, tiled
  and repeated in a footer strip, on an in-memory copy. The stored evidence is never
  touched. It is a visible watermark: it deters and attributes, and is not claimed to be
  steganographic or crop-proof.
- **Audit every view.** Each render appends a `document_viewed` row to the hash-chained
  trail; the document screen shows the custody trail to original readers only.
- **Rate limits** in the API process: 30 session mints per minute per address, 120 writes
  and 120 page renders per minute per session, keyed on hashes rather than raw tokens.
  The in-process scenario runner is exempt by a client host no socket can present.
- **Response hardening** on every API response (no-store, nosniff, frame denial, a
  deny-all CSP, COOP/CORP, Permissions-Policy), mirrored in the web tier, whose form routes
  also refuse cross-site posts by `Sec-Fetch-Site` and `Origin` as a second control beside
  `SameSite=Lax`.

## Consequences
- A tampered page is withheld rather than shown as evidence, and the screen says why.
- The audit trail grows with every view. That is the intended cost of access logging.
- **Stated limits:** the rate limiter is per api process and resets on restart, and behind
  the web tier every browser shares one address, so the session-mint limit is effectively
  global there. AR-8 is narrowed for this build, not closed; production puts limiting in
  front of the api keyed on the real client.
- React's development build needs `eval`; the CSP grants it only when `NODE_ENV` is
  development, so the demo path (`next start`) ships the strict policy.
