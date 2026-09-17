# 0006 — Postgres containerised, application processes native

## Context
CLAUDE.md specifies four containers from `docker compose up`, and that remains the
shipped and demonstrated shape. The build machine is also the demo machine: one
Windows 11 Home laptop with 7.8 GB of RAM, of which roughly 500 MB is typically
available.

Docker Desktop on Windows Home runs the Linux engine inside WSL2, and WSL2's default
memory ceiling is half of host RAM — about 3.9 GB here. Running all four containers
plus a Next.js dev server on this box means the OOM killer choosing a victim by size,
and that victim is Postgres: the audit chain, the job queue and the case record all
live there (threat OPS-03). The demo does not degrade, it disappears.

Deferring containers entirely was the alternative, and it fails differently: the
riskiest integration lands at the worst possible moment.

## Decision
**Dev loop is hybrid.** Postgres runs in Docker (one container, `mem_limit: 256m`,
bound to `127.0.0.1`). The api, worker and web run as native host processes for fast
reload and lower memory.

**`docker-compose.yml` defines all four services regardless**, each with an explicit
`mem_limit`, and `~/.wslconfig` caps the WSL2 VM at 2 GB since only Postgres needs it.

The integration risk is **scheduled, not deferred**: the full four-container compose
path is verified once before slice 3 begins, and again at the hour-30 hard stop.

Slice 1's acceptance test is therefore two paths — `dev` (native, must pass every
session) and `compose` (all four containers within 8 GB, verified at those two gates).

## Measured afterwards — the memory premise was wrong

`tasks.py verify-compose` at the end of slice 1b reports **203 MiB total** across all
four containers at idle:

    ordin-web 36.6  ·  ordin-worker 53.3  ·  ordin-api 78.7  ·  ordin-postgres 34.9

Against a fear of ~1.15 GB. The estimate above was a sum of the `mem_limit` *ceilings*,
not of actual consumption, and the gap is an order of magnitude. **Four containers fit
on this machine comfortably**, so "they will not fit" is not a reason to keep the hybrid
loop, and this ADR should not be cited as if it were.

What survives is the weaker and still-true reason: `next dev` gives sub-second reload and
`next start` does not, so the inner loop is faster natively. That is a developer-ergonomics
decision, not a capacity one, and it should be revisited the moment it costs anything.

The number is idle. The worker is 53 MiB with nothing to do; slice 5a gives it Tesseract
over 300 DPI scans, where a decoded A4 page alone is ~25 MB and working set runs several
hundred MB above baseline. Re-measure then rather than carrying 203 MiB forward as if it
were a steady state.

## Consequences
- The inner loop is fast and fits in available memory. Slice 1a measures ~400 MB.
- Dev and demo diverge by construction, which is exactly what the two-path acceptance
  test exists to catch. The gates are load-bearing: skip them and this ADR becomes the
  "develop natively, containerise later" trap it was written to avoid.
- Native Python is pinned to 3.11 to match the api image; see ADR 0007.
- If the compose path fails at the pre-slice-3 gate, that is a slice 1b bug found at
  the cheapest moment available, not a new problem.
