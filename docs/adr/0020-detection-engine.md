# 0020 — A deterministic detection engine for redaction, and consistency checks for review

## Context
Redaction covered the labelled fields and nothing else. A victim's name burned out of
"Victim Name: …" stayed readable two lines later in "Ms Deshmukh stated that…", and the
derivative with the surname in it went to a purpose-limited grantee. Every test and every
Sentinel scenario passed, because every one of them checked the labelled field.

Separately, extraction reported a hardcoded confidence of 1.0 for every value, and on the
specimen complaint Tesseract read the case reference `VRN-N/2026/0001` as `…/0004` and a
phone number with a digit missing — both presented as ordinary drafts.

CLAUDE.md rules out the obvious fixes: no LLM, no NER model, deterministic over ML.

## Decision
`domain/pii.py` finds every identifying span in three layers:
1. **Propagation of known values** — the version's identifying fields and the case's
   recorded parties are searched for across the whole text: exact sequences, OCR-tolerant
   sequences (bounded Damerau-Levenshtein after folding 0/O, 1/l, 5/S, rn/m), surname or
   given name alone, street-level address fragments, and digit sequences through spacing
   and one misread digit.
2. **Pattern detection** — mobile numbers, e-mail, PAN, vehicle registrations, and Aadhaar
   **validated by the Verhoeff check digit**, with single-digit OCR repair when the
   checksum fails. Verhoeff is a published check-digit scheme, not cryptography.
3. **Merging** of overlapping findings, keeping the strongest evidence.

A finding carries kind, span, rule id, confidence and source field — never the matched
text, because findings flow into manifests and logs (invariant 12).

`domain/consistency.py` cross-checks each draft against what the system already knows:
reference against the case it is filed in (with the correct value suggested when one or
two characters differ), phone shape, letters OCR reads for digits, and the OCR engine's
own per-word confidence in place of the pattern's meaningless 1.0.

## Consequences
- Redaction of the specimen statement removes 16 regions instead of 3 lines; Sentinel
  REDACT-05 reads the derivative and fails if any value survives anywhere on the page.
- The operator sees a preview of every region before anything is burned, labelled against
  "elsewhere on the page" — the number that shows what field-only redaction missed.
- A suggestion is only ever a button: accepting it records a `source='human'` value under
  the person's name. The engine proposes; a person commits (invariant 9).
- **Still not closed**: a name that is neither a recorded party nor a labelled field, and
  matches no identifier pattern, is not found. There is no entity recognition. AR-6 is
  narrowed, not retired, and the redaction screen says so.
