/**
 * The page image, proxied so the browser never talks to the API.
 *
 * This is the only route handler in the web tier and it is deliberately narrow: one
 * upstream path, built from a validated uuid, with the session cookie forwarded. A
 * generic `/api/[...path]` proxy would have been fewer lines and would have turned
 * the web tier into an open relay to every endpoint the API has — including any added
 * later by someone who assumed the API was not publicly reachable.
 *
 * It decides nothing. The API re-checks the case, the disclosure class and the
 * version's membership in the readable set on this request like any other, so a
 * subject who guessed a version id gets the same 404 here as anywhere else.
 */
import { cookies } from "next/headers";

const API_ORIGIN = process.env.ORDIN_API_ORIGIN ?? "http://127.0.0.1:8000";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function GET(
  request: Request,
  { params }: { params: Promise<{ versionId: string }> },
) {
  const { versionId } = await params;
  if (!UUID.test(versionId)) return new Response(null, { status: 404 });

  const page = Number(new URL(request.url).searchParams.get("page") ?? "0");
  if (!Number.isInteger(page) || page < 0 || page > 999) {
    return new Response(null, { status: 404 });
  }

  const token = (await cookies()).get("ordin_session")?.value;
  const upstream = await fetch(
    `${API_ORIGIN}/versions/${versionId}/page.png?page=${page}`,
    {
      headers: token ? { cookie: `ordin_session=${token}` } : {},
      cache: "no-store",
    },
  );
  if (!upstream.ok) return new Response(null, { status: upstream.status });

  return new Response(upstream.body, {
    status: 200,
    headers: {
      "content-type": "image/png",
      // Matches what the API sent. A page of evidence cached in a shared browser
      // outlives the session that was permitted to see it.
      "cache-control": "no-store, private",
    },
  });
}
