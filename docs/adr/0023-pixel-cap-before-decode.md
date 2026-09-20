# 0023 — The pixel cap is applied to the declared size, before decoding

## Context
ADR 0022 added photographs to intake with a pixel cap, and the comment on `MAX_PIXELS`
claimed it stopped "a small file that decompresses into gigabytes of pixmap from being
rasterised at all". It did not. `pdf_from_image` called `fitz.Pixmap(data)` — which
decodes the entire image — and tested the cap on the resulting pixmap. The cap measured
the damage rather than preventing it.

`MAX_BYTES` does not help: it caps the upload at 25 MB and says nothing about the
decoded size. Deflate reduces a uniform field to almost nothing, so 25 MB of PNG is
billions of pixels and gigabytes of pixmap. Any user who may upload could have taken
down the worker — whose compose memory limit is 256 MB — which is threat OPS-03 exactly:
an unbounded worker gets the OOM killer to take postgres down with it.

The existing test was named `test_an_enormous_image_is_refused_before_it_is_rasterised`
and passed, because it decoded the specimen **itself** to decide what to expect. It
asserted the rejection, never the ordering that made the rejection cheap.

## Decision
`declared_pixel_size` reads width and height from the header — PNG IHDR, GIF logical
screen descriptor, BMP info header, JPEG SOFn after a marker walk, TIFF tags 256/257 in
the first IFD — and `pdf_from_image` applies `MAX_PIXELS` to that **before** any decoder
sees the bytes. Every format `sniff` accepts is required by its own specification to
declare its dimensions, so this is always answerable for a well-formed file.

An unreadable header **denies** (invariant 2). `sniff` has already matched a known image
magic, so a header that will not give up its size is malformed, not exotic.

The post-decode check stays as well. The header is a claim; the pixmap is the
measurement. They agree for every well-formed file, and the cheap check is not the last
word.

Hand-written rather than a new dependency. `fitz.image_profile` is the obvious tool and
is broken in PyMuPDF 1.26.7 — its binding passes a `bytes` to `fz_recognize_image_format`,
which rejects it on every input. Pillow would solve it and is a dependency nobody has
approved; the parsing is ~70 lines of fixed-offset reads.

## Consequences
- The bomb is refused in microseconds, having allocated nothing.
- **A control that cannot run is worse than none**, because it reads as present. That
  applies to `image_profile`, and it applied to the cap this ADR replaces.
- The new test uses tiny headers declaring 50,000×50,000 with no pixel data behind them:
  decode-first reports `UNREADABLE`, header-first reports `TOO_MANY_PIXELS`. It
  discriminates the ordering without allocating anything, which a test built from a real
  bomb could not do safely on an 8 GB laptop.
- TIFF is the weakest of the five: the parser reads the first IFD only. Baseline TIFF
  requires tags 256 and 257 there, so a conforming scanner file is covered.
