/**
 * The application frame: an ink sidebar carrying the seal, navigation and the current
 * identity, and a warm paper working surface.
 *
 * Everything here renders on the server and works with scripting disabled. The identity
 * switcher is a native `<details>` disclosure holding plain form posts — no hydration
 * bundle has to load before someone can change who they are in the middle of a demo.
 *
 * It is labelled, in the frame itself, as a **specimen switcher and not a login**. No
 * credential is checked (accepted risk AR-1). What it does guarantee is that the
 * identity is minted and signed by the server, so the client cannot name itself — which
 * is the difference between the access decisions on these screens meaning something and
 * meaning nothing (threat EXT-02).
 */
import { get, type DemoSubject, type Subject } from "../lib/api";
import {
  IconCases,
  IconChevron,
  IconLogout,
  IconPulse,
  IconShield,
  Seal,
} from "./icons";

type Nav = "cases" | "sentinel" | "health";

export function initials(name: string): string {
  const parts = name.replace(/^(SI|SHO|PP|DSP|ASI|Dr|Ms|Mr)\s+/i, "").split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase();
}

export function ClearancePips({ level, dark = false }: { level: number; dark?: boolean }) {
  return (
    <span className="inline-flex items-center gap-0.5" aria-label={`clearance ${level} of 3`}>
      {[1, 2, 3].map((n) => (
        <span
          key={n}
          className={`h-1.5 w-3 rounded-sm ${
            n <= level ? "bg-brass-400" : dark ? "bg-ink-700" : "bg-paper-300"
          }`}
        />
      ))}
    </span>
  );
}

function NavLink({
  href, label, icon, active,
}: { href: string; label: string; icon: React.ReactNode; active: boolean }) {
  return (
    <a
      href={href}
      aria-current={active ? "page" : undefined}
      className={`group flex items-center gap-3 rounded-lg px-3 py-2 text-[0.8125rem] font-medium transition ${
        active
          ? "bg-ink-800 text-white shadow-[inset_2px_0_0_0_#C89C4B]"
          : "text-ink-300 hover:bg-ink-850 hover:text-white"
      }`}
    >
      <span className={active ? "text-brass-300" : "text-ink-400 group-hover:text-ink-200"}>
        {icon}
      </span>
      {label}
    </a>
  );
}

export default async function Shell({
  subject,
  returnTo,
  active,
  children,
}: {
  subject: Subject | null;
  returnTo: string;
  active: Nav;
  children: React.ReactNode;
}) {
  const directory = await get<{ subjects: DemoSubject[] }>("/demo/subjects");
  const subjects = directory?.subjects ?? [];

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[15.5rem_minmax(0,1fr)]">
      <aside className="relative flex flex-col bg-ink-900 text-ink-100 lg:sticky lg:top-0 lg:h-screen">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(120%_60%_at_0%_0%,rgba(200,156,75,0.10),transparent_60%)]" />

        <div className="relative flex items-center gap-3 px-5 pb-6 pt-6">
          <Seal className="h-9 w-9 drop-shadow" />
          <div>
            <p className="font-serif text-[1.35rem] leading-none tracking-tight text-white">Ordin</p>
            <p className="mt-1 text-[0.625rem] font-semibold uppercase tracking-eyebrow text-brass-300/80">
              Evidence registry
            </p>
          </div>
        </div>

        <nav className="relative space-y-0.5 px-3" aria-label="Primary">
          <p className="px-3 pb-2 text-[0.625rem] font-semibold uppercase tracking-eyebrow text-ink-500">
            Workspace
          </p>
          <NavLink href="/" label="Case files" icon={<IconCases />} active={active === "cases"} />
          <NavLink href="/sentinel" label="Sentinel" icon={<IconShield />} active={active === "sentinel"} />
          <NavLink href="/health" label="System health" icon={<IconPulse />} active={active === "health"} />
        </nav>

        <div className="relative mt-6 px-5 lg:mt-auto">
          <div className="rounded-lg border border-brass-500/25 bg-brass-500/[0.07] px-3 py-2.5">
            <p className="text-[0.625rem] font-semibold uppercase tracking-eyebrow text-brass-300">
              Specimen environment
            </p>
            <p className="mt-1 text-[0.6875rem] leading-snug text-ink-300">
              Synthetic records only. Every page is marked and every view is watermarked
              and audited.
            </p>
          </div>
        </div>

        <div className="relative border-t border-ink-800 p-3 lg:mt-4">
          <details className="group">
            <summary className="flex cursor-pointer items-center gap-3 rounded-lg px-2 py-2 transition hover:bg-ink-850">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-gradient-to-br from-ink-600 to-ink-800 text-xs font-semibold text-white ring-1 ring-ink-600">
                {subject ? initials(subject.display_name) : "—"}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[0.8125rem] font-semibold text-white">
                  {subject?.display_name ?? "No session"}
                </span>
                <span className="flex items-center gap-2 text-[0.6875rem] text-ink-400">
                  {subject ? (
                    <>
                      <span className="truncate">{subject.title}</span>
                      <ClearancePips level={subject.clearance_level} dark />
                    </>
                  ) : (
                    "Choose an identity"
                  )}
                </span>
              </span>
              <IconChevron className="h-4 w-4 -rotate-90 text-ink-500 transition group-open:rotate-90" />
            </summary>

            <div className="mt-2 space-y-1 rounded-xl border border-ink-700 bg-ink-850 p-2 shadow-lift">
              <p className="px-2 pb-1 pt-1 text-[0.625rem] font-semibold uppercase tracking-eyebrow text-brass-300">
                Specimen switcher — not a login
              </p>
              {subjects.map((s) => {
                const current = subject?.user_id === s.user_id;
                return (
                  <form key={s.user_id} method="post" action="/actions/session">
                    <input type="hidden" name="user_id" value={s.user_id} />
                    <input type="hidden" name="next" value={returnTo} />
                    <button
                      type="submit"
                      aria-label={`${s.display_name}, ${s.title}`}
                      className={`flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition ${
                        current ? "bg-ink-700" : "hover:bg-ink-800"
                      }`}
                    >
                      <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-ink-700 text-[0.625rem] font-semibold text-ink-100">
                        {initials(s.display_name)}
                      </span>
                      <span className="min-w-0">
                        <span className="block truncate text-[0.75rem] font-medium text-white">
                          {s.display_name}
                        </span>
                        <span className="block truncate text-[0.6875rem] text-ink-400">{s.title}</span>
                      </span>
                      {current && <span className="dot ml-auto bg-brass-400" />}
                    </button>
                  </form>
                );
              })}
              {subject && (
                <form method="post" action="/actions/session" className="border-t border-ink-700 pt-1">
                  <input type="hidden" name="end" value="1" />
                  <input type="hidden" name="next" value="/" />
                  <button type="submit" className="btn-ghost-ink w-full justify-start px-2 py-1.5 text-[0.75rem]">
                    <IconLogout className="h-3.5 w-3.5" /> End session
                  </button>
                </form>
              )}
              <p className="px-2 pb-1 pt-1 text-[0.625rem] leading-snug text-ink-500">
                No credential is checked. The server signs the chosen identity; every
                decision after that is made from its token, never from the request.
              </p>
            </div>
          </details>
        </div>
      </aside>

      <main className="min-w-0">
        <div className="grain min-h-screen">{children}</div>
      </main>
    </div>
  );
}

/** Page header: eyebrow, serif title, optional meta line and right-hand actions. */
export function PageHeader({
  eyebrow, title, meta, actions, crumbs,
}: {
  eyebrow?: React.ReactNode;
  title: React.ReactNode;
  meta?: React.ReactNode;
  actions?: React.ReactNode;
  crumbs?: { label: string; href?: string }[];
}) {
  return (
    <header className="border-b border-paper-300/70 bg-paper-50/80 backdrop-blur">
      <div className="mx-auto max-w-[88rem] px-6 py-6 lg:px-10">
        {crumbs && (
          <nav aria-label="Breadcrumb" className="mb-3 flex items-center gap-1.5 text-xs text-ink-400">
            {crumbs.map((c, i) => (
              <span key={i} className="flex items-center gap-1.5">
                {c.href ? (
                  <a href={c.href} className="hover:text-ink-800">{c.label}</a>
                ) : (
                  <span className="text-ink-600">{c.label}</span>
                )}
                {i < crumbs.length - 1 && <IconChevron className="h-3 w-3 text-ink-300" />}
              </span>
            ))}
          </nav>
        )}
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="min-w-0 animate-rise">
            {eyebrow && <p className="eyebrow mb-2">{eyebrow}</p>}
            <h1 className="page-title">{title}</h1>
            {meta && <div className="mt-2 text-sm text-ink-500">{meta}</div>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
      </div>
    </header>
  );
}
