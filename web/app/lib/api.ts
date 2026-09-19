/**
 * Talking to the API, from the server only.
 *
 * Every function here runs in the Next server process and forwards the session
 * cookie it was given. **The browser never calls the API directly**, which is a
 * deliberate choice rather than a convenience:
 *
 *  - The session cookie is HttpOnly. Script cannot read it, so a client-side fetch
 *    would need CORS with credentials, and the API would then need an allowed-origin
 *    list — more surface, and a configuration item that goes wrong silently.
 *  - It keeps the habit set in slice 1b intact. This tier renders; it decides
 *    nothing. A component cannot accidentally "helpfully" filter a list here,
 *    because the list it receives has already been filtered inside the SQL query
 *    (invariant 1, threat EXT-06).
 *
 * Errors are deliberately flat. A 404 from the API means "not found, or not yours,
 * and you may not learn which" — so it becomes `null` here, and the page renders the
 * same thing either way. Surfacing the status would rebuild the existence oracle the
 * API spent effort removing.
 */
import { cookies } from "next/headers";

const API_ORIGIN = process.env.ORDIN_API_ORIGIN ?? "http://127.0.0.1:8000";
export const SESSION_COOKIE = "ordin_session";

export type Subject = {
  user_id: string;
  display_name: string;
  title: string;
  clearance_level: number;
  provider: string;
  maturity: string;
};

export type DemoSubject = { user_id: string; display_name: string; title: string };

export type CaseRecord = {
  id: string;
  reference: string;
  state: string;
  access_class: string;
};

export type Version = {
  id: string;
  version_no: number;
  sha256: string;
  lifecycle_state: string;
  is_derivative: boolean;
};

export type DocumentRecord = {
  id: string;
  title: string;
  disclosure: "original" | "redacted" | "none";
  versions: Version[];
};

export type ExtractedField = {
  id: string;
  field_key: string;
  value: string;
  status: "draft" | "verified";
  source: string;
  confidence: number | null;
  source_span_start: number | null;
  source_span_end: number | null;
  provider: string | null;
  model: string | null;
  verified_by: string | null;
  entered_by: string | null;
  /** The OCR engine's own confidence in the words the value came from (lowest word). */
  ocr_confidence: number | null;
  anomalies: Anomaly[];
};

export type Anomaly = {
  code: string;
  severity: "warning" | "info";
  message: string;
  suggestion: string | null;
};

export type Integrity = {
  state: "VERIFIED" | "MISMATCH" | "DISPOSED_ANCHOR_ONLY" | "PENDING" | "UNAVAILABLE";
  detail: string;
  sha256: string;
  anchor_seq: number | null;
  anchored_at: string | null;
  checked_at: string;
  anchor_store: string;
  note: string;
};

export type Activity = {
  seq: number;
  action: string;
  object_type: string;
  at: string;
  actor: string | null;
  post: string | null;
};

export type PlanFinding = {
  kind: string;
  rule_id: string;
  confidence: number;
  source: string | null;
  /** On a labelled field's own span, as opposed to elsewhere on the page. */
  labelled: boolean;
  boxes: { page_no: number; x0: number; y0: number; x1: number; y1: number }[];
};

export type RedactionPlan = {
  page_width: number;
  page_height: number;
  unlocated: number;
  findings: PlanFinding[];
};

export type CaseSummary = {
  route: "designation" | "grant";
  disclosure: "original" | "redacted" | "none";
  purpose: string | null;
  grant_expires_at: string | null;
  clearance_valid_to: string | null;
  sealed: boolean;
  documents: number;
  drafts_awaiting: number | null;
  policy: string;
  rule: string;
};

export type OcrText = {
  text: string | null;
  method: string | null;
  provider: string | null;
  mean_confidence: number | null;
  requires_manual_entry: boolean;
};

export type SpanBoxes = {
  page_no: number;
  page_width: number;
  page_height: number;
  boxes: { x0: number; y0: number; x1: number; y1: number }[];
};

async function sessionHeader(): Promise<Record<string, string>> {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  return token ? { cookie: `${SESSION_COOKIE}=${token}` } : {};
}

/** GET, returning null for anything that is not a 200. */
export async function get<T>(path: string): Promise<T | null> {
  try {
    const response = await fetch(`${API_ORIGIN}${path}`, {
      headers: await sessionHeader(),
      cache: "no-store",
    });
    if (!response.ok) return null;
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

export type WriteResult<T> = { ok: true; data: T } | { ok: false; reason: string };

/**
 * POST, for the server actions.
 *
 * The failure reason is drawn from a fixed set here rather than from the response
 * body. The API's enumerated `detail` values are safe, but a route added later that
 * echoed something back would put it on a screen, and invariant 12 is easier to keep
 * when the boundary refuses to carry text at all.
 */
export async function post<T>(path: string, body?: unknown): Promise<WriteResult<T>> {
  try {
    const response = await fetch(`${API_ORIGIN}${path}`, {
      method: "POST",
      headers: { ...(await sessionHeader()), "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
    if (response.status === 401) return { ok: false, reason: "Your session has ended." };
    if (response.status === 404)
      return { ok: false, reason: "Not available to you." };
    if (!response.ok) return { ok: false, reason: "The request was refused." };
    return { ok: true, data: (await response.json()) as T };
  } catch {
    return { ok: false, reason: "The API did not respond." };
  }
}

export async function currentSubject(): Promise<Subject | null> {
  return get<Subject>("/session");
}

export async function apiOrigin(): Promise<string> {
  return API_ORIGIN;
}
