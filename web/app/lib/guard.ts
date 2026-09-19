/**
 * Cross-site request refusal for the form routes.
 *
 * The session cookie is `SameSite=Lax`, which browsers do not attach to a cross-site
 * POST — so a hostile page's forged form already arrives with no session and can drive
 * nothing (threat SESS-03). This is the second, independent control, and it fails
 * closed on its own:
 *
 *  - `Sec-Fetch-Site: cross-site` — set by the browser, not forgeable by page script —
 *    is refused outright.
 *  - An `Origin` naming a different host is refused. `Origin: null` is let through,
 *    because sandboxed and embedded contexts send it for same-origin posts too; those
 *    requests still carry no cookie cross-site, so the first control covers them.
 *
 * Two controls rather than one because each has a failure mode the other does not: a
 * browser that mishandles SameSite, or a deployment behind a proxy that rewrites hosts.
 */
export function isCrossSite(request: Request): boolean {
  if (request.headers.get("sec-fetch-site") === "cross-site") return true;
  const origin = request.headers.get("origin");
  if (!origin || origin === "null") return false;
  try {
    const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
    return host !== null && new URL(origin).host !== host;
  } catch {
    return true;
  }
}

export function refuse(): Response {
  return new Response("cross-site request refused", {
    status: 403,
    headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" },
  });
}
