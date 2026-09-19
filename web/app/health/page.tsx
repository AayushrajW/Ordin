/**
 * System health.
 *
 * Renders `/health` and nothing else, and surfaces no raw error body: `/health`
 * restricts itself to enumerated reasons so nothing carrying a DSN or a driver message
 * reaches a screen (invariant 12). `tasks.py verify-compose` reads this page for the
 * phrase "All dependencies healthy", so that wording is load-bearing.
 */
import Shell, { PageHeader } from "../components/Shell";
import { IconCheck, IconPulse, IconX } from "../components/icons";
import { currentSubject } from "../lib/api";

export const dynamic = "force-dynamic";

const API_ORIGIN = process.env.ORDIN_API_ORIGIN ?? "http://127.0.0.1:8000";

type Check = { name: string; status: "up" | "down"; latency_ms: number | null; reason: string | null };
type HealthReport = { status: "healthy" | "unhealthy"; version: string; checks: Check[] };

const DESCRIBE: Record<string, string> = {
  database: "Postgres reachable as the application role, which owns nothing",
  migrations: "Schema at the head revision this checkout defines",
  worker: "Worker heartbeat fresh — the process running OCR and the intake queue",
};

async function fetchHealth(): Promise<HealthReport | null> {
  try {
    const response = await fetch(`${API_ORIGIN}/health`, { cache: "no-store" });
    // 503 is a meaningful answer here, not a transport failure.
    return (await response.json()) as HealthReport;
  } catch {
    return null; // Deliberately no detail: see the file docstring.
  }
}

export default async function HealthPage() {
  const [report, subject] = await Promise.all([fetchHealth(), currentSubject()]);
  const healthy = report?.status === "healthy";

  const briefing = report === null
    ? "System health. The API is unreachable."
    : `System health. ${healthy ? "All dependencies healthy" : "Degraded"}. ` +
      report.checks.map((c) => `${c.name} is ${c.status}`).join(", ") + ".";

  return (
    <Shell subject={subject} returnTo="/health" active="health" voice={{ briefing }}>
      <PageHeader eyebrow="Operations" title="System health"
                  meta="Four containers on one machine, no network egress. This page renders health only and enforces nothing." />
      <div className="mx-auto max-w-3xl space-y-6 px-6 py-8 lg:px-10">
        <section className={`relative overflow-hidden rounded-2xl border px-7 py-6 ${
          healthy ? "border-verified-100 bg-gradient-to-br from-verified-50 to-white" : "border-danger-100 bg-gradient-to-br from-danger-50 to-white"}`}>
          <div className="flex items-center gap-4">
            <span className={`grid h-12 w-12 place-items-center rounded-full ${healthy ? "bg-verified-500 text-white animate-pulse-ring" : "bg-danger-500 text-white"}`}>
              {healthy ? <IconCheck className="h-6 w-6" /> : <IconX className="h-6 w-6" />}
            </span>
            <div>
              <p className="font-display text-xl font-semibold text-ink-900">
                {report === null ? "API unreachable" : healthy ? "All dependencies healthy" : "Degraded"}
              </p>
              <p className="text-sm text-ink-500">
                {report ? `Ordin API v${report.version}` : <>Start it with <span className="kbd">python tasks.py up</span></>}
              </p>
            </div>
          </div>
        </section>

        {report && (
          <ul className="surface divide-y divide-paper-200 overflow-hidden">
            {report.checks.map((check) => (
              <li key={check.name} className="flex items-center gap-4 px-5 py-4">
                <span className={`grid h-9 w-9 place-items-center rounded-lg ${check.status === "up" ? "bg-verified-50 text-verified-600" : "bg-danger-50 text-danger-600"}`}>
                  <IconPulse className="h-4 w-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="mono font-semibold text-ink-900">{check.name}</p>
                  <p className="text-xs text-ink-500">{DESCRIBE[check.name] ?? ""}</p>
                </div>
                {check.status === "up" && check.latency_ms !== null && (
                  <span className="num text-xs text-ink-400">{check.latency_ms} ms</span>
                )}
                {check.reason && <span className="text-xs text-danger-600">{check.reason}</span>}
                <span className={check.status === "up" ? "chip-verified" : "chip-danger"}>
                  <span className={`dot ${check.status === "up" ? "bg-verified-500" : "bg-danger-500"}`} />
                  {check.status}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Shell>
  );
}
