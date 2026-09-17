---
description: Start a slice — plan first, test first, then build
---

Slice: $ARGUMENTS

1. Read `CLAUDE.md` and this slice's entry in `BOOTSTRAP.md`.
2. Enter plan mode. Propose: the acceptance test, the files you will touch, the
   domain/application/interface split, and which CLAUDE.md invariants apply.
   Flag any invariant this slice could plausibly violate. Wait for approval.
3. On approval: write the acceptance test first and watch it fail.
4. Implement until green. Commit.
5. If the slice sprawls beyond this window, stop, split it, and record the split
   in `docs/STATUS.md` rather than pushing on.

Do not add a dependency without asking. State purpose, licence, RAM cost and
production replacement path.
