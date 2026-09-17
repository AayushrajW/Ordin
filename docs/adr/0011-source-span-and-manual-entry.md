# 0011 — `source_span` is required of machines, not of people

## Context
Security invariant 7:

> Every AI-derived field carries `source_span` (char offsets into the OCR text),
> `confidence`, `source` (regex|ner|llm|human), `provider`, `model` and
> `prompt_version`. **No span means the field is rejected at the schema boundary.**

And slice 5a's specification:

> Low OCR confidence or handwriting → `requires_manual_entry`.

These contradict. A field a human typed *because the OCR could not read it* has no
char offsets into the OCR text — there is nothing to point at. Enforced literally, the
invariant rejects exactly the fields the manual-entry path exists to create. This is
why `ExtractedField` was deferred out of slice 2 rather than guessed at in a migration.

Note the invariant's own enum already contains `human`, which is the seam: a field
whose `source` is a person is not "AI-derived", and the sentence was written about
machine output.

## Decision
`source_span` is **required when `source` is machine-derived** (`regex`, `ner`, `llm`)
and **permitted to be NULL only when `source = 'human'`**. Enforced by a CHECK
constraint in the migration, not by convention:

    CHECK (source = 'human' OR source_span_start IS NOT NULL)

A human-entered field instead carries `entered_by` and `entered_at`, which are NOT
NULL for `source = 'human'`. The provenance question does not disappear — it changes
from "which characters did this come from?" to "which person asserted this, and when?"
Accountability replaces traceability when traceability is impossible.

Machine fields additionally carry `confidence`, `provider`, `model` and
`prompt_version` as the invariant requires. For `regex` these are the pattern id and
the extractor version, not a model name — the field is populated honestly rather than
left null to look tidy.

## Consequences
- The manual-entry path is a first-class route rather than a violation. CLAUDE.md
  already calls deterministic extraction plus manual entry "a complete path, not a
  degraded one"; the schema now agrees.
- A machine field with no span is still rejected at the schema boundary, which is the
  half of the invariant that was actually protecting something: it stops a pipeline
  stage inventing a value it cannot point at.
- The CHECK means the guarantee survives a direct database write, which a Pydantic
  validator does not (the coverage pass raised exactly this about invariant 7).
- A human field cannot be highlighted in the source scan, because there is nothing to
  highlight. The verification UI in slice 5b must show it differently rather than
  pointing at an arbitrary offset.
