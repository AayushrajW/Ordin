#!/usr/bin/env python3
"""Ordin PreToolUse guard.

Enforces the CLAUDE.md rules that must not depend on the model remembering them.
Exit 2 blocks the tool call and returns stderr to Claude as feedback.
Fails closed: an unparseable payload blocks rather than passes.
"""
import json
import re
import sys

RULES = [
    # (tools, pattern, message)
    (
        {"Write", "Edit", "MultiEdit", "NotebookEdit"},
        r"class\s+(Blockchain|Chain[A-Z])",
        "'Blockchain*/Chain*' naming. The local hash-chain is LocalAnchorStore; "
        "only the Fabric adapter may use ledger/chain vocabulary (CLAUDE.md honesty rules).",
    ),
    (
        {"Write", "Edit", "MultiEdit", "NotebookEdit"},
        r"class\s+ESign(Service|Provider)\b",
        "'ESignService' names a stand-in after the real thing. Use SimulatedESignProvider.",
    ),
    (
        {"Write", "Edit", "MultiEdit", "NotebookEdit"},
        r"(if|elif)\b[^\n]*\b(?:current_user\.|user\.)?role\s*(==|!=)\s*['\"]"
        r"(admin|supervisor|investigator|officer|records)",
        "Hand-rolled role check. CLAUDE.md invariant 3: authorization is a versioned "
        "policy file evaluated by the policy engine, never a conditional in application code.",
    ),
    (
        {"Write", "Edit", "MultiEdit", "NotebookEdit"},
        r"BEGIN\s+(RSA |EC |OPENSSH )?PRIVATE KEY",
        "Private key material in a source file.",
    ),
    (
        {"Bash"},
        # `.env` but NOT `.env.example` / `.env.sample` / `.env.template`, which are
        # templates that MUST be committed - .gitignore explicitly un-ignores the
        # example. The original rule fired on them, which is a false positive that
        # teaches you to reword commit messages to get past the guard. A tripwire
        # people learn to step over is worse than no tripwire.
        r"git\s+(commit|add)\b[^\n]*"
        r"(\.env(?!\.example|\.sample|\.template)|id_rsa|\.pem|\.p12|\.pfx)",
        "Attempting to stage or commit a secret or .env file.",
    ),
    (
        {"Bash", "Write", "Edit", "MultiEdit"},
        r"(OPENAI_API_KEY|ANTHROPIC_API_KEY|GEMINI_API_KEY|api\.openai\.com|generativelanguage\.googleapis\.com)",
        "Hosted LLM API detected. CLAUDE.md: everything free and offline, no paid APIs, "
        "no external network calls on the demo path.",
    ),
]

# Redaction must be destructive, never presentational — only fires in redaction context.
PRESENTATIONAL = re.compile(
    r"filter:\s*blur|backdrop-filter|opacity:\s*0\b|visibility:\s*hidden|-webkit-text-security",
    re.I,
)


def block(msg: str) -> None:
    print(f"BLOCKED by ordin-guard: {msg}", file=sys.stderr)
    sys.exit(2)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:  # fail closed
        block(f"could not parse hook payload ({exc}). Refusing to allow unchecked.")

    tool = payload.get("tool_name", "")
    ti = payload.get("tool_input", {}) or {}
    body = "\n".join(
        str(ti.get(k, "")) for k in ("command", "content", "new_string", "file_path")
    )

    for tools, pattern, msg in RULES:
        if tool in tools and re.search(pattern, body, re.I):
            block(msg)

    if tool in {"Write", "Edit", "MultiEdit"}:
        if re.search(r"redact", body, re.I) and PRESENTATIONAL.search(body):
            block(
                "Presentational redaction. CLAUDE.md invariant 8: redaction is destructive — "
                "burn the region into the raster and strip the text layer underneath."
            )

    sys.exit(0)


if __name__ == "__main__":
    main()
