/**
 * Administrative writes, as ordinary form posts (ADR 0018).
 *
 * **This handler decides nothing.** It reshapes a form into a JSON body and forwards it
 * with the session cookie. Every one of these routes is guarded at the API by
 * `require_admin`, which is a policy decision made by `ordin.admin` and logged with the
 * rule id that made it. A check repeated here would be a second place to keep in sync
 * and would tempt somebody into trusting it (threat EXT-06).
 *
 * The API answers a non-administrator with 404, not 403, so a mistake here surfaces as
 * "not available" rather than as confirmation that an administration surface exists.
 */
import { isCrossSite, refuse } from "../../lib/guard";
import { post as apiPost, del as apiDelete } from "../../lib/api";

function seeOther(path: string): Response {
  return new Response(null, { status: 303, headers: { location: path } });
}

function text(form: FormData, name: string, max = 300): string {
  const value = form.get(name);
  return typeof value === "string" ? value.slice(0, max) : "";
}

export async function POST(request: Request) {
  if (isCrossSite(request)) return refuse();
  const form = await request.formData();
  const action = text(form, "action", 24);
  const back = "/admin";

  let result: { ok: boolean; reason?: string };

  switch (action) {
    case "place":
      result = await apiPost(`/admin/users/${text(form, "user_id", 64)}/place`, {
        post_id: text(form, "post_id", 64),
        clearance_level: Number(text(form, "clearance_level", 2)) || 1,
        is_active: true,
      });
      break;

    case "suspend":
      result = await apiPost(`/admin/users/${text(form, "user_id", 64)}/suspend`);
      break;

    case "assign":
      result = await apiPost("/admin/assignments", {
        user_id: text(form, "user_id", 64),
        case_id: text(form, "case_id", 64),
      });
      break;

    case "unassign":
      result = await apiDelete("/admin/assignments", {
        user_id: text(form, "user_id", 64),
        case_id: text(form, "case_id", 64),
      });
      break;

    case "grant":
      result = await apiPost("/admin/grants", {
        grantee_id: text(form, "user_id", 64),
        case_id: text(form, "case_id", 64),
        purpose: text(form, "purpose", 200),
        days: Number(text(form, "days", 4)) || 30,
      });
      break;

    case "revoke":
      result = await apiPost(`/admin/grants/${text(form, "grant_id", 64)}/revoke`);
      break;

    default:
      return seeOther(`${back}?error=unknown`);
  }

  // The reason is one of the fixed strings lib/api.ts produces, never an API body.
  return seeOther(result.ok ? `${back}?done=${action}` : `${back}?error=refused`);
}
