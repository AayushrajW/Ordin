/**
 * Ordin Sentinel — the scenarios, on a page. Slice 8.
 *
 * **Every load runs them.** Nothing here is stored and nothing is cached, because a
 * dashboard that renders a saved result can show green from an hour ago, and the
 * registry's own docstring is blunt that a check which cannot currently fail is worse
 * than no check: it manufactures confidence.
 *
 * The page renders whatever came back, including ERROR. An errored scenario proved
 * nothing and is shown as its own state rather than folded into either column —
 * folding it into "pass" is how a dashboard lies, and folding it into "fail" would
 * make a broken scenario look like a broken system.
 *
 * What to do in front of a judge: break something on purpose — comment out the
 * disclosure check, say — reload this page, and watch a critical row go red.
 */
import IdentityBar from "../components/IdentityBar";
import { currentSubject, post } from "../lib/api";

export const dynamic = "force-dynamic";

type Result = {
  id: string;
  invariant: string;
  setup: string;
  expected: string;
  actual: string;
  severity: "critical" | "high" | "medium";
  slice_id: string;
  outcome: "pass" | "fail" | "error";
};

type Run = { ran_at: string; passing: number; total: number; results: Result[] };

const SEVERITY: Record<string, string> = {
  critical: "bg-red-50 text-red-800 border-red-200",
  high: "bg-amber-50 text-amber-800 border-amber-200",
  medium: "bg-slate-50 text-slate-700 border-slate-200",
};

const OUTCOME: Record<string, { label: string; className: string }> = {
  pass: { label: "PASS", className: "bg-emerald-100 text-emerald-800" },
  fail: { label: "FAIL", className: "bg-red-100 text-red-800" },
  error: { label: "ERROR", className: "bg-orange-100 text-orange-900" },
};

export default async function SentinelPage() {
  const subject = await currentSubject();
  const run = subject ? await post<Run>("/sentinel/run") : null;

  return (
    <>
      <IdentityBar current={subject} returnTo="/sentinel" />
      <main className="mx-auto max-w-6xl px-6 py-10">
        <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Ordin Sentinel</h1>
            <p className="mt-1 max-w-2xl text-sm text-slate-600">
              Each row is a security claim this system makes, expressed as something
              that can visibly go red. They run against the live application on every
              load — this is not a stored report.
            </p>
          </div>
          <a
            href={`/sentinel?t=${Date.now()}`}
            className="rounded border border-slate-900 px-3 py-1.5 text-sm font-medium hover:bg-slate-50"
          >
            Run again
          </a>
        </header>

        {!subject || !run ? (
          <p className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-600">
            Choose a specimen identity above. Sentinel exercises authorization
            boundaries, so it is not a route an unauthenticated caller can reach.
          </p>
        ) : !run.ok ? (
          <p className="rounded-lg border border-red-200 bg-red-50 p-6 text-sm text-red-800">
            The scenarios did not run. {run.reason} The dashboard is restricted to the
            development environment (docs/adr/0015).
          </p>
        ) : (
          <>
            <div
              className={`mb-6 rounded-lg border p-5 ${
                run.data.passing === run.data.total
                  ? "border-emerald-200 bg-emerald-50"
                  : "border-red-200 bg-red-50"
              }`}
            >
              <p className="text-lg font-medium">
                {run.data.passing}/{run.data.total} passing
              </p>
              <p className="mt-1 text-xs text-slate-600">
                ran at {new Date(run.data.ran_at).toLocaleString()}
              </p>
            </div>

            <ul className="space-y-3">
              {run.data.results.map((r) => (
                <li
                  key={r.id}
                  className={`rounded-lg border bg-white p-4 ${
                    r.outcome === "pass" ? "border-slate-200" : "border-red-300"
                  }`}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-semibold ${
                        OUTCOME[r.outcome].className
                      }`}
                    >
                      {OUTCOME[r.outcome].label}
                    </span>
                    <span className="font-mono text-sm font-medium">{r.id}</span>
                    <span
                      className={`rounded border px-2 py-0.5 text-xs ${SEVERITY[r.severity]}`}
                    >
                      {r.severity}
                    </span>
                    <span className="text-xs text-slate-400">slice {r.slice_id}</span>
                  </div>

                  <dl className="mt-3 grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[7rem_1fr]">
                    <dt className="text-xs uppercase tracking-wide text-slate-400">
                      Invariant
                    </dt>
                    <dd className="text-slate-700">{r.invariant}</dd>
                    <dt className="text-xs uppercase tracking-wide text-slate-400">Setup</dt>
                    <dd className="text-slate-700">{r.setup}</dd>
                    <dt className="text-xs uppercase tracking-wide text-slate-400">
                      Expected
                    </dt>
                    <dd className="text-slate-700">{r.expected}</dd>
                    <dt className="text-xs uppercase tracking-wide text-slate-400">Actual</dt>
                    <dd
                      className={
                        r.outcome === "pass" ? "text-slate-700" : "font-medium text-red-800"
                      }
                    >
                      {r.actual}
                    </dd>
                  </dl>
                </li>
              ))}
            </ul>

            <p className="mt-8 max-w-3xl text-xs text-slate-400">
              An ERROR row means the scenario itself broke and proved nothing. It is
              never counted as a pass.
            </p>
          </>
        )}
      </main>
    </>
  );
}
