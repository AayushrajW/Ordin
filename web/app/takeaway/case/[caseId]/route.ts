/**
 * Case export archive, proxied. Same discipline as the version export route.
 */
import { cookies } from "next/headers";

const API_ORIGIN = process.env.ORDIN_API_ORIGIN ?? "http://127.0.0.1:8000";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ caseId: string }> },
) {
  const { caseId } = await params;
  if (!UUID.test(caseId)) return new Response(null, { status: 404 });

  const token = (await cookies()).get("ordin_session")?.value;
  const upstream = await fetch(`${API_ORIGIN}/cases/${caseId}/export`, {
    headers: token ? { cookie: `ordin_session=${token}` } : {},
    cache: "no-store",
  });
  // **Every refusal collapsed into a bodiless 404**, which was wrong twice over: a
  // grantee with nothing to export and a case too large to build in memory both got
  // the answer that means "there is no such case", and the reader got a blank page.
  // The status is preserved and the enumerated `detail` is mapped to a sentence.
  if (!upstream.ok) {
    let detail = "";
    try {
      detail = String(((await upstream.json()) as { detail?: unknown }).detail ?? "");
    } catch {
      detail = "";
    }
    const reason = detail === "nothing_to_export"
      ? "There is nothing in this case that you may receive a copy of."
      : detail.startsWith("too_many_documents")
      ? "This case holds more documents than one archive can carry. Export the documents individually."
      : detail.startsWith("too_large")
      ? "This case is larger than one archive can carry. Export the documents individually."
      : upstream.status === 404
      ? "Not available to you."
      : "The export was refused.";
    return new Response(reason, {
      status: upstream.status,
      headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" },
    });
  }

  const headers = new Headers();
  headers.set("cache-control", "no-store, private");
  const type = upstream.headers.get("content-type");
  const disposition = upstream.headers.get("content-disposition");
  const exportId = upstream.headers.get("x-ordin-export-id");
  const rows = upstream.headers.get("x-ordin-row-count");
  if (type) headers.set("content-type", type);
  if (disposition) headers.set("content-disposition", disposition);
  // Carried through so the recipient can tie the archive to its accounting row.
  if (exportId) headers.set("x-ordin-export-id", exportId);
  if (rows) headers.set("x-ordin-row-count", rows);

  return new Response(upstream.body, { status: 200, headers });
}
