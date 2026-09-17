"""Structured logging with correlation IDs.

Slice 1 sets the logging pattern every later slice copies, so invariant 12 — never
log document content, victim or witness identifiers, keys, or raw OCR text; log IDs
and decisions only — is enforced at the plumbing level here rather than by everyone
remembering it at 3am.

Two things this file does on purpose:

1. **Uvicorn's access logger is disabled.** It writes the full request line,
   including the query string, so the first `GET /search?q=<victim name>` puts a
   protected identifier into a log file (threat LOG-01). Our own middleware logs
   method, path, status and duration — never the query string.

2. **A correlation id is attached to every record** via a contextvar, so a request
   can be traced across api and worker without passing an argument through every
   function.
"""
import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

CORRELATION_ID: ContextVar[str] = ContextVar("correlation_id", default="-")

HEADER = "X-Correlation-Id"

# Records that must never carry free text from an untrusted source.
_RESERVED = {
    "args", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "module", "msecs", "message", "msg",
    "name", "pathname", "process", "processName", "relativeCreated",
    "stack_info", "thread", "threadName", "taskName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "correlation_id": CORRELATION_ID.get(),
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            # The type only. A formatted traceback can carry row values, file
            # paths and connection strings into the log.
            payload["error_type"] = record.exc_info[0].__name__
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    # See the module docstring: this logger writes query strings verbatim.
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("uvicorn.error").handlers = [handler]
    logging.getLogger("uvicorn.error").propagate = False


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Accepts a caller's correlation id, or mints one, and echoes it back."""

    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get(HEADER)
        correlation_id = incoming or uuid.uuid4().hex
        token = CORRELATION_ID.set(correlation_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            response.headers[HEADER] = correlation_id
            # Note what is absent: request.url.query. Deliberately.
            logging.getLogger("ordin.request").info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
            return response
        finally:
            # Reset last, so the log call above still sees the id.
            CORRELATION_ID.reset(token)
