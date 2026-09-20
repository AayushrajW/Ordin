"""Synthetic fixture corpus.

Produces 8-12 fictional documents as PDFs, each with a ground-truth sidecar. Run with
`python tasks.py fixtures`.

**Everything here is visibly synthetic**, per CLAUDE.md: fictional names, fictional
station codes, and `SPECIMEN - NOT A REAL RECORD` stamped on every page. Nothing here
cites a statutory section, because CLAUDE.md forbids guessing them and a fixture is
exactly where an invented section number would quietly become "the one we showed the
judge".

## Why a sidecar

The PDFs are the boring half. The sidecar is what two later slices consume:

  slice 11a  OCR character error rate. `pages[].text` is the exact string placed on
             the page *before* rendering. Tesseract never sees it, so comparing its
             output against it measures OCR, not agreement with ourselves. (The
             extraction metric was cut for exactly that reason - PLAN R9.)

  slice 7    Destructive redaction. `identifying_fields[].bbox` gives coordinates for
             every name, address and phone number on the page, so redaction has a
             target and its acceptance test has something to assert is gone.

## Why PyMuPDF renders them

The same library that will later redact these documents also draws them, so slice 7
is exercising a real round trip rather than a happy-path fixture built by a different
toolchain. It is AGPL-3.0 - see docs/adr/0009.

## Determinism

No randomness and no timestamps. Regenerating produces byte-identical sidecars, so an
OCR baseline measured in slice 11a does not move underneath you between runs.
"""
import json
from dataclasses import dataclass, field as dc_field
from pathlib import Path

import fitz

SPECIMEN_MARK = "SPECIMEN - NOT A REAL RECORD"

ROOT = Path(__file__).resolve().parent
DEVANAGARI_FONT = ROOT / "fonts" / "NotoSansDevanagari.ttf"
DEFAULT_OUT = ROOT / "corpus"

PAGE_W, PAGE_H = 595, 842  # A4 at 72 dpi
MARGIN = 56
LINE = 18


@dataclass(frozen=True)
class Field:
    """One identifying value, and what it is. The bbox is filled in at render time."""

    label: str
    value: str


@dataclass(frozen=True)
class Doc:
    slug: str
    title: str
    language: str  # "eng" | "hin"
    station: str
    reference: str
    body: list[str]
    fields: list[Field] = dc_field(default_factory=list)


# Fictional throughout. "Vranaspur" is not a real place; the station codes are invented
# and deliberately do not resemble a real NCRB or state police numbering scheme.
CORPUS: list[Doc] = [
    Doc(
        slug="complaint-0001", title="Complaint Record", language="eng",
        station="Vranaspur North Police Station", reference="VRN-N/2026/0001",
        fields=[
            Field("date_of_incident", "12 January 2026"),
            Field("complainant_name", "Anjali Bhosle"),
            Field("complainant_address", "14 Marigold Lane, Vranaspur North"),
            Field("complainant_phone", "0900000101"),
        ],
        body=[
            "The complainant attended the station and stated the following.",
            "On the evening in question she was followed from the bus stand",
            "to her residence by a person she did not recognise.",
            "She reported the matter the same night.",
            "The duty officer recorded the statement and issued a receipt.",
        ],
    ),
    Doc(
        slug="complaint-0002", title="Complaint Record", language="eng",
        station="Vranaspur South Police Station", reference="VRN-S/2026/0002",
        fields=[
            Field("date_of_incident", "14 January 2026"),
            Field("complainant_name", "Farida Sheikh"),
            Field("complainant_address", "8 Tamarind Road, Vranaspur South"),
            Field("complainant_phone", "0900000102"),
        ],
        body=[
            "The complainant reported repeated unwanted contact by telephone",
            "over a period of several weeks.",
            "Call records were produced and retained with this file.",
            "The complainant declined immediate medical examination.",
        ],
    ),
    Doc(
        slug="witness-0003", title="Witness Statement", language="eng",
        station="Vranaspur North Police Station", reference="VRN-N/2026/0001",
        fields=[
            Field("date_of_incident", "16 January 2026"),
            Field("witness_name", "Prakash Iyer"),
            Field("witness_address", "22 Canal Street, Vranaspur North"),
        ],
        body=[
            "The witness states that he was closing his shop at the time.",
            "He observed a person waiting near the bus stand for some minutes.",
            "He did not see the person's face clearly.",
            "He is willing to attend if required.",
        ],
    ),
    Doc(
        slug="witness-0004", title="Witness Statement", language="eng",
        station="Vranaspur North Police Station", reference="VRN-N/2026/0003",
        fields=[
            Field("date_of_incident", "18 January 2026"),
            Field("witness_name", "Leela Menon"),
            Field("witness_phone", "0900000104"),
        ],
        body=[
            "The witness states she was travelling on the same route.",
            "She recalls the complainant appearing distressed.",
            "She offered assistance and accompanied her to the station.",
        ],
    ),
    Doc(
        slug="medical-0005", title="Medical Examination Record", language="eng",
        station="Vranaspur District Hospital", reference="VRN-N/2026/0003",
        fields=[
            Field("date_of_incident", "21 January 2026"),
            Field("victim_name", "Sunita Kale"),
            Field("victim_address", "3 Peepal Colony, Vranaspur North"),
        ],
        body=[
            "Examination conducted on referral from the investigating officer.",
            "Consent was recorded before examination.",
            "Findings have been sealed and forwarded separately.",
            "This record contains no clinical detail.",
        ],
    ),
    Doc(
        slug="seizure-0006", title="Seizure Memo", language="eng",
        station="Vranaspur North Police Station", reference="VRN-N/2026/0001",
        fields=[
            Field("date_of_incident", "24 January 2026"),
            Field("officer_name", "SI Kavya Raut"),
            Field("witness_name", "Prakash Iyer"),
        ],
        body=[
            "One mobile handset was taken into custody at the place of report.",
            "The item was sealed in the presence of the witness named above.",
            "A copy of this memo was handed to the complainant.",
        ],
    ),
    Doc(
        slug="transfer-0007", title="Case Transfer Note", language="eng",
        station="Vranaspur South Police Station", reference="VRN-S/2026/0002",
        fields=[
            Field("date_of_incident", "27 January 2026"),
            Field("officer_name", "SHO Rahul Desai"),
        ],
        body=[
            "This case is transferred to the North station for further handling,",
            "the place of occurrence falling within that jurisdiction.",
            "All documents on record are forwarded with this note.",
        ],
    ),
    Doc(
        slug="complaint-0008-hi", title="शिकायत अभिलेख", language="hin",
        station="व्रनासपुर उत्तर पुलिस थाना", reference="VRN-N/2026/0008",
        fields=[
            Field("date_of_incident", "30 January 2026"),
            Field("complainant_name", "मीरा जोशी"),
            Field("complainant_address", "११ गुलमोहर मार्ग, व्रनासपुर उत्तर"),
        ],
        body=[
            "शिकायतकर्ता थाने पर उपस्थित हुईं और निम्नलिखित कथन दिया।",
            "उन्होंने बताया कि बाजार से लौटते समय एक व्यक्ति ने पीछा किया।",
            "उन्होंने उसी दिन इसकी सूचना दी।",
            "ड्यूटी अधिकारी ने कथन अभिलिखित किया।",
        ],
    ),
    Doc(
        slug="witness-0009-hi", title="साक्षी कथन", language="hin",
        station="व्रनासपुर उत्तर पुलिस थाना", reference="VRN-N/2026/0008",
        fields=[
            Field("date_of_incident", "02 February 2026"),
            Field("witness_name", "रमेश गुप्ता"),
        ],
        body=[
            "साक्षी ने बताया कि वह उस समय अपनी दुकान पर था।",
            "उसने एक व्यक्ति को कुछ देर प्रतीक्षा करते देखा।",
            "वह आवश्यकता होने पर उपस्थित होने को तैयार है।",
        ],
    ),
    # The document the redaction engine is proven against. Every identifying value
    # recurs in the narrative - full name, surname alone, given name alone, the phone
    # number and the street address - because that is how statements are written, and
    # a redaction that only covers the labelled lines leaves all of it standing.
    Doc(
        slug="statement-0011", title="Victim Statement", language="eng",
        station="Vranaspur North Police Station", reference="VRN-N/2026/0001",
        fields=[
            Field("date_of_incident", "05 February 2026"),
            Field("victim_name", "Rukmini Deshmukh"),
            Field("victim_phone", "0900000111"),
            Field("victim_address", "27 Banyan Cross, Vranaspur North"),
        ],
        body=[
            "The statement of Ms Rukmini Deshmukh was recorded at her request.",
            "Ms Deshmukh stated that she had been followed on three occasions.",
            "She asked to be contacted only on 0900000111, not at 27 Banyan Cross.",
            "Rukmini identified the vehicle as a grey two-wheeler.",
            "The statement was read over to her and she agreed it was correct.",
        ],
    ),
    Doc(
        slug="property-0010", title="Property Register Extract", language="eng",
        station="Vranaspur North Police Station", reference="VRN-N/2026/0001",
        fields=[
            Field("date_of_incident", "09 February 2026"),
            Field("officer_name", "SI Kavya Raut"),
        ],
        body=[
            "Extract from the station property register for the item seized.",
            "The entry number and date of deposit are recorded against the item.",
            "No movement of the item has been recorded since deposit.",
        ],
    ),
]


def _font_for(language: str) -> tuple[str, str | None]:
    """(fontname, fontfile). Devanagari needs the vendored OFL face."""
    if language == "hin":
        if not DEVANAGARI_FONT.exists():
            raise FileNotFoundError(
                f"{DEVANAGARI_FONT} is missing. The Hindi fixtures need it, and a "
                f"Windows system font is not an option: it is proprietary and absent "
                f"from the Linux container."
            )
        return "noto-deva", str(DEVANAGARI_FONT)
    return "helv", None


def _render(doc: Doc, out_dir: Path) -> Path:
    fontname, fontfile = _font_for(doc.language)
    pdf = fitz.open()
    page = pdf.new_page(width=PAGE_W, height=PAGE_H)

    # Measuring needs a Font object: fitz.get_text_length() only understands the
    # built-in base-14 names and raises on an embedded face.
    if fontfile:
        page.insert_font(fontname=fontname, fontfile=fontfile)
        measure = {False: fitz.Font(fontfile=fontfile), True: fitz.Font(fontfile=fontfile)}
        names = {False: fontname, True: fontname}
    else:
        measure = {False: fitz.Font("helv"), True: fitz.Font("hebo")}
        names = {False: "helv", True: "hebo"}

    truth: list[str] = []
    boxes: list[dict] = []
    y = MARGIN

    def write(text: str, size: int = 10, bold: bool = False) -> fitz.Rect:
        """Place one line and return the rectangle it occupies."""
        nonlocal y
        name = names[bold]
        width = measure[bold].text_length(text, fontsize=size)
        point = fitz.Point(MARGIN, y)
        page.insert_text(point, text, fontname=name, fontsize=size)
        rect = fitz.Rect(MARGIN, y - size, MARGIN + width, y + size * 0.3)
        truth.append(text)
        y += LINE
        return rect

    # Header. The specimen mark goes first so it is impossible to crop off the top
    # without the document obviously missing its first line.
    write(SPECIMEN_MARK, size=11, bold=True)
    y += 6
    write(doc.title, size=14, bold=True)
    write(doc.station, size=10)
    write(f"Reference: {doc.reference}", size=10)
    y += 10

    for label_value in doc.fields:
        label = label_value.label.replace("_", " ").title()
        prefix = f"{label}: "
        prefix_width = measure[False].text_length(prefix, fontsize=10)
        rect = write(f"{prefix}{label_value.value}", size=10)
        # The bbox covers the VALUE only, not the label - redaction must remove the
        # name, not the word "Victim Name".
        boxes.append(
            {
                "label": label_value.label,
                "value": label_value.value,
                "page": 0,
                "bbox": [
                    round(rect.x0 + prefix_width, 2),
                    round(rect.y0, 2),
                    round(rect.x1, 2),
                    round(rect.y1, 2),
                ],
            }
        )

    y += 10
    for line in doc.body:
        write(line, size=10)

    # And again at the foot, so a single-page crop cannot remove it either.
    y = PAGE_H - MARGIN
    write(SPECIMEN_MARK, size=9, bold=True)

    path = out_dir / f"{doc.slug}.pdf"
    pdf.save(path)
    pdf.close()

    sidecar = {
        "slug": doc.slug,
        "title": doc.title,
        "language": doc.language,
        "station": doc.station,
        "reference": doc.reference,
        "specimen": True,
        "pages": [{"number": 0, "text": "\n".join(truth)}],
        "identifying_fields": boxes,
    }
    path.with_suffix(".json").write_text(
        json.dumps(sidecar, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


def generate_corpus(out_dir: Path | str = DEFAULT_OUT) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for stale in list(out.glob("*.pdf")) + list(out.glob("*.json")):
        stale.unlink()
    return [_render(doc, out) for doc in CORPUS]


if __name__ == "__main__":
    written = generate_corpus()
    languages = {d.language for d in CORPUS}
    print(f"  {len(written)} documents -> {DEFAULT_OUT}")
    print(f"  languages: {', '.join(sorted(languages))}")
    print(f"  every page marked: {SPECIMEN_MARK}")
