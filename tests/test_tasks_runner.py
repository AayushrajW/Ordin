"""The task runner must work however it is started.

The README says `python tasks.py up`. On the build machine `python` is 3.10 with none of
the project's packages, and `tasks.py` imported the application in whatever interpreter
started it — so the documented command died with `No module named 'pydantic'` while
every command run as `.venv\\Scripts\\python.exe tasks.py` worked. The runner now hands
itself over to the venv; this test starts it with a different interpreter on purpose.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VENV_PY = ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def _another_interpreter() -> list[str] | None:
    """Any Python on this machine that is not the project's venv."""
    candidates: list[list[str]] = []
    launcher = shutil.which("py")
    if launcher:
        candidates += [[launcher, f"-3.{minor}"] for minor in (10, 12, 13, 9)]
    for name in ("python3", "python"):
        found = shutil.which(name)
        if found:
            candidates.append([found])
    for command in candidates:
        try:
            probe = subprocess.run(command + ["-c", "import sys; print(sys.executable)"],
                                   capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if probe.returncode != 0:
            continue
        if Path(probe.stdout.strip()).resolve() != VENV_PY.resolve():
            return command
    return None


def test_the_runner_hands_itself_over_to_the_venv():
    if not VENV_PY.exists():
        pytest.skip("no venv yet - `python tasks.py setup` creates it")
    other = _another_interpreter()
    if other is None:
        pytest.skip("no interpreter other than the venv on this machine")

    result = subprocess.run(other + [str(ROOT / "tasks.py"), "doctor"],
                            cwd=ROOT, capture_output=True, text=True, timeout=180)
    output = result.stdout + result.stderr
    assert "ModuleNotFoundError" not in output, output[-800:]
    assert str(VENV_PY) in output or ".venv" in output, (
        "doctor did not report running under the project's interpreter:\n" + output[-800:]
    )
