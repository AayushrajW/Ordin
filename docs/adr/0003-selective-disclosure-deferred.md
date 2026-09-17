# 0003 — Selective disclosure deferred for budget, not for the cryptography rule

## Context
BOOTSTRAP slice 12 proposes salted Merkle commitments over disclosable units so a
redacted copy still verifies against the anchor. It is the strongest idea in the design.

An earlier draft of the plan recorded this as cut partly for tension with CLAUDE.md's
non-goal "never implements custom cryptography". **That reasoning was wrong and is
corrected here.** A Merkle tree built on `hashlib` composes standard primitives, which
is exactly what the non-goal permits; the rule targets implementing primitives, not
using them. Recording it inaccurately would make a correct future decision harder.

## Decision
Cut slice 12 from this build **for budget alone**. It was priced at 6-8 hours against
zero hours remaining after the hour-30 hard stop.

If built later it declares `maturity: mvp` and claims content binding only.

## Consequences
- A redacted derivative cannot be verified against the original's anchor; it verifies
  only against its own. Acceptable, since the derivative is a first-class version.
- The honest limit must be stated if it is ever built: salted Merkle commitments disclose
  unit boundaries and the number of withheld units by construction. It must never be
  described as providing unlinkability or as concealing how much was withheld.
- The reasoning above is recorded so this is re-decided on cost, not on a misreading of
  the cryptography non-goal.
