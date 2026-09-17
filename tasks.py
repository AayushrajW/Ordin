#!/usr/bin/env python
"""Ordin task runner.

`make` is not installed on the Windows dev machine and is not native to it, so the
runner is plain Python: one interpreter, identical commands on every machine, no
install step.

    python tasks.py doctor          check the environment before blaming the code
    python tasks.py up             dev path: postgres in docker, api+worker+web native
    python tasks.py down           stop containers, leave the data
    python tasks.py fresh          destroy the volume and rebuild from nothing
    python tasks.py test           start postgres if needed, then run the suite
    python tasks.py migrate        apply migrations only
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

def cmd_doctor() -> int:
    print("ordin doctor")
    problems = 0

    print(f"  python           : {sys.version.split()[0]}  ({PY})")
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

    print(f"\n  {'ok' if problems == 0 else f'{problems} problem(s)'}")
    return 1 if problems else 0


def cmd_migrate() -> int:
    run([PY, "-m", "alembic", "upgrade", "head"])
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

        web_dir = ROOT / "web"
        if (web_dir / "node_modules").exists():
            print("  starting web (next dev)")
            procs.append(subprocess.Popen(
                ["npm", "run", "dev"], cwd=web_dir, env=web_env, shell=(os.name == "nt")))
        else:
            print("  skipping web - run `npm install` in web/ first")

        print(f"\n  api    http://{cfg.ordin_api_host}:{cfg.ordin_api_port}/health")
        print(f"  web    http://127.0.0.1:3000")
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
        print("  waiting for the api to become healthy (up to 180s)")
        deadline = time.time() + 180
        api_ok = False
        while time.time() < deadline:
            try:
                status, body = _http_json("http://127.0.0.1:8000/health")
                if status == 200 and body.get("status") == "healthy":
                    api_ok = True
                    print(f"    api healthy: {[c['name'] for c in body['checks']]}")
                    break
            except (urllib.error.URLError, OSError, ValueError):
                pass
            time.sleep(3)
        if not api_ok:
            failures.append("api never reported healthy")

        print("  checking the web page")
        try:
            with urllib.request.urlopen("http://127.0.0.1:3000", timeout=15) as r:
                html = r.read().decode(errors="replace")
            if r.status != 200:
                failures.append(f"web returned {r.status}")
            elif "All dependencies healthy" not in html:
                failures.append("web page did not render the healthy state")
            else:
                print("    web page green")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"web unreachable ({type(exc).__name__})")

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
        stats = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{.Name}}\t{{.MemUsage}}"],
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
    result = run([PY, "-m", "pytest", "-rs"], check=False)
    return result.returncode


COMMANDS = {
    "doctor": cmd_doctor,
    "up": cmd_up,
    "down": cmd_down,
    "fresh": cmd_fresh,
    "test": cmd_test,
    "migrate": cmd_migrate,
    "worker": cmd_worker,
    "verify-compose": cmd_verify_compose,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(COMMANDS[sys.argv[1]]())
