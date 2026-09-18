# Images for the api and worker services.
#
# One file, two targets. They shared an image until slice 5a, when the worker gained
# Tesseract and the api did not - the split ADR 0009 anticipated. A build target keeps
# the shared layers shared while letting the worker carry ~50 MB of OCR that the api
# has no use for.
#
# **Every source directory the application imports must be listed below.** That sounds
# obvious and it is exactly what broke: this file was written at slice 1b, when only
# api/ and worker/ existed, and kept working right up until slice 3a introduced
# domain/. The container then failed at import with "No module named 'domain'" while
# the dev loop - which runs from the source tree, not the image - stayed green for
# four slices. `tasks.py verify-compose` is the only thing that looks at this, which
# is why ADR 0006 schedules it rather than leaving it to chance.
#
# Base is pinned to 3.11 to match the native dev interpreter (ADR 0007). Pinning by
# digest rather than tag is recorded as accepted risk AR-10.

FROM python:3.11-slim AS base

# Non-root. The worker is the process that parses attacker-supplied documents through
# memory-unsafe C parsers (threat DOC-10); running it as root with a writable mount is
# how a parser bug becomes a host compromise.
RUN useradd --create-home --uid 10001 ordin

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

# Application source. Add a directory here the moment the application imports it.
COPY api/ ./api/
COPY worker/ ./worker/
COPY domain/ ./domain/
COPY infra/ ./infra/
COPY sentinel/ ./sentinel/
COPY policies/ ./policies/
COPY alembic/ ./alembic/
COPY alembic.ini seed.py ./

RUN mkdir -p /app/data/blobs && chown -R ordin:ordin /app

USER ordin

CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]


# --- worker -------------------------------------------------------------------
# Adds OCR. hin+eng per CLAUDE.md; the language packs are ~15 MB each, well inside
# the "no multi-gigabyte download" limit.
#
# The api target deliberately does NOT get Tesseract. OCR runs in the worker, and an
# api that could run it would invite someone to call it synchronously on a request.
FROM base AS worker

USER root
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin \
    && rm -rf /var/lib/apt/lists/*
USER ordin

# Fails the build rather than the demo if a language pack is missing.
RUN tesseract --list-langs | grep -q '^hin$' && tesseract --list-langs | grep -q '^eng$'

CMD ["python", "-m", "worker.main"]
