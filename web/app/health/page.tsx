/**
 * System health page.
 *
 * This tier **renders and enforces nothing**. Every authorization decision belongs
 * at the API, inside the data query (invariants 1 and 3). Gating anything here would
 * be gating that an attacker skips by calling the API directly (threat EXT-06), and
 * slice 1b is where that habit is set.
 *
 * It also does not surface a raw error body. `/health` restricts itself to an
 * enumerated set of reasons precisely so nothing carrying a DSN or a driver message
 * can reach a screen (invariant 12); re-introducing that here by rendering a caught
 * exception would undo it.
 */
import IdentityBar from "../components/IdentityBar";
import { currentSubject } from "../lib/api";

export const dynamic = "force-dynamic";

const API_ORIGIN = process.env.ORDIN_API_ORIGIN ?? "http://127.0.0.1:8000";

type Check = {
  name: string;
  status: "up" | "down";
  latency_ms: number | null;
  reason: string | null;
};

type HealthReport = {
  status: "healthy" | "unhealthy";
  version: string;
  checks: Check[];
};

async function fetchHealth(): Promise<HealthReport | null> {
  try {
    const response = await fetch(`${API_ORIGIN}/health`, { cache: "no-store" });
    // 503 is an expected, meaningful response here, not a transport failure.
    return (await response.json()) as HealthReport;
  } catch {
    // Deliberately no error detail: see the file docstring.
    return null;
  }
}

function StatusPill({ up }: { up: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${
        up ? "bg-emerald-100 text-emerald-800" : "bg-red-100 text-red-800"
      }`}
    >
      <span
        aria-hidden
        className={`h-1.5 w-1.5 rounded-full ${up ? "bg-emerald-600" : "bg-red-600"}`}
      />
      {up ? "up" : "down"}
    </span>
  );
}

export default async function HealthPage() {
  const report = await fetchHealth();
  const healthy = report?.status === "healthy";
  const subject = await currentSubject();

  return (
    <>
    <IdentityBar current={subject} returnTo="/health" />
    <main className="mx-auto max-w-2xl px-6 py-16">
      <header className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">Ordin</h1>
        <p className="mt-1 text-sm text-slate-500">
          Case-centric evidence intelligence · system health
        </p>
      </header>

      <section
        className={`rounded-lg border p-5 ${
          healthy ? "border-emerald-200 bg-emerald-50" : "border-red-200 bg-red-50"
        }`}
      >
        <div className="flex items-baseline justify-between">
          <h2 className="text-base font-medium">
            {report === null
              ? "API unreachable"
              : healthy
                ? "All dependencies healthy"
                : "Degraded"}
          </h2>
          {report && (
            <span className="text-xs text-slate-500">v{report.version}</span>
          )}
        </div>

        {report === null ? (
          <p className="mt-3 text-sm text-slate-600">
            No response from the API at {API_ORIGIN}. Start it with{" "}
            <code className="rounded bg-white px-1 py-0.5 text-xs">
              python tasks.py up
            </code>
            .
          </p>
        ) : (
          <ul className="mt-4 divide-y divide-slate-200/70">
            {report.checks.map((check) => (
              <li
                key={check.name}
                className="flex items-center justify-between py-2.5"
              >
                <span className="font-mono text-sm">{check.name}</span>
                <span className="flex items-center gap-3">
                  {check.status === "up" && check.latency_ms !== null && (
                    <span className="text-xs tabular-nums text-slate-500">
                      {check.latency_ms} ms
                    </span>
                  )}
                  {check.reason && (
                    <span className="text-xs text-slate-500">{check.reason}</span>
                  )}
                  <StatusPill up={check.status === "up"} />
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <p className="mt-6 text-xs text-slate-400">
        This page renders health only. It enforces no authorization — every access
        decision is made at the API, inside the data query.
      </p>
    </main>
    </>
  );
}
