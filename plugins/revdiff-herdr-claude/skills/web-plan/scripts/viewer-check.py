#!/usr/bin/env python3
"""Print "moshi" if the one attached Herdr client was opened by Moshi, else "unsure".

Read-only: parses `ss -xp` and /proc, never writes, signals, or asks Herdr.
Any problem or ambiguity answers "unsure", and the exit status is always 0.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

MARKER = "MOSHI_CLIENT=1"
DEFAULT_SOCKET = "~/.config/herdr/herdr.sock"
MAX_DEPTH = 64
PID_RE = re.compile(r"pid=(\d+)")
PROC = Path("/proc")


@dataclass(frozen=True)
class Proc:
    ppid: int
    args: tuple[str, ...]
    env: tuple[str, ...]


# Returns None when the process cannot be read.
ProcReader = Callable[[int], Proc | None]


@dataclass(frozen=True)
class Row:
    local: str
    inode: str
    peer_inode: str
    pids: frozenset[int]


def parse_rows(ss_text: str) -> list[Row]:
    """Columns: netid state recv-q send-q local inode peer peer-inode users."""
    rows = []
    for line in ss_text.splitlines():
        cols = line.split(None, 8)
        if len(cols) < 8 or cols[1] != "ESTAB":
            continue
        users = cols[8] if len(cols) > 8 else ""
        rows.append(Row(cols[4], cols[5], cols[7], frozenset(map(int, PID_RE.findall(users)))))
    return rows


def client_pid_sets(rows: list[Row], client_socket: str) -> list[frozenset[int]]:
    """One entry per connection to the client socket: the pids of its far end."""
    by_inode = {row.inode: row for row in rows}
    return [
        by_inode[row.peer_inode].pids if row.peer_inode in by_inode else frozenset()
        for row in rows
        if row.local == client_socket
    ]


def chain_has_marker(pid: int, read_proc: ProcReader) -> bool:
    seen: set[int] = set()
    while pid > 1 and pid not in seen and len(seen) < MAX_DEPTH:
        seen.add(pid)
        proc = read_proc(pid)
        if proc is None:
            return False
        if MARKER in proc.args or MARKER in proc.env:
            return True
        pid = proc.ppid
    return False


def detect(ss_text: str, client_socket: str, read_proc: ProcReader) -> str:
    connections = client_pid_sets(parse_rows(ss_text), client_socket)
    if len(connections) != 1 or len(connections[0]) != 1:
        return "unsure"
    (pid,) = connections[0]
    return "moshi" if chain_has_marker(pid, read_proc) else "unsure"


def read_proc(pid: int, root: Path = PROC) -> Proc | None:
    try:
        stat = (root / str(pid) / "stat").read_text(errors="replace")
        # The command name may contain spaces and parentheses; fields follow the last ")".
        ppid = int(stat.rpartition(")")[2].split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return Proc(ppid, read_nul_list(root / str(pid) / "cmdline"), read_nul_list(root / str(pid) / "environ"))


def read_nul_list(path: Path) -> tuple[str, ...]:
    try:
        return tuple(path.read_bytes().decode(errors="replace").split("\0"))
    except OSError:
        return ()


def client_socket_path() -> str:
    server = os.path.expanduser(os.environ.get("HERDR_SOCKET_PATH") or DEFAULT_SOCKET)
    return os.path.join(os.path.dirname(os.path.abspath(server)), "herdr-client.sock")


def run_ss() -> str:
    result = subprocess.run(["ss", "-xp"], capture_output=True, text=True, timeout=10, check=False)
    return result.stdout if result.returncode == 0 else ""


def main() -> int:
    answer = "unsure"
    try:
        answer = detect(run_ss(), client_socket_path(), read_proc)
    except Exception:  # The contract is one word and exit 0, whatever goes wrong.
        pass
    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
