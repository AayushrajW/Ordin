/**
 * The document workbench.
 *
 * Three panes. Left: the extracted fields, each with the OCR engine's own confidence and
 * any consistency anomaly the system found — a reference one character away from the
 * case it is filed in, a phone number with a digit missing — and, where it can, a
 * suggested correction a person may accept. Centre: the page, rendered, verified and
 * watermarked on the server, with the selected field's words highlighted. Right: the
 * integrity verdict, the OCR record, and the custody trail.
 *
 * `?mode=redact` turns the same screen into a redaction preview: every region the
 * detection engine found — labelled, repeated in the narrative, matched through an OCR
 * error, or caught by a pattern — drawn over the page before anything is burned.
 *
 * **Nothing here decides anything.** Every write is a form post the API re-authorizes.
 * A suggestion is a button that records a human value under the name of whoever presses
 * it; the system proposes and a person commits (invariant 9). The page works with
 * scripting disabled: selection and mode live in the URL.
 */
import Shell, { PageHeader } from "../../components/Shell";
import {
  IconAlert,
  IconChain,
  IconCheck,
  IconClock,
  IconEye,
  IconLock,
  IconPen,
  IconRedact,
  IconShield,
  IconSpark,
  IconUpload,
  IconX,
} from "../../components/icons";
import { Confidence, Empty, Notice, TechnicalDetails, TrustStrip, relative, when } from "../../components/ui";
import {
  currentSubject,
  get,
  type Activity,
  type DocumentRecord,
  type ExtractedField,
  type Integrity,
  type OcrText,
  type PlanFinding,
  type RedactionPlan,
  type SpanBoxes,
} from "../../lib/api";

export const dynamic = "force-dynamic";

const ERRORS: Record<string, string> = {
  refused: "Not available to you. Nothing was changed.",
  session: "Your session has ended. Choose an identity.",
  unreachable: "The API did not respond.",
  input: "That entry looked wrong. Nothing was written.",
  rate: "Too many requests in a short time. Wait a moment and try again.",
  nothinglocated:
    "Nothing identifying could be located on the page, so no derivative was made. A copy that removed nothing must never be handed on as redacted.",
  alreadyopen: "You can already open this case, so there is nothing to declare.",
  // A disposal refused for these two reasons used to report "alreadyopen".
  alreadydisposed: "This version was already disposed. Nothing was changed.",
  confirm: "The confirmation did not match the version. Nothing was destroyed.",
  notanchored:
    "This version has no anchor yet, so it cannot be disposed. Destroying bytes "
    + "that were never attested to leaves an absence nobody can explain.",
};

const humanKey = (key: string) =>
  key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

const RULES: Record<string, string> = {
  "propagate.exact": "Exact mention",
  "propagate.ocr_tolerant": "Matched through an OCR error",
  "propagate.partial_name": "Name referred to again in the text",
  "propagate.address_street": "Street address fragment",
  "pattern.aadhaar.verhoeff": "Aadhaar number · checksum valid",
  "pattern.aadhaar.ocr_repaired": "Aadhaar number · misread repaired",
  "pattern.aadhaar_shaped": "Aadhaar-shaped number",
  "pattern.mobile_in": "Mobile number",
  "pattern.email": "E-mail address",
  "pattern.pan": "PAN",
  "pattern.vehicle_in": "Vehicle registration",
};

const KIND_TONE: Record<string, { ring: string; chip: string; label: string }> = {
  name: { ring: "ring-danger-500", chip: "chip-danger", label: "Name" },
  address: { ring: "ring-caution-500", chip: "chip-caution", label: "Address" },
  phone: { ring: "ring-signal-500", chip: "chip-signal", label: "Phone" },
  aadhaar: { ring: "ring-brass-400", chip: "chip-brass", label: "Aadhaar" },
  pan: { ring: "ring-brass-400", chip: "chip-brass", label: "PAN" },
  email: { ring: "ring-signal-500", chip: "chip-signal", label: "E-mail" },
  vehicle: { ring: "ring-ink-500", chip: "chip-draft", label: "Vehicle" },
  other: { ring: "ring-ink-500", chip: "chip-draft", label: "Other" },
};

const sourceLabel = (source: string | null) =>
  !source ? "Pattern" : source.startsWith("party:") ? `Case party · ${source.slice(6)}` : humanKey(source);

const ACTIONS: Record<string, { label: string; icon: React.ReactNode }> = {
  field_verified: { label: "committed a value", icon: <IconCheck className="h-3.5 w-3.5" /> },
  field_entered: { label: "entered a value by hand", icon: <IconPen className="h-3.5 w-3.5" /> },
  document_viewed: { label: "viewed the page", icon: <IconEye className="h-3.5 w-3.5" /> },
  document_uploaded: { label: "filed the document", icon: <IconUpload className="h-3.5 w-3.5" /> },
  version_created: { label: "produced a redacted derivative", icon: <IconRedact className="h-3.5 w-3.5" /> },
  document_exported: { label: "exported a copy", icon: <IconEye className="h-3.5 w-3.5" /> },
  disposal_recorded: { label: "recorded a lawful disposal", icon: <IconLock className="h-3.5 w-3.5" /> },
};

const INTEGRITY: Record<Integrity["state"], { tone: string; icon: React.ReactNode; title: string }> = {
  VERIFIED: { tone: "border-verified-100 bg-verified-50 text-verified-700", icon: <IconCheck className="h-5 w-5" />, title: "Verified" },
  PENDING: { tone: "border-signal-100 bg-signal-50 text-signal-700", icon: <IconClock className="h-5 w-5" />, title: "Awaiting anchor" },
  MISMATCH: { tone: "border-danger-100 bg-danger-50 text-danger-700", icon: <IconX className="h-5 w-5" />, title: "Mismatch — possible tampering" },
  DISPOSED_ANCHOR_ONLY: { tone: "border-ink-200 bg-ink-100 text-ink-700", icon: <IconLock className="h-5 w-5" />, title: "Lawfully disposed" },
  UNAVAILABLE: { tone: "border-caution-100 bg-caution-50 text-caution-700", icon: <IconAlert className="h-5 w-5" />, title: "Unavailable" },
};

/** Group consecutive identical (actor, action) rows: forty views read as one line. */
function grouped(rows: Activity[]) {
  const out: (Activity & { count: number })[] = [];
  for (const row of rows) {
    const last = out.at(-1);
    if (last && last.actor === row.actor && last.action === row.action) last.count += 1;
    else out.push({ ...row, count: 1 });
  }
  return out;
}

function Box({ b, w, h, className, style }: {
  b: { x0: number; y0: number; x1: number; y1: number }; w: number; h: number;
  className: string; style?: React.CSSProperties;
}) {
  return (
    <span
      aria-hidden
      className={`pointer-events-none absolute ${className}`}
      style={{
        left: `${(b.x0 / w) * 100}%`, top: `${(b.y0 / h) * 100}%`,
        width: `${((b.x1 - b.x0) / w) * 100}%`, height: `${((b.y1 - b.y0) / h) * 100}%`,
        ...style,
      }}
    />
  );
}

function FieldCard({
  f, selected, href, here, versionId,
}: { f: ExtractedField; selected: boolean; href: string; here: string; versionId: string }) {
  const warnings = f.anomalies.filter((a) => a.severity === "warning");
  const infos = f.anomalies.filter((a) => a.severity === "info");
  const verified = f.status === "verified";
  if (f.superseded) {
    // Kept, not deleted: the machine's reading is the evidence the extractor erred.
    return (
      <li className="rounded-xl border border-dashed border-paper-300 bg-paper-50/70 px-4 py-2.5">
        <p className="flex items-center justify-between gap-3 text-[0.6875rem] text-ink-400">
          <span>Machine read <span className="mono text-ink-500 line-through decoration-ink-300">{f.value}</span></span>
          <span className="shrink-0">superseded by a person</span>
        </p>
      </li>
    );
  }
  return (
    <li className={`surface overflow-hidden transition ${selected ? "border-brass-300 shadow-lift ring-1 ring-brass-300/60" : "hover:border-ink-200"}`}>
      <a href={href} className="block px-4 pb-3 pt-3.5">
        <div className="flex items-start justify-between gap-3">
          <p className="eyebrow">{humanKey(f.field_key)}</p>
          {verified ? (
            <span className="chip-verified"><IconCheck className="h-3 w-3" /> Verified</span>
          ) : warnings.length ? (
            <span className="chip-caution"><IconAlert className="h-3 w-3" /> Check</span>
          ) : (
            <span className="chip-draft">Draft</span>
          )}
        </div>
        <p className={`mt-1.5 break-words text-[0.95rem] font-semibold leading-snug ${warnings.length && !verified ? "text-caution-700" : "text-ink-900"}`}>
          {f.value}
        </p>
        <div className="mt-2 flex items-center justify-between gap-2">
          {f.source === "human" ? (
            <span className="flex items-center gap-1 text-[0.6875rem] text-ink-500"><IconPen className="h-3 w-3" /> Entered by a person</span>
          ) : (
            <Confidence value={f.ocr_confidence} />
          )}
          <span className="mono text-[0.6875rem] text-ink-400">{f.source}</span>
        </div>
      </a>

      {!verified && warnings.map((a) => (
        <div key={a.code} className="border-t border-caution-100 bg-caution-50/70 px-4 py-2.5">
          <p className="flex gap-2 text-xs leading-relaxed text-caution-700">
            <IconAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {a.message}
          </p>
          {a.suggestion && (
            <form method="post" action="/actions/field" className="mt-2">
              <input type="hidden" name="intent" value="enter" />
              <input type="hidden" name="version_id" value={versionId} />
              <input type="hidden" name="field_key" value={f.field_key} />
              <input type="hidden" name="value" value={a.suggestion} />
              <input type="hidden" name="next" value={here} />
              <button type="submit" className="btn-quiet w-full justify-between py-1.5 text-xs">
                <span className="flex items-center gap-1.5"><IconSpark className="h-3.5 w-3.5 text-brass-500" /> Commit suggested value</span>
                <span className="mono font-semibold text-ink-900">{a.suggestion}</span>
              </button>
            </form>
          )}
        </div>
      ))}
      {!verified && infos.map((a) => (
        <p key={a.code} className="border-t border-signal-100 bg-signal-50/70 px-4 py-2.5 text-xs leading-relaxed text-signal-700">
          {a.message}
        </p>
      ))}

      {selected && (
        <div className="border-t border-paper-200 bg-paper-50/80 px-4 py-3">
          <dl className="grid grid-cols-[5.5rem_1fr] gap-x-3 gap-y-1 text-[0.6875rem]">
            <dt className="text-ink-400">Provider</dt>
            <dd className="mono text-ink-700">{f.provider ?? "—"}{f.model ? ` · ${f.model}` : ""}</dd>
            <dt className="text-ink-400">Source span</dt>
            <dd className="mono text-ink-700">
              {f.source_span_start === null ? "none — typed by a person" : `chars ${f.source_span_start}–${f.source_span_end}`}
            </dd>
            <dt className="text-ink-400">Pattern</dt>
            <dd className="text-ink-700">{f.confidence === null ? "—" : "deterministic match"}</dd>
          </dl>
          {!verified ? (
            <div className="mt-3 space-y-2">
              <form method="post" action="/actions/field">
                <input type="hidden" name="intent" value="verify" />
                <input type="hidden" name="field_id" value={f.id} />
                <input type="hidden" name="next" value={here} />
                <button
                  type="submit"
                  className={`btn-primary w-full flex items-center justify-center gap-2 py-2 text-xs font-semibold ${
                    warnings.length ? "border-caution-500 bg-caution-600 hover:bg-caution-700" : ""
                  }`}
                >
                  <IconCheck className="h-4 w-4" /> Confirm & Sign
                </button>
              </form>

              <div className="grid grid-cols-2 gap-2">
                <form method="post" action="/actions/field">
                  <input type="hidden" name="intent" value="enter" />
                  <input type="hidden" name="version_id" value={versionId} />
                  <input type="hidden" name="field_key" value={f.field_key} />
                  <input type="hidden" name="value" value={f.value} />
                  <input type="hidden" name="next" value={here} />
                  <button type="submit" className="btn-quiet w-full flex items-center justify-center gap-1.5 py-1.5 text-xs">
                    <IconPen className="h-3.5 w-3.5" /> Edit
                  </button>
                </form>

                <form method="post" action="/actions/field">
                  <input type="hidden" name="intent" value="enter" />
                  <input type="hidden" name="version_id" value={versionId} />
                  <input type="hidden" name="field_key" value={f.field_key} />
                  <input type="hidden" name="value" value="[DISCARDED / REJECTED]" />
                  <input type="hidden" name="next" value={here} />
                  <button type="submit" className="btn-quiet w-full flex items-center justify-center gap-1.5 py-1.5 text-xs text-danger-700 hover:bg-danger-50">
                    <IconX className="h-3.5 w-3.5" /> Reject
                  </button>
                </form>
              </div>

              <a href={here} className="block text-center text-[0.6875rem] text-ink-500 hover:text-ink-800">
                Save as draft (remain uncommitted)
              </a>
              <p className="text-center text-[0.625rem] text-ink-400">
                Confirming appends eSign cryptographic commitment and verified audit row.
              </p>
            </div>
          ) : (
            <p className="mt-3 flex items-center gap-1.5 rounded-lg bg-verified-50 px-3 py-2 text-[0.6875rem] text-verified-700">
              <IconShield className="h-3.5 w-3.5" /> Committed by a named person. The database refuses this state without one.
            </p>
          )}
        </div>
      )}
    </li>
  );
}

function PlanPanel({ plan, versionId, here }: { plan: RedactionPlan | null; versionId: string; here: string }) {
  if (!plan) return <Empty title="Preview unavailable" />;
  const regions = plan.findings.reduce((n, f) => n + f.boxes.length, 0);
  const byKind = plan.findings.reduce<Record<string, number>>((acc, f) => ({ ...acc, [f.kind]: (acc[f.kind] ?? 0) + 1 }), {});
  const narrative = plan.findings.filter((f) => !f.labelled).length;
  return (
    <div className="space-y-4">
      <div className="surface-ink overflow-hidden">
        <div className="px-4 py-4">
          <p className="text-[0.625rem] font-semibold uppercase tracking-eyebrow text-brass-300">Redaction preview</p>
          <p className="mt-2 font-display text-[1.6rem] font-semibold leading-none text-white">
            {plan.findings.length} <span className="text-base font-medium text-ink-300">mentions · {regions} regions</span>
          </p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {Object.entries(byKind).map(([kind, n]) => (
              <span key={kind} className="chip-ink">{KIND_TONE[kind]?.label ?? kind} · {n}</span>
            ))}
          </div>
          {narrative > 0 && (
            <p className="mt-3 text-xs leading-relaxed text-ink-300">
              <span className="font-semibold text-brass-300">{narrative}</span> of these are outside the labelled
              fields — repeated in the narrative, matched through an OCR error, or caught by a pattern.
              Field-only redaction would have left them readable.
            </p>
          )}
        </div>
        <form method="post" action="/actions/field" className="border-t border-ink-700 bg-ink-900 px-4 py-3">
          <input type="hidden" name="intent" value="redact" />
          <input type="hidden" name="version_id" value={versionId} />
          <input type="hidden" name="next" value={here} />
          <button type="submit" disabled={regions === 0} className="btn-brass w-full">
            <IconRedact className="h-4 w-4" /> Burn {regions} regions into a new version
          </button>
          <p className="mt-2 text-center text-[0.6875rem] leading-snug text-ink-400">
            Content removed, page rasterised, container rebuilt. The original is untouched.
          </p>
        </form>
      </div>

      <ul className="space-y-2">
        {plan.findings.map((f: PlanFinding, i) => (
          <li key={i} className="surface flex items-center gap-3 px-3.5 py-2.5">
            <span className={KIND_TONE[f.kind]?.chip ?? "chip-draft"}>{KIND_TONE[f.kind]?.label ?? f.kind}</span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-xs font-semibold text-ink-800">{RULES[f.rule_id] ?? f.rule_id}</span>
              <span className="block truncate text-[0.6875rem] text-ink-400">
                {sourceLabel(f.source)} · {f.labelled ? "labelled line" : "elsewhere on the page"}
              </span>
            </span>
            <span className="num text-[0.6875rem] text-ink-500">{Math.round(f.confidence * 100)}%</span>
          </li>
        ))}
      </ul>
      {plan.unlocated > 0 && (
        <Notice tone="caution" title={`${plan.unlocated} found in the text but not on the page`}>
          The OCR record has no word box for them, so they cannot be burned out. Read the
          page yourself before handing the derivative on.
        </Notice>
      )}
      <p className="px-1 text-[0.6875rem] leading-relaxed text-ink-400">
        Found from the case&apos;s recorded parties, the labelled fields and identifier
        patterns. A name nobody recorded and no pattern describes is not found — there is no
        entity recognition in this build (accepted risk AR-6).
      </p>
    </div>
  );
}

export default async function DocumentPage({
  params,
  searchParams,
}: {
  params: Promise<{ documentId: string }>;
  searchParams: Promise<{ field?: string; error?: string; version?: string; mode?: string; uploaded?: string; redacted?: string; compare?: string; disposed?: string }>;
}) {
  const { documentId } = await params;
  const { field: selectedId, error, version: wantedVersion, mode: rawMode, uploaded, redacted, compare: compareId, disposed } = await searchParams;
  const subject = await currentSubject();
  const document = subject ? await get<DocumentRecord>(`/documents/${documentId}`) : null;

  if (!document) {
    return (
      <Shell subject={subject} returnTo={`/documents/${documentId}`} active="cases">
        <PageHeader title="Not available" crumbs={[{ label: "Case files", href: "/" }, { label: "Unavailable" }]} />
        <div className="mx-auto max-w-[88rem] px-6 py-8 lg:px-10">
          <Empty title="There is no document here for this identity">
            It does not exist, or you may not receive it — deliberately indistinguishable.
          </Empty>
        </div>
      </Shell>
    );
  }

  // The newest *original* by default: an officer works the real document, and the
  // derivative is something produced from it. A grantee only has derivatives.
  const versions = document.versions;
  if (versions.length === 0) {
    return (
      <Shell subject={subject} returnTo={`/documents/${documentId}`} active="cases">
        <PageHeader title="No versions" crumbs={[{ label: "Case files", href: "/" }, { label: "Unavailable" }]} />
        <div className="mx-auto max-w-[88rem] px-6 py-8 lg:px-10">
          <Empty title="This document has no available versions">
            The document exists but no version is available to this identity.
          </Empty>
        </div>
      </Shell>
    );
  }
  const version =
    versions.find((v) => v.id === wantedVersion) ??
    [...versions].reverse().find((v) => !v.is_derivative) ??
    versions.at(-1)!;
  const original = document.disclosure === "original";
  const mode = rawMode === "redact" && original && !version.is_derivative ? "redact" : "review";

  const [fields, ocr, integrity, activity] = await Promise.all([
    get<ExtractedField[]>(`/versions/${version.id}/fields`).then((f) => f ?? []),
    get<OcrText>(`/versions/${version.id}/text`),
    get<Integrity>(`/versions/${version.id}/integrity`),
    original ? get<Activity[]>(`/documents/${documentId}/activity`).then((a) => a ?? []) : Promise.resolve([] as Activity[]),
  ]);
  const plan = mode === "redact" ? await get<RedactionPlan>(`/versions/${version.id}/redaction-plan`) : null;

  const selected =
    // A superseded draft is never the working selection: after a commit, the screen
    // moves on to the next field still waiting for someone.
    fields.find((f) => f.id === selectedId && !f.superseded) ??
    fields.find((f) => f.status === "draft" && !f.superseded && f.anomalies.length) ??
    fields.find((f) => f.status === "draft" && !f.superseded) ??
    fields[0] ??
    null;
  const spans = mode === "review" && selected ? await get<SpanBoxes>(`/fields/${selected.id}/spans`) : null;

  const compare =
    compareId && compareId !== version.id
      ? versions.find((v) => v.id === compareId) ?? null
      : null;
  const compareFields = compare
    ? await get<ExtractedField[]>(`/versions/${compare.id}/fields`).then((f) => f ?? [])
    : [];

  const base = `/documents/${documentId}?version=${version.id}`;
  const here = `${base}${mode === "redact" ? "&mode=redact" : ""}${selected ? `&field=${selected.id}` : ""}`;
  const open = fields.filter((f) => f.status === "draft" && !f.superseded);
  const drafts = open.length;
  const flagged = open.filter((f) => f.anomalies.some((a) => a.severity === "warning")).length;
  const pageW = plan?.page_width || spans?.page_width || 595;
  const pageH = plan?.page_height || spans?.page_height || 842;

  // **Field names, flags and counts — never a value.** A voice assistant that reads a
  // complainant's name into a room has disclosed it to everyone in that room, which no
  // access decision on the screen ever authorised.
  const flags = open
    .flatMap((f) => f.anomalies.filter((a) => a.severity === "warning").map((a) => ({ f, a })))
    .map(({ f, a }) => `${humanKey(f.field_key).toLowerCase()}: ${a.message}`);
  const briefing = version.is_derivative
    ? `${document.title}. Redacted derivative, version ${version.version_no}. Content removed ` +
      `and the page rasterised; no text layer and no fields. Integrity: ${integrity?.state ?? "unknown"}.`
    : mode === "redact"
      ? `Redaction preview for ${document.title}. ${plan?.findings.length ?? 0} mentions, ` +
        `${plan?.findings.reduce((n, f) => n + f.boxes.length, 0) ?? 0} regions. ` +
        `${plan?.findings.filter((f) => !f.labelled).length ?? 0} of them are outside the ` +
        "labelled fields. Nothing is removed until you press the button yourself."
      : `${document.title}, version ${version.version_no}. Integrity: ${integrity?.state ?? "unknown"}. ` +
        `${drafts} ${drafts === 1 ? "field" : "fields"} awaiting a human` +
        (flagged ? `, ${flagged} flagged.` : ".") +
        (flags.length ? ` First flag — ${flags[0]}` : "");

  const index = selected ? open.findIndex((f) => f.id === selected.id) : -1;
  const voiceCommands = [
    { phrase: "read the flags", aliases: ["what is wrong", "read flags"],
      say: flags.length ? flags.join(". ") : "Nothing is flagged on this version.",
      label: "Read the flags" },
    ...(original && !version.is_derivative
      ? [
          { phrase: "redact", aliases: ["show redaction", "redaction preview"],
            href: `${base}&mode=redact`, label: "Redaction preview" },
          { phrase: "review fields", aliases: ["review"], href: base, label: "Review fields" },
        ]
      : []),
    ...(index >= 0 && index + 1 < open.length
      ? [{ phrase: "next field", href: `${base}&field=${open[index + 1].id}`, label: "Next field" }]
      : []),
    ...(index > 0
      ? [{ phrase: "previous field", href: `${base}&field=${open[index - 1].id}`, label: "Previous field" }]
      : []),
    ...versions.map((v) => ({
      phrase: v.is_derivative ? "show the redacted version" : "show the original",
      href: `/documents/${documentId}?version=${v.id}`,
      label: v.is_derivative ? "Show redacted" : "Show original",
    })),
    { phrase: "back to the case", aliases: ["back to case"], href: document.case_id ? `/cases/${document.case_id}` : "/", label: "Case files" },
  ];

  return (
    <Shell subject={subject} returnTo={here} active="cases"
           voice={{ briefing, commands: voiceCommands }}>
      <PageHeader
        crumbs={[
          { label: "Case files", href: "/" },
          ...(document.case_id
            ? [{ label: "Case", href: `/cases/${document.case_id}` }]
            : []),
          { label: document.title },
        ]}
        eyebrow={version.is_derivative ? "Evidence passport · redacted" : "Evidence passport"}
        title={document.title}
        hindi={version.is_derivative ? "संपादित प्रति" : "मूल दस्तावेज़"}
        meta={
          <div className="space-y-2">
            <span className="flex flex-wrap items-center gap-2">
              {versions.map((v) => (
                <a key={v.id} href={`/documents/${documentId}?version=${v.id}`}
                   className={`chip transition ${v.id === version.id ? "bg-ink-900 text-white" : "bg-white text-ink-600 ring-1 ring-inset ring-paper-300 hover:ring-ink-300"}`}>
                  v{v.version_no} · {v.is_derivative ? "redacted" : "original"}
                </a>
              ))}
            </span>
            <TrustStrip
              integrity={integrity?.state}
              disclosure={document.disclosure}
              disposed={version.lifecycle_state === "disposed"}
            />
          </div>
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <a href={`/takeaway/version/${version.id}`} className="btn-quiet">
              Export this version
            </a>
            {original && !version.is_derivative ? (
              <nav className="flex rounded-lg bg-paper-200 p-1" aria-label="Mode">
                <a href={`${base}`} className={`rounded-md px-3.5 py-1.5 text-xs font-semibold transition ${mode === "review" ? "bg-white text-ink-900 shadow-card" : "text-ink-500 hover:text-ink-800"}`}>
                  Review fields{drafts ? ` · ${drafts}` : ""}
                </a>
                <a href={`${base}&mode=redact`} className={`flex items-center gap-1.5 rounded-md px-3.5 py-1.5 text-xs font-semibold transition ${mode === "redact" ? "bg-white text-ink-900 shadow-card" : "text-ink-500 hover:text-ink-800"}`}>
                  <IconRedact className="h-3.5 w-3.5" /> Redact
                </a>
              </nav>
            ) : (
              <span className="chip-signal"><IconLock className="h-3 w-3" /> {original ? "Derivative" : "You receive the redacted derivative only"}</span>
            )}
          </div>
        }
      />

      <div className="mx-auto max-w-[96rem] px-6 py-6 lg:px-8">
        {original && !version.is_derivative && (
          <div className="mb-4 flex flex-wrap items-center justify-between gap-4 rounded-xl border border-brass-400/80 bg-brass-50/70 p-4 shadow-sm animate-rise">
            <div className="flex items-center gap-3">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-brass-200 text-brass-800">
                <IconShield className="h-5 w-5" />
              </span>
              <div>
                <p className="text-sm font-bold text-ink-900">
                  AI output is a draft. Verify before commit.
                </p>
                <p className="text-xs text-ink-600">
                  Extracted values, field boundaries, and anomalies are machine drafts. Confirmation requires explicit human verification and signature.
                </p>
              </div>
            </div>
            <span className="chip-brass shrink-0 text-[0.6875rem]">
              Human Attestation Mandatory
            </span>
          </div>
        )}

        <div className="mb-4 space-y-2">
          {error && <Notice tone="danger" title={ERRORS[error] ?? "The request was refused."} />}
          {uploaded && (
            <Notice tone="signal" title="Filed and queued">
              The document was sanitised and versioned. The worker runs OCR, extraction,
              signing and anchoring within a few seconds — reload to see the fields.
            </Notice>
          )}
          {redacted && (
            <Notice tone="verified" title="Redacted derivative produced">
              This is the version a purpose-limited grantee receives. The removed content is
              gone from the page itself, not covered — the original is untouched and still
              yours to read.
            </Notice>
          )}
          {disposed && (
            <Notice tone="verified" title="Disposal recorded">
              Bytes destroyed; the anchor and the reason remain. Integrity on this version
              is DISPOSED_ANCHOR_ONLY — that is not a mismatch.
            </Notice>
          )}
          {integrity?.state === "MISMATCH" && (
            <Notice tone="danger" title="The stored bytes no longer match the anchored digest">
              This version may have been altered after it was filed. The page is withheld
              rather than shown as though it were evidence.
            </Notice>
          )}
        </div>

        {compare && (
          <section className="surface mb-6 overflow-hidden">
            <div className="border-b border-paper-200 px-5 py-3.5">
              <h2 className="section-title">Version comparison</h2>
              <p className="mt-1 text-xs text-ink-500">
                v{compare.version_no} → v{version.version_no}. Hashes and field keys, not a pixel diff.
              </p>
            </div>
            <dl className="grid gap-4 px-5 py-4 sm:grid-cols-2 text-sm">
              <div>
                <dt className="eyebrow">v{compare.version_no} digest</dt>
                <dd className="mono mt-1 break-all text-xs text-ink-700">{compare.sha256}</dd>
              </div>
              <div>
                <dt className="eyebrow">v{version.version_no} digest</dt>
                <dd className="mono mt-1 break-all text-xs text-ink-700">{version.sha256}</dd>
              </div>
              <div>
                <dt className="eyebrow">Hash</dt>
                <dd className="mt-1 text-ink-800">{compare.sha256 === version.sha256 ? "Identical" : "Different"}</dd>
              </div>
              <div>
                <dt className="eyebrow">Kind</dt>
                <dd className="mt-1 text-ink-800">
                  {compare.is_derivative ? "redacted" : "original"} → {version.is_derivative ? "redacted" : "original"}
                </dd>
              </div>
            </dl>
            {original && (
              <p className="border-t border-paper-200 px-5 py-3 text-xs text-ink-500">
                Field keys on v{version.version_no}: {fields.filter((f) => !f.superseded).length}.
                On v{compare.version_no}: {compareFields.filter((f) => !f.superseded).length}.
                Verification never carries forward to a new version.
              </p>
            )}
          </section>
        )}

        <div className="grid gap-6 xl:grid-cols-[20rem_minmax(0,1fr)] 2xl:grid-cols-[20rem_minmax(0,1fr)_18rem]">
          {/* ---- left ---------------------------------------------------------- */}
          <section className="min-w-0 space-y-3 xl:max-h-[calc(100vh-13rem)] xl:overflow-y-auto xl:pr-1">
            {mode === "redact" ? (
              <PlanPanel plan={plan} versionId={version.id} here={here} />
            ) : version.is_derivative ? (
              <div className="surface-ink px-4 py-4 text-sm">
                <p className="text-[0.625rem] font-semibold uppercase tracking-eyebrow text-brass-300">Redacted derivative</p>
                <p className="mt-2 leading-relaxed text-ink-200">
                  Identifying content was removed from this version and the page was
                  rasterised. It carries no text layer and no extracted fields — there is
                  nothing here to read back out.
                </p>
              </div>
            ) : (
              <>
                <div className="flex items-baseline justify-between px-1">
                  <h2 className="section-title">
                    Extracted fields
                    <span lang="hi" className="hi ml-2 text-xs font-normal text-ink-500">निकाले गए क्षेत्र</span>
                  </h2>
                  <span className="text-xs text-ink-400">
                    {drafts} awaiting{flagged ? <span className="text-caution-600"> · {flagged} flagged</span> : null}
                  </span>
                </div>
                {ocr?.requires_manual_entry && (
                  <Notice tone="caution" title="OCR confidence too low to extract">
                    A page a human must read is not a page to run patterns over. Enter the
                    values by hand below.
                  </Notice>
                )}
                {fields.length === 0 && !ocr?.requires_manual_entry && (
                  <Empty title={ocr ? "No fields extracted" : "Processing"}>
                    {ocr ? "No labelled value was found on this page." : "The worker has not processed this version yet. Reload in a few seconds."}
                  </Empty>
                )}
                <ul className="space-y-2.5">
                  {fields.map((f) => (
                    <FieldCard key={f.id} f={f} selected={selected?.id === f.id}
                               href={`${base}&field=${f.id}`} here={here} versionId={version.id} />
                  ))}
                </ul>
                <form method="post" action="/actions/field" className="surface-quiet space-y-2 border-dashed px-4 py-4">
                  <p className="text-xs font-semibold text-ink-700">Record a value by hand</p>
                  <p className="text-[0.6875rem] leading-relaxed text-ink-500">
                    Saved as a new field with <span className="mono">source=human</span>. The
                    machine&apos;s reading stays exactly as it was — it is the evidence that the
                    extractor needs fixing.
                  </p>
                  <input type="hidden" name="intent" value="enter" />
                  <input type="hidden" name="version_id" value={version.id} />
                  <input type="hidden" name="next" value={here} />
                  <input name="field_key" required placeholder="Field, e.g. complainant name" className="field" />
                  <input name="value" required placeholder="Value as it appears on the page" className="field" />
                  <button type="submit" className="btn-quiet w-full"><IconPen className="h-4 w-4" /> Record and commit</button>
                </form>
              </>
            )}
          </section>

          {/* ---- centre ------------------------------------------------------- */}
          <section className="desk min-w-0 overflow-hidden rounded-2xl p-4 lg:p-6">
            <div className="mb-4 flex items-center justify-between text-[0.6875rem] text-ink-300">
              <span className="flex items-center gap-2">
                <span className={`dot ${mode === "redact" ? "bg-danger-500" : "bg-brass-400"}`} />
                {mode === "redact"
                  ? "Preview — nothing is burned until you commit"
                  : version.is_derivative
                    ? "Redacted derivative — content removed and page rasterised"
                    : spans && spans.boxes.length
                    ? `${spans.boxes.length} word box${spans.boxes.length === 1 ? "" : "es"} for ${selected ? humanKey(selected.field_key).toLowerCase() : "the field"}`
                    : "Select a field to see where it was read from"}
              </span>
              <span className="flex items-center gap-1.5"><IconEye className="h-3.5 w-3.5" /> watermarked to you · view logged</span>
            </div>
            <div className="mx-auto max-w-[52rem]">
              <p className="mb-2 text-center font-serif text-[0.65rem] uppercase tracking-[0.22em] text-brass-300/80">
                Page · पृष्ठ {((spans?.page_no ?? 0) + 1).toString().padStart(2, "0")}
              </p>
              <div className="relative overflow-hidden rounded-sm bg-white shadow-page">
                {integrity?.state === "MISMATCH" ? (
                  <div className="grid aspect-[595/842] place-items-center bg-danger-50 text-danger-700">
                    <p className="flex items-center gap-2 text-sm font-semibold"><IconX className="h-5 w-5" /> Page withheld — integrity mismatch</p>
                  </div>
                ) : version.lifecycle_state === "disposed" ? (
                  <div className="grid aspect-[595/842] place-items-center bg-paper-100 text-ink-500">
                    <div className="text-center">
                      <IconLock className="mx-auto h-8 w-8 text-ink-400" />
                      <p className="mt-2 text-sm font-semibold">Lawfully disposed</p>
                      <p className="mt-1 text-xs text-ink-400">Bytes destroyed; anchor and reason remain.</p>
                    </div>
                  </div>
                ) : (
                  <>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={`/scan/${version.id}?page=${spans?.page_no ?? 0}`} alt={`Page of ${document.title}`} className="block w-full" />
                    {mode === "review" && spans?.boxes.map((b, i) => (
                      <Box key={i} b={b} w={spans.page_width} h={spans.page_height}
                           className="rounded-[2px] bg-brass-300/35 ring-2 ring-brass-400 mix-blend-multiply animate-pulse-ring" />
                    ))}
                    {mode === "redact" && plan?.findings.flatMap((f, i) =>
                      f.boxes.map((b, j) => (
                        <Box key={`${i}-${j}`} b={b} w={pageW} h={pageH}
                             className={`rounded-[2px] bg-ink-950/85 ring-2 ${KIND_TONE[f.kind]?.ring ?? "ring-ink-500"}`} />
                      )),
                    )}
                  </>
                )}
              </div>
            </div>
          </section>

          {/* ---- right -------------------------------------------------------- */}
          <aside className="grid min-w-0 content-start gap-4 md:grid-cols-3 xl:col-span-2 2xl:col-span-1 2xl:grid-cols-1">
            {integrity && (
              <div className={`rounded-xl border px-4 py-4 ${INTEGRITY[integrity.state].tone}`}>
                <div className="flex items-center gap-3">
                  <span className="grid h-10 w-10 place-items-center rounded-full bg-white/70">{INTEGRITY[integrity.state].icon}</span>
                  <div>
                    <p className="text-[0.625rem] font-semibold uppercase tracking-eyebrow opacity-80">Integrity · checked now</p>
                    <p className="font-display text-base font-semibold">{INTEGRITY[integrity.state].title}</p>
                  </div>
                </div>
                <p className="mt-3 text-xs leading-relaxed opacity-90">{integrity.detail}.</p>
                <dl className="mt-3 space-y-1.5 border-t border-current/10 pt-3 text-[0.6875rem]">
                  <div className="flex justify-between gap-2">
                    <dt className="opacity-70">SHA-256</dt>
                    <dd className="mono font-semibold">{integrity.sha256.slice(0, 16)}…</dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="opacity-70">Version</dt>
                    <dd className="font-semibold">v{version.version_no} ({version.is_derivative ? "Redacted" : "Original"})</dd>
                  </div>
                  {/* "Ledger anchor: TX-0000042" dressed a row number in a
                      distributed-ledger costume. `anchor_seq` is a bigint identity
                      column in `anchor_record` in this system's own Postgres; calling
                      it a transaction id invites the reader to believe a second party
                      witnessed it. Shown as what it is. */}
                  <div className="flex justify-between gap-2">
                    <dt className="opacity-70">Anchor row</dt>
                    <dd className="mono font-semibold">
                      {integrity.anchor_seq ? `#${integrity.anchor_seq}` : "Pending"}
                    </dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="opacity-70">Status</dt>
                    <dd className="font-semibold">{integrity.state === "VERIFIED" ? "Verified" : integrity.state}</dd>
                  </div>
                  {integrity.anchored_at && (
                    <div className="flex justify-between gap-2">
                      <dt className="opacity-70">Anchored</dt>
                      <dd>{relative(integrity.anchored_at)}</dd>
                    </div>
                  )}
                </dl>
                <p className="mt-2 text-[0.625rem] leading-snug opacity-70">{integrity.note}</p>
                <p className="mono mt-2 break-all text-[0.625rem] opacity-80">{integrity.sha256}</p>
                {/* CLAUDE.md, by name: "The local hash-chain is not a blockchain...
                    only the Fabric adapter may use ledger or chain vocabulary." This
                    read "anchored to the immutable ledger" two lines under
                    {'{'}integrity.note{'}'}, which is the API saying the opposite - that the
                    anchor store is hash-chained in the same database as the records it
                    attests to and is not an independent attestation (AR-4). The panel
                    contradicted itself, and the more impressive half was the false one. */}
                <div className="mt-3 rounded bg-black/5 p-2 text-[0.625rem] leading-snug opacity-85">
                  Document bytes are never placed on the anchor store; it holds digests,
                  identifiers and timestamps only. The store is a hash chain in this
                  system&rsquo;s own database, so it detects alteration after the fact —
                  it does not prevent it, and it is not witnessed by anyone else.
                </div>
              </div>
            )}

            <div className="surface px-4 py-4">
              <p className="eyebrow">Evidence passport</p>
              <dl className="mt-3 space-y-2 text-[0.75rem]">
                <div className="flex justify-between gap-3">
                  <dt className="text-ink-400">Version</dt>
                  <dd className="font-semibold text-ink-800">v{version.version_no}</dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-ink-400">Lifecycle</dt>
                  <dd className="text-ink-800">{version.lifecycle_state}</dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-ink-400">You receive</dt>
                  <dd className="text-ink-800">{document.disclosure}</dd>
                </div>
              </dl>
              {versions.length > 1 && (
                <div className="mt-3 border-t border-paper-200 pt-3">
                  <p className="text-[0.65rem] font-semibold uppercase tracking-eyebrow text-ink-500">Lineage</p>
                  <ol className="mt-2 space-y-1.5">
                    {versions.map((v) => (
                      <li key={v.id} className="flex items-center justify-between gap-2 text-xs">
                        <a href={`/documents/${documentId}?version=${v.id}`} className={v.id === version.id ? "font-semibold text-ink-900" : "text-ink-600 hover:text-ink-900"}>
                          v{v.version_no} · {v.is_derivative ? "redacted" : "original"}
                        </a>
                        {v.id !== version.id && (
                          <a href={`${base}&compare=${v.id}`} className="text-[0.65rem] font-semibold text-brass-700 hover:underline">
                            Compare
                          </a>
                        )}
                      </li>
                    ))}
                  </ol>
                </div>
              )}
            </div>

            {/* **Two deliberate steps, behind a closed disclosure.** This was a single
                red button beside a dropdown. It destroys bytes irreversibly, and AR-15
                records that two-person approval was cut — so the interface is the only
                friction left between an officer and permanent erasure, and it had none.
                Typing the version number is not security (the API neither sees nor
                checks it); it is the pause, and it is the part of the design that is
                honest about being a pause. Works with scripting off: `required` and
                `pattern` are the browser's own. */}
            {original && !version.is_derivative && version.lifecycle_state !== "disposed" && (
              <details className="surface-quiet px-4 py-4">
                <summary className="cursor-pointer text-xs font-semibold text-danger-700">
                  Lawful disposal
                </summary>
                <form method="post" action="/actions/govern" className="mt-3 space-y-2">
                  <p className="text-[0.6875rem] leading-relaxed text-ink-500">
                    Destroys the stored bytes and the derived text of{" "}
                    <span className="mono font-semibold">v{version.version_no}</span>, after
                    the anchor exists. <strong>This cannot be undone.</strong> The digest,
                    the anchor and this disposal record survive, so the version will verify
                    as lawfully disposed rather than as missing. Unilateral in this build:
                    there is no second officer to approve it.
                  </p>
                  <input type="hidden" name="intent" value="dispose" />
                  <input type="hidden" name="version_id" value={version.id} />
                  <input type="hidden" name="next" value={here} />
                  <label className="block text-[0.65rem] font-semibold uppercase tracking-eyebrow text-ink-500">
                    Basis
                    <select name="basis" className="field mt-1 text-xs" required defaultValue="">
                      <option value="" disabled>
                        Choose the basis
                      </option>
                      <option value="erroneous_upload">Erroneous upload</option>
                      <option value="superseded_original">Superseded original</option>
                      <option value="court_order">Court order</option>
                      <option value="retention_expiry">Retention expiry (configured basis only)</option>
                    </select>
                  </label>
                  <label className="block text-[0.65rem] font-semibold uppercase tracking-eyebrow text-ink-500">
                    Type <span className="mono normal-case">v{version.version_no}</span> to confirm
                    <input
                      type="text"
                      name="confirm"
                      required
                      pattern={`v${version.version_no}`}
                      autoComplete="off"
                      placeholder={`v${version.version_no}`}
                      className="field mt-1 w-28 text-xs"
                      aria-label={`Type v${version.version_no} to confirm irreversible disposal`}
                    />
                  </label>
                  <button type="submit" className="btn-danger w-full">
                    Destroy v{version.version_no} permanently
                  </button>
                </form>
              </details>
            )}

            <div className="surface px-4 py-4">
              <p className="eyebrow">Text source</p>
              <p className="mt-1.5 text-[0.8125rem] font-semibold text-ink-900">
                {version.is_derivative
                  ? "None — a rasterised derivative has no text layer"
                  : ocr?.method === "tesseract_ocr"
                    ? "Tesseract OCR over the rendered page"
                    : ocr?.method ?? "Queued for the worker"}
              </p>
              {ocr?.mean_confidence != null && <div className="mt-2"><Confidence value={ocr.mean_confidence} label="Mean" /></div>}
              <p className="mt-2 text-[0.6875rem] leading-relaxed text-ink-400">
                Extracted text is data, never instruction. Nothing on this page can change
                workflow state or influence an access decision.
              </p>
            </div>

            {original && (
              <div className="surface overflow-hidden">
                <div className="flex items-center gap-2 border-b border-paper-200 px-4 py-3">
                  <IconChain className="h-4 w-4 text-brass-500" />
                  <h2 className="section-title">Custody trail</h2>
                </div>
                {activity.length === 0 ? (
                  <p className="px-4 py-4 text-xs text-ink-400">No recorded activity yet.</p>
                ) : (
                  <ol className="relative max-h-80 space-y-3 overflow-y-auto px-4 py-4">
                    {grouped(activity).slice(0, 14).map((a) => (
                      <li key={a.seq} className="flex gap-3">
                        <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-paper-100 text-ink-500 ring-1 ring-paper-300">
                          {ACTIONS[a.action]?.icon ?? <IconClock className="h-3.5 w-3.5" />}
                        </span>
                        <span className="min-w-0 text-xs leading-snug">
                          <span className="font-semibold text-ink-800">{a.actor ?? "System"}</span>{" "}
                          <span className="text-ink-600">{ACTIONS[a.action]?.label ?? a.action.replace(/_/g, " ")}</span>
                          {a.count > 1 && <span className="text-ink-400"> · ×{a.count}</span>}
                          <span className="mt-0.5 block text-[0.6875rem] text-ink-400">{when(a.at)} · #{a.seq}</span>
                        </span>
                      </li>
                    ))}
                  </ol>
                )}
                <p className="border-t border-paper-200 bg-paper-50 px-4 py-2.5 text-[0.625rem] leading-snug text-ink-400">
                  Append-only; each row commits to the one before it. The application role
                  holds no UPDATE or DELETE on this table.
                </p>
              </div>
            )}
          </aside>
        </div>
      </div>
    </Shell>
  );
}
