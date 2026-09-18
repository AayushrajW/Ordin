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
              "script-src 'self' 'unsafe-inline'",
              "style-src 'self' 'unsafe-inline'",
              "img-src 'self' data:",
              `connect-src 'self' ${process.env.ORDIN_API_ORIGIN ?? "http://127.0.0.1:8000"}`,
              "font-src 'self'",
              "frame-ancestors 'none'",
            ].join("; "),
          },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
        ],
      },
    ];
  },
};

export default nextConfig;
