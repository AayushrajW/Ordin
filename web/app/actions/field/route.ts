/**
 * The two writes on the verification screen: commit a draft, or record a human value.
 *
 * This handler decides nothing. It forwards the session cookie and relays the API's
 * answer as a redirect, because the API re-checks the case, the disclosure class and
 * the version on every request. A button rendered on the page grants nothing: press
 * "verify" as a subject who may not, and the API returns 404 and the field stays a
 * draft. Sentinel VERIFY-02 watches exactly that.
 *
 * Failures come back as a `?error=` code on the page being returned to, drawn from a
 * fixed set here. The API's own `detail` values are enumerated and safe, but relaying
 * them would make this the place where a later route's free text reaches a screen
 * (invariant 12).
 *
 * CSRF: see `../session/route.ts`. `SameSite=Lax` means a cross-site form post
 * arrives with no session at all.
 */
import { cookies } from "next/headers";

import { isCrossSite, refuse } from "../../lib/guard";

const API_ORIGIN = process.env.ORDIN_API_ORIGIN ?? "http://127.0.0.1:8000";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function safeReturn(value: FormDataEntryValue | null): string {
  const path = typeof value === "string" ? value : "/";
  return path.startsWith("/") && !path.startsWith("//") ? path : "/";
}

/**
 * Relative Location, deliberately — see `../session/route.ts` for why an absolute one
 * built from `request.url` silently loses the session on this machine.
 */
function back(path: string, error?: string): Response {
  const separator = path.includes("?") ? "&" : "?";
  const target = error ? `${path}${separator}error=${encodeURIComponent(error)}` : path;
  return new Response(null, { status: 303, headers: { location: target } });
}

export async function POST(request: Request) {
  if (isCrossSite(request)) return refuse();
  const form = await request.formData();
  const target = safeReturn(form.get("next"));
  const token = (await cookies()).get("ordin_session")?.value;
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (token) headers.cookie = `ordin_session=${token}`;

  const intent = form.get("intent");
  let path: string;
  let body: string | undefined;

  if (intent === "verify") {
    const fieldId = form.get("field_id");
    if (typeof fieldId !== "string" || !UUID.test(fieldId)) return back(target, "input");
    path = `/fields/${fieldId}/verify`;
  } else if (intent === "enter") {
    const versionId = form.get("version_id");
    const rawKey = form.get("field_key");
    const value = form.get("value");
    if (typeof versionId !== "string" || !UUID.test(versionId)) {
      return back(target, "input");
    }
    // Normalised here so a human typing "Complainant Name" or "1st Witness" gets a valid key rather
    // than a validation error from the API. The API validates it again regardless.
    let key = String(rawKey ?? "").trim().toLowerCase().replace(/[^a-z0-9_]+/g, "_").replace(/^_+|_+$/g, "");
    if (/^[0-9]/.test(key)) {
      key = `field_${key}`;
    }
    if (!/^[a-z][a-z0-9_]*$/.test(key) || typeof value !== "string" || !value.trim()) {
      return back(target, "input");
    }
    path = `/versions/${versionId}/fields`;
    body = JSON.stringify({ field_key: key.slice(0, 64), value: value.trim().slice(0, 512) });
  } else if (intent === "redact") {
    const versionId = form.get("version_id");
    const fieldIds = form.getAll("field_id").filter(
      (v): v is string => typeof v === "string" && UUID.test(v),
    );
    // No field ids means every identifying value on the version, plus the case's
    // recorded parties and identifier patterns — the engine's default, and the one
    // that also catches the mentions nobody labelled.
    if (typeof versionId !== "string" || !UUID.test(versionId)) {
      return back(target, "input");
    }
    path = `/versions/${versionId}/redact`;
    body = JSON.stringify({ field_ids: fieldIds });
  } else {
    return back(target, "input");
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${API_ORIGIN}${path}`, {
      method: "POST",
      headers,
      body,
      cache: "no-store",
    });
  } catch {
    return back(target, "unreachable");
  }

  if (upstream.status === 401) return back(target, "session");
  if (upstream.status === 404) return back(target, "refused");
  if (upstream.status === 422) return back(target, "nothinglocated");
  if (upstream.status === 429) return back(target, "rate");
  if (!upstream.ok) return back(target, "refused");

  if (intent === "redact") {
    // Land on the derivative that was just produced, so the operator sees the result
    // rather than being told it happened.
    const made = (await upstream.json()) as { version_id?: string };
    if (made.version_id) {
      const base = target.split("?")[0];
      return back(`${base}?version=${made.version_id}&redacted=1`);
    }
  }
  return back(target);
}
