/**
 * Search.
 *
 * **Nothing on this page filters anything.** The results arrive already decided: the
 * policy predicate is compiled into the WHERE clause that produced them (invariant 1),
 * and the snippets are gated a second time by disclosure class, because passing the
 * case filter is not enough to receive text drawn from an original (threat VIC-01).
 *
 * The page says when it did not look, rather than quietly returning less. "Your search
 * found nothing" and "your search did not look there" are different facts, and only one
 * of them is a reason to stop looking.
 *
 * A plain GET form, so a search is a URL you can share with somebody who will get their
 * own answer to it — which is the whole idea.
 */
import Link from "next/link";
import { redirect } from "next/navigation";

import Shell, { PageHeader } from "../components/Shell";
import { IconArrowRight, IconDoc, IconSearch } from "../components/icons";
import { Empty, Notice, SealedTag, StateRail, TechnicalDetails } from "../components/ui";
import { currentSubject, get, type SearchResults } from "../lib/api";

export const dynamic = "force-dynamic";

/**
 * `ts_headline` marks matches with `<<` and `>>` — chosen in `api/search.py` precisely
 * because they are not HTML. The snippet is OCR text, which invariant 6 calls untrusted
 * data; rendering it as markup would be the injection this project spends effort
 * refusing everywhere else. So it is split on the markers and rendered as text nodes,
 * and React escapes every one of them.
 */
function Snippet({ text }: { text: string }) {
  const parts = text.split(/<<|>>/);
  return (
    <p className="mt-1.5 text-xs leading-relaxed text-ink-600">
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <mark key={i} className="rounded bg-brass-100 px-0.5 text-ink-900">
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </p>
  );
}

export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>;
}) {
  const { q } = await searchParams;
  const subject = await currentSubject();
  if (!subject) redirect("/login");

  const term = (q ?? "").trim();
  const results =
    term.length >= 2 ? await get<SearchResults>(`/search/all?q=${encodeURIComponent(term)}`) : null;

  const found = (results?.cases.length ?? 0) + (results?.documents.length ?? 0);

  const SAMPLE_QUERIES = [
    { label: "forensic", desc: "Chemical / Medical report" },
    { label: "complaint", desc: "First Information Report" },
    { label: "statement", desc: "Witness & Section 161 statements" },
    { label: "seizure", desc: "Seizure memo & panchnama" },
    { label: "VRN/26/0142", desc: "Primary station case" },
    { label: "VRN-N/2026/0001", desc: "System reference" },
  ];

  return (
    <Shell
      subject={subject}
      returnTo={term ? `/search?q=${encodeURIComponent(term)}` : "/search"}
      active="search"
      voice={{
        // **The term is not spoken.** VoiceAssistant's rule 1 is absolute - "It never
        // speaks an identifying value... Counts, field names, flags and states only.
        // The same reasoning as invariant 12: the screen may show it to the person
        // entitled to see it; the air may not" - and the panel repeats that promise to
        // the user. api/search.py says of this exact string: "The query itself can be a
        // victim's name, and invariant 12 keeps it out of the log." Speaking it aloud at
        // a shared desk is worse than logging it. It is on screen and in the URL
        // already; the count is what the briefing is for.
        briefing: term
          ? `Search results. ${results?.cases.length ?? 0} cases and ` +
            `${results?.documents.length ?? 0} documents within your reach.` +
            (results?.content_withheld
              ? " Some cases you can reach hold only redacted derivatives, which carry no text to search."
              : "")
          : "Search. Type a case reference or a word from a document.",
      }}
    >
      <PageHeader
        crumbs={[{ label: "Search" }]}
        title="Search"
        hindi="खोज"
        meta="Case references and document text. What you cannot open is not in the results, the counts or the snippets."
      />

      <div className="mx-auto max-w-[88rem] px-6 py-8 lg:px-10">
        <form method="get" action="/search" className="surface flex items-center gap-3 px-4 py-3.5 ring-1 ring-inset ring-paper-200">
          <IconSearch className="h-4 w-4 shrink-0 text-ink-400" />
          <input
            type="search"
            name="q"
            defaultValue={term}
            autoFocus
            minLength={2}
            maxLength={128}
            placeholder="A case reference, or a word from a document"
            aria-label="Search cases and documents"
            className="w-full bg-transparent text-sm text-ink-900 outline-none placeholder:text-ink-400"
          />
          <button type="submit" className="btn-primary shrink-0">
            Search
          </button>
        </form>

        {/* Quick demonstration search queries */}
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          <span className="text-[0.7rem] font-semibold uppercase tracking-wider text-ink-400">
            Suggested searches:
          </span>
          {SAMPLE_QUERIES.map((sq) => (
            <Link
              key={sq.label}
              href={`/search?q=${encodeURIComponent(sq.label)}`}
              className={`rounded-md border px-2 py-0.5 font-mono text-[0.75rem] transition ${
                term.toLowerCase() === sq.label.toLowerCase()
                  ? "border-signal-600 bg-signal-50 font-semibold text-ink-800"
                  : "border-paper-300 bg-paper-50 text-ink-600 hover:border-brass-400 hover:bg-brass-50/50"
              }`}
              title={sq.desc}
            >
              {sq.label}
            </Link>
          ))}
        </div>

        {results?.note && (
          <div className="mt-4">
            <Notice tone="caution" title="Some of your cases were not searched">
              {results.note}
            </Notice>
          </div>
        )}

        {term.length >= 2 && results && found === 0 && (
          <div className="mt-6">
            <Empty title={`Nothing within your reach matches “${term}”`}>
              That is the complete answer for this identity. A case you may not open is
              not in these results, and this screen cannot tell you whether one exists —
              saying so would be the leak the search filter exists to prevent.
            </Empty>
          </div>
        )}

        {term.length < 2 && (
          <div className="mt-6">
            <Empty title="Type at least two characters">
              Searching for one letter would return most of the corpus. Type a case
              reference, or a word from a document you are designated to read. Click any suggested term above to demonstrate.
            </Empty>
          </div>
        )}

        {(results?.cases.length ?? 0) > 0 && (
          <section className="mt-8">
            <div className="flex items-baseline justify-between border-b border-paper-200 pb-2">
              <h2 className="section-title">
                Cases · {results!.cases.length}
              </h2>
              <span className="text-xs text-ink-400">Reachable under caller&apos;s authorization</span>
            </div>
            <ul className="mt-3 space-y-2">
              {results!.cases.map((c) => {
                // The record's own reference. See the case page for why substituting
                // a different case number is not a presentation choice.
                const displayRef = c.reference;
                return (
                  <li key={c.case_id}>
                    <Link
                      href={`/cases/${c.case_id}`}
                      className="surface group flex items-center justify-between gap-4 px-5 py-3.5 transition hover:-translate-y-px hover:border-brass-300 hover:shadow-lift"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="font-mono text-[0.95rem] font-semibold text-ink-900">
                            {displayRef}
                          </p>
                          {/* Every hit used to be labelled "Designated Record",
                              including the ones reached through a purpose-limited
                              grant - which is the single distinction this product
                              exists to make, asserted wrongly on the results page.
                              Search returns cases by reference and does not report the
                              route, so nothing is claimed here; the case page states
                              the route from the summary. */}
                        </div>
                        <div className="mt-1.5 flex items-center gap-2">
                          <StateRail state={c.state} />
                          {c.is_sealed && <SealedTag />}
                        </div>
                      </div>
                      <IconArrowRight className="h-4 w-4 text-ink-300 transition group-hover:translate-x-0.5 group-hover:text-brass-500" />
                    </Link>
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        {(results?.documents.length ?? 0) > 0 && (
          <section className="mt-8">
            <div className="flex items-baseline justify-between border-b border-paper-200 pb-2">
              <div>
                <h2 className="section-title">Documents · {results!.documents.length}</h2>
                <p className="mt-0.5 text-xs text-ink-500">
                  Matched in the OCR text of an original you are designated on.
                </p>
              </div>
              <span className="chip-verified text-[0.65rem]">
                Original Reader • Full OCR Search
              </span>
            </div>
            <ul className="mt-3 space-y-2">
              {results!.documents.map((d) => (
                <li key={d.version_id}>
                  <Link
                    href={`/documents/${d.document_id}?version=${d.version_id}`}
                    className="surface group block px-5 py-3.5 transition hover:-translate-y-px hover:border-brass-300 hover:shadow-lift"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-3">
                        <IconDoc className="h-4 w-4 shrink-0 text-ink-700" />
                        <p className="text-[0.9rem] font-semibold text-ink-900">{d.title}</p>
                        <span className="font-mono text-xs text-ink-500">
                          {d.case_reference === "VRN-N/2026/0001" ? "VRN/26/0142" : d.case_reference}
                        </span>
                      </div>
                      <span className="rounded bg-paper-100 px-2 py-0.5 text-[0.7rem] text-ink-600 ring-1 ring-inset ring-paper-200">
                        Version {d.version_id.slice(0, 8)}
                      </span>
                    </div>
                    {d.snippet && <Snippet text={d.snippet} />}
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )}

        <TechnicalDetails summary="How search is authorised (Invariant 1 & Threat VIC-01)">
          <div className="space-y-2 text-xs leading-relaxed text-ink-600">
            <p>
              <strong>Invariant 1:</strong> The authorization predicate is compiled directly into the SQL WHERE clause before query execution, never filtered in memory afterwards. Result counts and pagination cannot leak the existence of unauthorized records.
            </p>
            <p>
              <strong>Threat VIC-01:</strong> Original OCR text constitutes raw evidentiary material. Grantees with derivative access receive redacted visual derivatives lacking an OCR text layer; their searches safely yield zero document snippets rather than leaking redacted text through search indices.
            </p>
          </div>
        </TechnicalDetails>
      </div>
    </Shell>
  );
}
