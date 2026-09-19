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
import { IconArrowRight, IconDoc, IconLock, IconShield, IconUpload } from "../../components/icons";
import { Empty, Notice, SealedTag, StateRail, relative, stateLabel } from "../../components/ui";
import {
  currentSubject,
  get,
  type CaseRecord,
  type CaseSummary,
  type DocumentRecord,
} from "../../lib/api";

export const dynamic = "force-dynamic";

const UPLOAD_ERRORS: Record<string, string> = {
  notpdf: "That file is not a PDF. The content decides, not the extension.",
  toolarge: "That file is over the size limit and was not read.",
  encrypted: "That PDF is encrypted. It is refused rather than guessed at.",
  unreadable: "That PDF could not be parsed and was refused.",
  unsafe: "Active content survived sanitisation, so the file was refused rather than stored.",
  refused: "Not available to you.",
  session: "Your session has ended. Choose an identity.",
  unreachable: "The API did not respond.",
  input: "That upload looked wrong. Nothing was stored.",
  rate: "Too many requests in a short time. Wait a moment and try again.",
};

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
  const summary = record ? await get<CaseSummary>(`/cases/${caseId}/summary`) : null;
  const documents = record ? ((await get<DocumentRecord[]>(`/cases/${caseId}/documents`)) ?? []) : [];

  if (!record) {
    return (
      <Shell subject={subject} returnTo={`/cases/${caseId}`} active="cases">
        <PageHeader title="Not available" crumbs={[{ label: "Case files", href: "/" }, { label: "Unavailable" }]} />
        <div className="mx-auto max-w-[88rem] px-6 py-8 lg:px-10">
          <Empty title="There is no case here for this identity">
            It does not exist, or you may not open it — and this screen deliberately cannot
            tell you which. Saying "not permitted" would confirm the case exists.
          </Empty>
        </div>
      </Shell>
    );
  }

  const original = summary?.disclosure === "original";

  return (
    <Shell subject={subject} returnTo={`/cases/${caseId}`} active="cases">
      <PageHeader
        crumbs={[{ label: "Case files", href: "/" }, { label: record.reference }]}
        eyebrow={stateLabel(record.state)}
        title={<span className="font-mono text-[1.85rem] font-semibold tracking-tight">{record.reference}</span>}
        meta={<StateRail state={record.state} />}
        actions={record.access_class === "sealed" ? <SealedTag /> : undefined}
      />

      <div className="mx-auto grid max-w-[88rem] gap-8 px-6 py-8 lg:grid-cols-[minmax(0,1fr)_22rem] lg:px-10">
        <section className="min-w-0 space-y-4">
          {error && <Notice tone="danger" title={UPLOAD_ERRORS[error] ?? "The request was refused."} />}

          <div className="flex items-baseline justify-between">
            <h2 className="section-title">Documents</h2>
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
            <ul className="surface divide-y divide-paper-200 overflow-hidden">
              {documents.map((d, i) => {
                const derivatives = d.versions.filter((v) => v.is_derivative).length;
                const originals = d.versions.length - derivatives;
                return (
                  <li key={d.id} className="animate-rise" style={{ animationDelay: `${i * 40}ms` }}>
                    <a href={`/documents/${d.id}`} className="group flex items-center gap-4 px-5 py-4 transition hover:bg-paper-50">
                      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg border border-paper-300 bg-paper-50 text-ink-500 group-hover:border-brass-300 group-hover:text-brass-600">
                        <IconDoc className="h-5 w-5" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[0.9rem] font-semibold text-ink-900">{d.title}</span>
                        <span className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-ink-500">
                          {originals > 0 && <span>{originals} original</span>}
                          {derivatives > 0 && (
                            <span className="flex items-center gap-1 text-signal-600">
                              <IconLock className="h-3 w-3" /> {derivatives} redacted
                            </span>
                          )}
                          <span className="mono text-ink-400">{d.versions.at(-1)?.sha256.slice(0, 12)}…</span>
                        </span>
                      </span>
                      <span className={d.disclosure === "original" ? "chip-draft" : "chip-signal"}>{d.disclosure}</span>
                      <IconArrowRight className="h-4 w-4 text-ink-300 transition group-hover:translate-x-0.5 group-hover:text-brass-500" />
                    </a>
                  </li>
                );
              })}
            </ul>
          )}

          {original && (
            <form method="post" action="/actions/upload" encType="multipart/form-data"
                  className="surface-quiet border-dashed px-5 py-5">
              <input type="hidden" name="case_id" value={caseId} />
              <input type="hidden" name="next" value={`/cases/${caseId}`} />
              <div className="flex flex-wrap items-center gap-5">
                <span className="grid h-11 w-11 place-items-center rounded-full bg-white text-brass-500 shadow-card ring-1 ring-paper-300">
                  <IconUpload className="h-5 w-5" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-[0.875rem] font-semibold text-ink-900">File a document into this case</p>
                  <p className="mt-0.5 max-w-xl text-xs leading-relaxed text-ink-500">
                    Sniffed by content, size-capped, and rebuilt without JavaScript, launch
                    actions, embedded files or form actions before anything is stored. The
                    worker then runs OCR, extraction, signing and anchoring.
                  </p>
                </div>
                <label className="btn-quiet cursor-pointer">
                  <input type="file" name="file" accept="application/pdf" required className="max-w-[12rem] text-xs file:hidden" />
                </label>
                <button type="submit" className="btn-primary">
                  <IconUpload className="h-4 w-4" /> Upload
                </button>
              </div>
            </form>
          )}
        </section>

        <aside className="space-y-4">
          <div className="surface overflow-hidden">
            <div className="flex items-center gap-2 border-b border-paper-200 px-5 py-3.5">
              <IconShield className="h-4 w-4 text-brass-500" />
              <h2 className="section-title">Why you can see this</h2>
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

          <div className="surface-quiet px-5 py-4 text-xs leading-relaxed text-ink-500">
            <p className="font-semibold text-ink-700">Access is logged</p>
            <p className="mt-1">
              Opening a page renders it on the server, watermarks it with your name and the
              time, and appends a view to the case&apos;s hash-chained audit trail.
            </p>
          </div>
        </aside>
      </div>
    </Shell>
  );
}
