/**
 * The identity switcher, labelled for what it is.
 *
 * CLAUDE.md's honesty rules apply to UI copy as much as to class names, and this is
 * the screen most likely to be mistaken for something it is not. It is a **specimen
 * switcher, not a login**: no credential is checked, and anyone who can reach the
 * endpoint can become any seeded identity. That is accepted risk AR-1 and it is
 * printed on the component rather than left in a document nobody opens.
 *
 * What it is *not* is a role dropdown the API trusts. Choosing an identity asks the
 * server to issue a signed token; every decision afterwards is made from that token,
 * server-side. The difference is the whole of slice 3 (threat EXT-02).
 *
 * Plain forms, no JavaScript. Switching identity mid-demo must not depend on a
 * hydration bundle having loaded.
 */
import { get, type DemoSubject, type Subject } from "../lib/api";

export default async function IdentityBar({
  current,
  returnTo,
}: {
  current: Subject | null;
  returnTo: string;
}) {
  const directory = await get<{ subjects: DemoSubject[] }>("/demo/subjects");
  const subjects = directory?.subjects ?? [];

  return (
    <div className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-3 px-6 py-3">
        <a href="/" className="text-sm font-semibold tracking-tight">
          Ordin
        </a>
        <nav className="flex gap-4 text-sm text-slate-600">
          <a className="hover:text-slate-900" href="/">
            Cases
          </a>
          <a className="hover:text-slate-900" href="/sentinel">
            Sentinel
          </a>
          <a className="hover:text-slate-900" href="/health">
            Health
          </a>
        </nav>

        <div className="ml-auto flex items-center gap-3">
          {current ? (
            <>
              <span className="text-sm text-slate-600">
                <span className="font-medium text-slate-900">{current.display_name}</span>
                <span className="text-slate-400"> · </span>
                {current.title}
                <span className="text-slate-400"> · clearance {current.clearance_level}</span>
              </span>
              <form method="post" action="/actions/session">
                <input type="hidden" name="end" value="1" />
                <input type="hidden" name="next" value={returnTo} />
                <button
                  type="submit"
                  className="rounded border border-slate-300 px-2.5 py-1 text-xs text-slate-700 hover:bg-slate-50"
                >
                  End session
                </button>
              </form>
            </>
          ) : (
            <span className="text-sm text-slate-500">No session</span>
          )}
        </div>
      </div>

      <div className="mx-auto max-w-6xl border-t border-slate-100 px-6 py-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="mr-1 text-xs font-medium uppercase tracking-wide text-amber-700">
            Specimen switcher — not a login
          </span>
          {subjects.map((s) => (
            <form key={s.user_id} method="post" action="/actions/session">
              <input type="hidden" name="user_id" value={s.user_id} />
              <input type="hidden" name="next" value={returnTo} />
              <button
                type="submit"
                aria-label={`${s.display_name}, ${s.title}`}
                className={`rounded-full border px-3 py-1 text-xs ${
                  current?.user_id === s.user_id
                    ? "border-slate-900 bg-slate-900 text-white"
                    : "border-slate-300 text-slate-700 hover:bg-slate-50"
                }`}
              >
                {s.display_name}
                <span className="ml-1.5 opacity-60">{s.title}</span>
              </button>
            </form>
          ))}
        </div>
        <p className="mt-1.5 text-xs text-slate-400">
          No credential is checked. Identity is resolved server-side from a signed
          session token, never from a header or a parameter — which is what makes the
          access decisions on these screens mean anything.
        </p>
      </div>
    </div>
  );
}
