/**
 * Opening and ending a session, as an ordinary form post.
 *
 * **Why not a Server Action.** Next guards server actions by comparing the `Origin`
 * header against the forwarded host, and aborts when they disagree. That is a
 * reasonable default and it is fragile in exactly the conditions this project has to
 * survive: a demo machine reached by IP rather than by name, an embedded browser that
 * sends `Origin: null`, any proxy in front. A form post to a route handler works in
 * all of them — and works with JavaScript disabled entirely, which is worth having on
 * a laptop in a hall with somebody else's browser.
 *
 * **What replaces that guard.** The session cookie is `SameSite=Lax`, which browsers
 * do *not* attach to a cross-site POST. A hostile page can submit a form here and it
 * arrives without a session, so it can drive nothing (threat SESS-03). The cookie
 * policy is the CSRF control, and it is set on the API side as well as here.
 *
 * This is still a **specimen switcher and not a login**: no credential is checked.
 * What it does guarantee is that the identity is minted and signed by the server, so
 * the client cannot name itself (threat EXT-02).
 */
import { cookies } from "next/headers";

import { isCrossSite, refuse } from "../../lib/guard";

const API_ORIGIN = process.env.ORDIN_API_ORIGIN ?? "http://127.0.0.1:8000";
const SESSION_COOKIE = "ordin_session";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const EIGHT_HOURS = 8 * 60 * 60;

/**
 * Relative Location, deliberately.
 *
 * The framework's redirect helper needs an absolute URL and builds it from
 * `request.url`, whose host is whatever the server resolved rather than what the
 * browser typed. On this machine that turned 127.0.0.1 into localhost, and the session
 * cookie — set for the host that was asked for — was not sent to the host that was
 * redirected to, so signing in silently did nothing. RFC 7231 permits a relative
 * Location and every browser resolves it against the request, which is the behaviour
 * wanted here: the demo works the same at 127.0.0.1, at localhost, and at a LAN
 * address a judge types.
 */
function seeOther(path: string): Response {
  return new Response(null, { status: 303, headers: { location: path } });
}

/** Only ever a path on this origin, so a crafted `next` cannot bounce the user off-site. */
function safeReturn(value: FormDataEntryValue | null): string {
  const path = typeof value === "string" ? value : "/";
  return path.startsWith("/") && !path.startsWith("//") ? path : "/";
}

export async function POST(request: Request) {
  if (isCrossSite(request)) return refuse();
  const form = await request.formData();
  const back = safeReturn(form.get("next"));
  const jar = await cookies();

  if (form.get("end") === "1") {
    jar.delete(SESSION_COOKIE);
    return seeOther(back);
  }

  const userId = form.get("user_id");
  if (typeof userId !== "string" || !UUID.test(userId)) {
    return seeOther(back);
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${API_ORIGIN}/session`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ user_id: userId }),
      cache: "no-store",
    });
  } catch {
    // The page will render "No session", which is the honest visible outcome. A
    // switcher that claimed an identity the server never issued would be worse.
    return seeOther(back);
  }

  if (upstream.ok) {
    // Read the token out of the API's own Set-Cookie rather than reconstructing it,
    // so the signature is whatever the server actually issued.
    const issued = upstream.headers.getSetCookie?.() ?? [];
    const token = issued
      .map((c) => /(?:^|;\s*)ordin_session=([^;]+)/.exec(c)?.[1])
      .find(Boolean);
    if (token) {
      jar.set(SESSION_COOKIE, token, {
        httpOnly: true,
        sameSite: "lax",
        secure: process.env.NODE_ENV === "production",
        maxAge: EIGHT_HOURS,
        path: "/",
      });
    }
  }
  return seeOther(back);
}
