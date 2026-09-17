# 0012 — OCR rasterises; extracting a text layer is not OCR

## Context
The slice 6a fixture corpus is generated with PyMuPDF and is **born-digital**: every
page carries a real text layer, and `page.get_text()` returns the exact string that
was drawn.

That makes an attractive shortcut available. The pipeline could "OCR" a document by
extracting its existing text layer — fast, no Tesseract dependency, no rasterising,
and every test would pass.

It would also be a fabricated metric. Slice 11a measures OCR character error rate
against the sidecar's pre-render text. If the "OCR" stage returns the text layer, it is
comparing a string to itself: CER would be approximately zero, the number would be
presented to judges, and it would mean nothing. CLAUDE.md forbids fabricated
statistics, and a metric that measures the wrong thing is the most persuasive kind.

## Decision
The OCR stage **rasterises the page and runs Tesseract on the image**, at 200 dpi,
with `-l hin+eng`, reading TSV output for per-word boxes and confidence. Tesseract 5.5
is invoked as a binary via `subprocess`; no Python wrapper dependency is added.

**Text-layer extraction is available and is not called OCR.** It lives behind the same
`TextSource` interface as `TesseractOcr`, named `EmbeddedTextLayer`, declares
`maturity: mvp`, and exists for one purpose: when a PDF genuinely carries a text layer
authored by the originating system, reading it is better than OCR-ing a render of it.
Any figure derived from it is labelled as text-layer extraction, never as OCR, and
slice 11a must exclude it from character-error-rate entirely.

## Consequences
- The corpus is a real OCR workload despite being born-digital, because the pipeline
  renders it to pixels first. The sidecar's pre-render text stays genuine ground truth,
  which is the whole reason it exists.
- Tesseract becomes a real dependency of the worker: `tesseract-ocr` plus
  `tesseract-ocr-hin` in the worker image (~50 MB, well inside CLAUDE.md's limits).
  This is the first thing that makes the worker diverge from the shared
  `docker/python.Dockerfile`, which ADR 0009 anticipated splitting at this slice.
- Rasterising costs a few seconds per page. Acceptable: it is the honest cost of a
  measurement that means something.
- `EmbeddedTextLayer` must never be silently substituted when Tesseract is missing.
  A missing OCR engine is a failed stage with a recorded error code, not a quiet
  fallback that produces perfect text and a perfect score.
