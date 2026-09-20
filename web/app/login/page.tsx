/**
 * Sign in.
 *
 * Server-rendered, no client JavaScript. The form posts to `/actions/auth`, which is a
 * route handler rather than a server action for the reasons in ADR 0018.
 *
 * The failure text is the same sentence whatever went wrong, because the API returns
 * the same response whatever went wrong: a message distinguishing "no such account"
 * from "wrong password" answers *does this person work here* to somebody who has
 * proved nothing.
 */
import Link from "next/link";
import { redirect } from "next/navigation";

import { Seal } from "../components/icons";
import { authStatus, currentSubject } from "../lib/api";

export const dynamic = "force-dynamic";

const MESSAGES: Record<string, string> = {
  refused: "Those credentials do not match an account.",
  throttled: "Too many attempts from this address. Wait a minute and try again.",
  unreachable: "The server is not reachable. Nothing was sent.",
};

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; created?: string }>;
}) {
  const { error, created } = await searchParams;

  // Already signed in and placed: there is nothing to do here.
  const subject = await currentSubject();
  if (subject) redirect("/");
  const status = await authStatus();
  if (status?.authenticated && status.awaiting_placement) redirect("/awaiting-placement");

  const devSwitcher = process.env.ORDIN_ENV === "dev";

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center px-5 py-16">
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
        <h1 className="font-serif text-2xl font-semibold tracking-tight text-ink-900">Sign in</h1>
        <p className="mt-1.5 text-xs leading-relaxed text-ink-500">
          Your access is decided after you sign in, from the post you hold — not from
          anything this page sends.
        </p>

        {created && (
          <p className="mt-5 rounded-lg bg-verified-50 px-3.5 py-2.5 text-xs leading-relaxed text-verified-700 ring-1 ring-inset ring-verified-100">
            Account created. An administrator has to place it before it can open
            anything — you can sign in now to check its status.
          </p>
        )}
        {error && (
          <p className="mt-5 rounded-lg bg-danger-50 px-3.5 py-2.5 text-xs leading-relaxed text-danger-700 ring-1 ring-inset ring-danger-100">
            {MESSAGES[error] ?? MESSAGES.refused}
          </p>
        )}

        <form method="post" action="/actions/auth" className="mt-6 space-y-4">
          <input type="hidden" name="mode" value="login" />
          <label className="block">
            <span className="mb-1.5 block text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-ink-500">
              Email
            </span>
            <input
              type="email"
              name="email"
              required
              autoComplete="username"
              autoFocus
              className="field w-full"
            />
          </label>
          <label className="block">
            <span className="mb-1.5 block text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-ink-500">
              Password
            </span>
            <input
              type="password"
              name="password"
              required
              autoComplete="current-password"
              className="field w-full"
            />
          </label>
          <button type="submit" className="btn-primary w-full justify-center">
            Sign in
          </button>
        </form>

        <p className="mt-5 text-xs text-ink-500">
          No account?{" "}
          <Link href="/signup" className="font-semibold text-ink-900 underline underline-offset-2">
            Request one
          </Link>
        </p>
      </div>

      {devSwitcher && (
        <div className="surface-quiet mt-4 px-5 py-4">
          <p className="text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-caution-700">
            Development only
          </p>
          <p className="mt-1 text-xs leading-relaxed text-ink-500">
            The specimen identity switcher checks no credential, so it is refused
            entirely when <code className="text-ink-700">ORDIN_ENV</code> is not{" "}
            <code className="text-ink-700">dev</code>.{" "}
            <Link href="/specimen" className="font-semibold text-ink-900 underline underline-offset-2">
              Open the switcher
            </Link>
          </p>
        </div>
      )}
    </main>
  );
}
