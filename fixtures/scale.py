"""Slice 6b: more documents, and a degradation pass.

Two separate jobs, and the second is the one that matters.

**Scale.** The hand-written corpus in `generate.py` is ten documents chosen to cover
the cases the tests need: two languages, a witness statement, a medical memo, the
document slice 7 redacts. Scaling means *variants* — the same document shapes with
different fictional people, stations and references — generated from a seeded
`random.Random` so the corpus is reproducible. A corpus that differs between two
machines is a corpus you cannot compare two accuracy figures from.

**Degradation.** Every fixture so far is a clean born-digital render, and slice 11a's
0.34% English character error rate is a figure measured on exactly that. Real intake is
photographed and scanned paper. This applies, without adding a dependency:

  - a small **skew**, applied to the raster rather than to the text, so the lines keep
    their relationship to each other — a crooked sheet, not crooked typing;
  - a **resolution drop**, rasterising at 120 dpi rather than the 200 the OCR path
    uses, so the engine sees fewer pixels per glyph than the renderer drew;
  - **speckle**, a scatter of dark pixels standing in for sensor noise and paper
    grain;
  - and the result is re-wrapped as an **image-only PDF**, so there is no text layer
    to fall back to and the OCR figure is a figure about OCR.

**What it does not model, said plainly**: compression artefacts, uneven illumination,
shadow gradients, fold lines, handwriting, or a phone camera's perspective distortion.
It is a floor on how much worse real paper is, not an estimate of it.

**Degraded documents carry no bounding boxes.** The skew moves every glyph, and a
sidecar box that no longer covers its value would let slice 7's redaction test pass
while the name stayed legible — the exact failure `test_fixture_corpus.py` exists to
catch. The ground-truth *text* is unaffected, because it is recorded before rendering,
so these documents still measure character error rate. They are excluded from the
geometry tests by the `degraded` flag in their own sidecar.
"""
import json
import random
from dataclasses import replace
from pathlib import Path

import fitz

from fixtures.generate import CORPUS, DEFAULT_OUT, Doc, Field, _render

# Fictional throughout, and visibly so. No real person, station or district.
GIVEN = [
    "Anjali", "Farida", "Sunita", "Rukmini", "Devika", "Parvati", "Zainab", "Lalita",
    "Kamala", "Nafisa", "Shreya", "Bhavna", "Ismat", "Gauri", "Meenakshi", "Rehana",
]
FAMILY = [
    "Bhosle", "Sheikh", "Kale", "Iyer", "Deshmukh", "Nandgaonkar", "Qureshi", "Patil",
    "Raut", "Wagh", "Fernandes", "Dandekar", "Sayyed", "Gokhale",
]
STREETS = [
    "Marigold Lane", "Tamarind Road", "Canal Street", "Old Mill Path", "Banyan Cross",
    "Kumbhar Wadi", "Station Approach", "Fig Tree Lane",
]
STATIONS = [
    ("Vranaspur North Police Station", "VRN-N"),
    ("Vranaspur South Police Station", "VRN-S"),
    ("Kalimath Road Police Station", "KMR-E"),
    ("Sundarhalli Police Station", "SDH-W"),
]

# Rasterised well below the 200 dpi the OCR path renders at, so the engine genuinely
# sees a coarser page rather than the same page relabelled.
DEGRADED_DPI = 120
SKEW_DEGREES = 0.8
SPECKLES_PER_PAGE = 900


def _variant(rng: random.Random, template: Doc, index: int) -> Doc:
    """One document of the same shape, with different fictional particulars."""
    station, code = rng.choice(STATIONS)
    reference = f"{code}/2026/{index:04d}"
    person = f"{rng.choice(GIVEN)} {rng.choice(FAMILY)}"
    address = f"{rng.randint(1, 99)} {rng.choice(STREETS)}, {station.split()[0]}"

    fields: list[Field] = []
    for original in template.fields:
        if original.label.endswith("_name"):
            fields.append(Field(original.label, person))
        elif original.label.endswith("_address"):
            fields.append(Field(original.label, address))
        elif original.label.endswith("_phone"):
            fields.append(Field(original.label, f"09{rng.randint(10**8, 10**9 - 1)}"))
        else:
            fields.append(original)

    return replace(
        template,
        slug=f"{template.slug.split('-')[0]}-{index:04d}",
        station=station,
        reference=reference,
        fields=fields,
    )


def _render_skewed(doc: Doc, out_dir: Path) -> Path:
    """Render cleanly, then re-emit the page as a tilted, coarse, speckled image.

    The tilt is a rotation matrix applied while rasterising, because PyMuPDF's page
    rotation is 90-degree steps only. Rotating the raster rather than the text means
    the relationship between lines is preserved — a crooked sheet, not crooked typing,
    which is what a scanner actually produces.
    """
    path = _render(doc, out_dir)
    rng = random.Random(doc.slug)

    # Opened from bytes, not from the path: on Windows the file stays locked while a
    # Document holds it, and saving over it fails with a permission error.
    source = fitz.open(stream=path.read_bytes(), filetype="pdf")
    out = fitz.open()
    for page in source:
        scale = DEGRADED_DPI / 72
        matrix = fitz.Matrix(scale, scale).prerotate(SKEW_DEGREES)
        pixmap = page.get_pixmap(matrix=matrix, colorspace=fitz.csGRAY)
        for _ in range(SPECKLES_PER_PAGE):
            pixmap.set_pixel(
                rng.randrange(pixmap.width), rng.randrange(pixmap.height),
                (rng.randrange(0, 90),),
            )
        target = out.new_page(width=page.rect.width, height=page.rect.height)
        target.insert_image(page.rect, pixmap=pixmap)
    rendered = out.tobytes(garbage=4, deflate=True)
    out.close()
    source.close()
    path.write_bytes(rendered)
    return path


def scale_corpus(
    out_dir: Path | str = DEFAULT_OUT, *, count: int = 48, degraded_share: float = 0.25,
    seed: int = 26190,
) -> dict:
    """Generate `count` documents, a share of them degraded. Deterministic for a seed.

    The ten hand-written documents are emitted first and unchanged: the tests and the
    demo depend on them by slug, and a corpus whose first ten members moved would be a
    corpus that breaks slice 7 every time it is regenerated.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for stale in list(out.glob("*.pdf")) + list(out.glob("*.json")):
        stale.unlink()

    rng = random.Random(seed)
    written: list[Path] = []
    degraded: list[str] = []

    for doc in CORPUS:
        written.append(_render(doc, out))

    index = 1000
    while len(written) < count:
        index += 1
        template = CORPUS[rng.randrange(len(CORPUS))]
        variant = _variant(rng, template, index)
        should_degrade = rng.random() < degraded_share

        path = _render_skewed(variant, out) if should_degrade else _render(variant, out)
        sidecar = path.with_suffix(".json")
        record = json.loads(sidecar.read_text(encoding="utf-8"))
        record["degraded"] = should_degrade
        if should_degrade:
            # The boxes were measured before the tilt and no longer describe the page.
            # Recording them anyway would be worse than recording none.
            record["identifying_fields"] = []
            record["degradation"] = {
                "dpi": DEGRADED_DPI,
                "skew_degrees": SKEW_DEGREES,
                "speckles": SPECKLES_PER_PAGE,
                "text_layer": False,
                "not_modelled": [
                    "compression artefacts",
                    "uneven illumination",
                    "fold lines",
                    "handwriting",
                    "camera perspective",
                ],
            }
            degraded.append(path.stem)
        sidecar.write_text(
            json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        written.append(path)

    return {
        "documents": len(written),
        "handwritten": len(CORPUS),
        "degraded": degraded,
        "seed": seed,
    }


if __name__ == "__main__":
    summary = scale_corpus()
    print(f"  {summary['documents']} documents -> {DEFAULT_OUT}")
    print(f"  {summary['handwritten']} hand-written, {len(summary['degraded'])} degraded")
    print(f"  seed {summary['seed']} - regenerating gives the same corpus")
    print("  degraded documents are image-only: no text layer, tilted, speckled, 120 dpi")
