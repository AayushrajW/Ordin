/**
 * Case list — the front page of the product.
 *
 * This list is not filtered here. It arrives already filtered, because the policy
 * predicate sits inside the SQL `WHERE` clause that produced it (invariant 1). The
 * count beside the heading comes from `/cases/count`, a separate endpoint that
 * applies the same predicate inside the aggregate — so it is the number of cases this
 * subject may see, not a total they may not.
 *
 * Switching identity in the bar above changes what this page contains. That is the
 * demo: same URL, same code path, different subject.
 */
import IdentityBar from "./components/IdentityBar";
import { currentSubject, get, type CaseRecord } from "./lib/api";

export const dynamic = "force-dynamic";

const STATE_LABEL: Record<string, string> = {
  registered: "Registered",
  under_investigation: "Under investigation",
  filed: "Filed",
  in_trial: "In trial",
  closed: "Closed",
};

export default async function CaseListPage() {
  const subject = await currentSubject();
  const cases = subject ? ((await get<CaseRecord[]>("/cases?limit=50")) ?? []) : [];
  const counted = subject ? await get<{ count: number }>("/cases/count") : null;

  return (
    <>
      <IdentityBar current={subject} returnTo="/" />
      <main className="mx-auto max-w-6xl px-6 py-10">
        {!subject ? (
          <div className="rounded-lg border border-slate-200 bg-white p-6">
            <h1 className="text-lg font-medium">Choose a specimen identity to begin</h1>
            <p className="mt-2 max-w-2xl text-sm text-slate-600">
              Every screen in Ordin is rendered from what the chosen subject is
              permitted to see. Nothing on this tier filters anything — the decision
              is made inside the database query, so an identity with no route to a
              case cannot reach it by calling the API directly either.
            </p>
          </div>
        ) : (
          <>
            <header className="mb-6 flex items-baseline justify-between">
              <h1 className="text-xl font-semibold tracking-tight">Cases</h1>
              <span className="text-sm text-slate-500">
                {counted?.count ?? cases.length} visible to {subject.display_name}
              </span>
            </header>

            {cases.length === 0 ? (
              <p className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-600">
                No cases. This subject holds neither a designation nor an unexpired
                grant that reaches one — which is a result, not an error.
              </p>
            ) : (
              <ul className="divide-y divide-slate-200 overflow-hidden rounded-lg border border-slate-200 bg-white">
                {cases.map((c) => (
                  <li key={c.id}>
                    <a
                      href={`/cases/${c.id}`}
                      className="flex items-center justify-between px-5 py-4 hover:bg-slate-50"
                    >
                      <span>
                        <span className="font-mono text-sm font-medium">{c.reference}</span>
                        <span className="ml-3 text-sm text-slate-500">
                          {STATE_LABEL[c.state] ?? c.state}
                        </span>
                      </span>
                      {c.access_class === "sealed" && (
                        <span className="rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-800">
                          sealed
                        </span>
                      )}
                    </a>
                  </li>
                ))}
              </ul>
            )}

            <p className="mt-6 max-w-3xl text-xs text-slate-400">
              Case states are generic procedural stages, not confirmed Indian statutory
              ones. They are placeholders pending a citation (docs/adr/0008).
            </p>
          </>
        )}
      </main>
    </>
  );
}
