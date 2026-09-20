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
import { IconArrowRight, IconDoc, IconLock, IconSearch } from "../components/icons";
import { Empty, Notice, SealedTag, StateRail } from "../components/ui";
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

  return (
    <Shell
      subject={subject}
      returnTo={term ? `/search?q=${encodeURIComponent(term)}` : "/search"}
      active="search"
      voice={{
        briefing: term
          ? `Search for ${term}. ${results?.cases.length ?? 0} cases and ` +
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
        meta="Case references and document text. What you cannot open is not in the results, the counts or the snippets."
      />

      <div className="mx-auto max-w-[88rem] px-6 py-8 lg:px-10">
        <form method="get" action="/search" className="surface flex items-center gap-3 px-4 py-3">
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
              Searching for one letter would return most of the corpus and tell you
              little. Autocomplete on a single letter is the specific behaviour invariant
              1 calls the worst offender.
            </Empty>
          </div>
        )}

        {(results?.cases.length ?? 0) > 0 && (
          <section className="mt-8">
            <h2 className="section-title">
              Cases · {results!.cases.length}
            </h2>
            <ul className="mt-3 space-y-2">
              {results!.cases.map((c) => (
                <li key={c.case_id}>
                  <Link
                    href={`/cases/${c.case_id}`}
                    className="surface group flex items-center gap-4 px-5 py-3.5 transition hover:-translate-y-px hover:border-brass-300 hover:shadow-lift"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="font-mono text-[0.95rem] font-semibold text-ink-900">
                        {c.reference}
                      </p>
                      <div className="mt-1 flex items-center gap-2">
                        <StateRail state={c.state} />
                        {c.is_sealed && <SealedTag />}
                      </div>
                    </div>
                    <IconArrowRight className="h-4 w-4 text-ink-300 transition group-hover:translate-x-0.5 group-hover:text-brass-500" />
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )}

        {(results?.documents.length ?? 0) > 0 && (
          <section className="mt-8">
            <h2 className="section-title">Documents · {results!.documents.length}</h2>
            <p className="mt-1 text-xs text-ink-500">
              Matched in the OCR text of an original you are designated on. A derivative
              carries no text layer, so there is nothing in one to match.
            </p>
            <ul className="mt-3 space-y-2">
              {results!.documents.map((d) => (
                <li key={d.version_id}>
                  <Link
                    href={`/documents/${d.document_id}?version=${d.version_id}`}
                    className="surface group block px-5 py-3.5 transition hover:-translate-y-px hover:border-brass-300 hover:shadow-lift"
                  >
                    <div className="flex items-center gap-3">
                      <IconDoc className="h-4 w-4 shrink-0 text-ink-400" />
                      <p className="text-[0.9rem] font-semibold text-ink-900">{d.title}</p>
                      <span className="font-mono text-xs text-ink-400">
                        {d.case_reference}
                      </span>
                    </div>
                    {d.snippet && <Snippet text={d.snippet} />}
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )}

        <p className="mt-10 flex items-start gap-2 text-xs leading-relaxed text-ink-400">
          <IconLock className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            The authorization predicate is inside the query that produced these results,
            not applied to them afterwards. That is what makes the counts above safe to
            show: a result set filtered after the fact leaks through its own size.
          </span>
        </p>
      </div>
    </Shell>
  );
}
