#!/usr/bin/env python
"""Ordin task runner.

`make` is not installed on the Windows dev machine and is not native to it, so the
runner is plain Python: one interpreter, identical commands on every machine, no
install step.

    python tasks.py doctor   check the environment before blaming the code
    python tasks.py up       start postgres, apply migrations, run the api
    python tasks.py down     stop postgres, leave the data
    python tasks.py fresh    destroy the volume and rebuild from nothing
    python tasks.py test     start postgres if needed, then run the suite
    python tasks.py migrate  apply migrations only
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


def cmd_up() -> int:
    run(["docker", "compose", "up", "-d"])
    wait_for_postgres()
    cmd_migrate()
    cfg = settings()
    print(f"\n  api on http://{cfg.ordin_api_host}:{cfg.ordin_api_port}/health   (ctrl-c to stop)\n")
    run([PY, "-m", "uvicorn", "api.main:app",
         "--host", cfg.ordin_api_host, "--port", str(cfg.ordin_api_port), "--reload"],
        check=False)
    return 0


def cmd_down() -> int:
    run(["docker", "compose", "down"])
    return 0


def cmd_fresh() -> int:
    print("  destroying the database volume")
    run(["docker", "compose", "down", "-v"], check=False)
    run(["docker", "compose", "up", "-d"])
    wait_for_postgres()
    cmd_migrate()
    print("\n  fresh database ready")
    return 0


def cmd_test() -> int:
    """Start postgres first, so requires_db tests actually run rather than skip."""
    if not port_open(settings().postgres_host, settings().postgres_port):
        run(["docker", "compose", "up", "-d"])
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
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(COMMANDS[sys.argv[1]]())
