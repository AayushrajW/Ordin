---
description: End a session safely — green, committed, written down
---

Close out this session. Do not skip steps, and tell me plainly if one fails.

1. Run `python tasks.py test`. If anything fails, fix it or revert the offending change —
   never end a session red.
2. Stage and commit all work with a conventional-commit message.
3. Rewrite `docs/STATUS.md` so a cold session can resume without me. Include:
   - current slice and acceptance criterion
   - what landed this session
   - what is half-done and the exact file and function it stopped at
   - the next concrete action
   - open questions or anything surprising found
   - slices completed so far, as a checklist
   Write it for someone with no memory of this conversation. No "as discussed".
4. If a real decision was made, write `docs/adr/NNNN-title.md` (~15 lines:
   context, decision, consequences).
5. If a slice completed, write its `docs/modules/NN-name.md` brief: what it does,
   why this design, and the two questions a judge will ask with answers.
6. Report what you wrote in three lines.
