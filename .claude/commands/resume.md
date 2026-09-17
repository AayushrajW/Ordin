---
description: Cold-start a session — load state, verify the build, report status
---

Do these in order and report concisely. Do not start coding until I confirm.

1. Read `CLAUDE.md`, `BOOTSTRAP.md` and `docs/STATUS.md`.
2. Read the slice file named as current in STATUS.md, if there is one.
3. Run `git log --oneline -8` and `git status --short`.
4. Run `python tasks.py test`. If it fails, that is the first thing to fix — say so.
5. Report, in under 15 lines:
   - current slice and its acceptance criterion
   - test suite state (pass/fail, count)
   - anything uncommitted or half-done, and exactly where it stopped
   - the single next action you propose
   - anything in STATUS.md that looks stale or contradicts the repo

If STATUS.md is missing or empty, say so plainly and propose reconstructing it
from git history rather than guessing.
