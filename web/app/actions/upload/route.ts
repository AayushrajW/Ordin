/**
 * Upload: parse the browser's multipart form here, forward the bytes to the API.
 *
 * FastAPI needs `python-multipart` to accept a file, and CLAUDE.md is explicit that a
 * dependency is asked for rather than added. The web runtime already parses multipart
 * with the platform's own `FormData`, so doing it here costs nothing and leaves the
 * API route taking a plain `application/pdf` body.
 *
 * This handler does no validation beyond a cheap size guard: the sanitising, the
 * content sniffing and the authorization all happen at the API, inside
 * `Pipeline.run`, where no future caller can skip them. A check repeated here would
 * be a second place to keep in sync and would tempt somebody into trusting it.
 */
import { cookies } from "next/headers";

const API_ORIGIN = process.env.ORDIN_API_ORIGIN ?? "http://127.0.0.1:8000";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const MAX_BYTES = 25 * 1024 * 1024;

const CODES: Record<string, string> = {
  content_is_not_pdf: "notpdf",
  exceeds_size_limit: "toolarge",
  exceeds_page_limit: "toolarge",
  encrypted_pdf: "encrypted",
  pdf_could_not_be_parsed: "unreadable",
  active_content_survived_sanitisation: "unsafe",
  empty_upload: "input",
};

function back(path: string, key?: string, value?: string): Response {
  const separator = path.includes("?") ? "&" : "?";
  const target = key ? `${path}${separator}${key}=${encodeURIComponent(value ?? "1")}` : path;
  return new Response(null, { status: 303, headers: { location: target } });
}

export async function POST(request: Request) {
  const form = await request.formData();
  const caseId = form.get("case_id");
  const raw = form.get("next");
  const target =
    typeof raw === "string" && raw.startsWith("/") && !raw.startsWith("//") ? raw : "/";

  if (typeof caseId !== "string" || !UUID.test(caseId)) return back(target, "error", "input");

  const file = form.get("file");
  if (!(file instanceof File) || file.size === 0) return back(target, "error", "input");
  if (file.size > MAX_BYTES) return back(target, "error", "toolarge");

  const token = (await cookies()).get("ordin_session")?.value;
  let upstream: Response;
  try {
    upstream = await fetch(
      `${API_ORIGIN}/cases/${caseId}/documents?filename=${encodeURIComponent(file.name)}`,
      {
        method: "POST",
        headers: {
          "content-type": "application/pdf",
          ...(token ? { cookie: `ordin_session=${token}` } : {}),
        },
        body: await file.arrayBuffer(),
        cache: "no-store",
      },
    );
  } catch {
    return back(target, "error", "unreachable");
  }

  if (upstream.status === 401) return back(target, "error", "session");
  if (upstream.status === 404) return back(target, "error", "refused");
  if (upstream.status === 422) {
    const detail = (await upstream.json().catch(() => ({}))) as { detail?: string };
    return back(target, "error", CODES[detail.detail ?? ""] ?? "refused");
  }
  if (!upstream.ok) return back(target, "error", "refused");

  const result = (await upstream.json()) as { document_id: string };
  return back(`/documents/${result.document_id}`, "uploaded", "1");
}
