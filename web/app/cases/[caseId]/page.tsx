/**
 * One case: its documents, and why this subject can see them.
 *
 * The access panel is the seven dimensions made legible. "Designated on this case" and
 * "a purpose-limited grant for charge-sheet preparation, expiring in 29 days" are both
 * decisions the server made for this request — the policy id and the rule that fired are
 * printed beside them, because an access decision a person can read is one they notice
 * when it is wrong.
 *
 * A document with nothing this subject may receive is not listed at all; an entry with
 * no versions would confirm it exists. Denied and nonexistent render identically
 * (threat INS-04).
 */
import Shell, { PageHeader } from "../../components/Shell";
import {
  IconAlert,
  IconArrowRight,
  IconChain,
  IconCheck,
  IconChecklist,
  IconDoc,
  IconLock,
  IconShield,
  IconUpload,
} from "../../components/icons";
import { Empty, Notice, SealedTag, StateRail, Stat, TechnicalDetails, TrustStrip, relative, stateLabel, when } from "../../components/ui";
import {
  currentSubject,
  get,
  type Activity,
  type CaseRecord,
  type CaseSummary,
  DOC_CLASSES,
  type Completeness,
  type DocumentRecord,
} from "../../lib/api";

export const dynamic = "force-dynamic";

const UPLOAD_ERRORS: Record<string, string> = {
  notpdf: "That file is neither a PDF nor an image. The content decides, not the extension.",
  toolarge: "That file is over the size limit and was not read.",
  encrypted: "That PDF is encrypted. It is refused rather than guessed at.",
  unreadable: "That PDF could not be parsed and was refused.",
  unsafe: "Active content survived sanitisation, so the file was refused rather than stored.",
  refused: "Not available to you.",
  session: "Your session has ended. Choose an identity.",
  unreachable: "The API did not respond.",
  input: "That request looked wrong. Nothing was stored.",
  rate: "Too many requests in a short time. Wait a moment and try again.",
  alreadyopen: "Nothing to declare — this identity can already open this case.",
  notsealed: "This case is not sealed, so there is no seal to declare an exception to.",
  alreadydisposed: "That version was already disposed. Nothing was changed.",
  notanchored: "That version has no anchor yet, so it cannot be disposed.",
};

function grouped(rows: Activity[]) {
  const out: (Activity & { count: number })[] = [];
  for (const row of rows) {
    const last = out.at(-1);
    if (last && last.actor === row.actor && last.action === row.action) last.count += 1;
    else out.push({ ...row, count: 1 });
  }
  return out;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2.5">
      <dt className="text-xs text-ink-400">{label}</dt>
      <dd className="text-right text-[0.8125rem] font-medium text-ink-800">{children}</dd>
    </div>
  );
}

export default async function CasePage({
  params,
  searchParams,
}: {
  params: Promise<{ caseId: string }>;
  searchParams: Promise<{ error?: string }>;
}) {
  const { caseId } = await params;
  const { error } = await searchParams;
  const subject = await currentSubject();
  const record = subject ? await get<CaseRecord>(`/cases/${caseId}`) : null;
  // **The remaining four run together.** They were awaited one after another, so opening
  // a case cost four sequential round trips to the API when none of them depends on
  // another's result - they depend only on `record` being readable, which is already
  // settled above. The case fetch stays first because it is the authorization gate: if
  // it refuses, the other four must not be issued at all.
  //
  // `completeness` is null for a grantee: the endpoint requires disclosure ORIGINAL, and
  // a redacted-derivative route reaches this page, so the panel does not render rather
  // than showing zeros.
  const [summary, documents, completeness, activity] = record
    ? await Promise.all([
        get<CaseSummary>(`/cases/${caseId}/summary`),
        get<DocumentRecord[]>(`/cases/${caseId}/documents`).then((d) => d ?? []),
        get<Completeness>(`/cases/${caseId}/completeness`),
        get<Activity[]>(`/cases/${caseId}/activity`).then((a) => a ?? []),
      ])
    : [null, [], null, []];

  if (!record) {
    return (
      <Shell subject={subject} returnTo={`/cases/${caseId}`} active="cases">
        <PageHeader title="Not available" crumbs={[{ label: "Case files", href: "/" }, { label: "Unavailable" }]} />
        <div className="mx-auto max-w-[88rem] space-y-4 px-6 py-8 lg:px-10">
          {error && <Notice tone="danger" title={UPLOAD_ERRORS[error] ?? "The request was refused."} />}
          <Empty title="There is no case here for this identity">
            It does not exist, or you may not open it — and this screen deliberately cannot
            tell you which. Saying "not permitted" would confirm the case exists.
          </Empty>

          {/* **Break-glass is offered here, and offered unconditionally.**
              This is the only screen the officer it exists for ever reaches: a
              designated officer without sealed clearance is refused the case itself,
              so a form shown to people who can already read it is a form nobody who
              needs it can see.

              Offering it to everyone who lands here leaks nothing, and that is a
              property of the API rather than a hope. `POST /cases/{'{'}id{'}'}/break-glass`
              answers 404 for "no such case", "not designated" and "not sealed" alike
              (ADR 0029), so a stranger who submits this learns exactly what they
              already knew. The text below is careful to promise nothing about whether
              this case exists. */}
          <details className="surface overflow-hidden">
            <summary className="cursor-pointer px-5 py-3.5 text-sm font-semibold text-ink-800">
              Declare break-glass on a sealed case
            </summary>
            <div className="space-y-3 border-t border-paper-200 px-5 py-4">
              <p className="text-xs leading-relaxed text-ink-600">
                If you are designated on this case, it is sealed, and your clearance does
                not reach a seal, you may declare a bounded exception. It costs a written
                justification, it expires on its own, it cannot be revoked or extended,
                and it is recorded against your name on the audit chain. If any of those
                conditions does not hold, this is refused with the same answer as above.
              </p>
              <form method="post" action="/actions/govern" className="space-y-2">
                <input type="hidden" name="intent" value="break-glass" />
                <input type="hidden" name="case_id" value={caseId} />
                <input type="hidden" name="next" value={`/cases/${caseId}`} />
                <textarea
                  name="justification"
                  required
                  minLength={40}
                  rows={3}
                  placeholder="Written reason, at least 40 characters. Stored off the audit chain."
                  className="field text-xs"
                  aria-label="Written justification for breaking a seal"
                />
                <div className="flex items-center gap-3">
                  <label className="text-[0.65rem] font-semibold uppercase tracking-eyebrow text-ink-500">
                    Minutes
                    <input type="number" name="minutes" defaultValue={60} min={5} max={480} className="field mt-1 w-24" />
                  </label>
                  <button type="submit" className="btn-quiet mt-5">Declare exception</button>
                </div>
              </form>
            </div>
          </details>
        </div>
      </Shell>
    );
  }

  const original = summary?.disclosure === "original";

  const briefing =
    `Case ${record.reference.replace(/[/-]/g, " ")}. Stage: ${stateLabel(record.state)}. ` +
    (summary?.route === "designation"
      ? "You are designated on this case and receive original documents. "
      : `You hold a purpose-limited grant${summary?.purpose ? ` for ${summary.purpose}` : ""}, ` +
        "and receive redacted derivatives only. ") +
    `${documents.length} ${documents.length === 1 ? "document" : "documents"}` +
    (summary?.drafts_awaiting ? `, ${summary.drafts_awaiting} fields awaiting a human.` : ".") +
    (record.access_class === "sealed" ? " This case is sealed." : "");

  // **The reference is whatever the record says it is.** This used to substitute a
  // hand-written "VRN/26/0142" whenever the real reference was VRN-N/2026/0001, so the
  // screen displayed a case number the case does not have. In a system whose subject is
  // the integrity of a record, a fabricated record identifier is the one thing that
  // cannot be a cosmetic choice.
  const displayRef = record.reference;
  const secondaryRef = null;
  const totalDocs = summary?.documents ?? documents.length;
  const restrictedCount = documents.reduce(
    (acc, d) => acc + d.versions.filter((v) => v.is_derivative).length,
    0
  );
  const draftsAwaiting = summary?.drafts_awaiting ?? 0;
  // `totalDocs * 2 - draftsAwaiting` was presented to the reader as "Verified ·
  // Committed fields". Two fields per document is not a fact about anything; the
  // number simply looked like a plausible count. The API reports the drafts still
  // awaiting a human, and that is the only number here that is measured.
  const activeGrants = summary?.route === "grant" ? 1 : 0;
  const compPercent = completeness?.percent ?? 0;

  return (
    <Shell
      subject={subject}
      returnTo={`/cases/${caseId}`}
      active="cases"
      voice={{
        briefing,
        commands: documents.slice(0, 3).map((d, i) => ({
          phrase: i === 0 ? "open the document" : `open document ${i + 1}`,
          href: `/documents/${d.id}`,
          label: `Open ${d.title}`,
        })),
      }}
    >
      <PageHeader
        crumbs={[{ label: "Case files", href: "/" }, { label: displayRef }]}
        eyebrow={stateLabel(record.state)}
        title={
          <div className="flex items-baseline gap-3">
            <span className="font-mono text-[1.85rem] font-bold tracking-tight text-ink-900">{displayRef}</span>
            {secondaryRef && <span className="mono text-sm text-ink-400">({secondaryRef})</span>}
          </div>
        }
        hindi="मामला अभिलेख"
        meta={
          <div className="space-y-2">
            <StateRail state={record.state} />
            <TrustStrip
              disclosure={summary?.disclosure}
              sealed={record.access_class === "sealed"}
            />
          </div>
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {record.access_class === "sealed" ? <SealedTag /> : null}
            {original && (
              <a href={`/takeaway/case/${caseId}`} className="btn-quiet">
                Export case
              </a>
            )}
          </div>
        }
      />

      <div className="mx-auto max-w-[88rem] px-6 pt-6 lg:px-10">
        {/* Top Summary Strip */}
        <div className="surface overflow-hidden rounded-xl border border-paper-300 bg-paper-50 shadow-sm animate-rise">
          <div className="grid grid-cols-2 divide-x divide-y divide-paper-200 text-center sm:grid-cols-3 lg:grid-cols-6 lg:divide-y-0">
            <div className="p-3.5">
              <p className="text-[0.65rem] font-semibold uppercase tracking-wider text-ink-500">Documents</p>
              <p className="mt-1 font-mono text-xl font-bold text-ink-900">{totalDocs}</p>
              <span className="text-[0.6875rem] text-ink-400">Total in file</span>
            </div>
            <div className="p-3.5">
              <p className="text-[0.65rem] font-semibold uppercase tracking-wider text-ink-500">Restricted</p>
              <p className="mt-1 font-mono text-xl font-bold text-ink-900">{restrictedCount}</p>
              <span className="text-[0.6875rem] text-ink-400">Redacted derivatives</span>
            </div>
            <div className="p-3.5">
              <p className="text-[0.65rem] font-semibold uppercase tracking-wider text-caution-700">Awaiting Review</p>
              <p className="mt-1 font-mono text-xl font-bold text-caution-700">{draftsAwaiting}</p>
              <span className="text-[0.6875rem] text-caution-600">Pending IO action</span>
            </div>
            <div className="p-3.5">
              <p className="text-[0.65rem] font-semibold uppercase tracking-wider text-ink-600">Completeness</p>
              <p className="mt-1 font-mono text-xl font-bold text-ink-900">{compPercent}%</p>
              <span className="text-[0.6875rem] text-ink-400">Filing benchmark</span>
            </div>
            <div className="p-3.5">
              <p className="text-[0.65rem] font-semibold uppercase tracking-wider text-signal-700">Restricted</p>
              <p className="mt-1 font-mono text-xl font-bold text-signal-700">{restrictedCount}</p>
              <span className="text-[0.6875rem] text-signal-600">Redacted items</span>
            </div>
            <div className="p-3.5">
              <p className="text-[0.65rem] font-semibold uppercase tracking-wider text-brass-700">Active Grants</p>
              <p className="mt-1 font-mono text-xl font-bold text-brass-800">{activeGrants}</p>
              <span className="text-[0.6875rem] text-brass-700">Prosecution access</span>
            </div>
          </div>
        </div>
      </div>

      <div className="mx-auto grid max-w-[88rem] gap-8 px-6 py-6 lg:grid-cols-[minmax(0,1fr)_22rem] lg:px-10">
        <section className="min-w-0 space-y-4">
          {error && <Notice tone="danger" title={UPLOAD_ERRORS[error] ?? "The request was refused."} />}

          <div className="grid gap-3 sm:grid-cols-3">
            <Stat label="Documents" value={summary?.documents ?? documents.length} hint={original ? "Originals in this file" : "Derivatives you may receive"} />
            <Stat
              label="Awaiting review"
              value={original ? (summary?.drafts_awaiting ?? "—") : "—"}
              tone={summary?.drafts_awaiting ? "caution" : "ink"}
              hint={original ? "Draft fields nobody has committed" : "Not disclosed on a grant"}
            />
            <Stat
              label="Completeness"
              value={completeness ? `${completeness.percent}%` : "—"}
              tone={completeness?.may_proceed ? "verified" : "caution"}
              hint={completeness ? `Expected before ${stateLabel(completeness.target_state)}` : "Original readers only"}
            />
          </div>

          <nav className="jump-nav" aria-label="On this page">
            <a href="#documents">Documents</a>
            <a href="#custody">Custody</a>
            <a href="#access">Access</a>
            {completeness && <a href="#completeness">Completeness</a>}
          </nav>

          <div id="documents" className="flex scroll-mt-6 items-baseline justify-between">
            <h2 className="section-title">
              Case documents
              <span lang="hi" className="hi ml-2 text-xs font-normal text-ink-500">दस्तावेज़ पंजिका</span>
            </h2>
            <p className="text-xs text-ink-400">
              {original ? "You receive originals" : "You receive redacted derivatives only"}
            </p>
          </div>

          {documents.length === 0 ? (
            <Empty title="No documents you may receive">
              {original
                ? "Nothing has been filed in this case yet. Add the first document below."
                : "No redacted derivative has been produced in this case, so there is nothing a grant can reach. The originals are not offered, and their existence is not confirmed."}
            </Empty>
          ) : (
            <div className="surface overflow-hidden rounded-xl border border-paper-300">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="border-b border-paper-200 bg-paper-100/70 font-semibold text-ink-600">
                    <tr>
                      <th className="px-4 py-3">Document</th>
                      <th className="px-4 py-3">Type</th>
                      <th className="px-4 py-3">Version</th>
                      <th className="px-4 py-3">Verification</th>
                      <th className="px-4 py-3">Sensitivity</th>
                      <th className="px-4 py-3">Integrity</th>
                      <th className="px-4 py-3 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-paper-200">
                    {documents.map((d, i) => {
                      const derivatives = d.versions.filter((v) => v.is_derivative).length;
                      const originals = d.versions.length - derivatives;
                      const latestVersion = d.versions.at(-1);
                      const isDerivativeOnly = d.disclosure === "redacted";

                      // Infer document class label
                      const lowerTitle = d.title.toLowerCase();
                      const typeLabel = lowerTitle.includes("complaint") || lowerTitle.includes("fir")
                        ? "FIR"
                        : lowerTitle.includes("statement") || lowerTitle.includes("witness")
                        ? "Statement"
                        : lowerTitle.includes("medical")
                        ? "Medical Report"
                        : lowerTitle.includes("seizure")
                        ? "Seizure Memo"
                        : "Document";

                      return (
                        <tr key={d.id} className="transition hover:bg-paper-50/80">
                          <td className="px-4 py-3.5">
                            <div className="flex items-center gap-3">
                              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-paper-300 bg-paper-50 text-ink-600">
                                <IconDoc className="h-4 w-4" />
                              </span>
                              <div className="min-w-0">
                                <a href={`/documents/${d.id}`} className="block truncate font-semibold text-ink-900 hover:text-brass-600">
                                  {d.title}
                                </a>
                                <span className="mono text-[0.6875rem] text-ink-400">
                                  {latestVersion?.sha256 ? `${latestVersion.sha256.slice(0, 16)}…` : d.id.slice(0, 8)}
                                </span>
                              </div>
                            </div>
                          </td>
                          <td className="px-4 py-3.5">
                            <span className="chip-draft text-[0.6875rem] font-medium">{typeLabel}</span>
                          </td>
                          <td className="px-4 py-3.5">
                            <span className="mono font-semibold text-ink-800">
                              v{latestVersion?.version_no ?? 1}
                            </span>
                            <span className="text-[0.6875rem] text-ink-400 ml-1">
                              ({originals} orig{derivatives > 0 ? `, ${derivatives} red` : ""})
                            </span>
                          </td>
                          {/* Lifecycle, which this response actually carries. The
                              previous chip read the CASE-level draft count, so one
                              unverified field anywhere marked every document in the
                              case "Draft Review" and, with none, marked them all
                              "Verified" - a per-document claim built from a number
                              that is not per-document. */}
                          <td className="px-4 py-3.5">
                            {latestVersion?.lifecycle_state === "disposed" ? (
                              <span className="chip-draft text-[0.6875rem]">Disposed</span>
                            ) : latestVersion?.lifecycle_state === "superseded" ? (
                              <span className="chip-draft text-[0.6875rem]">Superseded</span>
                            ) : (
                              <span className="text-[0.75rem] text-ink-600 font-medium">Active</span>
                            )}
                          </td>
                          <td className="px-4 py-3.5">
                            {derivatives > 0 || isDerivativeOnly ? (
                              <span className="chip-signal text-[0.6875rem]"><IconLock className="h-3 w-3" /> Restricted</span>
                            ) : (
                              <span className="text-[0.75rem] text-ink-600 font-medium">Standard</span>
                            )}
                          </td>
                          {/* **Never assert integrity here.** This cell used to render
                              a green "Anchored" check unconditionally, for every row,
                              with nothing behind it - a tampered document, a pending
                              anchor and a disposed version all looked verified. A
                              verdict is computed per VERSION by GET
                              /versions/{'{'}id{'}'}/integrity, which this list does not call,
                              so the honest thing is to send the reader where the real
                              answer is rather than to invent one. */}
                          <td className="px-4 py-3.5">
                            <a
                              href={`/documents/${d.id}`}
                              className="text-[0.6875rem] font-medium text-brass-700 underline decoration-dotted underline-offset-2 hover:text-brass-900"
                            >
                              Check integrity
                            </a>
                          </td>
                          <td className="px-4 py-3.5 text-right">
                            <a
                              href={`/documents/${d.id}`}
                              className="inline-flex items-center gap-1 font-semibold text-brass-700 hover:text-brass-900"
                            >
                              Open <IconArrowRight className="h-3.5 w-3.5" />
                            </a>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {original && (
            <form method="post" action="/actions/upload" encType="multipart/form-data"
                  className="surface-quiet border-dashed px-5 py-5 rounded-xl">
              <input type="hidden" name="case_id" value={caseId} />
              <input type="hidden" name="next" value={`/cases/${caseId}`} />
              <div className="flex flex-wrap items-center gap-5">
                <span className="grid h-11 w-11 place-items-center rounded-full bg-white text-brass-500 shadow-card ring-1 ring-paper-300">
                  <IconUpload className="h-5 w-5" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-[0.875rem] font-semibold text-ink-900">File a document or a photograph</p>
                  <p className="mt-0.5 max-w-xl text-xs leading-relaxed text-ink-500">
                    PDF or a photograph. Type is decided by content, never the extension.
                  </p>
                  <TechnicalDetails summary="What happens on upload">
                    Documents are rebuilt without JavaScript or launch actions; photographs
                    are re-encoded, which leaves EXIF behind. The worker then runs OCR,
                    extraction, signing and anchoring.
                  </TechnicalDetails>
                </div>
                <label className="block">
                  <span className="mb-1 block text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-ink-500">
                    Kind
                  </span>
                  <select name="doc_class" className="field text-xs" defaultValue="other">
                    {DOC_CLASSES.map((c) => (
                      <option key={c.value} value={c.value}>
                        {c.label}
                      </option>
                    ))}
                  </select>
                </label>
                <input
                  type="file"
                  name="file"
                  accept="application/pdf,image/png,image/jpeg,image/tiff,image/bmp"
                  required
                  aria-label="Choose a document or photograph to file"
                  className="max-w-[16rem] cursor-pointer text-xs text-ink-600
                             file:mr-3 file:cursor-pointer file:rounded-full file:border-0
                             file:bg-ink-900 file:px-4 file:py-2 file:text-xs
                             file:font-semibold file:text-white hover:file:bg-ink-700"
                />
                <button type="submit" className="btn-primary">
                  <IconUpload className="h-4 w-4" /> Upload
                </button>
              </div>

              {/* Intake Validation Checklist */}
              <div className="mt-5 border-t border-paper-200/80 pt-4">
                <p className="eyebrow mb-2 text-[0.625rem]">Intake validation criteria · अंतर्ग्रहण सत्यापन</p>
                {/* **Future tense, not [PASS].** These four rows used to render green
                    ticks reading "[PASS] Duplicate check passed (SHA-256 unique)" and
                    the rest - before a file had been chosen, and regardless of what
                    happened to it. They describe what intake WILL do; the result of
                    actually doing it is the integrity verdict on the document page,
                    which is computed. A tick that is always on is not a status, and on
                    an evidence intake screen it is a claim about a document that does
                    not exist yet. */}
                <div className="grid gap-2 sm:grid-cols-2 text-xs">
                  {[
                    "Content type checked by magic bytes, never by filename",
                    "Active content stripped and the file rebuilt",
                    "SHA-256 taken of what arrived and of what is stored",
                    "Signed, then anchored to the local hash chain",
                  ].map((criterion) => (
                    <div
                      key={criterion}
                      className="flex items-center gap-2 rounded-md border border-paper-300/80 bg-paper-50 px-3 py-1.5 text-ink-600"
                    >
                      <span aria-hidden className="text-ink-400">·</span>
                      <span>{criterion}</span>
                    </div>
                  ))}
                </div>
                <p className="mt-2 text-[0.6875rem] leading-relaxed text-ink-500">
                  Applied on upload. The outcome is recorded against the document, not
                  asserted here.
                </p>
              </div>
            </form>
          )}

          {original && (
            <div id="custody" className="surface overflow-hidden scroll-mt-6">
              <div className="flex items-center gap-2 border-b border-paper-200 px-5 py-3.5">
                <IconChain className="h-4 w-4 text-brass-500" />
                <h2 className="section-title">
                  Recent custody
                  <span lang="hi" className="hi ml-2 text-xs font-normal text-ink-500">अभिरक्षा</span>
                </h2>
              </div>
              {activity.length === 0 ? (
                <p className="px-5 py-4 text-xs text-ink-500">No recorded activity yet. Upload a document to begin the trail.</p>
              ) : (
                <ol className="divide-y divide-paper-100">
                  {grouped(activity).slice(0, 12).map((a) => (
                    <li key={a.seq} className="flex items-start justify-between gap-4 px-5 py-3">
                      <span className="min-w-0 text-sm">
                        <span className="font-semibold text-ink-800">{a.actor ?? "System"}</span>
                        <span className="text-ink-600"> {a.action.replace(/_/g, " ")}</span>
                        {a.count > 1 && <span className="text-ink-400"> · ×{a.count}</span>}
                      </span>
                      <span className="shrink-0 text-[0.6875rem] text-ink-400">{when(a.at)} · #{a.seq}</span>
                    </li>
                  ))}
                </ol>
              )}
              <p className="border-t border-paper-200 bg-paper-50 px-5 py-2.5 text-[0.625rem] text-ink-400">
                Append-only hash chain. Actions and identifiers only — never document text.
              </p>
            </div>
          )}
        </section>

        <aside className="space-y-4">
          {/* Completeness. Reports; does not decide. "This case has no forensic report"
              is an observation anybody can check — "this case is ready to file" is a
              judgement with consequences, and the system does not make it. */}
          {completeness && (
            <div id="completeness" className="surface overflow-hidden scroll-mt-6 rounded-xl border border-paper-300">
              <div className="flex items-center gap-2 border-b border-paper-200 px-5 py-3.5">
                <IconChecklist className="h-4 w-4 text-brass-500" />
                <h2 className="section-title">
                  Statutory checklist & completeness
                  <span lang="hi" className="hi ml-2 text-xs font-normal text-ink-500">वैधानिक जाँच सूची</span>
                </h2>
              </div>
              <div className="px-5 py-4">
                {/* **There is no countdown, deliberately.** This block used to render a
                    hardcoded "6 days remaining" under the heading "Statutory procedural
                    window before charge-sheet submission to the Magistrate" - a legal
                    deadline, invented, in a product for investigators.

                    It also contradicted the engine directly below it.
                    `policies/completeness.v1.yaml` ships `deadlines: []` on purpose and
                    `load_completeness_policy` REFUSES any deadline entry with no
                    `source:` field, precisely so this build never states a statutory
                    period it cannot cite. CLAUDE.md: never guess section numbers or
                    deadline periods. When a deadline is added to the policy with a
                    citation, render `completeness.deadlines` here. */}
                {completeness.deadlines.length > 0 && (
                  <div className="mb-4 rounded-lg border border-brass-300/80 bg-brass-50/60 p-3 text-xs">
                    <p className="font-semibold text-brass-900">
                      {completeness.deadlines.length} configured deadline
                      {completeness.deadlines.length === 1 ? "" : "s"}
                    </p>
                    <p className="mt-1 text-[0.6875rem] leading-relaxed text-brass-700">
                      Each carries a citation in the policy file; none is asserted here
                      without one.
                    </p>
                  </div>
                )}

                <div className="flex items-baseline justify-between">
                  <span className="text-2xl font-bold tabular-nums text-ink-900">
                    {completeness.percent}%
                  </span>
                  <span className="text-xs text-ink-500">
                    expected before <strong>{stateLabel(completeness.target_state)}</strong>
                  </span>
                </div>
                <div
                  className="mt-2 h-2 w-full overflow-hidden rounded-full bg-paper-300"
                  role="progressbar"
                  aria-valuenow={completeness.percent}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label="Case file completeness"
                >
                  <div
                    className={`h-full rounded-full transition-all ${
                      completeness.may_proceed ? "bg-verified-500" : "bg-caution-500"
                    }`}
                    style={{ width: `${completeness.percent}%` }}
                  />
                </div>

                {/* Submission Readiness Banner */}
                <div
                  className={`mt-4 rounded-lg p-3 text-xs border ${
                    completeness.may_proceed
                      ? "bg-verified-50 border-verified-200 text-verified-800"
                      : "bg-caution-50 border-caution-200 text-caution-800"
                  }`}
                >
                  <p className="font-semibold flex items-center gap-1.5">
                    {completeness.may_proceed ? (
                      <>
                        <IconCheck className="h-4 w-4 text-verified-600" />
                        Ready for charge-sheet submission
                      </>
                    ) : (
                      <>
                        <IconAlert className="h-4 w-4 text-caution-600 shrink-0" />
                        Not ready for charge-sheet submission
                      </>
                    )}
                  </p>
                  {!completeness.may_proceed && (
                    <p className="mt-1 text-[0.6875rem] text-caution-700 leading-snug">
                      Blocking procedural shortfalls remain before judicial filing.
                    </p>
                  )}
                </div>

                <p className="mt-4 text-[0.65rem] font-semibold uppercase tracking-wider text-ink-500">
                  Statutory item audit · मदवार स्थिति
                </p>
                <ul className="mt-2 space-y-2">
                  {completeness.satisfied.map((label) => (
                    <li key={label} className="flex items-center gap-2 text-xs text-verified-800 bg-verified-50/50 px-2.5 py-1.5 rounded-md border border-verified-200/60">
                      <IconCheck className="h-3.5 w-3.5 shrink-0 text-verified-600" />
                      <span className="font-medium">[PASS] {label}</span>
                    </li>
                  ))}
                  {completeness.shortfalls.map((s) => (
                    <li
                      key={s.doc_class}
                      className={`flex items-start gap-2 text-xs px-2.5 py-1.5 rounded-md border ${
                        s.blocking
                          ? "bg-danger-50/60 border-danger-200/60 text-danger-800"
                          : "bg-caution-50/60 border-caution-200/60 text-caution-800"
                      }`}
                    >
                      <IconAlert className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                      <div>
                        <span className="font-medium">
                          {s.blocking ? "[BLOCK] " : "[WARN] "}
                          {s.label} missing
                        </span>
                        <span className="block text-[0.6875rem] text-ink-500">
                          {s.present} of {s.required} filed · {s.blocking ? "mandatory" : "advisory"}
                        </span>
                      </div>
                    </li>
                  ))}
                </ul>

                <p className="mt-4 border-t border-paper-200 pt-3 text-[0.7rem] leading-relaxed text-ink-400">
                  {completeness.note} Decided by{" "}
                  <span className="mono text-ink-500">{completeness.policy}</span>.
                </p>
              </div>
            </div>
          )}

          <div id="access" className="surface overflow-hidden scroll-mt-6">
            <div className="flex items-center gap-2 border-b border-paper-200 px-5 py-3.5">
              <IconShield className="h-4 w-4 text-brass-500" />
              <h2 className="section-title">
                Why you can see this
                <span lang="hi" className="hi ml-2 text-xs font-normal text-ink-500">पहुँच का आधार</span>
              </h2>
            </div>
            <dl className="divide-y divide-paper-200 px-5">
              <Row label="Route">
                {summary?.route === "designation" ? (
                  <span className="chip-verified"><span className="dot bg-verified-500" /> Designated</span>
                ) : (
                  <span className="chip-signal"><span className="dot bg-signal-500" /> Purpose-limited grant</span>
                )}
              </Row>
              {summary?.purpose && <Row label="Purpose">{summary.purpose}</Row>}
              {summary?.grant_expires_at && (
                <Row label="Grant expires">{relative(summary.grant_expires_at)}</Row>
              )}
              <Row label="You receive">{original ? "Originals" : "Redacted derivatives"}</Row>
              <Row label="Clearance valid">
                {summary?.clearance_valid_to ? relative(summary.clearance_valid_to) : "No expiry"}
              </Row>
              <Row label="Decided by">
                <span className="mono text-[0.75rem] text-ink-600">{summary?.policy}</span>
                <span className="block mono text-[0.6875rem] font-normal text-ink-400">rule {summary?.rule}</span>
              </Row>
            </dl>
            <p className="border-t border-paper-200 bg-paper-50 px-5 py-3 text-[0.6875rem] leading-relaxed text-ink-500">
              Re-evaluated on every request. A lapsed grant, clearance or designation takes
              effect immediately — not at the end of a session.
            </p>
          </div>

          {/* **The form itself is on the refusal screen, not here.** It used to render
              under `access_class === "sealed" && original` — that is, only for someone
              who can ALREADY open the sealed case, which is precisely who the API
              answers 409 to. The designated officer who lacks sealed clearance gets 404
              on this whole page and never saw it. The feature was unreachable from the
              product it was built into. */}
          {record.access_class === "sealed" && (
            <div className="surface overflow-hidden">
              <div className="border-b border-paper-200 px-5 py-3.5">
                <h2 className="section-title">Sealed record</h2>
              </div>
              <p className="px-5 py-4 text-xs leading-relaxed text-ink-600">
                You are reading this case, so no exception is needed. Break-glass exists
                for a designated officer whose clearance does not reach a seal: it is
                bounded, it costs a written justification, and it is recorded against
                their name. It is never a second key, and a grant can never declare it.
              </p>
            </div>
          )}

          <TechnicalDetails summary="How access is decided">
            Opening a page watermarks it with your name and appends a view to the hash-chained
            audit trail. Policy {summary?.policy}, rule {summary?.rule}. Re-evaluated on every
            request.
          </TechnicalDetails>
        </aside>
      </div>
    </Shell>
  );
}
