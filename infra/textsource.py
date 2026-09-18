"""Getting text out of a document, with char offsets that point back at pixels.

Two implementations behind one interface, and the distinction between them is an
honesty requirement rather than a design preference (docs/adr/0012):

  `TesseractOcr`        rasterises the page and runs Tesseract on the image. This is
                        OCR. Its output is what slice 11a may measure a character
                        error rate against.

  `EmbeddedTextLayer`   reads a text layer the originating system authored. This is
                        NOT OCR, is recorded as `method='embedded_text_layer'`, and
                        must be excluded from any accuracy figure. Comparing it to the
                        text it was generated from would score ~100% and mean nothing.

**A missing Tesseract is a failed stage, not a silent fallback to the text layer.**
That substitution would produce perfect text and a perfect score on a machine where
OCR is not installed, which is the most flattering possible way to be wrong.

Every word carries a character span into the assembled text and a rectangle on the
page. That mapping is the thing slice 5b needs to highlight a field's source span in
the scan, and the thing slice 7 needs to know where to redact.
"""
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

import fitz

RASTER_DPI = 200

# **Confidence is 0..1 everywhere in this system.** Tesseract reports 0..100 and the
# figure was stored raw, so `ocr_text.mean_confidence` held 92.5 while
# `extracted_field.confidence` held 1.0 — two columns with the same name, the same
# type and different scales. The screen rendered "mean confidence 9252.6%", which is
# how it was noticed; the real cost is that any future comparison or threshold across
# the two would have been wrong and would not have looked wrong.
CONFIDENCE_SCALE = 100.0

# Below this mean confidence the page goes to a human rather than being trusted.
# Slice 5a's spec: "Low OCR confidence or handwriting -> requires_manual_entry".
MANUAL_ENTRY_CONFIDENCE_THRESHOLD = 0.70


@dataclass(frozen=True)
class Word:
    text: str
    char_start: int
    char_end: int
    x0: float
    y0: float
    x1: float
    y1: float
    confidence: float | None
    page_no: int = 0


@dataclass
class TextResult:
    text: str
    words: list[Word] = field(default_factory=list)
    method: str = "tesseract_ocr"
    provider: str = ""
    model: str = ""
    maturity: str = "mvp"
    mean_confidence: float | None = None
    requires_manual_entry: bool = False


class TextSourceUnavailable(RuntimeError):
    """The engine is not installed. A failed stage, never a fallback."""


def _break_line(chunks: list[str]) -> int:
    """End the current line. Returns how many characters that added (0 or 1).

    Words are appended followed by a separator, so at a line boundary the separator
    that is already there is *converted* to a newline rather than a newline being
    added. That keeps every character offset recorded so far exact. Adding one instead
    would shift every later span by one per line, and a span off by a few characters
    aims the redaction at the wrong pixels.
    """
    if chunks and chunks[-1] == " ":
        chunks[-1] = "\n"
        return 0
    chunks.append("\n")
    return 1


class TextSource(ABC):
    method: str
    maturity = "mvp"

    @abstractmethod
    def extract(self, pdf_bytes: bytes) -> TextResult: ...


class TesseractOcr(TextSource):
    """Real OCR: rasterise, then read pixels."""

    method = "tesseract_ocr"
    production_adapter = "a managed OCR service, or Tesseract with a tuned model set"

    def __init__(self, languages: str = "hin+eng", dpi: int = RASTER_DPI) -> None:
        self.languages = languages
        self.dpi = dpi

    @staticmethod
    def available() -> bool:
        return shutil.which("tesseract") is not None

    def _binary(self) -> str:
        path = shutil.which("tesseract")
        if not path:
            raise TextSourceUnavailable(
                "tesseract is not installed. The OCR stage fails rather than falling "
                "back to the embedded text layer, which would produce perfect text "
                "and a meaningless accuracy figure (docs/adr/0012)."
            )
        return path

    def _version(self) -> str:
        out = subprocess.run(
            [self._binary(), "--version"], capture_output=True, text=True, timeout=30
        )
        first = (out.stdout or out.stderr or "").splitlines()
        return first[0].strip() if first else "tesseract"

    def extract(self, pdf_bytes: bytes) -> TextResult:
        binary = self._binary()
        import tempfile

        words: list[Word] = []
        chunks: list[str] = []
        cursor = 0
        confidences: list[float] = []

        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc, tempfile.TemporaryDirectory() as tmp:
            for page_no, page in enumerate(doc):
                image_path = Path(tmp) / f"p{page_no}.png"
                page.get_pixmap(dpi=self.dpi).save(str(image_path))

                result = subprocess.run(
                    [binary, str(image_path), "stdout", "-l", self.languages, "--psm", "6", "tsv"],
                    capture_output=True, text=True, encoding="utf-8", timeout=180,
                )
                if result.returncode != 0:
                    raise TextSourceUnavailable(
                        f"tesseract exited {result.returncode} on page {page_no}"
                    )

                scale = 72.0 / self.dpi  # back to PDF points, so boxes match the page
                # Tesseract reports block, paragraph and line numbers, and they
                # matter. Assembling every word into one long line makes every
                # `Label: value` pattern fail, because the value can never reach a
                # line ending - which is exactly what happened the first time.
                previous_line: tuple[int, int, int] | None = None
                for row in (result.stdout or "").splitlines()[1:]:
                    parts = row.split("\t")
                    if len(parts) < 12:
                        continue
                    text = parts[11].strip()
                    if not text:
                        continue
                    try:
                        block, paragraph, line_no = (int(parts[i]) for i in (2, 3, 4))
                        left, top, width, height = (int(parts[i]) for i in (6, 7, 8, 9))
                        confidence = float(parts[10])
                    except ValueError:
                        continue
                    if confidence < 0:
                        continue
                    # Normalised at the boundary, so nothing downstream has to know
                    # that this engine counts to a hundred.
                    confidence /= CONFIDENCE_SCALE

                    here = (block, paragraph, line_no)
                    if previous_line is not None and here != previous_line:
                        cursor += _break_line(chunks)
                    previous_line = here

                    start = cursor
                    chunks.append(text)
                    cursor += len(text)
                    words.append(
                        Word(
                            text=text,
                            char_start=start,
                            char_end=cursor,
                            x0=left * scale,
                            y0=top * scale,
                            x1=(left + width) * scale,
                            y1=(top + height) * scale,
                            confidence=confidence,
                            page_no=page_no,
                        )
                    )
                    chunks.append(" ")
                    cursor += 1
                    confidences.append(confidence)

                chunks.append("\n")
                cursor += 1

        mean = sum(confidences) / len(confidences) if confidences else None
        return TextResult(
            text="".join(chunks),
            words=words,
            method=self.method,
            provider="tesseract",
            model=self._version(),
            mean_confidence=mean,
            # No text at all also routes to a human: a blank result is not a
            # confident answer that the page is blank.
            requires_manual_entry=(mean is None or mean < MANUAL_ENTRY_CONFIDENCE_THRESHOLD),
        )


class EmbeddedTextLayer(TextSource):
    """Reads a text layer the originating system authored. **This is not OCR.**

    Legitimate when a PDF genuinely carries authored text - reading it beats OCR-ing a
    render of it. Recorded as its own method so no accuracy figure can be computed
    from it by accident.
    """

    method = "embedded_text_layer"
    production_adapter = "unchanged"

    def extract(self, pdf_bytes: bytes) -> TextResult:
        words: list[Word] = []
        chunks: list[str] = []
        cursor = 0

        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            for page_no, page in enumerate(doc):
                previous_line: tuple[int, int] | None = None
                # get_text("words") yields (x0,y0,x1,y1, text, block, line, word).
                for w in page.get_text("words"):
                    x0, y0, x1, y1, text = w[0], w[1], w[2], w[3], w[4]
                    if not text.strip():
                        continue
                    here = (w[5], w[6])
                    if previous_line is not None and here != previous_line:
                        cursor += _break_line(chunks)
                    previous_line = here
                    start = cursor
                    chunks.append(text)
                    cursor += len(text)
                    words.append(
                        Word(text=text, char_start=start, char_end=cursor,
                             x0=x0, y0=y0, x1=x1, y1=y1,
                             confidence=None, page_no=page_no)
                    )
                    chunks.append(" ")
                    cursor += 1
                chunks.append("\n")
                cursor += 1

        return TextResult(
            text="".join(chunks),
            words=words,
            method=self.method,
            provider="pymupdf",
            model="text-layer",
            mean_confidence=None,
            # No confidence to threshold on: authored text is either there or not.
            requires_manual_entry=not words,
        )
