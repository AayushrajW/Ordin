/**
 * Ordin web configuration.
 *
 * Security invariant 11: no external network calls on the demo path.
 *
 * Next.js does two things by default that break this, both silently:
 *   - anonymous telemetry, posted to a Vercel endpoint at build and run time
 *   - `next/font/google`, which fetches from Google's CDN at build time
 *
 * Telemetry is NOT configurable from this file. There is no `telemetry` key — Next
 * rejects it as unrecognised and carries on posting, which is the worst kind of
 * fix: one that looks applied and is not. The only portable control is the
 * environment variable NEXT_TELEMETRY_DISABLED=1, which is set in tasks.py for the
 * dev path and in docker/web.Dockerfile plus docker-compose.yml for the demo path.
 * `tasks.py verify-compose` asserts it, because this is precisely the kind of
 * setting that silently regresses.
 *
 * The font helper is simply never imported — see app/layout.tsx, which uses a
 * system font stack. At an air-gapped venue either one fails visibly, in front of
 * a judge, at the worst possible moment.
 *
 * `output: "standalone"` is what lets the container run `next start` on a ~150 MB
 * footprint instead of `next dev` on ~800 MB (ADR 0006).
 */
/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,

  // Next 16 writes CLAUDE.md and AGENTS.md into this directory on first dev run.
  // Unasked-for files are bad enough; a CLAUDE.md under web/ would also shadow the
  // project's own instructions for anyone working in this tier.
  agentRules: false,

  // The dev server is reached at 127.0.0.1 as well as localhost on this machine.
  // Development only: it has no effect on `next start`, which the demo path runs.
  allowedDevOrigins: ["127.0.0.1", "localhost"],

  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          // The page renders whatever /health returns and nothing else. No
          // external origins are needed, so none are permitted.
          {
            key: "Content-Security-Policy",
            value: [
              "default-src 'self'",
              // React's development build uses eval() to reconstruct call stacks; the
              // production build never does. Granting it in dev only keeps the policy
              // the demo path (`next start`) ships with strict.
              `script-src 'self' 'unsafe-inline'${process.env.NODE_ENV === "development" ? " 'unsafe-eval'" : ""}`,
              "style-src 'self' 'unsafe-inline'",
              "img-src 'self' data:",
              // The dev server's hot-reload socket needs `ws:` named explicitly; without
              // it the connection is refused and live reload silently stops working
              // while the console fills with failures. `next start` has no such socket,
              // so the demo path keeps the tighter policy.
              `connect-src 'self' ${process.env.ORDIN_API_ORIGIN ?? "http://127.0.0.1:8000"}` +
                (process.env.NODE_ENV === "development"
                  ? " ws://127.0.0.1:* ws://localhost:*"
                  : ""),
              "font-src 'self'",
              "frame-ancestors 'none'",
            ].join("; "),
          },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
          // frame-ancestors above covers modern browsers; this covers the rest.
          { key: "X-Frame-Options", value: "DENY" },
          // A window this app opens cannot reach back into it, and it cannot be
          // reached from one it did not open.
          { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
          { key: "Cross-Origin-Resource-Policy", value: "same-origin" },
          // Nothing here needs a camera, microphone, location or payment API, so
          // nothing injected into a page can ask for one either.
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()",
          },
          // Every page is the product of an authorization decision for one session.
          { key: "Cache-Control", value: "no-store, private" },
        ],
      },
    ];
  },
};

export default nextConfig;
