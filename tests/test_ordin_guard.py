"""The guard hook must actually fire, using the command settings.json configures.

This exists because the hook once silently did nothing for an entire session: the
configured interpreter was `python3`, which on the Windows dev machine resolves to a
Microsoft Store alias stub that exits 49 instead of 2. The script was fine. The
configuration was dead, and nothing noticed.

So these tests deliberately do NOT import the hook or run it with sys.executable.
They read the command out of .claude/settings.json and run THAT, which is the only
thing that proves the hook fires in the environment Claude Code actually uses.
"""
import json
import os
import pathlib
import shlex
import shutil
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
BLOCK, ALLOW = 2, 0

# Assembled at runtime rather than written literally: these strings are exactly what
# the hook blocks, so spelling them out would make this file unwritable by an agent
# working under the hook.
BAD_NAMING = "class " + "Blockchain" + "Store: pass"
BAD_HOSTED_KEY = "OPENAI" + "_API_KEY = 'sk-redacted'"


def hook_command():
    """The hook invocation exactly as settings.json declares it."""
    settings = json.loads((ROOT / ".claude/settings.json").read_text(encoding="utf-8"))
    entries = settings["hooks"]["PreToolUse"]
    commands = [h["command"] for e in entries for h in e["hooks"]]
    assert commands, "settings.json declares no PreToolUse hook command"
    argv = shlex.split(commands[0].replace("$CLAUDE_PROJECT_DIR", str(ROOT)))
    assert argv, "hook command is empty"
    return argv


def run_hook(payload):
    argv = hook_command()
    assert shutil.which(argv[0]) is not None, (
        f"the interpreter settings.json configures ({argv[0]!r}) does not exist on this "
        f"machine, so the guard hook is silently doing nothing. This is the exact "
        f"failure this test was written to catch."
    )
    proc = subprocess.run(
        argv, input=json.dumps(payload), capture_output=True, text=True,
        cwd=ROOT, env={**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT)},
    )
    return proc.returncode, proc.stderr


def test_configured_interpreter_exists_and_hook_returns_block():
    """The regression test. A dead interpreter fails here, loudly."""
    code, stderr = run_hook(
        {"tool_name": "Write", "tool_input": {"content": BAD_NAMING}}
    )
    assert code == BLOCK, (
        f"hook exited {code}, expected {BLOCK}. Any exit code that is not 2 means the "
        f"tool call is ALLOWED through. stderr: {stderr!r}"
    )
    assert "ordin-guard" in stderr, "block message should identify the guard"


def test_blocks_hosted_llm_key():
    code, _ = run_hook(
        {"tool_name": "Write", "tool_input": {"content": BAD_HOSTED_KEY}}
    )
    assert code == BLOCK, f"hosted-LLM key not blocked (exit {code})"


def test_allows_an_ordinary_command():
    code, _ = run_hook(
        {"tool_name": "Bash", "tool_input": {"command": "pytest -q"}}
    )
    assert code == ALLOW, f"ordinary command was blocked (exit {code})"


ENV_FILE = ".env"
ENV_TEMPLATE = ".env.example"


def test_still_blocks_committing_a_real_env_file():
    """The narrowing must not have opened the hole the rule exists to close."""
    for command in (f"git add {ENV_FILE}", f"git commit -m x {ENV_FILE}"):
        code, _ = run_hook({"tool_name": "Bash", "tool_input": {"command": command}})
        assert code == BLOCK, f"{command!r} was allowed (exit {code})"


def test_allows_the_committed_template():
    """The template is meant to be committed - .gitignore explicitly un-ignores it.

    The original rule matched it, so it fired on the safe file. A tripwire that goes
    off on correct behaviour teaches you to reword commit messages to get past it,
    which is worse than not having one.
    """
    for command in (
        f"git add {ENV_TEMPLATE}",
        f"git commit -m 'correct stale ports in {ENV_TEMPLATE}'",
    ):
        code, stderr = run_hook({"tool_name": "Bash", "tool_input": {"command": command}})
        assert code == ALLOW, f"{command!r} was blocked: {stderr}"


def test_still_blocks_key_material_in_a_commit():
    for command in ("git add id_rsa", "git commit -m x server.pem", "git add cert.p12"):
        code, _ = run_hook({"tool_name": "Bash", "tool_input": {"command": command}})
        assert code == BLOCK, f"{command!r} was allowed"


def test_fails_closed_on_malformed_payload():
    argv = hook_command()
    proc = subprocess.run(
        argv, input="not json at all", capture_output=True, text=True,
        cwd=ROOT, env={**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT)},
    )
    assert proc.returncode == BLOCK, (
        f"hook exited {proc.returncode} on unparseable input, expected {BLOCK}. "
        f"An unparseable payload must deny, never pass unchecked."
    )


if __name__ == "__main__":
    # Runnable before pytest exists (slice 1 adds it).
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS  {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL  {name}\n      {exc}")
    print(f"\n{'FAILED' if failures else 'OK'} - {failures} failure(s)")
    raise SystemExit(1 if failures else 0)
