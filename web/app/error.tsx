"use client";

/**
 * The boundary every route was missing.
 *
 * Without an `error.tsx`, an exception thrown while rendering a server component falls
 * through to Next's own handler: a stack trace in development, and in production a
 * generic page this project never wrote, reviewed, or checked for what it says.
 *
 * **The message is deliberately not rendered.** `error.message` on a server-side failure
 * is whatever threw — a SQLAlchemy exception carrying a statement and its bound
 * parameters, an httpx error naming the internal API origin, a driver message quoting a
 * row. Invariant 12 forbids putting document content or identifiers in front of a
 * reader, and a case reference is exactly the sort of thing that reaches a browser this
 * way. Next already logs the real error server-side; the `digest` is the handle that
 * ties this screen to that log line without carrying anything with it.
 *
 * A boundary that hides the cause from the operator would be its own failure, so the
 * digest is shown. It is a hash, not a message.
 */
export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="grid min-h-screen place-items-center bg-paper px-6">
      <div className="surface mx-auto w-full max-w-lg px-6 py-8 text-center">
        <div
          aria-hidden
          className="mx-auto mb-4 grid h-10 w-10 place-items-center rounded-full border border-danger-200 bg-danger-50 text-danger-600"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5">
            <path d="M12 9v4M12 17h.01" strokeLinecap="round" />
            <circle cx="12" cy="12" r="9" />
          </svg>
        </div>
        <h1 className="section-title">This screen could not be built</h1>
        <p className="mt-2 text-sm leading-relaxed text-ink-500">
          Something failed while assembling the page. Nothing was written, and no record
          was changed. The cause is in the server log; the reference below identifies it.
        </p>
        {error.digest && (
          <p className="mono mt-4 rounded-lg bg-paper-100 px-3 py-2 text-[0.6875rem] text-ink-500">
            reference {error.digest}
          </p>
        )}
        <div className="mt-6 flex items-center justify-center gap-3">
          <button type="button" onClick={reset} className="btn-primary">
            Try again
          </button>
          <a href="/" className="btn-quiet">
            Back to case files
          </a>
        </div>
      </div>
    </div>
  );
}
