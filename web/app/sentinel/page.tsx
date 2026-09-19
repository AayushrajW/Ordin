/**
 * Ordin Sentinel — every security claim this system makes, tested live.
 *
 * **Every load runs the scenarios.** Nothing is stored or cached (ADR 0015): a
 * dashboard rendering a saved result can show green from an hour ago, and a check that
 * cannot currently fail manufactures confidence.
 *
 * ERROR is its own state. A scenario that raised proved nothing; folding it into "pass"
 * is how a dashboard lies, and into "fail" makes a broken instrument look like a broken
 * system.
 *
 * To show it working: break something on purpose — comment out `_require_original` in
 * `api/documents.py` — and reload. A critical row goes red with the actual result beside
 * the expected one.
 */
import Shell, { PageHeader } from "../components/Shell";
import { IconAlert, IconArrowRight, IconCheck, IconChevron, IconShield, IconX } from "../components/icons";
import { Notice } from "../components/ui";
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

const FAMILY: Record<string, string> = {
  AUTHZ: "Authorization",
  REDACT: "Redaction & disclosure",
  VERIFY: "Human commit",
  AUDIT: "Audit chain",
  INTEG: "Integrity",
  SEC: "Transport & headers",
};

const SEVERITY: Record<Result["severity"], string> = {
  critical: "chip-danger",
  high: "chip-caution",
  medium: "chip-draft",
};

function Ring({ passing, total }: { passing: number; total: number }) {
  const r = 52;
  const c = 2 * Math.PI * r;
  const share = total ? passing / total : 0;
  const clean = passing === total;
  return (
    <div className="relative h-36 w-36">
      <svg viewBox="0 0 120 120" className="h-36 w-36 -rotate-90">
        <circle cx="60" cy="60" r={r} fill="none" stroke="#1E2A47" strokeWidth="9" />
        <circle
          cx="60" cy="60" r={r} fill="none"
          stroke={clean ? "#C89C4B" : "#C2412F"} strokeWidth="9" strokeLinecap="round"
          strokeDasharray={`${c * share} ${c}`}
        />
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center">
        <div>
          <p className="num font-display text-[2.1rem] font-semibold leading-none text-white">
            {passing}<span className="text-lg text-ink-400">/{total}</span>
          </p>
          <p className="mt-1 text-[0.625rem] font-semibold uppercase tracking-eyebrow text-ink-400">holding</p>
        </div>
      </div>
    </div>
  );
}

export default async function SentinelPage() {
  const subject = await currentSubject();
  const run = subject ? await post<Run>("/sentinel/run") : null;

  const results = run && run.ok ? run.data.results : [];
  const families = Object.entries(
    results.reduce<Record<string, Result[]>>((acc, r) => {
      const key = r.id.split("-")[0];
      (acc[key] ??= []).push(r);
      return acc;
    }, {}),
  );
  const failing = results.filter((r) => r.outcome !== "pass");
  const critical = results.filter((r) => r.severity === "critical").length;

  return (
    <Shell subject={subject} returnTo="/sentinel" active="sentinel">
      <PageHeader
        eyebrow="Live security verification"
        title="Sentinel"
        meta="Each row is a claim this system makes, expressed as something that can visibly go red — and run against the live application on every load."
        actions={
          <a href={`/sentinel?t=${Date.now()}`} className="btn-primary">
            <IconShield className="h-4 w-4" /> Run again
          </a>
        }
      />

      <div className="mx-auto max-w-[88rem] space-y-8 px-6 py-8 lg:px-10">
        {!subject || !run ? (
          <Notice tone="signal" title="Choose a specimen identity first">
            Sentinel exercises authorization boundaries, so it is not reachable without a session.
          </Notice>
        ) : !run.ok ? (
          <Notice tone="danger" title="The scenarios did not run">
            {run.reason} The runner is restricted to the development environment (ADR 0015).
          </Notice>
        ) : (
          <>
            <section className="surface-ink relative overflow-hidden">
              <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(70%_120%_at_100%_0%,rgba(200,156,75,0.14),transparent_60%)]" />
              <div className="relative flex flex-wrap items-center gap-8 px-8 py-7">
                <Ring passing={run.data.passing} total={run.data.total} />
                <div className="min-w-0 flex-1">
                  <p className="text-[0.625rem] font-semibold uppercase tracking-eyebrow text-brass-300">
                    {failing.length === 0 ? "All claims holding" : `${failing.length} claim${failing.length === 1 ? "" : "s"} not holding`}
                  </p>
                  <p className="mt-2 font-serif text-[1.9rem] leading-tight text-white">
                    {failing.length === 0
                      ? "Every security claim held against the running system."
                      : "Something this system promises is not currently true."}
                  </p>
                  <p className="mt-3 text-sm text-ink-300">
                    Ran {new Date(run.data.ran_at).toLocaleTimeString("en-IN", { hour12: false })} ·{" "}
                    {critical} critical scenarios · nothing stored, nothing cached
                  </p>
                </div>
                <dl className="grid grid-cols-3 gap-6 text-center">
                  {(["critical", "high", "medium"] as const).map((s) => {
                    const all = results.filter((r) => r.severity === s);
                    const ok = all.filter((r) => r.outcome === "pass").length;
                    return (
                      <div key={s}>
                        <dt className="text-[0.625rem] font-semibold uppercase tracking-eyebrow text-ink-400">{s}</dt>
                        <dd className="num mt-1 font-display text-2xl font-semibold text-white">{ok}<span className="text-sm text-ink-500">/{all.length}</span></dd>
                      </div>
                    );
                  })}
                </dl>
              </div>
            </section>

            {families.map(([family, rows]) => (
              <section key={family}>
                <div className="mb-3 flex items-baseline justify-between">
                  <h2 className="section-title">{FAMILY[family] ?? family}</h2>
                  <p className="text-xs text-ink-400">
                    {rows.filter((r) => r.outcome === "pass").length} of {rows.length} holding
                  </p>
                </div>
                <ul className="surface divide-y divide-paper-200 overflow-hidden">
                  {rows.map((r) => (
                    <li key={r.id}>
                      <details className="group" open={r.outcome !== "pass"}>
                        <summary className="flex cursor-pointer items-center gap-4 px-5 py-3.5 transition hover:bg-paper-50">
                          <span className={`grid h-7 w-7 shrink-0 place-items-center rounded-full ${
                            r.outcome === "pass" ? "bg-verified-50 text-verified-600 ring-1 ring-verified-100"
                              : r.outcome === "fail" ? "bg-danger-50 text-danger-600 ring-1 ring-danger-100"
                                : "bg-caution-50 text-caution-600 ring-1 ring-caution-100"}`}>
                            {r.outcome === "pass" ? <IconCheck className="h-3.5 w-3.5" /> : r.outcome === "fail" ? <IconX className="h-3.5 w-3.5" /> : <IconAlert className="h-3.5 w-3.5" />}
                          </span>
                          <span className="mono w-24 shrink-0 font-semibold text-ink-800">{r.id}</span>
                          <span className="min-w-0 flex-1 truncate text-[0.8125rem] text-ink-700">{r.invariant}</span>
                          <span className={SEVERITY[r.severity]}>{r.severity}</span>
                          <IconChevron className="h-4 w-4 text-ink-300 transition group-open:rotate-90" />
                        </summary>
                        <div className="grid gap-4 border-t border-paper-200 bg-paper-50/60 px-5 py-4 md:grid-cols-3">
                          <div>
                            <p className="eyebrow">Setup</p>
                            <p className="mt-1 text-[0.8125rem] leading-relaxed text-ink-700">{r.setup}</p>
                          </div>
                          <div>
                            <p className="eyebrow">Expected</p>
                            <p className="mt-1 text-[0.8125rem] leading-relaxed text-ink-700">{r.expected}</p>
                          </div>
                          <div>
                            <p className="eyebrow flex items-center gap-1">Actual <IconArrowRight className="h-3 w-3" /></p>
                            <p className={`mt-1 text-[0.8125rem] font-medium leading-relaxed ${r.outcome === "pass" ? "text-verified-700" : "text-danger-700"}`}>
                              {r.actual}
                            </p>
                          </div>
                        </div>
                      </details>
                    </li>
                  ))}
                </ul>
              </section>
            ))}

            <p className="text-xs text-ink-400">
              An error row means the scenario itself broke and proved nothing; it is never
              counted as a pass. Green means these specific claims held just now — not that
              the system is secure. The accepted risks in the threat model are not covered here.
            </p>
          </>
        )}
      </div>
    </Shell>
  );
}
