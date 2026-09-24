"""Response hardening and rate limiting, applied to every request.

**Headers.** The API serves JSON and PNG to one caller — the web tier's server — and
nothing it returns should ever be framed, sniffed, cached, or embedded cross-origin.
The headers say so explicitly rather than relying on the web tier to strip or add them,
because an API reachable directly (a judge's `curl`, a misconfigured proxy) must be
safe on its own. `Cache-Control: no-store` matters most: every response here is the
product of an authorization decision made *for this request*, and a cached copy outlives
the session that was entitled to it.

**Rate limits.** Accepted risk AR-9 was "no rate limiting, lockout or user-enumeration
protection". This narrows it:

  minting a session     30 per minute per client address
  writes                120 per minute per session
  page renders          120 per minute per session — each one hashes, watermarks and
                        rasterises, so an unbounded loop is a cheap denial of service
                        and a bulk-exfiltration path at once

Sliding window, in process memory. **Stated limits of that**: per api process, not per
deployment; reset on restart; and the web tier calls the API from one address, so the
per-address limit on session minting is effectively global behind it. That is a real
narrowing of AR-9 for this build, not a closing of it. A production deployment puts this
in front of the api, keyed on the real client.

Keys are hashes, never raw tokens: a limiter's memory must not become a session store
somebody can read out of a heap dump.
"""
import hashlib
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from infra.subject_provider import COOKIE_NAME

# The in-process scenario runner addresses the app as this host. No network client can
# present it: uvicorn fills `request.client` from the socket's peer address. Sentinel is
# exempt so repeatedly reloading the dashboard cannot make its own security checks fail
# with 429 and report the system broken for the wrong reason.
INTERNAL_CLIENT = "sentinel.internal"

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-site",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}


# How often to drop keys nobody has used for a full window. Every call would be
# O(keys); never would leak one dict entry per distinct caller for the life of the
# process, which is what the previous delete-then-reinsert actually did - it removed
# the key and immediately recreated it through the defaultdict on the next line.
_SWEEP_EVERY = 512


class SlidingWindow:
    def __init__(self, limit: int, seconds: float = 60.0) -> None:
        self.limit = limit
        self.seconds = seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._calls = 0

    def _sweep(self, now: float) -> None:
        """Drop keys whose last hit has left the window. Amortised, not per-call.

        The map is keyed on a session fingerprint or a client address, so without this
        a long-running process accumulates one entry per caller it has ever seen. Not
        an attack on its own; it is the thing that turns a busy week into an OOM on a
        container capped at 256 MiB.
        """
        self._calls += 1
        if self._calls % _SWEEP_EVERY:
            return
        stale = [k for k, hits in self._hits.items() if not hits or now - hits[-1] >= self.seconds]
        for key in stale:
            del self._hits[key]

    def allow(self, key: str, now: float | None = None) -> tuple[bool, int]:
        """(allowed, seconds until the oldest hit leaves the window)."""
        now = time.monotonic() if now is None else now
        self._sweep(now)
        hits = self._hits[key]
        while hits and now - hits[0] >= self.seconds:
            hits.popleft()
        if len(hits) >= self.limit:
            return False, max(1, int(self.seconds - (now - hits[0])) + 1)
        hits.append(now)
        return True, 0


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


class SecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, session_limit: int = 30, write_limit: int = 120,
                 render_limit: int = 120, export_limit: int = 20) -> None:
        super().__init__(app)
        self.sessions = SlidingWindow(session_limit)
        self.writes = SlidingWindow(write_limit)
        self.renders = SlidingWindow(render_limit)
        # Tighter than a page render, and separate from it. An export is the one read
        # that both leaves the system with bytes in hand and builds an archive in
        # memory, so the two reasons to bound it - AR-17's exfiltration rate and the
        # 256 MiB container - point the same way.
        self.exports = SlidingWindow(export_limit)

    def _bucket(self, request: Request) -> tuple[SlidingWindow, str] | None:
        client = request.client.host if request.client else "unknown"
        if client == INTERNAL_CLIENT:
            return None
        path, method = request.url.path, request.method
        token = request.cookies.get(COOKIE_NAME)
        who = _fingerprint(token) if token else f"addr:{client}"
        # Minting a session, by either route. `/auth/login` is the one endpoint an
        # unauthenticated caller can use to guess, so it is keyed on the address and
        # shares the tightest bucket. `infra/accounts.py` also counts failures on the
        # account row, because this limiter is per process and resets on restart.
        if method == "POST" and path in ("/session", "/auth/login", "/auth/signup"):
            return self.sessions, f"addr:{client}"
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            return self.writes, who
        # **Export is a GET, so it fell through every bucket.** The most expensive
        # route in the application and the one AR-17 is written about was the only
        # unmetered one: a designated officer could pull every case they hold as fast
        # as the network allowed, and each case export builds a zip in memory. Matched
        # before the render bucket because neither path overlaps, and named explicitly
        # rather than by method, so a future GET does not inherit the limit by accident.
        if path.endswith("/export"):
            return self.exports, who
        if path.endswith("/page.png"):
            return self.renders, who
        return None

    async def dispatch(self, request: Request, call_next) -> Response:
        bucket = self._bucket(request)
        if bucket is not None:
            window, key = bucket
            allowed, retry_after = window.allow(key)
            if not allowed:
                response: Response = JSONResponse(
                    {"detail": "rate_limited"}, status_code=429,
                    headers={"Retry-After": str(retry_after)},
                )
                for name, value in SECURITY_HEADERS.items():
                    response.headers.setdefault(name, value)
                return response

        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        # The interactive docs page in dev loads its own scripts; do not break it.
        if request.url.path.startswith(("/docs", "/openapi.json")):
            del response.headers["Content-Security-Policy"]
        response.headers.setdefault("Cache-Control", "no-store, private")
        return response
