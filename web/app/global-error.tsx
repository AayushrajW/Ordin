"use client";

/**
 * The last boundary: a failure in the root layout itself, which `error.tsx` sits inside
 * and therefore cannot catch.
 *
 * It has to render its own `<html>` and `<body>` because the layout that normally
 * provides them is the thing that failed, and it cannot import `globals.css` through a
 * layout that is not running — so the few styles it needs are inline. This screen should
 * never be seen; it exists so that when it is, it is still a page and not a blank
 * document.
 *
 * Same rule as `error.tsx`: the digest, never the message.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          background: "#FAF9F7",
          color: "#1C1B19",
          fontFamily: "ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif",
          padding: "1.5rem",
        }}
      >
        <main style={{ maxWidth: "32rem", textAlign: "center" }}>
          <h1 style={{ fontSize: "1.0625rem", fontWeight: 600, margin: 0 }}>
            Ordin could not start this page
          </h1>
          <p style={{ marginTop: "0.75rem", fontSize: "0.875rem", lineHeight: 1.6, color: "#6B6862" }}>
            The application shell itself failed. Nothing was written and no record was
            changed. The cause is in the server log.
          </p>
          {error.digest && (
            <p
              style={{
                marginTop: "1rem",
                fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                fontSize: "0.6875rem",
                color: "#6B6862",
                background: "#F2F0EC",
                borderRadius: "0.5rem",
                padding: "0.5rem 0.75rem",
              }}
            >
              reference {error.digest}
            </p>
          )}
          <button
            type="button"
            onClick={reset}
            style={{
              marginTop: "1.5rem",
              cursor: "pointer",
              borderRadius: "9999px",
              border: 0,
              background: "#1C1B19",
              color: "#fff",
              padding: "0.5rem 1.25rem",
              fontSize: "0.8125rem",
              fontWeight: 600,
            }}
          >
            Try again
          </button>
        </main>
      </body>
    </html>
  );
}
