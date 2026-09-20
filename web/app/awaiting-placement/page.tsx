/**
 * Where a signed-in but unplaced account lands.
 *
 * This page exists so that the correct behaviour does not read as a fault. The account
 * is real, the password was right, and `load_subject` forms no Subject because there is
 * no post — so every authorized query is empty and `/session` answers 401. Without
 * somewhere to say that, a new person would log in successfully and be bounced straight
 * back to the login form, which looks exactly like a broken login.
 */
import { redirect } from "next/navigation";

import { Seal } from "../components/icons";
import { authStatus, currentSubject } from "../lib/api";

export const dynamic = "force-dynamic";

export default async function AwaitingPlacementPage() {
  const subject = await currentSubject();
  if (subject) redirect("/");

  const status = await authStatus();
  if (!status?.authenticated) redirect("/login");

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-lg flex-col justify-center px-5 py-16">
      <div className="mb-8 flex items-center gap-3">
        <Seal className="h-10 w-10 text-brass-500" />
        <div>
          <p className="font-serif text-xl font-semibold tracking-tight text-ink-900">Ordin</p>
          <p className="text-[0.7rem] uppercase tracking-[0.18em] text-ink-400">
            Evidence registry
          </p>
        </div>
      </div>

      <div className="surface px-6 py-7">
        <p className="text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-caution-700">
          Awaiting placement
        </p>
        <h1 className="mt-2 font-serif text-2xl font-semibold tracking-tight text-ink-900">
          You are signed in{status.display_name ? `, ${status.display_name}` : ""}.
        </h1>
        <p className="mt-3 text-sm leading-relaxed text-ink-600">
          Your account holds no post yet, so it has no organization, no jurisdiction and
          no clearance. Until an administrator places it, there is no case it can open.
        </p>
        <p className="mt-3 text-xs leading-relaxed text-ink-500">
          This is not a delay in the system finding your records. Access here comes from
          the office you hold, and nobody — including you — can assign that from a signup
          form. It is the same reason a warrant card is issued rather than printed.
        </p>

        <form method="post" action="/actions/auth" className="mt-6">
          <input type="hidden" name="mode" value="logout" />
          <button type="submit" className="btn-quiet">
            Sign out
          </button>
        </form>
      </div>
    </main>
  );
}
