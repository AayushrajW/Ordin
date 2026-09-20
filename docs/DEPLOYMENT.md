# Deploying Ordin

Two targets, because they answer different questions.

**On-premise** is the real one. A police or prosecution deployment does not put case
evidence on somebody else's computer, and every design decision in this project — no
external network on the demo path, OCR that runs locally, an anchor store rather than a
ledger — assumes a machine the agency controls.

**A cloud host** exists so there is a link a judge can open. Its limits are stated
below rather than discovered.

---

## Before either: the four things that must be true

### 1. Generate the session secret

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

This signs the session token from which **every access decision is resolved**. A known
value is not a weak password: it mints a session as any account, including an
administrative one, without touching the database (threat SESS-01).

`Settings.refuse_unsafe_production` refuses to start when `ORDIN_ENV` is not `dev` and
this is unset, shorter than 32 characters, or still the template value. It raises rather
than warns, because a deployment running on a placeholder **starts, serves traffic and
looks correct**.

### 2. Generate the database passwords

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"   # twice
```

`POSTGRES_OWNER_PASSWORD` owns the schema and runs Alembic. `ORDIN_APP_PASSWORD` is the
restricted role the application connects as, which owns nothing — that separation is
what makes the audit table's `REVOKE` binding, because **a table owner is not subject to
`REVOKE` on its own table** (ADR 0001). Collapsing them to one role makes invariant 10
void and green at the same time.

### 3. Put them in the environment, not in a file in the repository

`.env` is gitignored, and `.env.example` carries no values. On a server, prefer the
environment your process manager provides. If you must use a file, `chmod 600` it and
keep it outside the checkout.

### 4. Create the first administrator

```bash
python tasks.py admin --email you@agency.gov.in --password '<at least 12 characters>'
```

The screen that creates administrators requires an administrator; this closes that
circle from the command line, by somebody who already has shell access.

---

## On-premise

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

The overlay changes five things, each for a stated reason — read the comments in
`docker-compose.prod.yml`, they are the documentation. In summary:

- `ORDIN_ENV=production`, so the config guard binds and the credential-free **specimen
  switcher 404s**. In a deployment it would be a complete authentication bypass sitting
  next to a working authentication system.
- **The api and the database publish no ports at all.** Only the web tier is published,
  and only to loopback.
- `read_only` root filesystems, `no-new-privileges`, all capabilities dropped. This
  narrows accepted risk AR-11.
- `restart: always`, because `unless-stopped` does not survive a host reboot.
- Log rotation, because the first thing that fails when a disk fills is postgres.

Migrations run on boot: the api's command is `alembic upgrade head` followed by uvicorn,
so a container that starts has a schema at head or does not start.

### Put a reverse proxy in front

The web tier binds to `127.0.0.1:3001` over plain HTTP. **Do not publish that.** A
session cookie sent over plain HTTP is a session anyone on the path can take, and the
cookie's `Secure` flag is set automatically outside dev — which means over plain HTTP the
browser will not send it at all, and nothing works. TLS is not optional here; it is
load-bearing.

Caddy is the shortest correct answer:

```
ordin.example.gov.in {
    reverse_proxy 127.0.0.1:3001
}
```

That obtains and renews a certificate by itself. nginx with certbot is equally fine.

### Verify it

```bash
curl -sf https://your-host/health | python -m json.tool     # three checks up
python tasks.py sentinel                                     # 21 scenarios, live
```

Then sign in and confirm the specimen switcher is gone: `https://your-host/specimen`
must redirect to the login page, and `POST /session` at the API must 404.

---

## Backups

`docker compose down -v` destroys the database **and** the blob store. There is no undo
and no second copy. AR-18 recorded the absence of backups as accepted; this is the
minimum that stops being true.

```bash
./scripts/backup.sh /var/backups/ordin
```

It dumps Postgres and tars the blob volume **in that order**, into one timestamped
directory, because a blob store newer than its database is recoverable and a database
newer than its blobs references bytes that do not exist.

**Run the restore once, before you need it.** A backup nobody has restored is a belief,
not a backup:

```bash
./scripts/restore.sh /var/backups/ordin/2026-09-20T14-00-00
```

---

## A cloud host, and its limits

`render.yaml` is a Render blueprint covering all four services. It will work, and three
things about it are worth knowing before you rely on it for a demo.

**The worker cannot be free.** Render background workers are a paid instance type, and
the worker is what runs OCR, extraction, signing and anchoring. Without it, an upload is
accepted, queued, and never processed — the document sits there with no fields. That is
the honest failure, not a hidden one, but it will look broken to somebody who does not
know.

**Free web services sleep.** After inactivity the instance spins down, and the next
request waits for a cold start. On an image carrying Tesseract and its language data
that is tens of seconds. For a judge clicking a link at an unknown moment, that is the
difference between a working demo and a blank tab.

**The image is large.** Tesseract with `hin+eng` plus PyMuPDF is several hundred
megabytes. Build times are minutes, not seconds.

**And the thesis argues against it.** "No cloud, no model, no telemetry — OCR,
extraction and verification run offline" is on the front page of this product. A hosted
instance is a convenience for review, not the deployment story. Say that out loud rather
than letting someone infer that the cloud version is the real one.

---

## What this does not cover

Stated here rather than left for someone to assume.

- **Secret management.** Environment variables, not a vault. Rotating the session secret
  invalidates every live session, which is correct behaviour and needs saying.
- **High availability.** One of everything. A restart is an outage.
- **Monitoring and alerting.** `/health` is a truthful endpoint; nothing watches it.
- **Malware scanning** remains a named stub (AR-12). Ordin proves the bytes are the bytes
  that arrived — an authenticity claim, never a safety claim.
- **An independent witness** for the anchor chain (AR-4). The party asserting integrity
  still controls every input to the assertion.
