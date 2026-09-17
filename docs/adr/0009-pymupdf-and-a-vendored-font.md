# 0009 — PyMuPDF (AGPL), and a vendored Devanagari font

## Context
CLAUDE.md already decides PyMuPDF for destructive redaction and requires the AGPL
licence to be noted in a dependency ADR. Slice 6a is where it first enters the tree,
so this is that note.

Slice 6a also needs to render Devanagari. The build machine has `Nirmala.ttc`, but it
is a proprietary Windows font: not redistributable, and absent from the
`python:3.11-slim` container. Depending on it would produce fixtures that generate on
one machine and fail on the demo path — the exact dev/demo divergence ADR 0006's
two-path acceptance test exists to catch.

## Decision

**PyMuPDF 1.26**, pinned `>=1.24,<1.27`. Purpose: destructive redaction
(`add_redact_annot` + `apply_redactions`, which removes content rather than covering
it) in slice 7, and rendering the fixture corpus in slice 6a. Using the same library
for both means slice 7 exercises a real round trip rather than a happy path built by
a different toolchain. RAM: ~40 MB resident. Alternative considered: `pypdf`, which
cannot remove underlying content and would reduce redaction to drawing rectangles —
i.e. exactly the presentational masking invariant 8 forbids. Production replacement:
unchanged; PyMuPDF is production-grade here.

**Licence: AGPL-3.0.** Acceptable for this submission because Ordin's source is
public. It is the only AGPL component in the tree and it is worth knowing why that
matters: AGPL obligations attach to *network use*, so if Ordin were ever deployed as
a hosted service without publishing source, this dependency would have to be replaced
or licensed commercially. That is a deployment decision, not a hackathon one, and it
is recorded here so it is not discovered later.

**Noto Sans Devanagari, vendored** at `fixtures/fonts/NotoSansDevanagari.ttf` (642 KB)
with its `OFL.txt`. Licence: SIL Open Font License 1.1, which permits redistribution
inside this repository. It travels with the checkout, so Hindi fixtures render
identically on Windows, in the container, and on any machine a judge uses.

## Consequences
- The AGPL note now exists, as CLAUDE.md requires. It is the one licence in the tree
  that constrains future deployment, and the constraint is written down.
- 642 KB of binary in git. Cheap against the alternative: a download step in the build,
  which would break the air-gapped demo path (invariant 11).
- The generator raises a clear error if the font is missing rather than silently
  falling back to a system font — a fallback would work on the build machine and
  produce blank glyphs in the container, which is the worst possible failure shape.
- Field *labels* on the Hindi fixtures remain Latin ("Complainant Name:"), as bilingual
  forms genuinely are. Slice 11a should be aware when breaking character error rate
  down by language: those pages are mixed-script, and the sidecar records exactly what
  is on them so a per-script figure is computable if wanted.
