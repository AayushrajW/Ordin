/**
 * Request an account.
 *
 * Called "request" rather than "sign up" on purpose: what this creates is an account
 * that holds no post, and therefore no organization, no jurisdiction and no clearance.
 * It can open nothing at all until an administrator places it. The page says so before
 * the form rather than after, because a person who expects to be working in thirty
 * seconds and instead sees an empty screen will reasonably think the system is broken.
 *
 * The refusal text does not distinguish an address already in use from one that was
 * rejected, because the API does not: a signup form that confirms who already has an
 * account is an enumeration oracle.
 */
import Link from "next/link";

import PasswordField from "../components/PasswordField";
import { Seal } from "../components/icons";
import { MIN_PASSWORD } from "../lib/constants";

export const dynamic = "force-dynamic";

const MESSAGES: Record<string, string> = {
  rejected: "That address cannot be registered.",
  weak: `That password is too short — use at least ${MIN_PASSWORD} characters.`,
  unreachable: "The server is not reachable. Nothing was sent.",
};

export default async function SignupPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const { error } = await searchParams;

  return (
    <main className="min-h-screen bg-paper-100">
      <div className="tricolor" aria-hidden />
      <div className="mx-auto flex w-full max-w-md flex-col justify-center px-5 py-16">
      <div className="mb-8 flex items-center gap-3">
        <Seal className="h-10 w-10 text-brass-500" />
        <div>
          <p className="font-serif text-xl font-semibold tracking-tight text-ink-900">Ordin</p>
          <p className="text-[0.7rem] uppercase tracking-[0.18em] text-ink-500">
            Evidence registry
          </p>
          <p lang="hi" className="hi text-sm text-ink-500">साक्ष्य अभिलेख</p>
        </div>
      </div>

      <div className="surface px-6 py-7">
        <h1 className="font-serif text-2xl font-semibold tracking-tight text-ink-900">
          Request an account
        </h1>
        <p lang="hi" className="hi mt-1 text-sm text-ink-500">खाता अनुरोध</p>
        <p className="mt-1.5 text-xs leading-relaxed text-ink-500">
          This creates an account and nothing else. It holds no post, so it can open no
          case until an administrator places it. You cannot choose your own organization
          or clearance here — that is the point.
        </p>

        {error && (
          <p className="mt-5 rounded-lg bg-danger-50 px-3.5 py-2.5 text-xs leading-relaxed text-danger-700 ring-1 ring-inset ring-danger-100">
            {MESSAGES[error] ?? MESSAGES.rejected}
          </p>
        )}

        <form method="post" action="/actions/auth" className="mt-6 space-y-4">
          <input type="hidden" name="mode" value="signup" />
          <label className="block">
            <span className="mb-1.5 block text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-ink-500">
              Name
            </span>
            <input
              type="text"
              name="display_name"
              required
              maxLength={120}
              autoComplete="name"
              className="field w-full"
            />
          </label>
          <label className="block">
            <span className="mb-1.5 block text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-ink-500">
              Email
            </span>
            <input
              type="email"
              name="email"
              required
              autoComplete="username"
              className="field w-full"
            />
          </label>
          <PasswordField
            autoComplete="new-password"
            minLength={MIN_PASSWORD}
            hint={`At least ${MIN_PASSWORD} characters. Length is the only rule — required symbols and capitals are known to produce predictable passwords.`}
          />
          <button type="submit" className="btn-primary w-full justify-center">
            Request an account
          </button>
        </form>

        <p className="mt-5 text-xs text-ink-500">
          Already have one?{" "}
          <Link href="/login" className="font-semibold text-ink-900 underline underline-offset-2">
            Sign in
          </Link>
        </p>
      </div>
      </div>
    </main>
  );
}
