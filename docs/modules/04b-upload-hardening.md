# 04b — Upload hardening

> Status: complete. The last unhardened entry point.

## What it does

Size cap, content sniffing and structural sanitisation, applied **inside
`Pipeline.run`** before a version exists. A PDF carrying JavaScript, a launch action, an
embedded file, an XFA form or an open-action comes out with all of it removed; a file
that is not a PDF is refused by its bytes rather than by its name; an encrypted file is
refused rather than guessed at.

## Why this design

**PyMuPDF rather than qpdf** (ADR 0016). PLAN named qpdf. PyMuPDF is already a
dependency, already licence-recorded, and already does the harder version of this for
redaction. qpdf would have been a second native binary to install on the demo machine
for no capability the project did not have.

**Inside the pipeline, not at the HTTP boundary.** Sanitising in the upload route would
leave every other caller — a route added later, a fixture loader, a test — able to create
a version from unsanitised bytes. Putting it before `_upsert_version` makes "unsanitised
bytes never become a version" a property of the system rather than a habit of one
endpoint.

**The route stops at the version; the worker runs the thread** (ADR 0019). The first
implementation ran OCR inside the request and crash-looped the api container, because the
image deliberately has no Tesseract — with a comment saying an api that could run OCR
would invite exactly that. The route answers 202, and `worker/intake_queue.py` claims the
version with `FOR UPDATE SKIP LOCKED`.

**The sanitiser re-scans its own output** and raises rather than returning a file it has
not verified. This project has three recorded cases of a control that looked applied and
did nothing — a Next config key the framework ignored, a database guard that always read
its own container, a forgery test that forged nothing. A sanitiser that trusts itself
would have been the fourth.

**The scan walks the object table**, not the raw bytes. Object streams are compressed,
so a text search over the file misses exactly the constructs that were hidden. It also
strips `KEY null` pairs before matching: PyMuPDF removes a key by setting it to null and
the key stays in the object, which made the self-check reject every clean upload.

**Determinism turned out to be load-bearing** (ADR 0017). mupdf writes a random trailer
`/ID` on each save, so the same upload sanitised twice produced different bytes, a
different digest, and — because storage is content-addressed — a second version on every
re-upload. Slice 4b broke slice 5a's acceptance criterion, and only the row counts showed
it.

## The two questions a judge will ask

**"Show me it actually strips something."**

`tests/test_intake_hardening.py` builds a PDF that opens by running `app.alert(1)`,
asserts the specimen really carries JavaScript, sanitises it, and asserts nothing
executable survives — and then asserts the document is still there, with its text intact,
because a sanitiser that returned an empty file would pass every check up to that point.
Over HTTP the same thing is asserted against the **stored blob** rather than the
response, since a route that sanitised for the reply and stored the upload would pass any
check made on what came back.

**"So an uploaded file is safe?"**

No, and the module says so. It carries no executable content, which is a narrower claim.
This is not malware scanning — `MalwareScanner` remains a declared stub — and a PDF whose
*pixels* are a phishing page passes here, correctly. Nothing here inspects what the
document says, only what it can do.
