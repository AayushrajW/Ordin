/**
 * Login, signup and logout, as ordinary form posts.
 *
 * Same shape as `actions/session` and for the same reasons (ADR 0018): a form post to a
 * route handler survives being reached by IP, an embedded browser sending
 * `Origin: null`, a proxy in front, and JavaScript switched off entirely. The CSRF
 * control is the `SameSite=Lax` cookie, which a browser does not attach to a cross-site
 * POST, plus the explicit `isCrossSite` refusal.
 *
 * **No credential is ever put in a URL.** Errors come back as a short enumerated code in
 * the query string and the page turns it into a sentence. A redirect carrying the email
 * or the password would put both in browser history, in the proxy log and in the
 * referrer — `api/logging.py` already says the query string is exactly where secrets go
 * to be recorded by accident.
 */
import { cookies } from "next/headers";

import { isCrossSite, refuse } from "../../lib/guard";

const API_ORIGIN = process.env.ORDIN_API_ORIGIN ?? "http://127.0.0.1:8000";
const SESSION_COOKIE = "ordin_session";
const EIGHT_HOURS = 8 * 60 * 60;

function seeOther(path: string): Response {
  return new Response(null, { status: 303, headers: { location: path } });
}

function field(form: FormData, name: string, max = 400): string {
  const value = form.get(name);
  return typeof value === "string" ? value.slice(0, max) : "";
}

/** Copy the API's own Set-Cookie through, so the signature is the one the server issued. */
async function adoptSession(upstream: Response): Promise<boolean> {
  const issued = upstream.headers.getSetCookie?.() ?? [];
  const token = issued
    .map((c) => /(?:^|;\s*)ordin_session=([^;]+)/.exec(c)?.[1])
    .find(Boolean);
  if (!token) return false;
  (await cookies()).set(SESSION_COOKIE, token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    maxAge: EIGHT_HOURS,
    path: "/",
  });
  return true;
}

export async function POST(request: Request) {
  if (isCrossSite(request)) return refuse();
  const form = await request.formData();
  const mode = field(form, "mode", 16);

  if (mode === "logout") {
    (await cookies()).delete(SESSION_COOKIE);
    try {
      await fetch(`${API_ORIGIN}/auth/logout`, { method: "POST", cache: "no-store" });
    } catch {
      // The cookie is already gone from this browser, which is what ending a session
      // means here. The API holds no server-side session state to clear.
    }
    return seeOther("/login");
  }

  const email = field(form, "email", 320);
  const password = field(form, "password", 1024);

  if (mode === "signup") {
    const displayName = field(form, "display_name", 120);
    let upstream: Response;
    try {
      upstream = await fetch(`${API_ORIGIN}/auth/signup`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email, password, display_name: displayName }),
        cache: "no-store",
      });
    } catch {
      return seeOther("/signup?error=unreachable");
    }
    if (upstream.status === 201) return seeOther("/login?created=1");
    if (upstream.status === 422) return seeOther("/signup?error=weak");
    let reason = "rejected";
    try {
      const body = await upstream.json();
      if (typeof body?.detail === "string" && body.detail.startsWith("password")) {
        reason = "weak";
      }
    } catch {
      // Keep the generic reason.
    }
    return seeOther(`/signup?error=${reason}`);
  }

  // Login.
  let upstream: Response;
  try {
    upstream = await fetch(`${API_ORIGIN}/auth/login`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email, password }),
      cache: "no-store",
    });
  } catch {
    return seeOther("/login?error=unreachable");
  }

  if (upstream.status === 429) return seeOther("/login?error=throttled");
  if (!upstream.ok) return seeOther("/login?error=refused");

  if (!(await adoptSession(upstream))) return seeOther("/login?error=refused");

  let placed = false;
  try {
    placed = Boolean((await upstream.json())?.placed);
  } catch {
    placed = false;
  }
  // An account nobody has placed yet is told so, rather than landing on an empty
  // dashboard that looks like a fault.
  return seeOther(placed ? "/" : "/awaiting-placement");
}
