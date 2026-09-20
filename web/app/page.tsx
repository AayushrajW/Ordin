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

import Shell, { ClearancePips, PageHeader, initials } from "./components/Shell";
import { IconArrowRight, IconChain, IconEye, IconLock, IconRedact, IconShield, Seal } from "./components/icons";
import { Empty, SealedTag, StateRail, Stat, relative } from "./components/ui";
import {
  authStatus,
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
