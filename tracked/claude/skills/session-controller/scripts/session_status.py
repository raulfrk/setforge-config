#!/usr/bin/env python3
"""Print a short, redacted status line set for each Claude Code session on this host.

Reads ~/.claude/sessions/*.json and each session's transcript. Never prints raw
log text: every excerpt is redacted first, then cut to a bound.
"""
import argparse
import json
import os
import re
from pathlib import Path

HOME = Path.home() / ".claude"
WRAPPERS = ("<system-reminder", "<task-notification", "<local-command", "<command-name",
            "<cross-session", "[SYSTEM", "This session is being continued")

REDACTIONS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(-----END [A-Z ]*PRIVATE KEY-----|$)", re.S),
     "[private-key]"),
    (re.compile(r"\b(ssh-(rsa|ed25519|dss)|ecdsa-sha2-\S+|sk-ssh-\S+)\s+[A-Za-z0-9+/=]+(\s+\S+@\S+)?"),
     "[ssh-key]"),
    (re.compile(r"\b[a-z][a-z0-9+.-]*://\S+", re.I), "[url]"),
    (re.compile(r"\b[\w.-]+:\d{2,5}/\S*"), "[url]"),  # scheme-less host:port/path?query
    (re.compile(r"\b(bearer|basic)\s+\S+", re.I), "[auth]"),
    # Key/value secrets, plain or quoted; requiring [:=] keeps prose like "the code" intact.
    (re.compile(r"\b([A-Za-z0-9_]*(password|passwd|secret|token|api[_-]?key|auth|code|state))"
                r"([\"']?\s*[:=]\s*[\"']?)\S+", re.I), r"\1\3[redacted]"),
    (re.compile(r"\b(sk-|ghp_|gho_|ghs_|github_pat_|xox[abpr]-|AKIA|glpat-|tskey-)[A-Za-z0-9_\-]+"),
     "[token]"),
    # Long random-looking strings: 20+ token characters mixing letters and digits.
    (re.compile(r"(?<![A-Za-z0-9+/=_\-])(?=[A-Za-z0-9+/=_\-]*\d)(?=[A-Za-z0-9+/=_\-]*[A-Za-z])"
                r"[A-Za-z0-9+/=_\-]{20,}(?![A-Za-z0-9+/=_\-])"), "[random]"),
]


def redact(text, limit=200):
    """Redact secrets from the full text, then collapse whitespace and cut to `limit`."""
    for pattern, replacement in REDACTIONS:
        text = pattern.sub(replacement, text)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def typed_prompt(record):
    """Return the prompt Raul typed, or None for tool results, meta, sidechains and wrappers."""
    if record.get("type") != "user" or record.get("isMeta") or record.get("isSidechain"):
        return None
    if "toolUseResult" in record:
        return None
    content = (record.get("message") or {}).get("content")
    if not isinstance(content, str) or content.lstrip().startswith(WRAPPERS):
        return None
    return content


def summarize(path, tools=5):
    last = {"time": None, "prompt": None, "tools": [], "reply": None}
    with open(path, encoding="utf-8", errors="replace") as lines:
        for line in lines:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            last["time"] = record.get("timestamp") or last["time"]
            prompt = typed_prompt(record)
            if prompt is not None:
                last["prompt"] = prompt
            if record.get("type") == "assistant" and not record.get("isSidechain"):
                content = (record.get("message") or {}).get("content")
                for block in content if isinstance(content, list) else []:
                    if block.get("type") == "tool_use":
                        last["tools"] = (last["tools"] + [str(block.get("name"))])[-tools:]
                    elif block.get("type") == "text" and block.get("text", "").strip():
                        last["reply"] = block["text"]
    return last


def transcript(session):
    project = re.sub(r"[^A-Za-z0-9]", "-", session.get("cwd", ""))
    direct = HOME / "projects" / project / f"{session.get('sessionId')}.jsonl"
    if direct.is_file():
        return direct
    return next((HOME / "projects").glob(f"*/{session.get('sessionId')}.jsonl"), None)


def process_flags(pid):
    try:
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except OSError:
        return "not running"
    flags = [a.decode() for a in argv if a in (b"--resume", b"--fork-session", b"--continue")]
    return " ".join(flags) or "running"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", nargs="*", help="only these session names or id prefixes")
    parser.add_argument("--chars", type=int, default=200, help="bound for each excerpt")
    args = parser.parse_args()
    for path in sorted((HOME / "sessions").glob("*.json")):
        try:
            session = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        name, sid = str(session.get("name") or "?"), str(session.get("sessionId") or "?")
        if args.names and not any(n == name or sid.startswith(n) for n in args.names):
            continue
        print(f"## {redact(name, 60)}  pid={session.get('pid')} ({process_flags(session.get('pid'))})"
              f"  status={session.get('status')}  id={sid[:8]}  cwd={redact(str(session.get('cwd')), 120)}")
        log = transcript(session)
        if log is None:
            print("  transcript: not found")
            continue
        last = summarize(log)
        print(f"  last record: {last['time']}")
        print(f"  last prompt: {redact(last['prompt'] or '-', args.chars)}")
        print(f"  last tools:  {', '.join(last['tools']) or '-'}")
        print(f"  last reply:  {redact(last['reply'] or '-', args.chars)}")


if __name__ == "__main__":
    main()
