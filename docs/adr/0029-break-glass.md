# 0029 — Break-glass: the seal has an exception, and the exception pays for itself

## Context
CLAUDE.md: "Sealed records require authorization beyond ordinary clearance." That was
implemented as a flat deny, and a deny with no exception is a design that gets worked
around rather than obeyed. The officer who needs a sealed file at 2am does not go home.
They ring somebody with clearance and use their session — and the system then records
the wrong person reading the wrong file for a reason nobody wrote down.

That is a worse outcome than the access itself. The seal did not hold; it just moved
the event out of the record.

## Decision

**A designated officer may declare a bounded, justified exception to a seal.** It costs
a written justification of at least 40 characters, it expires in minutes to hours, and
it puts a row on the audit chain naming the person who took it.

**Two policies, not one, and the split is the design.**

    ordin.break_glass   may this subject DECLARE an exception?
    ordin.case_read     does an existing declaration COUNT?

`break_glass_active` appears in `ordin.case_read` in exactly one place: the **deny**
rule for sealed records, as a third condition. So it can only subtract an obstacle from
a path the subject already had. In an allow rule it would be a master key — a written
excuse that opens any sealed case in the system. `test_break_glass_is_never_a_ground_for_access`
asserts that placement structurally, over the file, because every example-based test
would still pass if somebody moved it.

**A grant never opens a seal.** `ordin.break_glass` requires an in-force designation in
the same organization and jurisdiction, and names no grant predicate at all. An external
party holding a lawful, purpose-limited grant must not be able to self-authorize past a
seal, because there is nobody upstream of them to answer for it. Merging the two
policies would have let `purpose-limited-grant` do both jobs, which is the single route
this split exists to close.

**The justification lives in `break_glass_access`, never on the chain.** Invariant 4
fixes the audit payload; a free-text column on the audit table is where a case summary,
a victim's name or a witness's address eventually lands. The chain carries the row's id.

**Append-only, with no revocation column.** A justification that can be edited later is
a draft. The window is the control and it closes by itself — a revoke button on a
sixty-minute exception is theatre, and a column that exists to look thorough is worse
than an absent one.

**The order of the checks is the leak control.** Read access is evaluated first; a
subject who can already read the case is told plainly why they do not need this (409),
which is safe precisely because they can already see it. Everybody else gets 404,
whether the case does not exist, is not theirs, or is not sealed. A 409 "this case is
not sealed" for a stranger is an existence oracle (threat INS-04).

**`case_read` went to v2 rather than being edited in place.** v1 stays on disk, because
decisions already in `policy_decision` name it and a version nobody can read is a
decision nobody can explain. That is the whole argument for policy as versioned data —
and `latest_policy_path` now resolves the current version for the app *and* the tests,
because four test files hardcoded `case_read.v1.yaml` and a bump would have left the
suite green while asserting against a file nothing loads.

## Consequences
- **This weakens the seal, deliberately, in exchange for evidence.** An officer who
  would have borrowed a colleague's session now has an easier and fully attributed
  route. The honest claim is "sealed access is exceptional, bounded and recorded",
  never "sealed access is prevented".
- **Nothing reviews the justifications.** Writing one is a cost, not a check — no
  approval, no alert, no supervisor sign-off. AR-15 already records that two-person
  approval was cut; this is another instance of it, not a new gap.
- An officer can declare repeatedly to extend their window. `ordin.break_glass` does not
  read `break_glass_active`, so each declaration is judged on designation alone — but
  each one is a separate row and a separate chain entry, so the pattern is visible.
  Refusing a renewal would push the officer back to borrowing a session.
- The declaration is case-scoped: breaking the glass on one sealed file opens that file
  and no other. The SQL predicate is a row-level EXISTS rather than a lifted constant
  for exactly this reason.
