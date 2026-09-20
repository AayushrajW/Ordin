# 0026 — Search results are filtered in the query; snippets follow disclosure class

## Context
Invariant 1 names search and autocomplete as the worst offenders, and the reason is
specific: a search that ranks first and filters afterwards returns the right *rows* while
disclosing the wrong things through its **counts**, its **pagination** and its
**snippets**. All three look like features.

There is a second, sharper problem that the case filter does not reach. A grantee holds a
lawful grant, so a case is legitimately theirs to find. The documents in it are not —
they receive a redacted derivative, and **the original's OCR text is the same content in
a different shape** (threat VIC-01, `infra/disclosure.py`). A snippet drawn from
`ocr_text` would hand a grantee precisely what redaction destroyed, through a box built
for convenience. That is the slice-7 leak arriving through a new door.

## Decision

**Every query starts from `authorized_cases` / `authorized_case_ids`**, which return a
`Select` with the policy compiled into the WHERE clause. The reference match is an
additional condition on that select, never a filter over its results. Nothing in
`api/search.py` filters a list in Python.

**Content search is gated by disclosure class, which is stricter than the case filter.**
Designation yields ORIGINAL and its documents are searched; a grant yields REDACTED and
**no document content is searched at all**. A derivative carries no text layer, so there
is genuinely nothing of theirs to search.

**The response says when it did not look.** `content_withheld` and a sentence, because
"your search found nothing" and "your search did not look there" are different facts and
only one of them is a reason to stop looking.

**`plainto_tsquery`, always bound.** The caller's text is words, never query syntax. A
tsquery built by concatenation would let somebody write a boolean expression over an
index they cannot otherwise reach.

**`simple`, not `english`.** The corpus is bilingual. An English stemmer does nothing for
Devanagari and mangles transliterated Hindi. `simple` means no stemming and no stop-word
removal — a real loss, taken deliberately, because silently dropping Hindi from a
bilingual system's search would be worse than losing "investigating" matching
"investigate".

**No index on `extracted_field.value`.** Those rows are names, phone numbers and
addresses; an index over them is an index of victims and witnesses.

## Consequences
- Snippets are marked by `ts_headline` with `<<` and `>>`, deliberately not HTML. OCR
  text is untrusted data (invariant 6); the page splits on the markers and renders text
  nodes, so React escapes everything.
- Two Sentinel scenarios, both critical. SEARCH-01 searches the exact reference of an
  unreachable case. SEARCH-02 takes a word from an original's own OCR text and checks the
  officer gets snippets and the grantee gets none.
- **SEARCH-02 failed on its first run, and the fault was in the scenario.** It asserted
  the grantee could still find their case using the *word* query, but case matching is on
  the reference, so that query returns no cases to anybody. Worth recording: a scenario
  that asserts the wrong thing reports the system broken, and the version of that mistake
  which asserts too little reports it sound.
- A single-letter query is refused at two characters. Autocomplete on one letter is the
  precise behaviour invariant 1 calls the worst offender.
