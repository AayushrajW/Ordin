# Shared image for the api and worker services.
#
# One image, two commands. The api and worker run identical dependencies over an
# identical code tree in slice 1, and two Dockerfiles differing only in CMD would
# cost a second build and ~150 MB of layers for nothing.
#
# They will diverge at slice 5a, when the worker gains Tesseract and PyMuPDF and
# the api does not. Splitting the file then is natural; splitting it now is
# duplication in advance of a reason.
#
# Base is pinned to 3.11 to match the native dev interpreter (ADR 0007). Pinning
# by digest rather than tag is the next hardening step and is recorded as accepted
# risk AR-10 - `python:3.11-slim` is a moving tag.

FROM python:3.11-slim

# Non-root. The worker is the process that will eventually parse attacker-supplied
# documents through memory-unsafe C parsers (threat DOC-10); running it as root
# with a writable bind mount is how a parser bug becomes a host compromise.
RUN useradd --create-home --uid 10001 ordin

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Dependencies first, so a source change does not reinstall the world.
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY api/ ./api/
COPY worker/ ./worker/
COPY alembic/ ./alembic/
COPY alembic.ini ./

USER ordin

# Overridden per service in docker-compose.yml.
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
