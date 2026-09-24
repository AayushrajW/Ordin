/**
 * The case dashboard, and the front door for anyone already signed in.
 *
 * Without a session this redirects to `/login`, which is a real login (ADR 0024) — or
 * to `/awaiting-placement` when the account is authenticated but holds no post, because
 * bouncing a successful login back to the login form reads as a broken login. The
 * specimen switcher lives at `/specimen` and exists only under `ORDIN_ENV=dev`.
 *
 * With one: the cases this subject may see. **Nothing on this page filters anything.**
 * The list arrives already filtered, because the policy predicate sits inside the SQL
 * `WHERE` clause that produced it (invariant 1), and the count comes from a separate
 * endpoint that applies the same predicate inside the aggregate. Switching identity
 * changes what this page contains; the code path is identical.
 */
import { redirect } from "next/navigation";

import Shell, { ClearancePips, PageHeader } from "./components/Shell";
import { IconArrowRight, IconChain, IconEye, IconLock, IconRedact, IconShield } from "./components/icons";
import { Empty, SealedTag, StateRail, Stat, TechnicalDetails, relative, Bi } from "./components/ui";
import {
  authStatus,
  currentSubject,
  get,
  type CaseRecord,
  type CaseSummary,
  type Completeness,
  type DocumentRecord,
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
  { icon: <IconEye className="h-4 w-4" />, title: "Demonstration runs locally",
    body: "This demonstration runs entirely on the local machine. No demonstration data leaves this environment. Production deployment is designed for controlled government infrastructure." },
];

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
  if (!subject) {
    // An account can be signed in and hold no post, in which case `/session` refuses
    // and there is a page that explains why rather than a login loop.
    const status = await authStatus();
    redirect(status?.authenticated ? "/awaiting-placement" : "/login");
  }

  const cases = (await get<CaseRecord[]>("/cases?limit=50")) ?? [];
  const counted = await get<{ count: number }>("/cases/count");
  const summaries = await Promise.all(cases.map((c) => get<CaseSummary>(`/cases/${c.id}/summary`)));
  const completenessList = await Promise.all(cases.map((c) => get<Completeness>(`/cases/${c.id}/completeness`)));
  const documentsList = await Promise.all(cases.map((c) => get<DocumentRecord[]>(`/cases/${c.id}/documents`)));
  // Same guard as Shell.tsx, and for the same reason: `api/session.py` 404s this
  // endpoint outside ORDIN_ENV=dev, so an unguarded call makes every production
  // dashboard render pay a wasted round-trip and write a 404 to the log — a control
  // working correctly, producing noise that reads as a fault.
  const demoDirectory =
    process.env.ORDIN_ENV === "dev"
      ? await get<{ subjects: DemoSubject[] }>("/demo/subjects")
      : null;
  const shoUser = demoDirectory?.subjects?.find((s) => s.display_name.startsWith("SHO"));
  const isIO = subject.user_id === shoUser?.user_id;

  const documents = summaries.reduce((n, s) => n + (s?.documents ?? 0), 0);
  const drafts = summaries.reduce((n, s) => n + (s?.drafts_awaiting ?? 0), 0);
  const originalReader = summaries.some((s) => s?.disclosure === "original");

  // Counts and names of things, never the contents of a case.
  const briefing =
    `Case files. ${counted?.count ?? cases.length} ` +
    `${(counted?.count ?? cases.length) === 1 ? "case is" : "cases are"} within reach of ` +
    `${subject.display_name}, ${subject.title}. ${documents} documents. ` +
    (originalReader
      ? `${drafts} fields awaiting a human.`
      : "You receive redacted derivatives only.");

  return (
    <Shell
      subject={subject}
      returnTo="/"
      active="cases"
      voice={{
        briefing,
        commands: cases.slice(0, 3).map((c, i) => ({
          phrase: i === 0 ? "open the case" : `open case ${i + 1}`,
          aliases: i === 0 ? ["open first case"] : [],
          href: `/cases/${c.id}`,
          label: `Open ${c.reference}`,
        })),
      }}
    >
      <PageHeader
        eyebrow={`Signed in as ${subject.title}`}
        title="Case files"
        hindi="मामला पंजिका"
        meta={
          <span className="flex flex-wrap items-center gap-3">
            <span>{subject.display_name}</span>
            <span className="text-ink-300">·</span>
            <span className="flex items-center gap-2">clearance <ClearancePips level={subject.clearance_level} /></span>
          </span>
        }
      />

      <div className="mx-auto max-w-[88rem] space-y-8 px-6 py-8 lg:px-10">
        {!isIO && shoUser && (
          <div className="surface flex flex-wrap items-center justify-between gap-4 border-l-4 border-brass-500 bg-paper-50 p-4 shadow-sm animate-rise">
            <div className="flex items-center gap-3.5">
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-brass-100 text-brass-700">
                <IconShield className="h-5 w-5" />
              </span>
              <div>
                <p className="text-sm font-semibold text-ink-900">
                  Primary Demonstration Case · Investigating Officer View
                </p>
                <p className="text-xs text-ink-600">
                  Primary case record <strong className="font-mono font-bold text-ink-900">VRN/26/0142</strong> is assigned to Investigating Officer <strong className="text-ink-800">SHO Rahul Desai</strong> (Clearance 3). Switch identity to access the complete operational case file.
                </p>
              </div>
            </div>
            <form method="post" action="/actions/session">
              <input type="hidden" name="user_id" value={shoUser.user_id} />
              <input type="hidden" name="next" value="/" />
              <button type="submit" className="btn-primary flex items-center gap-2 px-3.5 py-2 text-xs">
                Switch to SHO Rahul Desai <IconArrowRight className="h-3.5 w-3.5" />
              </button>
            </form>
          </div>
        )}

        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Stat
            label={<Bi en="Cases you can open" hi="आपके मामले" />}
            value={counted?.count ?? cases.length}
            hint="Counted inside the query — not a total you may not see"
          />
          <Stat
            label={<Bi en="Documents in reach" hi="दस्तावेज़" />}
            value={documents}
            hint={originalReader ? "Originals and their derivatives" : "Redacted derivatives only"}
          />
          <Stat
            label={<Bi en="Awaiting a human" hi="मानव पुष्टि बाकी" />}
            value={originalReader ? drafts : "—"}
            tone={drafts ? "caution" : "ink"}
            hint={originalReader ? "Machine-extracted drafts nobody has committed" : "Not disclosed to a grantee"}
          />
          <a href="/sentinel" className="surface group block px-5 py-4 transition hover:border-brass-300 hover:shadow-lift">
            <p className="eyebrow">Security posture · सुरक्षा स्थिति</p>
            <p className="mt-2 flex items-center gap-2 font-display text-[1.05rem] font-semibold text-ink-900">
              <IconShield className="h-5 w-5 text-brass-500" /> Run Sentinel
            </p>
            <p lang="hi" className="hi mt-0.5 text-xs text-ink-500">प्रहरी चलाएँ</p>
            <p className="mt-2 text-xs text-ink-500">
              Every security claim, tested live against this system
              <IconArrowRight className="ml-1 inline h-3 w-3 transition group-hover:translate-x-0.5" />
            </p>
          </a>
        </div>

        {(drafts > 0 && originalReader) || cases.length === 0 ? (
          <section className="surface px-5 py-4">
            <p className="eyebrow">Attention required · ध्यान दें</p>
            <ul className="mt-3 space-y-1.5 text-sm text-ink-700">
              {drafts > 0 && originalReader && (
                <li className="flex items-center gap-2 text-caution-700">
                  <span className="dot bg-caution-500" />
                  {drafts} extracted {drafts === 1 ? "field awaits" : "fields await"} a named person
                </li>
              )}
              {cases.length === 0 && (
                <li>No case is within reach of this identity — that is a query result, not an empty database.</li>
              )}
            </ul>
          </section>
        ) : null}

        {cases.length === 0 ? (
          <Empty title="No case is within your reach">
            This identity holds neither a designation nor an unexpired, lawfully issued grant
            with a current clearance — so the query returned nothing. Administration is an
            office that reads no case; switch to a designated officer to open the specimen file.
          </Empty>
        ) : (
          <section>
            <div className="mb-3 flex items-baseline justify-between">
              <h2 className="section-title">
                Open matters
                <span lang="hi" className="hi ml-2 text-xs font-normal text-ink-500">खुले मामले</span>
              </h2>
              <p className="text-xs text-ink-500">Stages are generic placeholders pending a statutory citation</p>
            </div>
            <ul className="grid gap-4 xl:grid-cols-2">
              {cases.map((c, i) => {
                const s = summaries[i];
                const comp = completenessList[i];
                const docs = documentsList[i] ?? [];
                // The reference the record carries, not a nicer-looking one. See the
                // same note on the case page: a substituted case number is a
                // fabricated record identifier.
                const displayRef = c.reference;
                const secondaryRef = null;
                const restrictedCount = docs.reduce(
                  (acc, d) => acc + d.versions.filter((v) => v.is_derivative).length,
                  0
                );
                // **Never name an officer this response does not name.** This used to
                // hardcode "SHO Rahul Desai (IO)" for one seeded case, attributing a
                // case to a person on no evidence - and to the wrong person as soon as
                // the assignment changed. The summary reports the caller's own ROUTE to
                // the case, which is a fact about the caller, so that is all it says.
                const ioDisplay =
                  s?.route === "designation"
                    ? `${subject.display_name} (designated)`
                    : s?.route === "grant"
                    ? "Reached by grant"
                    : null;

                return (
                  <li key={c.id} className="animate-rise" style={{ animationDelay: `${i * 50}ms` }}>
                    <a href={`/cases/${c.id}`} className="docket group block transition hover:-translate-y-px hover:border-brass-300 hover:shadow-lift">
                      <div className="flex items-start justify-between gap-4 px-6 pb-4 pt-5">
                        <div className="min-w-0 pl-1">
                          <div className="flex items-center gap-2">
                            <p className="eyebrow">Case reference · मामला संख्या</p>
                          </div>
                          <div className="mt-1 flex items-baseline gap-2">
                            <p className="font-mono text-[1.4rem] font-bold tracking-tight text-ink-900">
                              {displayRef}
                            </p>
                            {secondaryRef && (
                              <span className="mono text-xs text-ink-400">({secondaryRef})</span>
                            )}
                          </div>
                          {ioDisplay && (
                            <p className="mt-1 text-xs font-medium text-ink-600">
                              {ioDisplay}
                              {s?.route === "grant" && s?.purpose ? ` · ${s.purpose}` : ""}
                            </p>
                          )}
                        </div>
                        <div className="flex flex-col items-end gap-2">
                          {c.access_class === "sealed" && <SealedTag />}
                          <AccessLine summary={s} />
                        </div>
                      </div>

                      <div className="px-6 pb-3 pl-7">
                        <StateRail state={c.state} />
                      </div>

                      {comp && (
                        <div className="px-6 pb-4 pl-7">
                          <div className="flex items-center justify-between text-xs mb-1.5">
                            <span className="text-ink-600 font-medium">Completeness</span>
                            <span className="tabular-nums font-semibold text-ink-900">{comp.percent}%</span>
                          </div>
                          <div className="h-1.5 w-full overflow-hidden rounded-full bg-paper-300">
                            <div
                              className={`h-full rounded-full transition-all ${
                                comp.may_proceed ? "bg-verified-500" : "bg-caution-500"
                              }`}
                              style={{ width: `${comp.percent}%` }}
                            />
                          </div>
                        </div>
                      )}

                      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-paper-200 bg-paper-50/80 px-6 py-3 pl-7 text-xs text-ink-500">
                        <span className="flex flex-wrap items-center gap-x-3.5 gap-y-1">
                          <span>
                            <span className="num font-semibold text-ink-800">{s?.documents ?? docs.length}</span> documents
                          </span>
                          {s?.drafts_awaiting !== null && s?.drafts_awaiting !== undefined && (
                            <span className={s.drafts_awaiting ? "chip-caution py-0 px-2 text-[0.6875rem]" : "chip-verified py-0 px-2 text-[0.6875rem]"}>
                              <span className="num font-semibold">{s.drafts_awaiting}</span>
                              {s.drafts_awaiting ? " awaiting review" : " verified"}
                            </span>
                          )}
                          {restrictedCount > 0 && (
                            <span className="chip-signal py-0 px-2 text-[0.6875rem]">
                              <IconLock className="h-3 w-3" /> {restrictedCount} restricted
                            </span>
                          )}
                          {s?.grant_expires_at && (
                            <span>grant {relative(s.grant_expires_at)}</span>
                          )}
                        </span>
                        <span className="flex items-center gap-1 font-semibold text-ink-700 group-hover:text-brass-600">
                          Open workspace <IconArrowRight className="h-3.5 w-3.5 transition group-hover:translate-x-0.5" />
                        </span>
                      </div>
                    </a>
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        <TechnicalDetails summary="How this list is authorised">
          <ul className="space-y-2">
            {PROMISES.map((p) => (
              <li key={p.title}>
                <span className="font-semibold text-ink-700">{p.title}.</span> {p.body}
              </li>
            ))}
          </ul>
        </TechnicalDetails>
      </div>
    </Shell>
  );
}
