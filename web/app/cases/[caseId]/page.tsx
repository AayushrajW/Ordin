/**
 * One case: its documents, and which version of each this subject receives.
 *
 * The disclosure badge is the visible half of slice 7. A designated officer sees
 * `original`; a purpose-limited grantee sees `redacted` and is offered derivatives
 * only. A document with nothing the subject may receive is not listed at all — an
 * entry with an empty version list would confirm that it exists.
 */
import IdentityBar from "../../components/IdentityBar";
import { currentSubject, get, type CaseRecord, type DocumentRecord } from "../../lib/api";

export const dynamic = "force-dynamic";

const UPLOAD_ERRORS: Record<string, string> = {
  notpdf: "That file is not a PDF. The content decides, not the extension.",
  toolarge: "That file is over the size limit and was not read.",
  encrypted: "That PDF is encrypted. It is refused rather than guessed at.",
  unreadable: "That PDF could not be parsed and was refused.",
  unsafe: "Active content survived sanitisation, so the file was refused rather than stored.",
  refused: "Not available to you.",
  session: "Your session has ended. Choose an identity above.",
  unreachable: "The API did not respond.",
  input: "That upload looked wrong. Nothing was stored.",
};

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
  const documents = record
    ? ((await get<DocumentRecord[]>(`/cases/${caseId}/documents`)) ?? [])
    : [];

  return (
    <>
      <IdentityBar current={subject} returnTo={`/cases/${caseId}`} />
      <main className="mx-auto max-w-6xl px-6 py-10">
        {!record ? (
          // Denied and nonexistent are the same response from the API, and they are
          // the same screen here. Saying "you are not permitted" would confirm the
          // case exists (threat INS-04).
          <div className="rounded-lg border border-slate-200 bg-white p-6">
            <h1 className="text-lg font-medium">Not available</h1>
            <p className="mt-2 text-sm text-slate-600">
              No case here for this subject.
            </p>
            <a className="mt-4 inline-block text-sm text-slate-500 underline" href="/">
              Back to cases
            </a>
          </div>
        ) : (
          <>
            <header className="mb-6">
              <a className="text-sm text-slate-500 underline" href="/">
                Cases
              </a>
              <h1 className="mt-2 font-mono text-xl font-semibold tracking-tight">
                {record.reference}
              </h1>
              <p className="mt-1 text-sm text-slate-500">
                {record.state.replace(/_/g, " ")}
                {record.access_class === "sealed" && " · sealed"}
              </p>
            </header>

            {error && (
              <p className="mb-4 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
                {UPLOAD_ERRORS[error] ?? "The request was refused."}
              </p>
            )}

            {documents.length === 0 ? (
              <p className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-600">
                No documents this subject may receive.
              </p>
            ) : (
              <ul className="space-y-3">
                {documents.map((d) => (
                  <li
                    key={d.id}
                    className="overflow-hidden rounded-lg border border-slate-200 bg-white"
                  >
                    <a href={`/documents/${d.id}`} className="block px-5 py-4 hover:bg-slate-50">
                      <div className="flex items-center justify-between">
                        <span className="font-medium">{d.title}</span>
                        <span
                          className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${
                            d.disclosure === "original"
                              ? "bg-slate-100 text-slate-700"
                              : "bg-indigo-100 text-indigo-800"
                          }`}
                        >
                          {d.disclosure}
                        </span>
                      </div>
                      <p className="mt-1 text-xs text-slate-500">
                        {d.versions.length} version{d.versions.length === 1 ? "" : "s"} available
                        {d.versions.some((v) => v.is_derivative) && " · includes a redacted derivative"}
                      </p>
                    </a>
                  </li>
                ))}
              </ul>
            )}
            <form
              method="post"
              action="/actions/upload"
              encType="multipart/form-data"
              className="mt-6 rounded-lg border border-dashed border-slate-300 bg-white p-4"
            >
              <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
                Add a document
              </h2>
              <p className="mt-1 max-w-2xl text-xs text-slate-500">
                The file is sniffed by content rather than by extension, size-capped, and
                rebuilt without JavaScript, launch actions, embedded files or form
                actions before anything is stored. What gets hashed, signed and anchored
                is the sanitised file — anchoring the upload would anchor something the
                system does not hold.
              </p>
              <input type="hidden" name="case_id" value={caseId} />
              <input type="hidden" name="next" value={`/cases/${caseId}`} />
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <input
                  type="file"
                  name="file"
                  accept="application/pdf"
                  required
                  className="text-sm"
                />
                <button
                  type="submit"
                  className="rounded border border-slate-900 px-3 py-1.5 text-xs font-medium hover:bg-slate-50"
                >
                  Upload and process
                </button>
              </div>
            </form>
          </>
        )}
      </main>
    </>
  );
}
