# 0019 — The upload route versions; the worker runs the thread

## Context
Slice 4b added an HTTP upload route, and the first implementation ran the whole golden
thread inside the request: sanitise, version, OCR, extract, sign, anchor. It worked
natively and the api container then crash-looped, because `docker/python.Dockerfile`
gives the api target no Tesseract — with a comment saying exactly why:

> The api target deliberately does NOT get Tesseract. OCR runs in the worker, and an
> api that could run it would invite someone to call it synchronously on a request.

The route had become the thing that comment exists to prevent, and only the container
noticed. The dev loop runs from source on a machine where Tesseract is installed, so it
was green throughout.

The tempting fix — add Tesseract to the api image — reverses a recorded decision to make
a newer, smaller one work. The worker, meanwhile, had a heartbeat and no jobs; CLAUDE.md
decided its queue would be a Postgres table with `FOR UPDATE SKIP LOCKED` and nothing had
built it.

## Decision
`Pipeline` splits in two:

- **`ingest`** — sanitise, version, store bytes. No stage runs, so no OCR engine is
  needed. This is what the upload route calls, and it answers **202**, not 201: the
  version exists, the thread has not run.
- **`process_version`** — the four stages against a version that already exists.
  Deliberately does *not* re-sanitise, because sanitising is not its own fixed point
  (ADR 0017) and a worker that re-ran it could mint a second version of a document it
  was only asked to process.

`worker/intake_queue.py` claims versions with no `ocr_text` using `FOR UPDATE SKIP
LOCKED` and calls `process_version`. `Pipeline.run` remains `ingest` + `process_version`
for the headless path, the fixtures loader and the tests.

## Consequences
- The api keeps no OCR engine, and the recorded reason for that stays true.
- The worker finally does the job its docstring promised since slice 1b, and `/health`'s
  worker check now reports a process that does something.
- An upload appears immediately as a version and gains its fields within one worker tick
  (ten seconds). The document screen shows the version with no fields until then; that
  is honest rather than hidden behind a spinner that implies synchrony.
- A second worker is useful rather than duplicative: `SKIP LOCKED` hands it the next row.
  The stage-level idempotency key would have caught a double-claim anyway — this avoids
  the wasted work rather than the wrong result.
- Redacted derivatives are excluded from the queue. Whether a derivative should itself be
  OCR'd and indexed is an open question in STATUS, and it is written into the query
  explicitly so the omission is visible rather than accidental.
- `httpx` moved from dev-only to a runtime dependency, because the Sentinel dashboard
  runs scenarios through an ASGI transport and the demo path is compose. Its import is
  lazy, so a missing client disables the dashboard instead of stopping the api — which is
  what happened the first time.
