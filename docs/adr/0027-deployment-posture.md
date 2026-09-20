# 0027 — Deployment refuses to start on development configuration

## Context
Every configuration mistake that matters here produces a system which **starts, serves
traffic and looks entirely correct**. A placeholder session secret does not cause an
error; it signs tokens perfectly well. That is precisely what makes it dangerous, and
why a warning in a log is not a control.

`ORDIN_SESSION_SECRET` is the sharpest of them. Every access decision is resolved from
the token it signs, so a known value is not a weak password — it is the ability to mint
a session as any account, including an administrative one, without touching the
database (threat SESS-01).

## Decision

**`Settings.refuse_unsafe_production` raises**, and `create_app` calls it before
anything else, so no code path constructs a production application without passing it.
It checks the session secret (unset, template, or under 32 characters) and both database
passwords, and reports **every** problem at once — one restart per mistake is how a
deployment takes an afternoon.

**Anything that is not `dev`, `development` or `test` is production.** Failing closed on
the environment name too: treating only the literal `production` as production would
leave a deployment named `staging` or `pilot` running on development defaults.

**The overlay, not a second compose file.** `docker-compose.prod.yml` changes five
things against one description of the system: `ORDIN_ENV=production`; the api and the
database publish **no ports at all**; read-only root filesystems with all capabilities
dropped and `no-new-privileges` (narrowing AR-11); `restart: always`, because
`unless-stopped` does not survive a host reboot; and log rotation, because the first
thing that fails when a disk fills is postgres.

**Backups are scripts that run, not a sentence.** `scripts/backup.sh` dumps the database
and then archives the blob volume — **in that order**, because a blob store newer than
its database holds bytes nothing references, while a database newer than its blobs
claims evidence it cannot produce. `restore.sh` reverses the order and refuses without
an explicit confirmation variable.

**A cloud blueprint exists and states its own limits.** `render.yaml` covers all four
services; the worker is a paid instance type, free web services sleep, the image is
large, and a hosted instance contradicts this product's own "nothing leaves this
machine". All four are in the file and in `docs/DEPLOYMENT.md`, because a reviewer
should not have to infer that the cloud version is not the real one.

## Consequences
- The guard is tested by asserting it **refuses**, including that its message names
  every problem and echoes none of the values it is complaining about.
- The web tier binds to loopback over plain HTTP and requires a reverse proxy for TLS.
  This is load-bearing rather than advisory: the session cookie carries `Secure` outside
  dev, so over plain HTTP the browser will not send it and nothing works at all. The
  failure is loud, which is the right way round.
- `docs/DEPLOYMENT.md` has a section for what deployment does **not** cover — secret
  management, high availability, monitoring, malware scanning, an independent witness —
  so that the absence of each is a recorded decision rather than an assumption.
- AR-18 ("no backups and no restore verification") is half closed. The second half only
  becomes untrue once somebody runs `restore.sh`, and the script says so in its own
  output rather than leaving that to the documentation.
