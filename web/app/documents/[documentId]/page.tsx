/**
 * The verification screen. Slice 5b's acceptance criterion, plus 5b+'s highlighting.
 *
 * Draft fields on the left, the scan on the right, and the selected field's OCR word
 * boxes drawn over it. Selection lives in the URL (`?field=…`) rather than in client
 * state: the page then works with no JavaScript at all, and a highlighted field is a
 * link somebody can paste into a chat. On a demo laptop that is worth more than a
 * smoother transition.
 *
 * Which versions exist for a subject is not a choice this page makes. The API returns
 * the ones their disclosure class permits — originals for a designation, derivatives
 * for a purpose-limited grant — and the switcher offers exactly those. A grantee
 * opening this URL sees the redacted derivative and nothing else; the parent's id is
 * not in the response to be asked for, and naming it by hand returns 404.
 *
 * Boxes arrive in PDF points with the page size beside them, and are positioned as
 * percentages, so the overlay tracks the rendered image at any width without this file
 * knowing what zoom the API rasterised at.
 */
import IdentityBar from "../../components/IdentityBar";
import {
  currentSubject,
  get,
  type DocumentRecord,
  type ExtractedField,
  type OcrText,
  type SpanBoxes,
} from "../../lib/api";

export const dynamic = "force-dynamic";

const ERRORS: Record<string, string> = {
  refused: "Not available to you. The field is unchanged.",
  session: "Your session has ended. Choose an identity above.",
  unreachable: "The API did not respond.",
  input: "That entry looked wrong. Nothing was written.",
  nothinglocated:
    "OCR located none of those values on the page, so nothing was removed and no " +
    "derivative was made. A copy that removed nothing must not be handed on as redacted.",
};

function Provenance({ field }: { field: ExtractedField }) {
  // Invariant 7's tuple, on the screen rather than only in the table. A judge asking
  // "where did this come from?" should not need a database client.
  return (
    <dl className="mt-2 grid grid-cols-[4.5rem_1fr] gap-x-3 gap-y-0.5 text-xs text-slate-500">
      <dt>source</dt>
      <dd className="font-mono">{field.source}</dd>
      {field.provider && (
        <>
          <dt>provider</dt>
          <dd className="font-mono">
            {field.provider}
            {field.model ? ` · ${field.model}` : ""}
          </dd>
        </>
      )}
      {field.confidence !== null && (
        <>
          <dt>confidence</dt>
          <dd className="font-mono">{(field.confidence * 100).toFixed(1)}%</dd>
        </>
      )}
      <dt>span</dt>
      <dd className="font-mono">
        {field.source_span_start === null
          ? "none — entered by hand"
          : `${field.source_span_start}–${field.source_span_end}`}
      </dd>
    </dl>
  );
}

export default async function DocumentPage({
  params,
  searchParams,
}: {
  params: Promise<{ documentId: string }>;
  searchParams: Promise<{ field?: string; error?: string; version?: string }>;
}) {
  const { documentId } = await params;
  const { field: selectedId, error, version: wantedVersion } = await searchParams;
  const subject = await currentSubject();
  const document = subject ? await get<DocumentRecord>(`/documents/${documentId}`) : null;

  // Default to the newest **original**, not simply the newest version. A designated
  // officer works the real document; the redacted derivative is a thing they produced
  // from it, and defaulting to it would hide the original behind its own redaction.
  // A grantee has only derivatives in this list, so they get one either way.
  const versions = document?.versions ?? [];
  const version =
    versions.find((v) => v.id === wantedVersion) ??
    [...versions].reverse().find((v) => !v.is_derivative) ??
    versions.at(-1) ??
    null;
  const fields = version
    ? ((await get<ExtractedField[]>(`/versions/${version.id}/fields`)) ?? [])
    : [];
  const ocr = version ? await get<OcrText>(`/versions/${version.id}/text`) : null;

  const selected =
    fields.find((f) => f.id === selectedId) ??
    fields.find((f) => f.status === "draft") ??
    fields[0] ??
    null;
  // One request, for the selected field only. The whole set would be N+1 for boxes
  // nobody is looking at.
  const spans = selected ? await get<SpanBoxes>(`/fields/${selected.id}/spans`) : null;

  const here =
    `/documents/${documentId}?version=${version?.id ?? ""}` +
    (selected ? `&field=${selected.id}` : "");
  const drafts = fields.filter((f) => f.status === "draft").length;

  return (
    <>
      <IdentityBar current={subject} returnTo={here} />
      <main className="mx-auto max-w-6xl px-6 py-10">
        {!document || !version ? (
          // Denied and nonexistent are the same response from the API and the same
          // screen here. "You are not permitted" would confirm it exists (INS-04).
          <div className="rounded-lg border border-slate-200 bg-white p-6">
            <h1 className="text-lg font-medium">Not available</h1>
            <p className="mt-2 text-sm text-slate-600">No document here for this subject.</p>
            <a className="mt-4 inline-block text-sm text-slate-500 underline" href="/">
              Back to cases
            </a>
          </div>
        ) : (
          <>
            <header className="mb-6 flex flex-wrap items-baseline justify-between gap-3">
              <div>
                <h1 className="text-xl font-semibold tracking-tight">{document.title}</h1>
                <p className="mt-1 font-mono text-xs text-slate-500">
                  version {version.version_no} · sha256 {version.sha256.slice(0, 16)}…
                  {version.is_derivative && " · derived"}
                </p>
              </div>
              <span
                className={`rounded-full px-3 py-1 text-xs font-medium ${
                  document.disclosure === "original"
                    ? "bg-slate-100 text-slate-700"
                    : "bg-indigo-100 text-indigo-800"
                }`}
              >
                disclosure: {document.disclosure}
              </span>
            </header>

            {versions.length > 1 && (
              <div className="mb-4 flex flex-wrap items-center gap-2 text-xs">
                <span className="uppercase tracking-wide text-slate-400">Versions</span>
                {versions.map((v) => (
                  <a
                    key={v.id}
                    href={`/documents/${documentId}?version=${v.id}`}
                    className={`rounded-full border px-2.5 py-0.5 ${
                      v.id === version.id
                        ? "border-slate-900 bg-slate-900 text-white"
                        : "border-slate-300 text-slate-600 hover:bg-slate-50"
                    }`}
                  >
                    v{v.version_no}
                    {v.is_derivative ? " · redacted" : " · original"}
                  </a>
                ))}
              </div>
            )}

            {error && (
              <p className="mb-4 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
                {ERRORS[error] ?? "The request was refused."}
              </p>
            )}

            <div className="grid gap-6 lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
              <section>
                <div className="mb-3 flex items-baseline justify-between">
                  <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
                    Extracted fields
                  </h2>
                  <span className="text-xs text-slate-500">{drafts} awaiting a human</span>
                </div>

                {ocr?.requires_manual_entry && (
                  <p className="mb-3 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                    OCR confidence was too low to extract anything, and that is
                    deliberate: a page a human must read is not a page to run patterns
                    over and call draft evidence. Enter the values by hand below.
                  </p>
                )}

                {fields.length === 0 && !ocr?.requires_manual_entry && (
                  <p className="rounded border border-slate-200 bg-white px-3 py-3 text-sm text-slate-600">
                    No extracted fields on this version.
                  </p>
                )}

                <ul className="space-y-2">
                  {fields.map((f) => {
                    const isSelected = selected?.id === f.id;
                    return (
                      <li
                        key={f.id}
                        className={`rounded-lg border bg-white p-3 ${
                          isSelected ? "border-slate-900 shadow-sm" : "border-slate-200"
                        }`}
                      >
                        <a
                          href={`/documents/${documentId}?version=${version.id}&field=${f.id}`}
                          className="block"
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <p className="font-mono text-xs text-slate-500">{f.field_key}</p>
                              <p className="truncate text-sm font-medium">{f.value}</p>
                            </div>
                            <span
                              className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${
                                f.status === "verified"
                                  ? "bg-emerald-100 text-emerald-800"
                                  : "bg-slate-100 text-slate-600"
                              }`}
                            >
                              {f.status}
                            </span>
                          </div>
                        </a>

                        {isSelected && (
                          <>
                            <Provenance field={f} />
                            {f.status === "draft" ? (
                              <form method="post" action="/actions/field" className="mt-3">
                                <input type="hidden" name="intent" value="verify" />
                                <input type="hidden" name="field_id" value={f.id} />
                                <input type="hidden" name="next" value={here} />
                                <button
                                  type="submit"
                                  className="w-full rounded bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800"
                                >
                                  Verify this value
                                </button>
                              </form>
                            ) : (
                              <p className="mt-3 rounded bg-emerald-50 px-2.5 py-1.5 text-xs text-emerald-900">
                                Committed by a person. The database refuses this state
                                without one named.
                              </p>
                            )}
                          </>
                        )}
                      </li>
                    );
                  })}
                </ul>

                {!version.is_derivative && fields.some((f) => f.source_span_start !== null) && (
                  <form method="post" action="/actions/field" className="mt-4">
                    <input type="hidden" name="intent" value="redact" />
                    <input type="hidden" name="version_id" value={version.id} />
                    <input type="hidden" name="next" value={here} />
                    {fields
                      .filter((f) => f.source_span_start !== null)
                      .map((f) => (
                        <input key={f.id} type="hidden" name="field_id" value={f.id} />
                      ))}
                    <button
                      type="submit"
                      className="w-full rounded border border-amber-600 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-900 hover:bg-amber-100"
                    >
                      Redact every located identifying value
                    </button>
                    <p className="mt-1.5 text-xs text-slate-500">
                      Produces a new version with the content removed and the page
                      rasterised — not a black box over it. It can only cover what OCR
                      located, which on a poor scan is less than everything (AR-6).
                    </p>
                  </form>
                )}

                <form
                  method="post"
                  action="/actions/field"
                  className="mt-4 rounded-lg border border-dashed border-slate-300 p-3"
                >
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Enter a value by hand
                  </h3>
                  <p className="mt-1 text-xs text-slate-500">
                    A correction is recorded as a new field with{" "}
                    <code>source=human</code>. The machine&apos;s value is left exactly
                    as extracted — it is the evidence that the extractor needs fixing.
                  </p>
                  <input type="hidden" name="intent" value="enter" />
                  <input type="hidden" name="version_id" value={version.id} />
                  <input type="hidden" name="next" value={here} />
                  <div className="mt-2 space-y-2">
                    <input
                      name="field_key"
                      required
                      placeholder="field name, e.g. complainant_name"
                      className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
                    />
                    <input
                      name="value"
                      required
                      placeholder="value"
                      className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
                    />
                    <button
                      type="submit"
                      className="w-full rounded border border-slate-900 px-3 py-1.5 text-xs font-medium hover:bg-slate-50"
                    >
                      Record as a human entry
                    </button>
                  </div>
                </form>
              </section>

              <section>
                <div className="mb-3 flex items-baseline justify-between">
                  <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
                    {version.is_derivative ? "Redacted derivative" : "Scan"}
                  </h2>
                  <span className="text-xs text-slate-500">
                    {ocr?.method ?? "no text source"}
                    {ocr?.mean_confidence != null &&
                      ` · mean confidence ${(ocr.mean_confidence * 100).toFixed(1)}%`}
                  </span>
                </div>

                <div className="relative overflow-hidden rounded-lg border border-slate-200 bg-white">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={`/scan/${version.id}?page=${spans?.page_no ?? 0}`}
                    alt="Page image of this document version"
                    className="block w-full"
                  />
                  {spans?.boxes.map((box, i) => (
                    <span
                      key={i}
                      aria-hidden
                      className="pointer-events-none absolute rounded-sm bg-amber-300/40 ring-2 ring-amber-500"
                      style={{
                        left: `${(box.x0 / spans.page_width) * 100}%`,
                        top: `${(box.y0 / spans.page_height) * 100}%`,
                        width: `${((box.x1 - box.x0) / spans.page_width) * 100}%`,
                        height: `${((box.y1 - box.y0) / spans.page_height) * 100}%`,
                      }}
                    />
                  ))}
                </div>

                <p className="mt-2 text-xs text-slate-400">
                  {spans && spans.boxes.length > 0
                    ? `${spans.boxes.length} OCR word box(es) for the selected field.`
                    : "Select a field to highlight the words it was read from. A hand-entered value has no span and highlights nothing."}
                </p>
              </section>
            </div>

            <p className="mt-8 max-w-3xl text-xs text-slate-400">
              Extracted text is treated as data and never as instruction (invariant 6):
              nothing on this page can change workflow state, and no field value
              influences an access decision. Committing a value writes one append-only,
              hash-chained audit row naming the person who committed it.
            </p>
          </>
        )}
      </main>
    </>
  );
}
