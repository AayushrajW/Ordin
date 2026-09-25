# Moving Ordin to another machine

Written for the case where the demo has to run somewhere it has never run before —
a second laptop, a borrowed machine at a venue, a fresh Windows install the night
before.

Everything the system needs is either in the repository or generated on arrival.
**Nothing is carried across.** That is deliberate, and the two things people try to
carry are the two that break.

---

## What does NOT come with you

**`.env` is gitignored and must not be copied.** It holds this machine's master key,
its session secret and its database passwords. Copying it moves a secret onto a second
machine over whatever channel you used, and it points the new machine at a key whose
blobs are not there. `python tasks.py setup` writes a fresh one.

**`var/` does not come.** It is the content-addressed blob store, and it is encrypted
with the master key in the `.env` you just did not copy. Without that key every file in
it is unreadable — ADR 0028 is blunt: lose the key and there is no recovery. The new
machine generates its own key and its own documents.

**`fixtures/corpus/` does not come.** The synthetic documents are deterministic, so
they are generated rather than carried (`python tasks.py fixtures`, and `setup` does it
for you). There is a test asserting they generate identically.

**`node_modules/`, `.venv/` and `web/.next/` do not come.** Platform-specific builds.

So: `git clone`, then setup. Not a folder copy. A folder copy brings the first three
things across and each of them fails differently — the last one silently.

---

## Prerequisites, in the order they bite

| | Why it is needed | Without it |
|---|---|---|
| **Docker Desktop** | Postgres runs in a container | Nothing starts at all |
| **Python 3.11** | matches the api image (ADR 0007) | Setup warns and uses what it finds; the dev and demo paths then diverge, which is the thing ADR 0006's two-path test exists to catch |
| **Tesseract 5**, `eng` + `hin` | OCR | OCR stages fail **by design** rather than falling back (ADR 0012). The rest of the system works |
| **Node 20+** | the web tier | The API and Sentinel still run; there is just no UI |

`python tasks.py setup` checks all four and names whichever is missing. It is written to
work on a machine where nothing is set up yet — that is the situation it is for.

---

## The sequence

```bash
git clone <your remote> ordin && cd ordin
python tasks.py setup      # venv, dependencies, .env with a fresh key, fixtures
python tasks.py up         # postgres in docker; api, worker and web natively
python tasks.py migrate    # schema
python tasks.py demo       # seed, then documents through the real pipeline
python tasks.py admin      # the administrator, from the values setup wrote
python tasks.py doctor     # says what is still wrong, and what to do about it
python tasks.py sentinel   # the security claims, red or green
```

Then open **http://127.0.0.1:3001**.

**Run `demo` before anything that matters.** A correct-but-empty case list demonstrates
nothing, and `demo` is what puts real documents through the real pipeline rather than
inserting rows that look like output.

**Run `setup` before `demo`, not after.** Setup generates the master key, and switching
encryption on does not re-encrypt blobs already written (ADR 0028). A store built before
the key existed stays in plaintext for ever, and nothing in the application looks wrong —
Sentinel CRYPT-03 is the only thing that notices.

---

## What setup puts in `.env`, and what it does not

**A freshly generated `ORDIN_MASTER_KEY`.** Per machine, never shipped: a key in the
repository would be a committed secret shared by everyone who ever cloned it, which
would make "encrypted at rest" true of the file format and false of the system. Without
a key, blobs are written in plaintext and Sentinel CRYPT-01/02/03 report red — correctly,
which is why setup generates one rather than leaving a new machine to open on three red
criticals for a feature that works.

**Loopback database passwords**, named `dev_owner_pw_local_only` and so on, so nobody
finding one in a running system has to wonder whether it is real.

**The demo administrator**, `admin@gmail.com` / `admin`, because the sign-in hint on the
login screen is hardcoded and without the matching account the first thing a new operator
sees is a screen stating a password that does not work. It is five characters; `admin.py`
accepts it only because `ORDIN_ENV` is a development value **and**
`ORDIN_ADMIN_ALLOW_WEAK` is set. Both conditions are required on purpose.

**It never overwrites an existing `.env`**, and `render_env` fills only values that are
empty or still `change_me_*`. A key somebody chose deliberately survives, because
replacing one orphans the entire store.

---

## Before it is reachable by anyone else

The defaults above are for a machine on a desk. Before this is on a network someone else
can reach:

- Change `ORDIN_ADMIN_PASSWORD`, and remove the sign-in hint from
  `web/app/login/page.tsx`. It is rendered to every visitor of `/login`.
- Set `ORDIN_ENV=production`. `Settings.refuse_unsafe_production()` then refuses to start
  on a template session secret, template database passwords, or a missing master key —
  it fails loudly rather than running in a state that looks fine.
- Read `docs/DEPLOYMENT.md`, which covers the on-premise and cloud paths and is explicit
  about what neither covers.

---

## If something is wrong

`python tasks.py doctor` first. It reports the database revision, whether this checkout
migrated the database it is pointed at, and what is missing.

**Ports are deliberately non-default** — Postgres 5434, api 8001, web 3001 — because a
second checkout of this project once shared a container with the first. If you change
them in `.env`, change `docker-compose.yml` to match and re-run `doctor`, which will tell
you if you are pointed at a database this checkout did not migrate.

**`seed()` refuses while a test suite is running** (`infra/suite_guard.py`). It TRUNCATEs
the case tables, so doing it under a live suite deletes rows that suite is mid-way
through asserting on, and the failure lands in a different test each run looking exactly
like flakiness. If it refuses and nothing is actually running, the message names the lock
file to delete.
