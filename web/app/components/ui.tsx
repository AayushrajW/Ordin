/**
 * Small presentational pieces shared by the screens. Server components, no state.
 */
import { IconAlert, IconCheck, IconClock, IconLock, IconX } from "./icons";

/** Generic procedural stages — placeholders pending a statutory citation (ADR 0008). */
export const STATES = [
  { key: "registered", label: "Registered" },
  { key: "under_investigation", label: "Investigation" },
  { key: "filed", label: "Filed" },
  { key: "in_trial", label: "Trial" },
  { key: "closed", label: "Closed" },
] as const;

export function stateLabel(key: string): string {
  return STATES.find((s) => s.key === key)?.label ?? key.replace(/_/g, " ");
}

export function StateRail({ state, compact = false }: { state: string; compact?: boolean }) {
  const index = STATES.findIndex((s) => s.key === state);
  return (
    <ol className={`flex items-center ${compact ? "gap-1" : "gap-1.5"}`} aria-label={`Stage: ${stateLabel(state)}`}>
      {STATES.map((s, i) => {
        const done = i < index;
        const here = i === index;
        return (
          <li key={s.key} className="flex items-center gap-1.5">
            <span
              title={s.label}
              className={`block rounded-full transition ${compact ? "h-1.5 w-6" : "h-1.5 w-10"} ${
                here ? "bg-brass-400" : done ? "bg-ink-700" : "bg-paper-300"
              }`}
            />
          </li>
        );
      })}
      {!compact && (
        <li className="ml-2 text-xs font-medium text-ink-600">{stateLabel(state)}</li>
      )}
    </ol>
  );
}

export function SealedTag() {
  return (
    <span className="chip-danger">
      <IconLock className="h-3 w-3" /> Sealed
    </span>
  );
}

export function relative(iso: string | null, now = Date.now()): string {
  if (!iso) return "";
  const ms = new Date(iso).getTime() - now;
  const future = ms > 0;
  const mins = Math.round(Math.abs(ms) / 60000);
  const text =
    mins < 1 ? "moments" : mins < 60 ? `${mins} min` : mins < 60 * 48 ? `${Math.round(mins / 60)} h` : `${Math.round(mins / 1440)} days`;
  return future ? `in ${text}` : `${text} ago`;
}

export function when(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false,
    timeZone: "UTC",
  }) + " UTC";
}

export function Stat({
  label, value, hint, tone = "ink",
}: { label: string; value: React.ReactNode; hint?: React.ReactNode; tone?: "ink" | "brass" | "caution" | "verified" }) {
  const accent = {
    ink: "text-ink-900",
    brass: "text-brass-600",
    caution: "text-caution-600",
    verified: "text-verified-600",
  }[tone];
  return (
    <div className="surface px-5 py-4">
      <p className="eyebrow">{label}</p>
      <p className={`num mt-2 font-display text-[1.9rem] font-semibold leading-none tracking-tight ${accent}`}>{value}</p>
      {hint && <p className="mt-2 text-xs text-ink-400">{hint}</p>}
    </div>
  );
}

export function Notice({
  tone, title, children,
}: { tone: "danger" | "caution" | "verified" | "signal"; title: string; children?: React.ReactNode }) {
  const styles = {
    danger: "border-danger-100 bg-danger-50 text-danger-700",
    caution: "border-caution-100 bg-caution-50 text-caution-700",
    verified: "border-verified-100 bg-verified-50 text-verified-700",
    signal: "border-signal-100 bg-signal-50 text-signal-700",
  }[tone];
  const icon = { danger: <IconX />, caution: <IconAlert />, verified: <IconCheck />, signal: <IconClock /> }[tone];
  return (
    <div role={tone === "danger" ? "alert" : "status"} className={`flex gap-3 rounded-xl border px-4 py-3 text-sm ${styles}`}>
      <span className="mt-0.5 shrink-0">{icon}</span>
      <div>
        <p className="font-semibold">{title}</p>
        {children && <div className="mt-0.5 text-[0.8125rem] opacity-90">{children}</div>}
      </div>
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="surface-quiet grid place-items-center px-6 py-14 text-center">
      <div className="mx-auto max-w-md">
        <div className="mx-auto mb-4 h-10 w-10 rounded-full border border-dashed border-paper-400" />
        <p className="section-title">{title}</p>
        {children && <div className="mt-2 text-sm text-ink-500">{children}</div>}
      </div>
    </div>
  );
}

/** A thin confidence bar. Tone follows the threshold the consistency engine uses. */
export function Confidence({ value, label = "OCR" }: { value: number | null; label?: string }) {
  if (value === null) {
    return <span className="text-[0.6875rem] text-ink-400">{label} n/a</span>;
  }
  const pct = Math.round(value * 100);
  const tone = value >= 0.9 ? "bg-verified-500" : value >= 0.8 ? "bg-brass-400" : "bg-danger-500";
  return (
    <span className="inline-flex items-center gap-2" title={`${label} confidence ${pct}%`}>
      <span className="h-1 w-14 overflow-hidden rounded-full bg-paper-200">
        <span className={`block h-full ${tone}`} style={{ width: `${pct}%` }} />
      </span>
      <span className="num text-[0.6875rem] text-ink-500">{label} {pct}%</span>
    </span>
  );
}
