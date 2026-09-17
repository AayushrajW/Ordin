"""Reading the current correlation id from outside the logging module.

`api/logging.py` owns the contextvar; this exposes it so a decision row can be tied
to the request that produced it without importing the middleware.
"""
from api.logging import CORRELATION_ID


def current_correlation_id() -> str | None:
    value = CORRELATION_ID.get()
    return None if value == "-" else value
