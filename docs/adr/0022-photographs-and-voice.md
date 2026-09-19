# 0022 — Photographs are documents; the voice assistant reads but cannot attest

## Context
Two gaps found by using the system rather than testing it.

**Intake took PDFs only.** A photograph of a complaint — how a document most often
reaches a station — was refused as `content_is_not_pdf`. The whole pipeline downstream
rasterises anyway, so nothing after intake had any reason to care.

**There was no hands-free path.** An officer working a case has their hands on paper.

## Decision

### Photographs
`sniff` returns a type rather than asserting one, and PNG, JPEG, TIFF, GIF and BMP are
accepted on their magic bytes. `pdf_from_image` wraps the picture in a one-page PDF and
everything downstream treats it as any other document.

**The pixels are decoded and re-encoded, never embedded as they arrived.** A phone photo
carries EXIF: the camera, sometimes the owner's name, and GPS coordinates — for a
photographed complaint, the location of the station or the victim's home. Embedding the
original JPEG would carry all of it into the evidence store inside the image stream,
where nothing downstream would ever look. A test splices a GPS marker into a specimen and
asserts it is absent afterwards.

The page is sized so one image pixel is one pixel at the OCR path's raster density;
fitting a photograph to A4 would throw away half the detail OCR needs. A pixel cap
refuses the image equivalent of a decompression bomb before anything is rasterised.
`source_sha256` remains the digest of the image as received (migration 0008).

### The voice assistant
Reads the state of the screen aloud and accepts a small fixed set of spoken commands.
Four constraints shape it, each from CLAUDE.md rather than taste:

- **It never speaks an identifying value.** A room is not a private channel. Field names,
  counts, flags and states only — "complainant name, flagged, one character differs",
  never the name. The screen may show it to the person entitled to see it; the air may not.
- **It cannot commit a value or burn a redaction.** Those two write evidence: an
  attestation under someone's name, and the destruction of content. A misheard word must
  do neither. Voice opens the redaction *preview*; a hand presses the button.
- **The grammar is a fixed list matched deterministically** — no model, no intent
  inference. An unmatched phrase is refused. Nothing the assistant hears, and nothing in a
  document, can become an instruction (invariant 6).
- **Output is on-device; input is not, and the panel says so.** `speechSynthesis` uses the
  operating system's voices and makes no network call. `SpeechRecognition` streams audio
  to the browser vendor, which invariant 11 forbids on the demo path — so listening is
  **off by default** behind a switch that states what enabling it does. Named honestly on
  the panel: `BrowserSpeechRecognition`, maturity mvp, production adapter an on-device
  recogniser such as Vosk or whisper.cpp, which would need a model download and an ADR of
  its own.

## Consequences
- Speech that does not start **says so**. Some embedded browsers expose `speechSynthesis`
  and ship no voices; without that report the panel would sit there looking as though it
  had spoken, which is this project's recurring failure mode in a new costume.
- No Indian English voice is installed on the build machine, so it falls back to en-GB.
  Adding one is a Windows setting, not a code change.
- The assistant is the only client-side JavaScript in the product. Every page still
  renders and every action still works with scripting disabled; it is additive.
- There is no JavaScript test framework in this repo, so the assistant is covered by
  manual use rather than by tests. Adding one is a dependency decision nobody has made.
