/**
 * Sign in.
 *
 * The form is a plain post to `/actions/auth` and works with scripting disabled
 * (ADR 0018). The only client-side JavaScript on the page is the password reveal
 * toggle, which appears after hydration and is absent rather than inert without it.
 *
 * The failure text is one sentence whatever went wrong, because the API returns one
 * response whatever went wrong: distinguishing "no such account" from "wrong password"
 * answers *does this person work here* to somebody who has proved nothing.
 */
import Link from "next/link";
import { redirect } from "next/navigation";

import PasswordField from "../components/PasswordField";
import { IconChain, IconEye, IconLock, IconRedact, IconShield, Seal } from "../components/icons";
import { authStatus, currentSubject } from "../lib/api";

export const dynamic = "force-dynamic";

const MESSAGES: Record<string, string> = {
  refused: "Those credentials do not match an account.",
  throttled: "Too many attempts from this address. Wait a minute and try again.",
  unreachable: "The server is not reachable. Nothing was sent.",
};

const ASSURANCES = [
  {
    icon: <IconShield className="h-4 w-4" />,
    title: "Signing in grants nothing by itself",
    body: "Access comes from the post you hold, the cases you are designated on and the grants issued to you — re-checked on every request, never carried in this form.",
  },
  {
    icon: <IconLock className="h-4 w-4" />,
    title: "Your password is never stored",
    body: "Only an Argon2id hash, salted per account. Nobody with the database can read it back, and nothing here is ever written to a log.",
  },
  {
    icon: <IconChain className="h-4 w-4" />,
    title: "Every view is recorded",
    body: "Opening a document appends a hash-chained audit row naming you and the moment. The application role holds no UPDATE or DELETE on that table.",
  },
  {
    icon: <IconEye className="h-4 w-4" />,
    title: "Nothing leaves this machine",
    body: "No cloud, no model, no telemetry. OCR, extraction and verification run offline.",
  },
];

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; created?: string }>;
}) {
  const { error, created } = await searchParams;

  const subject = await currentSubject();
  if (subject) redirect("/");
  const status = await authStatus();
  if (status?.authenticated && status.awaiting_placement) redirect("/awaiting-placement");

  return (
    <main className="grid min-h-screen lg:grid-cols-[1.05fr_1fr]">
      {/* Left: what signing in does and does not do. */}
      <section className="relative overflow-hidden bg-ink-900 px-8 py-12 text-ink-100 lg:px-14 lg:py-16">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(90%_70%_at_10%_0%,rgba(200,156,75,0.16),transparent_60%),radial-gradient(70%_60%_at_100%_100%,rgba(68,89,214,0.18),transparent_60%)]" />
        <div className="relative flex h-full max-w-xl flex-col">
          <div className="flex items-center gap-3">
            <Seal className="h-11 w-11" />
            <div>
              <p className="font-serif text-2xl leading-none text-white">Ordin</p>
              <p className="mt-1 text-[0.625rem] font-semibold uppercase tracking-eyebrow text-brass-300/80">
                Evidence registry
              </p>
            </div>
          </div>

          <h1 className="mt-14 font-serif text-[2.6rem] leading-[1.08] tracking-tight text-white lg:mt-20">
            The case record,
            <br />
            <span className="text-brass-300">not the document store.</span>
          </h1>
          <p className="mt-5 max-w-md text-[0.95rem] leading-relaxed text-ink-300">
            A document here exists as proof that a step in a case lawfully happened, and
            every screen shows only what the person looking is entitled to see.
          </p>

          <ul className="mt-10 grid gap-5 sm:grid-cols-2">
            {ASSURANCES.map((a) => (
              <li key={a.title} className="animate-rise">
                <span className="grid h-8 w-8 place-items-center rounded-lg bg-ink-800 text-brass-300 ring-1 ring-ink-700">
                  {a.icon}
                </span>
                <p className="mt-3 text-[0.8125rem] font-semibold text-white">{a.title}</p>
                <p className="mt-1 text-xs leading-relaxed text-ink-400">{a.body}</p>
              </li>
            ))}
          </ul>

          <p className="mt-auto pt-12 text-[0.6875rem] text-ink-500">
            SIH 2026 · Problem Statement 26190 · Team Valora · specimen environment — every
            record is synthetic.
          </p>
        </div>
      </section>

      {/* Right: the form. */}
      <section className="flex items-center bg-paper-100 px-6 py-12 lg:px-14">
        <div className="mx-auto w-full max-w-sm">
          <p className="eyebrow text-brass-600">Secure sign-in</p>
          <h2 className="mt-2 font-serif text-3xl tracking-tight text-ink-900">
            Welcome back
          </h2>
          <p className="mt-2 text-sm leading-relaxed text-ink-500">
            Your access is decided after you sign in, from the post you hold — not from
            anything this page sends.
          </p>

          {created && (
            <p className="mt-6 rounded-lg bg-verified-50 px-3.5 py-2.5 text-xs leading-relaxed text-verified-700 ring-1 ring-inset ring-verified-100">
              Account created. An administrator has to place it before it can open
              anything — sign in now to check its status.
            </p>
          )}
          {error && (
            <p
              role="alert"
              className="mt-6 rounded-lg bg-danger-50 px-3.5 py-2.5 text-xs leading-relaxed text-danger-700 ring-1 ring-inset ring-danger-100"
            >
              {MESSAGES[error] ?? MESSAGES.refused}
            </p>
          )}

          <form method="post" action="/actions/auth" className="mt-7 space-y-4">
            <input type="hidden" name="mode" value="login" />
            <label className="block">
              <span className="mb-1.5 block text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-ink-400">
                Email
              </span>
              <input
                type="email"
                name="email"
                required
                autoComplete="username"
                autoFocus
                placeholder="you@department.gov.in"
                className="field w-full"
              />
            </label>

            <PasswordField autoComplete="current-password" />

            <button type="submit" className="btn-primary w-full justify-center py-2.5">
              Sign in
            </button>
          </form>

          <p className="mt-6 border-t border-paper-300 pt-5 text-xs text-ink-500">
            No account?{" "}
            <Link
              href="/signup"
              className="font-semibold text-ink-900 underline underline-offset-2 hover:text-brass-600"
            >
              Request one
            </Link>
            <span className="mt-1.5 block text-[0.7rem] leading-relaxed text-ink-400">
              A request creates an account that holds no post, so it can open nothing
              until an administrator places it.
            </span>
          </p>

          <p className="mt-5 text-[0.7rem] leading-relaxed text-ink-400">
            Demonstrating this system?{" "}
            <Link href="/specimen" className="font-semibold text-ink-600 underline underline-offset-2">
              Specimen identity switcher
            </Link>
            {" — "}development only, and refused outright by the API in any other
            environment.
          </p>
        </div>
      </section>
    </main>
  );
}
