/**
 * The application frame: an ink sidebar carrying the seal, navigation and the current
 * identity, and a warm paper working surface.
 *
 * Everything here renders on the server and works with scripting disabled. The identity
 * switcher is a native `<details>` disclosure holding plain form posts — no hydration
 * bundle has to load before someone can change who they are in the middle of a demo.
 *
 * **Authentication is real** (ADR 0024): `/login` checks a password, and AR-1 is closed.
 * The specimen switcher in the footer is a development convenience that survives only
 * under `ORDIN_ENV=dev` — the API 404s its endpoints outside it, so this frame fetches
 * them only in dev and renders no switcher at all in a deployment.
 *
 * What both routes share, and what the access decisions on these screens rest on, is
 * that the identity is minted and signed by the *server*: the client cannot name itself
 * (threat EXT-02).
 */
import { get, type DemoSubject, type Subject } from "../lib/api";
import VoiceAssistant, { type VoiceCommand } from "./VoiceAssistant";
import {
  IconCases,
  IconChevron,
  IconLogout,
  IconPulse,
  IconSearch,
  IconShield,
  Seal,
} from "./icons";

type Nav = "cases" | "search" | "sentinel" | "health" | "admin";

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
  href, label, hindi, icon, active,
}: { href: string; label: string; hindi: string; icon: React.ReactNode; active: boolean }) {
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
      <span className={active ? "text-brass-300" : "text-ink-300 group-hover:text-ink-200"}>
        {icon}
      </span>
      <span className="min-w-0 leading-tight">
        <span className="block truncate">{label}</span>
        <span lang="hi" className="hi block truncate text-[0.65rem] font-normal text-ink-300 group-hover:text-ink-100">
          {hindi}
        </span>
      </span>
    </a>
  );
}

function WorkspaceNav({ active, isAdmin }: { active: Nav; isAdmin: boolean }) {
  return (
    <>
      <p className="px-3 pb-2 text-[0.625rem] font-semibold uppercase tracking-eyebrow text-ink-500">
        Workspace
        <span lang="hi" className="hi ml-1.5 font-normal normal-case tracking-normal text-ink-500">
          कार्यक्षेत्र
        </span>
      </p>
      <NavLink href="/" label="Case files" hindi="मामला पंजिका" icon={<IconCases />} active={active === "cases"} />
      <NavLink href="/search" label="Search" hindi="खोज" icon={<IconSearch />} active={active === "search"} />
      <p className="px-3 pb-2 pt-4 text-[0.625rem] font-semibold uppercase tracking-eyebrow text-ink-500">
        Assurance
        <span lang="hi" className="hi ml-1.5 font-normal normal-case tracking-normal text-ink-500">
          आश्वासन
        </span>
      </p>
      <NavLink href="/sentinel" label="Sentinel" hindi="प्रहरी" icon={<IconShield />} active={active === "sentinel"} />
      <NavLink href="/health" label="System health" hindi="प्रणाली स्वास्थ्य" icon={<IconPulse />} active={active === "health"} />
      {isAdmin && (
        <NavLink href="/admin" label="Administration" hindi="प्रशासन" icon={<IconShield />} active={active === "admin"} />
      )}
    </>
  );
}

export default async function Shell({
  subject,
  returnTo,
  active,
  voice,
  children,
}: {
  subject: Subject | null;
  returnTo: string;
  active: Nav;
  /** What the assistant reads for this screen, and what it accepts beyond navigation. */
  voice?: { briefing: string; commands?: VoiceCommand[] };
  children: React.ReactNode;
}) {
  // Only in development. `api/session.py` 404s this endpoint outside `ORDIN_ENV=dev`,
  // so without the guard every production page render paid a wasted round-trip and
  // wrote a 404 to the log — a control working correctly, producing noise that looks
  // like a fault.
  const showSpecimen = process.env.ORDIN_ENV === "dev";
  const directory = showSpecimen
    ? await get<{ subjects: DemoSubject[] }>("/demo/subjects")
    : null;
  const subjects = directory?.subjects ?? [];

  return (
    <div className="min-h-screen md:grid md:grid-cols-[16.25rem_minmax(0,1fr)]">
      <aside className="relative flex flex-col overflow-y-auto bg-ink-900 text-ink-100 md:sticky md:top-0 md:h-screen">
        <div className="tricolor relative z-10" aria-hidden />
        <div className="pointer-events-none absolute inset-0 top-[9px] bg-[radial-gradient(120%_60%_at_0%_0%,rgba(200,156,75,0.10),transparent_60%)]" />

        <div className="relative flex items-center justify-between gap-3 px-5 pb-5 pt-5">
          <a href="/" className="flex items-center gap-3">
            <Seal className="h-10 w-10" />
            <span>
              <span className="block font-serif text-[1.4rem] leading-none tracking-tight text-white">Ordin</span>
              <span className="mt-1 block text-[0.625rem] font-semibold uppercase tracking-eyebrow text-brass-300/90">
                Evidence registry
              </span>
              <span lang="hi" className="hi mt-0.5 block text-[0.7rem] text-ink-300">
                साक्ष्य अभिलेख
              </span>
            </span>
          </a>
          <details className="md:hidden">
            <summary className="btn-ghost-ink px-2 py-1 text-xs">Menu</summary>
            <nav className="absolute left-3 right-3 z-20 mt-2 space-y-0.5 rounded-xl border border-ink-700 bg-ink-850 p-2" aria-label="Primary">
              <WorkspaceNav active={active} isAdmin={Boolean(subject?.is_administrative)} />
            </nav>
          </details>
        </div>

        <nav className="relative hidden space-y-0.5 px-3 md:block" aria-label="Primary">
          <WorkspaceNav active={active} isAdmin={Boolean(subject?.is_administrative)} />
        </nav>

        <div className="relative mt-6 px-5 md:mt-auto">
          <div className="rounded-lg border border-brass-500/25 bg-brass-500/[0.07] px-3 py-2.5">
            <p className="text-[0.625rem] font-semibold uppercase tracking-eyebrow text-brass-300">
              Specimen · प्रतिरूप
            </p>
            <p className="mt-1 text-[0.6875rem] leading-snug text-ink-300">
              Synthetic records only. Every page is marked. Every view is watermarked
              and written to the audit chain.
            </p>
          </div>
        </div>

        <div className="relative border-t border-ink-800 p-3 md:mt-4">
          <details className="group">
            <summary className="flex cursor-pointer items-center gap-3 rounded-lg px-2 py-2 transition hover:bg-ink-850">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-ink-700 text-xs font-semibold text-white ring-1 ring-brass-500/40">
                {subject ? initials(subject.display_name) : "—"}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[0.8125rem] font-semibold text-white">
                  {subject?.display_name ?? "No session"}
                </span>
                <span className="flex items-center gap-2 text-[0.6875rem] text-ink-300">
                  {subject ? (
                    <>
                      <span className="truncate">{subject.title}</span>
                      <ClearancePips level={subject.clearance_level} dark />
                    </>
                  ) : (
                    "Sign in to continue"
                  )}
                </span>
              </span>
              <IconChevron className="h-4 w-4 -rotate-90 text-ink-500 transition group-open:rotate-90" />
            </summary>

            <div className="mt-2 space-y-1 rounded-xl border border-ink-700 bg-ink-850 p-2 shadow-lift">
              {showSpecimen && subjects.length > 0 && (
                <p className="px-2 pb-1 pt-1 text-[0.625rem] font-semibold uppercase tracking-eyebrow text-brass-300">
                  Specimen identities · development
                </p>
              )}
              {showSpecimen && subjects.map((s) => {
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
                        <span className="block truncate text-[0.6875rem] text-ink-300">{s.title}</span>
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
                {showSpecimen
                  ? "Development only. The server signs the chosen identity; access is re-decided from the database, never from this menu."
                  : "Session is a signed cookie. Access is re-decided from your post, designation and grants on every request."}
              </p>
            </div>
          </details>
        </div>
      </aside>

      <main className="min-w-0">
        <div className="specimen-tape" role="note">
          <span>SPECIMEN DATA: Synthetic record • Not for operational use</span>
          <span aria-hidden className="text-caution-300">·</span>
          <span lang="hi" className="hi font-normal normal-case tracking-normal">
            प्रतिरूप — वास्तविक अभिलेख नहीं
          </span>
        </div>
        <div className="grain min-h-[calc(100vh-2.25rem)]">{children}</div>
      </main>

      <VoiceAssistant
        briefing={
          voice?.briefing ??
          `Ordin, signed in as ${subject?.display_name ?? "nobody"}. Nothing selected.`
        }
        commands={[
          ...(voice?.commands ?? []),
          { phrase: "case files", aliases: ["go to cases", "open cases"], href: "/", label: "Case files" },
          { phrase: "sentinel", aliases: ["security", "run sentinel"], href: "/sentinel", label: "Sentinel" },
          { phrase: "system health", aliases: ["health"], href: "/health", label: "System health" },
          { phrase: "stop", aliases: ["quiet", "be quiet"], cancel: true, label: "Stop speaking" },
        ]}
      />
    </div>
  );
}

/** Page header: eyebrow, serif title, optional meta line and right-hand actions. */
export function PageHeader({
  eyebrow, title, hindi, meta, actions, crumbs,
}: {
  eyebrow?: React.ReactNode;
  title: React.ReactNode;
  hindi?: string;
  meta?: React.ReactNode;
  actions?: React.ReactNode;
  crumbs?: { label: string; href?: string }[];
}) {
  return (
    <header className="border-b border-paper-300/80 bg-paper-50/90">
      <div className="mx-auto max-w-[88rem] px-6 py-6 lg:px-10">
        {crumbs && (
          <nav aria-label="Breadcrumb" className="mb-3 flex items-center gap-1.5 text-xs text-ink-500">
            {crumbs.map((c, i) => (
              <span key={i} className="flex items-center gap-1.5">
                {c.href ? (
                  <a href={c.href} className="hover:text-ink-800">{c.label}</a>
                ) : (
                  <span className="text-ink-700">{c.label}</span>
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
            {hindi && (
              <p lang="hi" className="hi mt-1 text-base text-ink-500">
                {hindi}
              </p>
            )}
            {meta && <div className="mt-2 text-sm text-ink-500">{meta}</div>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
      </div>
      <div className="register-rule" />
    </header>
  );
}
