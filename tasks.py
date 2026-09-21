#!/usr/bin/env python
"""Ordin task runner.

`make` is not installed on the Windows dev machine and is not native to it, so the
runner is plain Python: one interpreter, identical commands on every machine, no
install step.

    python tasks.py setup           first run on a clean clone: venv, deps, .env, fixtures
    python tasks.py doctor          check the environment before blaming the code
    python tasks.py demo           fresh + seed + ingest documents: a case file to show
    python tasks.py up             dev path: postgres in docker, api+worker+web native
    python tasks.py down           stop containers, leave the data
    python tasks.py fresh          destroy the volume and rebuild from nothing
    python tasks.py test           start postgres if needed, then run the suite
    python tasks.py migrate        apply migrations only
    python tasks.py sentinel       run the security scenarios and print the result
    python tasks.py evaluate       OCR accuracy and latency over the fixture corpus
    python tasks.py fixtures       regenerate the synthetic document corpus
    python tasks.py seed           load the demo seed (3 cases, 2 organizations)
    python tasks.py worker         run the worker alone, natively
    python tasks.py verify-compose demo path: all four containers, checked, torn down
"""
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PY = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
PY = str(VENV_PY) if VENV_PY.exists() else sys.executable

MIN_FREE_MB = 800


def run(cmd: list[str], check: bool = True, **kw) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=check, cwd=ROOT, **kw)


def settings():
    sys.path.insert(0, str(ROOT))
    from api.config import Settings

    return Settings()


def dependencies_installed() -> bool:
    """Can we import the application at all?

    `doctor` must answer usefully on a machine where nothing is set up yet - that is
    the entire situation it exists for. It used to call settings() unconditionally and
    die with ModuleNotFoundError on a clean clone, which is the diagnostic tool
    requiring the thing it diagnoses.
    """
    probe = subprocess.run(
        [PY, "-c", "import pydantic_settings, sqlalchemy, fastapi"],
        cwd=ROOT, capture_output=True,
    )
    return probe.returncode == 0


def port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def available_mb() -> int | None:
    """Best-effort free memory, for the doctor's warning."""
    try:
        if os.name == "nt":
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-Counter '\\Memory\\Available MBytes').CounterSamples[0].CookedValue"],
                capture_output=True, text=True, timeout=15,
            )
            return int(float(out.stdout.strip()))
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except Exception:
        return None
    return None


def wait_for_postgres(timeout: float = 60.0) -> None:
    cfg = settings()
    print(f"  waiting for postgres on {cfg.postgres_host}:{cfg.postgres_port} ...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        probe = subprocess.run(
            ["docker", "compose", "exec", "-T", "postgres",
             "pg_isready", "-U", cfg.postgres_owner_user, "-d", cfg.postgres_db],
            cwd=ROOT, capture_output=True,
        )
        if probe.returncode == 0:
            print("  postgres ready")
            return
        time.sleep(1)
    raise SystemExit("postgres did not become ready in time - try `python tasks.py doctor`")


# --- commands ---------------------------------------------------------------

def database_revision() -> str | None:
    """Whatever the database currently reports, or None if it has none.

    Queried over the SAME connection the application uses - host and port from
    settings - and deliberately NOT via `docker compose exec`. Exec runs inside this
    checkout's own container whatever the configured port says, so it would always
    report our own revision and the check would pass while the app talked to someone
    else's database. That mistake was made here once and caught by testing the guard
    against the other tree's port rather than trusting it.
    """
    import asyncio

    sys.path.insert(0, str(ROOT))
    import sqlalchemy as sa
    from sqlalchemy.ext.asyncio import create_async_engine

    cfg = settings()

    async def read() -> str | None:
        engine = create_async_engine(cfg.owner_dsn)
        try:
            async with engine.connect() as conn:
                return (
                    await conn.execute(sa.text("SELECT version_num FROM alembic_version"))
                ).scalar_one_or_none()
        except Exception:  # noqa: BLE001 - no table yet, or unreachable
            return None
        finally:
            await engine.dispose()

    return asyncio.run(read())


def check_database_identity() -> bool:
    """Is the database on the other end actually this checkout's?

    Cheap, and it catches the failure that cost an evening: two checkouts sharing a
    container, one migrating over the other, Alembic truthfully reporting "at head"
    of a revision history this tree has never contained.
    """
    sys.path.insert(0, str(ROOT))
    from infra.db_identity import check_revision, known_revisions

    result = check_revision(database_revision(), known_revisions(ROOT / "alembic" / "versions"))
    if not result.ok:
        print("")
        print("  DATABASE IDENTITY CHECK FAILED")
        print(f"    {result.message}")
    return result.ok


def cmd_doctor() -> int:
    print("ordin doctor")
    problems = 0

    # The interpreter actually running this, not the one subprocesses will use. They
    # are the same after the handover; printing PY here reported 3.10 beside the venv
    # path when they were not.
    print(f"  python           : {sys.version.split()[0]}  ({sys.executable})")
    if not sys.version.startswith("3.11"):
        print("    ! expected 3.11 to match the api container")
        problems += 1

    if shutil.which("docker"):
        engine = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                                capture_output=True, text=True)
        if engine.returncode == 0:
            print(f"  docker engine    : {engine.stdout.strip()}")
        else:
            print("  docker engine    : NOT RUNNING - start Docker Desktop")
            problems += 1
    else:
        print("  docker           : NOT FOUND")
        problems += 1

    env_present = (ROOT / ".env").exists()
    deps = dependencies_installed()
    print(f"  dependencies     : {'installed' if deps else 'NOT INSTALLED'}")
    print(f"  tesseract        : {'present' if shutil.which('tesseract') else 'NOT FOUND (OCR will fail)'}")

    if not deps or not env_present:
        # Everything below needs the application importable and configured. Say what
        # to do rather than crashing halfway through the report.
        print(f"  .env             : {'present' if env_present else 'MISSING'}")
        print("\n  not set up yet - run:  python tasks.py setup")
        return 1

    cfg = settings()
    reachable = port_open(cfg.postgres_host, cfg.postgres_port)
    print(f"  postgres         : {'reachable' if reachable else 'not reachable'} "
          f"at {cfg.postgres_host}:{cfg.postgres_port}")
    if not reachable:
        print("    run `python tasks.py up`")

    if port_open("127.0.0.1", 5432) and cfg.postgres_port != 5432:
        print("    note: something else holds 5432 (a native postgres service?); "
              "this project deliberately uses "
              f"{cfg.postgres_port}")

    mem = available_mb()
    if mem is not None:
        print(f"  memory available : {mem} MB")
        if mem < MIN_FREE_MB:
            print(f"    ! under {MIN_FREE_MB} MB - close applications before running the "
                  f"full compose path; the OOM killer takes postgres first")
    env_file = ROOT / ".env"
    print(f"  .env             : {'present' if env_file.exists() else 'MISSING - copy .env.example'}")
    if not env_file.exists():
        problems += 1

    if reachable:
        sys.path.insert(0, str(ROOT))
        from infra.db_identity import check_revision, known_revisions

        identity = check_revision(
            database_revision(), known_revisions(ROOT / "alembic" / "versions")
        )
        print(f"  database identity: {'ours' if identity.ok else 'FOREIGN'}")
        if not identity.ok:
            print(f"    {identity.message}")
            problems += 1

    print(f"\n  {'ok' if problems == 0 else f'{problems} problem(s)'}")
    return 1 if problems else 0


def cmd_migrate() -> int:
    run([PY, "-m", "alembic", "upgrade", "head"])
    return 0


def cmd_setup() -> int:
    """Everything a clean clone needs before anything else works.

    Written after a clone-to-a-fresh-directory rehearsal, where the honest answer to
    "what does a newcomer type?" turned out to be a sequence nobody had written down.
    Idempotent: safe to re-run, and it says what it skipped.
    """
    import venv as venv_module

    print("ordin setup\n")
    problems = 0

    # 1. Interpreter. 3.11 to match the api image (ADR 0007).
    venv_dir = ROOT / ".venv"
    if VENV_PY.exists():
        print("  venv             : already present")
    else:
        launcher = shutil.which("py")
        created = False
        if launcher:
            probe = subprocess.run([launcher, "-3.11", "--version"], capture_output=True)
            if probe.returncode == 0:
                print("  venv             : creating with python 3.11")
                subprocess.run([launcher, "-3.11", "-m", "venv", str(venv_dir)], check=True)
                created = True
        if not created:
            print(f"  venv             : python 3.11 not found; using {sys.version.split()[0]}")
            print("    ! the api image is 3.11; a different interpreter here is the")
            print("      dev/demo divergence ADR 0006's two-path test exists to catch")
            venv_module.create(venv_dir, with_pip=True)
            problems += 1

    python = str(VENV_PY) if VENV_PY.exists() else sys.executable

    # 2. Python dependencies.
    print("  python deps      : installing")
    subprocess.run([python, "-m", "pip", "install", "--quiet", "--upgrade", "pip"], cwd=ROOT)
    install = subprocess.run([python, "-m", "pip", "install", "--quiet", "-e", ".[dev]"], cwd=ROOT)
    if install.returncode != 0:
        print("    ! pip install failed")
        problems += 1

    # 3. Configuration. Never overwrite an existing .env.
    env_file, example = ROOT / ".env", ROOT / ".env.example"
    if env_file.exists():
        print("  .env             : already present, left alone")
    elif example.exists():
        body = example.read_text(encoding="utf-8")
        # Replace the placeholders so the stack starts. These are local dev values
        # for a database bound to loopback; .env is gitignored.
        for placeholder, value in (
            ("change_me_owner", "dev_owner_pw_local_only"),
            ("change_me_app", "dev_app_pw_local_only"),
            ("change_me_session_secret", "dev_session_secret_local_only"),
        ):
            body = body.replace(placeholder, value)
        env_file.write_text(body, encoding="utf-8")
        print("  .env             : created from .env.example with local dev values")
    else:
        print("  .env             : MISSING and no .env.example to copy")
        problems += 1

    # 4. Web dependencies, if node is here. Not fatal: the api and the security
    #    demo work without the web tier.
    web = ROOT / "web"
    if (web / "node_modules").exists():
        print("  web deps         : already present")
    elif shutil.which("npm"):
        print("  web deps         : installing (npm)")
        subprocess.run(["npm", "install", "--no-audit", "--no-fund"], cwd=web,
                       shell=(os.name == "nt"))
    else:
        print("  web deps         : npm not found - the web tier will not run")

    # 5. Fixtures. Gitignored and deterministic, so they are generated not carried.
    if list((ROOT / "fixtures" / "corpus").glob("*.pdf")):
        print("  fixtures         : already generated")
    else:
        print("  fixtures         : generating")
        subprocess.run([python, "-m", "fixtures.generate"], cwd=ROOT)

    if not shutil.which("tesseract"):
        print("\n  ! tesseract is not installed. OCR stages will fail by design rather")
        print("    than falling back to the text layer (docs/adr/0012).")
        problems += 1

    print(f"\n  {'setup complete' if not problems else f'{problems} thing(s) need attention'}")
    print("  next:  python tasks.py doctor")
    return 0


def cmd_evaluate() -> int:
    """Slice 11a: OCR character error rate and latency over the fixture corpus."""
    return run([PY, "evaluate.py"], check=False).returncode


def cmd_sentinel() -> int:
    """Run the Sentinel scenarios and print the result."""
    return run([PY, "-m", "sentinel.run"], check=False).returncode


def cmd_fixtures() -> int:
    """Regenerate the synthetic corpus and its ground-truth sidecars.

    Slice 6b: 48 documents, of which the first ten are the hand-written ones the
    tests and the demo address by slug, and a quarter of the remainder are degraded
    scans. Seeded, so two machines produce byte-identical corpora and their accuracy
    figures can be compared.
    """
    run([PY, "-m", "fixtures.scale"])
    return 0


def cmd_seed() -> int:
    """Load the structural demo seed: 3 cases across 2 organizations."""
    run([PY, "seed.py"])
    return 0


def cmd_demo() -> int:
    """Fresh database, seed, then ingest documents through the real pipeline.

    One command between a clean checkout and a case file worth showing somebody.
    """
    if cmd_fresh() != 0:
        return 1
    if cmd_seed() != 0:
        return 1
    code = run([PY, "demo.py"], check=False).returncode
    # seed.py TRUNCATEs app_user, which takes the administrator with it. Put it back
    # when .env says who it is, so `demo` does not quietly lock the operator out of
    # their own system.
    if code == 0:
        # --if-configured: exits quietly when no administrator is set, so `demo` stays
        # one command on a clean clone. admin.py reads .env itself, because a value
        # there is invisible to os.environ.
        run([PY, "admin.py", "--if-configured"], check=False)
    return code


def cmd_admin() -> int:
    """Create or update an administrator. The bootstrap every admin system needs."""
    return run([PY, "admin.py", *sys.argv[2:]], check=False).returncode


def cmd_newkey() -> int:
    """Generate a master key for encryption at rest.

    Printed, never written to a file for you. A command that edited `.env` would put
    the key into shell history, terminal scrollback and any screen share running at the
    time, and the one thing this key must not do is travel.
    """
    sys.path.insert(0, str(ROOT))
    from infra.crypto import generate_master_key

    print("")
    print("  ORDIN_MASTER_KEY=" + generate_master_key())
    print("")
    print("  Put that in .env, or in the deployment environment.")
    print("")
    print("  It wraps the data key of every stored document. Lose it and every blob")
    print("  is unreadable, with no recovery path - so back it up somewhere that is")
    print("  not the machine holding the blobs. Changing it does NOT re-encrypt what")
    print("  is already stored: blobs written under the old key stop opening.")
    return 0


def cmd_counts() -> int:
    """Every number this project quotes about itself, computed from the source.

    Emitted rather than remembered. `docs/STATUS.md` once carried three different test
    counts and three different Sentinel counts, and two of the test numbers were both
    right — test *functions* and test *cases* differ because of parametrisation, and
    nothing said which was which. Paste this output; do not retype it.
    """
    import re

    tests = sorted((ROOT / "tests").glob("test_*.py"))
    functions = sum(
        len(re.findall(r"^\s*(?:async\s+)?def test_", f.read_text(encoding="utf-8"), re.M))
        for f in tests
    )
    scenarios = sum(
        len(re.findall(r"@scenario\(", f.read_text(encoding="utf-8")))
        for f in (ROOT / "sentinel").glob("scenarios_*.py")
    )
    adrs = len(list((ROOT / "docs" / "adr").glob("*.md")))
    migrations = len(list((ROOT / "alembic" / "versions").glob("[0-9]*.py")))
    policies = len(list((ROOT / "policies").glob("*.yaml")))
    modules = len(list((ROOT / "docs" / "modules").glob("*.md")))

    print("")
    print("  ordin counts        (generated, not remembered)")
    print(f"  test functions    : {functions}   across {len(tests)} files")
    # ASCII only: this prints to a Windows console whose code page mangles an em dash.
    print("  test cases        : run `python tasks.py test` - parametrisation expands")
    print(f"                      the functions above into more cases")
    print(f"  sentinel scenarios: {scenarios}")
    print(f"  ADRs              : {adrs}")
    print(f"  migrations        : {migrations}")
    print(f"  policy files      : {policies}")
    print(f"  module briefs     : {modules}")
    print("")
    print("  Quote both test numbers or neither. One without the other invites")
    print("  somebody to find the second and conclude you were rounding.")
    return 0


def cmd_package() -> int:
    """Build the submission archive from git, never from the working directory.

    A directory copy ships `.env` — real credentials, correctly gitignored and then
    included anyway — plus `.venv`, `.git`, `node_modules`, `.next`, `var/` and every
    `__pycache__`. That is how a 5 MB submission becomes 477 MB with secrets in it.

    `git archive` emits exactly what is committed, which is exactly what a reviewer
    should receive.
    """
    out = ROOT / "dist"
    out.mkdir(exist_ok=True)
    name = out / "ordin-submission.zip"
    result = run(["git", "archive", "--format=zip", "-o", str(name), "HEAD"], check=False)
    if result.returncode != 0:
        print("  git archive failed; is this a git checkout with a commit?")
        return 1
    size = name.stat().st_size / (1024 * 1024)
    print("")
    print(f"  wrote {name}  ({size:.1f} MB)")
    print("")
    print("  Contains only committed files. Verify before sending:")
    print(f"    python -c \"import zipfile;print([n for n in zipfile.ZipFile(r'{name}').namelist() if '.env' in n or 'node_modules' in n] or 'clean')\"")
    print("")
    print("  If a previous archive shipped .env, rotate ORDIN_SESSION_SECRET, both")
    print("  Postgres passwords and the admin password: they have left the machine.")
    return 0


def cmd_worker() -> int:
    """Run the worker alone, natively."""
    run([PY, "-m", "worker.main"], check=False)
    return 0


def cmd_up() -> int:
    """Dev path: postgres in docker, api + worker + web native (ADR 0006)."""
    run(["docker", "compose", "up", "-d", "postgres"])
    wait_for_postgres()
    cmd_migrate()
    cfg = settings()

    procs: list[subprocess.Popen] = []
    web_env = {**os.environ, "NEXT_TELEMETRY_DISABLED": "1",
               "ORDIN_API_ORIGIN": f"http://{cfg.ordin_api_host}:{cfg.ordin_api_port}"}
    try:
        print("  starting worker")
        procs.append(subprocess.Popen([PY, "-m", "worker.main"], cwd=ROOT))

        # The same port the compose path publishes. `package.json` says 3000 because
        # that is the port inside the container, and the native loop must not take it:
        # 3000 belongs to the second checkout at D:\Legal Assistant, and two dev
        # servers on one port is the class of collision that already cost this project
        # a shared postgres container.
        web_port = os.environ.get("ORDIN_WEB_PORT", "3001")
        web_dir = ROOT / "web"
        if (web_dir / "node_modules").exists():
            print(f"  starting web (next dev, port {web_port})")
            procs.append(subprocess.Popen(
                ["npm", "run", "dev", "--", "--port", web_port],
                cwd=web_dir, env=web_env, shell=(os.name == "nt")))
        else:
            print("  skipping web - run `npm install` in web/ first")

        print(f"\n  api    http://{cfg.ordin_api_host}:{cfg.ordin_api_port}/health")
        print(f"  web    http://127.0.0.1:{web_port}")
        print("  ctrl-c to stop everything\n")
        run([PY, "-m", "uvicorn", "api.main:app",
             "--host", cfg.ordin_api_host, "--port", str(cfg.ordin_api_port), "--reload"],
            check=False)
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
    return 0


def _http_json(url: str, timeout: float = 5.0):
    import json as _json
    import urllib.request

    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.status, _json.loads(response.read().decode())


class _ComposeNotUp(RuntimeError):
    """The stack did not start. Every later check would be measuring something else."""


def cmd_verify_compose() -> int:
    """The demo path. Brings all four containers up, checks them, tears down.

    Run this before slice 3 and again at the hour-30 hard stop (ADR 0006). The
    dev loop never exercises the containers, so without this the compose path
    rots silently and is discovered broken in front of a judge.
    """
    import json as _json
    import urllib.error
    import urllib.request

    failures: list[str] = []
    print("verify-compose: building and starting all four containers")
    run(["docker", "compose", "up", "-d", "--build"], check=False)

    try:
        # **Check the containers are actually running before believing any endpoint.**
        # Without this the harness lies: the native dev loop publishes the api and the
        # web tier on the same ports, so when `up` failed to bind them this reported
        # "web page green" against a process compose had not started, while the web
        # container sat in `Created`. A verification that can pass against something
        # else entirely is worse than no verification.
        print("  confirming all four containers are running")
        expected = {"postgres", "api", "worker", "web"}
        deadline = time.time() + 60
        running: set[str] = set()
        while time.time() < deadline:
            listing = subprocess.run(
                ["docker", "compose", "ps", "--format", "{{.Service}} {{.State}}"],
                capture_output=True, text=True,
            )
            running = {
                line.split()[0]
                for line in (listing.stdout or "").splitlines()
                if line.strip().endswith("running")
            }
            if expected <= running:
                print(f"    running: {', '.join(sorted(running & expected))}")
                break
            time.sleep(2)
        missing = expected - running
        if missing:
            failures.append(
                f"container(s) not running: {', '.join(sorted(missing))} "
                f"- if a port is already bound, stop `tasks.py up` first"
            )
            # Everything below would be measuring the wrong thing.
            raise _ComposeNotUp(missing)

        # The published port, not the container's internal one. This probed 8000 for
        # three sessions while compose published 8001, so the check either found
        # nothing or found a different process - never the container it was verifying.
        api_url = f"http://127.0.0.1:{os.environ.get('ORDIN_API_PORT', '8001')}"
        print(f"  waiting for the api at {api_url} to become healthy (up to 180s)")
        deadline = time.time() + 180
        api_ok = False
        while time.time() < deadline:
            try:
                status, body = _http_json(f"{api_url}/health")
                if status == 200 and body.get("status") == "healthy":
                    api_ok = True
                    print(f"    api healthy: {[c['name'] for c in body['checks']]}")
                    break
            except (urllib.error.URLError, OSError, ValueError):
                pass
            time.sleep(3)
        if not api_ok:
            failures.append("api never reported healthy")

        # Poll rather than check once. The web container renders server-side, so it
        # needs the api reachable AND itself finished starting; a single immediate
        # check reported a false FAILURE while the page was in fact fine. A
        # verification harness that cries wolf gets ignored, which is worse than not
        # having one.
        cfg = settings()
        web_url = f"http://127.0.0.1:{os.environ.get('ORDIN_WEB_PORT', '3001')}"
        # The health page, not the front page: slice 5b made `/` the case list, and
        # what this check is for is "the web tier rendered something that required
        # the api to answer", which the health page states unambiguously.
        print(f"  checking the web health page at {web_url}/health (up to 90s)")
        deadline = time.time() + 90
        web_ok, last = False, "never responded"
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"{web_url}/health", timeout=10) as r:
                    html = r.read().decode(errors="replace")
                if r.status != 200:
                    last = f"web returned {r.status}"
                elif "All dependencies healthy" not in html:
                    last = "web page did not render the healthy state"
                else:
                    web_ok = True
                    print("    web page green")
                    break
            except Exception as exc:  # noqa: BLE001
                last = f"web unreachable ({type(exc).__name__})"
            time.sleep(3)
        if not web_ok:
            failures.append(last)

        # Invariant 11. This setting silently regresses - next.config.mjs cannot
        # express it and a machine-local opt-out does not travel with the repo.
        print("  asserting telemetry is disabled in the web container")
        probe = subprocess.run(
            ["docker", "compose", "exec", "-T", "web", "sh", "-c", "echo $NEXT_TELEMETRY_DISABLED"],
            cwd=ROOT, capture_output=True, text=True,
        )
        if probe.stdout.strip() != "1":
            failures.append("NEXT_TELEMETRY_DISABLED is not 1 in the web container")
        else:
            print("    NEXT_TELEMETRY_DISABLED=1")

        print("  measuring memory")
        # Only this project's containers. `docker stats` with no arguments reports
        # every container on the host, which silently included a second checkout's
        # postgres in the total and overstated the footprint.
        mine = subprocess.run(
            ["docker", "compose", "ps", "--format", "{{.Name}}"],
            cwd=ROOT, capture_output=True, text=True,
        ).stdout.split()
        stats = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{.Name}}\t{{.MemUsage}}", *mine],
            cwd=ROOT, capture_output=True, text=True,
        )
        total_mb = 0.0
        for line in stats.stdout.strip().splitlines():
            if "\t" not in line:
                continue
            name, usage = line.split("\t", 1)
            used = usage.split("/")[0].strip()
            try:
                value = float(used.rstrip("GKMiB"))
                if used.endswith("GiB"):
                    value *= 1024
                elif used.endswith("KiB"):
                    value /= 1024
                total_mb += value
                print(f"    {name:16} {used}")
            except ValueError:
                pass
        print(f"    {'TOTAL':16} {total_mb:.0f}MiB")
        if total_mb > 1500:
            failures.append(f"containers used {total_mb:.0f} MiB, over the 1500 MiB ceiling")
    except _ComposeNotUp:
        pass
    finally:
        print("  tearing down")
        run(["docker", "compose", "down"], check=False)

    if failures:
        print("\n  FAILED:")
        for f in failures:
            print(f"    - {f}")
        return 1
    print("\n  compose path verified")
    return 0


def cmd_down() -> int:
    run(["docker", "compose", "down"])
    return 0


def cmd_fresh() -> int:
    print("  destroying the database volume")
    run(["docker", "compose", "down", "-v"], check=False)
    # postgres only: the dev loop runs api/worker/web natively (ADR 0006).
    # Starting all four here would also mean tests hit a containerised api
    # built from an older image rather than the code under test.
    run(["docker", "compose", "up", "-d", "postgres"])
    wait_for_postgres()
    cmd_migrate()
    print("\n  fresh database ready")
    return 0


def cmd_test() -> int:
    """Start postgres first, so requires_db tests actually run rather than skip."""
    if not port_open(settings().postgres_host, settings().postgres_port):
        run(["docker", "compose", "up", "-d", "postgres"])
        wait_for_postgres()
    # Refuse to run against someone else's schema. A suite that passes or fails
    # against a foreign database tells you nothing, and says it confidently.
    if not check_database_identity():
        print("    refusing to run the suite against a database this checkout did "
              "not migrate")
        return 2
    # -rfEs, not -rs. `-r` replaces pytest's default report characters rather than
    # adding to them, so `-rs` listed skips and silently dropped the names of failing
    # tests — a run could end "1 failed, 365 passed" with no way to tell which.
    result = run([PY, "-m", "pytest", "-rfEs"], check=False)
    return result.returncode


COMMANDS = {
    "doctor": cmd_doctor,
    "up": cmd_up,
    "down": cmd_down,
    "fresh": cmd_fresh,
    "test": cmd_test,
    "migrate": cmd_migrate,
    "worker": cmd_worker,
    "seed": cmd_seed,
    "admin": cmd_admin,
    "counts": cmd_counts,
    "newkey": cmd_newkey,
    "package": cmd_package,
    "fixtures": cmd_fixtures,
    "sentinel": cmd_sentinel,
    "evaluate": cmd_evaluate,
    "demo": cmd_demo,
    "setup": cmd_setup,
    "verify-compose": cmd_verify_compose,
}

def _running_in_venv() -> bool:
    try:
        return Path(sys.executable).resolve() == VENV_PY.resolve()
    except OSError:
        return False


def _hand_over_to_venv() -> None:
    """Re-run this command under the project's own interpreter, if we are not in it.

    The README says `python tasks.py up`, and on this machine `python` is 3.10 with none
    of the project's packages — so every command that imports the application died with
    `No module named 'pydantic'`. Subprocesses already used the venv; the runner itself
    did not, and nobody noticed because it was only ever invoked as
    `.venv\\Scripts\\python.exe tasks.py`, which is not what anyone else types.

    Only when the venv exists — which is what lets `doctor` still answer on a bare
    clone. `setup` is the one command that never hands over, because it is the one that
    creates the venv.
    """
    # The guard is the interpreter path itself, never an environment variable. A
    # marker in the environment is inherited by every descendant, so anything this
    # runner starts that calls the runner again - the test suite does exactly that -
    # would silently skip the handover and fail with the error this exists to prevent.
    # Comparing paths cannot leak: the child IS the venv interpreter, so it stops.
    if not VENV_PY.exists() or _running_in_venv():
        return
    child = subprocess.Popen([str(VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]],
                             cwd=ROOT)
    # Ctrl-C reaches the child too, and `up` shuts its processes down cleanly on it.
    # Waiting again rather than killing lets that shutdown finish.
    for _ in range(3):
        try:
            raise SystemExit(child.wait())
        except KeyboardInterrupt:
            continue
    child.kill()
    raise SystemExit(130)


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        raise SystemExit(2)
    if sys.argv[1] != "setup":
        _hand_over_to_venv()
    raise SystemExit(COMMANDS[sys.argv[1]]())
