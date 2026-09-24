/**
 * Writes that govern a record: break-glass on a seal, lawful disposal of a version.
 *
 * Form posts, same shape as `/actions/field`. The API re-authorizes every request.
 */
import { cookies } from "next/headers";

import { isCrossSite, refuse } from "../../lib/guard";

const API_ORIGIN = process.env.ORDIN_API_ORIGIN ?? "http://127.0.0.1:8000";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const BASES = new Set([
  "retention_expiry",
  "court_order",
  "erroneous_upload",
  "superseded_original",
]);

function safeReturn(value: FormDataEntryValue | null): string {
  const path = typeof value === "string" ? value : "/";
  return path.startsWith("/") && !path.startsWith("//") ? path : "/";
}

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

  if (intent === "break-glass") {
    const caseId = form.get("case_id");
    const justification = form.get("justification");
    const minutes = Number(form.get("minutes") ?? "60");
    if (typeof caseId !== "string" || !UUID.test(caseId)) return back(target, "input");
    if (typeof justification !== "string" || justification.trim().length < 40) {
      return back(target, "input");
    }
    if (!Number.isInteger(minutes) || minutes < 5 || minutes > 480) {
      return back(target, "input");
    }
    path = `/cases/${caseId}/break-glass`;
    body = JSON.stringify({ justification: justification.trim(), minutes });
  } else if (intent === "dispose") {
    const versionId = form.get("version_id");
    const basis = form.get("basis");
    const confirm = form.get("confirm");
    if (typeof versionId !== "string" || !UUID.test(versionId)) return back(target, "input");
    if (typeof basis !== "string" || !BASES.has(basis)) return back(target, "input");
    // The typed confirmation is re-checked here, not only by the browser's `pattern`.
    // It is a pause rather than a control - the API neither sees it nor could trust it
    // - but a pause that a form post can skip is not a pause at all.
    if (typeof confirm !== "string" || !/^v\d+$/.test(confirm.trim())) {
      return back(target, "confirm");
    }
    path = `/versions/${versionId}/dispose`;
    body = JSON.stringify({ basis });
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
  // 409 means different things to the two verbs, and mapping them all to one label
  // told an officer whose disposal was refused for `not_anchored` that the case was
  // already open to them. The API's `detail` is an enumerated code, so it can be
  // mapped without echoing an upstream body to the browser.
  if (upstream.status === 409) {
    let detail = "";
    try {
      detail = String(((await upstream.json()) as { detail?: unknown }).detail ?? "");
    } catch {
      detail = "";
    }
    if (detail === "clearance_sufficient") return back(target, "alreadyopen");
    if (detail === "case_not_sealed") return back(target, "notsealed");
    if (detail === "already_disposed") return back(target, "alreadydisposed");
    if (detail === "not_anchored") return back(target, "notanchored");
    return back(target, "refused");
  }
  if (upstream.status === 404) return back(target, "refused");
  if (upstream.status === 422) return back(target, "input");
  if (!upstream.ok) return back(target, "refused");
  if (intent === "dispose") {
    const base = target.split("?")[0];
    const versionId = form.get("version_id");
    return back(`${base}?version=${String(versionId)}&disposed=1`);
  }
  return back(target);
}
