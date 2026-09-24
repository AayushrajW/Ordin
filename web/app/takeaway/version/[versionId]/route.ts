/**
 * Byte-exact version export, proxied so the browser never talks to the API.
 *
 * Narrower than a generic relay: one uuid, GET only. The API re-checks disclosure
 * and refuses a mismatched digest (ADR 0031). The copy is unwatermarked so the
 * recipient's sha256 still matches the case record.
 */
import { cookies } from "next/headers";

const API_ORIGIN = process.env.ORDIN_API_ORIGIN ?? "http://127.0.0.1:8000";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ versionId: string }> },
) {
  const { versionId } = await params;
  if (!UUID.test(versionId)) return new Response(null, { status: 404 });

  const token = (await cookies()).get("ordin_session")?.value;
  const upstream = await fetch(`${API_ORIGIN}/versions/${versionId}/export`, {
    headers: token ? { cookie: `ordin_session=${token}` } : {},
    cache: "no-store",
  });
  // **A refusal has to say something.** Returning a bodiless status meant a browser
  // navigating here for a tampered document showed a blank page: the API's 409
  // `not_exportable:MISMATCH` — the loudest signal this system produces — arrived as
  // nothing at all. The upstream `detail` is an enumerated code, so it can be mapped
  // to a sentence without relaying an upstream body to the client.
  if (!upstream.ok) {
    let detail = "";
    try {
      detail = String(((await upstream.json()) as { detail?: unknown }).detail ?? "");
    } catch {
      detail = "";
    }
    const reason = detail.startsWith("not_exportable:DISPOSED")
      ? "This version was lawfully disposed. Its bytes are not retained, so there is nothing to export. The anchor and the disposal record remain."
      : detail.startsWith("not_exportable:MISMATCH") || detail === "integrity_mismatch"
      ? "This document does not match its anchored digest and was NOT exported. An altered document is never handed over as evidence."
      : detail.startsWith("not_exportable:PENDING")
      ? "This version is not anchored yet. Export is available once its anchor is written."
      : detail.startsWith("not_exportable:")
      ? "This version could not be verified, so it was not exported."
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
  const digest = upstream.headers.get("x-ordin-sha256");
  if (type) headers.set("content-type", type);
  if (disposition) headers.set("content-disposition", disposition);
  if (digest) headers.set("x-ordin-sha256", digest);

  return new Response(upstream.body, { status: 200, headers });
}
