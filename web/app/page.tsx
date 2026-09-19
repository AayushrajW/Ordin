/**
 * Front door and case dashboard.
 *
 * Without a session: the identity chooser, presented as what it is — a specimen
 * switcher, not a login.
 *
 * With one: the cases this subject may see. **Nothing on this page filters anything.**
 * The list arrives already filtered, because the policy predicate sits inside the SQL
 * `WHERE` clause that produced it (invariant 1), and the count comes from a separate
 * endpoint that applies the same predicate inside the aggregate. Switching identity
 * changes what this page contains; the code path is identical.
 */
import Shell, { ClearancePips, PageHeader, initials } from "./components/Shell";
import { IconArrowRight, IconChain, IconEye, IconLock, IconRedact, IconShield, Seal } from "./components/icons";
import { Empty, SealedTag, StateRail, Stat, relative } from "./components/ui";
import {
  currentSubject,
  get,
  type CaseRecord,
  type CaseSummary,
  type DemoSubject,
} from "./lib/api";

export const dynamic = "force-dynamic";

const PROMISES = [
  { icon: <IconShield className="h-4 w-4" />, title: "Authorization inside every query",
    body: "Seven dimensions, evaluated in the database. A case you may not open is not in the list, the count, the search or the autocomplete." },
  { icon: <IconRedact className="h-4 w-4" />, title: "Redaction that destroys, not covers",
    body: "Every mention of a protected identity is found and burned out of the page — including the ones in the narrative." },
  { icon: <IconChain className="h-4 w-4" />, title: "A hash-chained record of custody",
    body: "Every commit, upload and view is an append-only audit row that commits to the one before it." },
  { icon: <IconEye className="h-4 w-4" />, title: "Nothing leaves this machine",
    body: "No cloud, no model, no telemetry. OCR, extraction and verification run offline." },
];

async function Chooser() {
  const directory = await get<{ subjects: DemoSubject[] }>("/demo/subjects");
  const subjects = directory?.subjects ?? [];
  return (
    <div className="grid min-h-screen lg:grid-cols-[1.05fr_1fr]">
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
            Case-centric evidence intelligence for investigation and prosecution. A document
            here exists as proof that a step in a case lawfully happened — and every screen
            shows only what the person looking is entitled to see.
          </p>

          <ul className="mt-10 grid gap-5 sm:grid-cols-2">
            {PROMISES.map((p) => (
              <li key={p.title} className="animate-rise">
                <span className="grid h-8 w-8 place-items-center rounded-lg bg-ink-800 text-brass-300 ring-1 ring-ink-700">
                  {p.icon}
                </span>
                <p className="mt-3 text-[0.8125rem] font-semibold text-white">{p.title}</p>
                <p className="mt-1 text-xs leading-relaxed text-ink-400">{p.body}</p>
              </li>
            ))}
          </ul>

          <p className="mt-auto pt-12 text-[0.6875rem] text-ink-500">
            SIH 2026 · Problem Statement 26190 · Team Valora · specimen environment — every
            record is synthetic.
          </p>
        </div>
      </section>

      <section className="flex items-center px-6 py-12 lg:px-14">
        <div className="mx-auto w-full max-w-md">
          <p className="eyebrow text-brass-600">Specimen switcher — not a login</p>
          <h2 className="mt-2 font-serif text-3xl tracking-tight text-ink-900">Choose who you are</h2>
          <p className="mt-2 text-sm leading-relaxed text-ink-500">
            No credential is checked. The server signs the identity you pick, and every
            decision after that — designation, grant, clearance, purpose, expiry — is made
            from that token on the server, never from anything this page sends.
          </p>

          <div className="mt-8 space-y-2.5">
            {subjects.map((s, i) => (
              <form key={s.user_id} method="post" action="/actions/session" style={{ animationDelay: `${i * 60}ms` }} className="animate-rise">
                <input type="hidden" name="user_id" value={s.user_id} />
                <input type="hidden" name="next" value="/" />
                <button
                  type="submit"
                  aria-label={`${s.display_name}, ${s.title}`}
                  className="surface group flex w-full items-center gap-4 px-4 py-3.5 text-left transition hover:-translate-y-px hover:border-brass-300 hover:shadow-lift"
                >
                  <span className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-gradient-to-br from-ink-700 to-ink-900 text-sm font-semibold text-white ring-2 ring-paper-200">
                    {initials(s.display_name)}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[0.9rem] font-semibold text-ink-900">{s.display_name}</span>
                    <span className="block text-xs text-ink-500">{s.title}</span>
                  </span>
                  <IconArrowRight className="h-4 w-4 text-ink-300 transition group-hover:translate-x-0.5 group-hover:text-brass-500" />
                </button>
              </form>
            ))}
          </div>
          {subjects.length === 0 && (
            <p className="mt-8 rounded-xl border border-danger-100 bg-danger-50 px-4 py-3 text-sm text-danger-700">
              The API is not answering. Start it with <span className="kbd">python tasks.py up</span>.
            </p>
          )}
        </div>
      </section>
    </div>
  );
}

function AccessLine({ summary }: { summary: CaseSummary | null }) {
  if (!summary) return null;
  if (summary.route === "designation") {
    return (
      <span className="chip-verified">
        <span className="dot bg-verified-500" /> Designated · original documents
      </span>
    );
  }
  return (
    <span className="chip-signal" title={summary.purpose ?? undefined}>
      <span className="dot bg-signal-500" /> Grant · {summary.purpose} · expires{" "}
      {relative(summary.grant_expires_at)}
    </span>
  );
}

export default async function Home() {
  const subject = await currentSubject();
  if (!subject) return <Chooser />;

  const cases = (await get<CaseRecord[]>("/cases?limit=50")) ?? [];
  const counted = await get<{ count: number }>("/cases/count");
  const summaries = await Promise.all(cases.map((c) => get<CaseSummary>(`/cases/${c.id}/summary`)));
  const documents = summaries.reduce((n, s) => n + (s?.documents ?? 0), 0);
  const drafts = summaries.reduce((n, s) => n + (s?.drafts_awaiting ?? 0), 0);
  const originalReader = summaries.some((s) => s?.disclosure === "original");

  return (
    <Shell subject={subject} returnTo="/" active="cases">
      <PageHeader
        eyebrow={`Signed in as ${subject.title}`}
        title="Case files"
        meta={
          <span className="flex flex-wrap items-center gap-3">
            <span>{subject.display_name}</span>
            <span className="text-ink-300">·</span>
            <span className="flex items-center gap-2">clearance <ClearancePips level={subject.clearance_level} /></span>
          </span>
        }
      />

      <div className="mx-auto max-w-[88rem] space-y-8 px-6 py-8 lg:px-10">
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Stat label="Cases you can open" value={counted?.count ?? cases.length}
                hint="Counted inside the query — not a total you may not see" />
          <Stat label="Documents in reach" value={documents}
                hint={originalReader ? "Originals and their derivatives" : "Redacted derivatives only"} />
          <Stat label="Awaiting a human" value={originalReader ? drafts : "—"} tone={drafts ? "caution" : "ink"}
                hint={originalReader ? "Machine-extracted drafts nobody has committed" : "Not disclosed to a grantee"} />
          <a href="/sentinel" className="surface group block px-5 py-4 transition hover:border-brass-300 hover:shadow-lift">
            <p className="eyebrow">Security posture</p>
            <p className="mt-2 flex items-center gap-2 font-display text-[1.05rem] font-semibold text-ink-900">
              <IconShield className="h-5 w-5 text-brass-500" /> Run Sentinel
            </p>
            <p className="mt-2 text-xs text-ink-400">
              Every security claim, tested live against this system
              <IconArrowRight className="ml-1 inline h-3 w-3 transition group-hover:translate-x-0.5" />
            </p>
          </a>
        </div>

        {cases.length === 0 ? (
          <Empty title="No case is within your reach">
            This identity holds neither a designation nor an unexpired, lawfully issued grant
            with a current clearance — so the query returned nothing. That is a result, not an
            error, and it is the same result calling the API directly would give.
          </Empty>
        ) : (
          <section>
            <div className="mb-3 flex items-baseline justify-between">
              <h2 className="section-title">Open matters</h2>
              <p className="text-xs text-ink-400">Stages are generic placeholders pending a statutory citation</p>
            </div>
            <ul className="grid gap-4 xl:grid-cols-2">
              {cases.map((c, i) => {
                const s = summaries[i];
                return (
                  <li key={c.id} className="animate-rise" style={{ animationDelay: `${i * 50}ms` }}>
                    <a href={`/cases/${c.id}`} className="surface group block overflow-hidden transition hover:-translate-y-px hover:border-brass-300 hover:shadow-lift">
                      <div className="flex items-start justify-between gap-4 px-6 pb-4 pt-5">
                        <div className="min-w-0">
                          <p className="eyebrow">Case reference</p>
                          <p className="mt-1 font-mono text-[1.35rem] font-semibold tracking-tight text-ink-900">{c.reference}</p>
                        </div>
                        <div className="flex flex-col items-end gap-2">
                          {c.access_class === "sealed" && <SealedTag />}
                          <AccessLine summary={s} />
                        </div>
                      </div>
                      <div className="px-6 pb-5"><StateRail state={c.state} /></div>
                      <div className="flex items-center justify-between border-t border-paper-200 bg-paper-50/70 px-6 py-3 text-xs text-ink-500">
                        <span className="flex items-center gap-4">
                          <span><span className="num font-semibold text-ink-800">{s?.documents ?? 0}</span> documents</span>
                          {s?.drafts_awaiting !== null && s?.drafts_awaiting !== undefined && (
                            <span className={s.drafts_awaiting ? "text-caution-600" : ""}>
                              <span className="num font-semibold">{s.drafts_awaiting}</span> awaiting review
                            </span>
                          )}
                          {s?.disclosure === "redacted" && (
                            <span className="flex items-center gap-1 text-signal-600"><IconLock className="h-3 w-3" /> derivatives only</span>
                          )}
                        </span>
                        <span className="flex items-center gap-1 font-semibold text-ink-700 group-hover:text-brass-600">
                          Open <IconArrowRight className="h-3.5 w-3.5 transition group-hover:translate-x-0.5" />
                        </span>
                      </div>
                    </a>
                  </li>
                );
              })}
            </ul>
          </section>
        )}
      </div>
    </Shell>
  );
}
