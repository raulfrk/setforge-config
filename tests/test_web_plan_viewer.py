"""Tests for the web-plan viewer check (plugins/revdiff-herdr-claude)."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "plugins/revdiff-herdr-claude/skills/web-plan/scripts/viewer-check.py"
)
SOCKET = "/home/raul/.config/herdr/herdr-client.sock"

# Real `ss -xp | grep -i herdr` output with one phone client (pid 1336591) attached.
ONE_CLIENT_SS = """\
u_str ESTAB 0      0                                                           * 4913663            * 4913662 users:(("herdr",pid=1336591,fd=9))
u_str ESTAB 0      0                                                           * 4913662            * 4913663 users:(("herdr",pid=1336591,fd=10),("herdr",pid=1336591,fd=8))
u_str ESTAB 0      0                  /home/raul/.config/herdr/herdr-client.sock 4914756            * 4913661 users:(("herdr",pid=300644,fd=30),("herdr",pid=300644,fd=18))
u_str ESTAB 0      0                                                           * 4913661            * 4914756 users:(("herdr",pid=1336591,fd=11),("herdr",pid=1336591,fd=4))
u_str ESTAB 0      0                                                           * 1201998            * 1201999 users:(("herdr",pid=300644,fd=11),("herdr",pid=300644,fd=9))
u_str ESTAB 0      0                                                           * 1201999            * 1201998 users:(("herdr",pid=300644,fd=10))
"""

# Real output with a phone (pid 1261717) and a laptop (pid 1306502) attached.
TWO_CLIENTS_SS = """\
u_str ESTAB 0      0                                                           * 4790767            * 4790768 users:(("herdr",pid=1306502,fd=10),("herdr",pid=1306502,fd=8))
u_str ESTAB 0      0                                                           * 4613676            * 4613675 users:(("herdr",pid=1261717,fd=9))
u_str ESTAB 0      0                                                           * 4613674            * 4610003 users:(("herdr",pid=1261717,fd=11),("herdr",pid=1261717,fd=4))
u_str ESTAB 0      0                                                           * 4790768            * 4790767 users:(("herdr",pid=1306502,fd=9))
u_str ESTAB 0      0                                                           * 4613675            * 4613676 users:(("herdr",pid=1261717,fd=10),("herdr",pid=1261717,fd=8))
u_str ESTAB 0      0                  /home/raul/.config/herdr/herdr-client.sock 4791774            * 4790730 users:(("herdr",pid=300644,fd=32),("herdr",pid=300644,fd=31))
u_str ESTAB 0      0                  /home/raul/.config/herdr/herdr-client.sock 4610003            * 4613674 users:(("herdr",pid=300644,fd=18),("herdr",pid=300644,fd=17))
u_str ESTAB 0      0                                                           * 4790730            * 4791774 users:(("herdr",pid=1306502,fd=11),("herdr",pid=1306502,fd=4))
u_str ESTAB 0      0                                                           * 1201998            * 1201999 users:(("herdr",pid=300644,fd=11),("herdr",pid=300644,fd=9))
u_str ESTAB 0      0                                                           * 1201999            * 1201998 users:(("herdr",pid=300644,fd=10))
"""

# Process chain of the one-client sample: herdr client 1336591 under mosh-server 1336590.
MOSH_ARGS = (
    "/usr/bin/mosh-server", "new", "-s", "-c", "256", "-l", "LANG=C.utf8",
    "-l", "MOSHI_CLIENT=1", "--", "sh", "-lc", "exec herdr --session 'default'",
)  # fmt: skip
CLIENT_ARGS = ("/home/raul/.local/bin/herdr", "--session", "default")


@pytest.fixture(scope="module")
def vc() -> ModuleType:
    spec = importlib.util.spec_from_file_location("viewer_check", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["viewer_check"] = module  # dataclasses resolve annotations through it
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True  # keep the plugin dir clean
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def table(vc: ModuleType, procs: dict[int, tuple[int, tuple[str, ...], tuple[str, ...]]]):
    """Fake process reader: pid -> (ppid, args, env); unknown pids are unreadable."""

    def read(pid: int):
        if pid not in procs:
            return None
        ppid, args, env = procs[pid]
        return vc.Proc(ppid, args, env)

    return read


# ---------- detect(): the decision ----------


def test_one_client_marker_in_own_args_is_moshi(vc):
    reader = table(vc, {1336591: (1336590, CLIENT_ARGS + ("MOSHI_CLIENT=1",), ())})
    assert vc.detect(ONE_CLIENT_SS, SOCKET, reader) == "moshi"


def test_one_client_marker_in_parent_args_is_moshi(vc):
    reader = table(
        vc,
        {1336591: (1336590, CLIENT_ARGS, ()), 1336590: (1, MOSH_ARGS, ())},
    )
    assert vc.detect(ONE_CLIENT_SS, SOCKET, reader) == "moshi"


def test_marker_only_in_ancestor_environment_is_moshi(vc):
    reader = table(
        vc,
        {
            1336591: (1336590, CLIENT_ARGS, ("TERM=xterm",)),
            1336590: (4000, ("mosh-server",), ("PATH=/bin", "MOSHI_CLIENT=1")),
            4000: (1, ("sh",), ()),
        },
    )
    assert vc.detect(ONE_CLIENT_SS, SOCKET, reader) == "moshi"


def test_one_client_without_marker_is_unsure(vc):
    reader = table(
        vc,
        {
            1336591: (1336590, CLIENT_ARGS, ("TERM=xterm",)),
            1336590: (1, ("sshd", "-D"), ("PATH=/bin",)),
        },
    )
    assert vc.detect(ONE_CLIENT_SS, SOCKET, reader) == "unsure"


@pytest.mark.parametrize(
    "args, env",
    [
        (("MOSHI_CLIENT=0",), ()),
        (("MOSHI_CLIENT=10",), ()),
        (("sh", "-lc", "x; MOSHI_CLIENT=1 herdr"), ()),  # substring, not an argument
        ((), ("XMOSHI_CLIENT=1",)),
        ((), ("MOSHI_CLIENT=",)),
    ],
)
def test_near_miss_markers_are_unsure(vc, args, env):
    reader = table(vc, {1336591: (1, args, env)})
    assert vc.detect(ONE_CLIENT_SS, SOCKET, reader) == "unsure"


def test_two_clients_real_sample_is_unsure_even_if_both_are_moshi(vc):
    marked = (CLIENT_ARGS + ("MOSHI_CLIENT=1",), ())
    reader = table(vc, {1306502: (1, *marked), 1261717: (1, *marked)})
    assert vc.detect(TWO_CLIENTS_SS, SOCKET, reader) == "unsure"


def test_no_clients_is_unsure(vc):
    server_only = "\n".join(
        line for line in ONE_CLIENT_SS.splitlines() if "herdr-client.sock" not in line
    )
    reader = table(vc, {1336591: (1, ("MOSHI_CLIENT=1",), ())})
    assert vc.detect(server_only, SOCKET, reader) == "unsure"
    assert vc.detect("", SOCKET, reader) == "unsure"


def test_other_socket_directory_is_not_this_herdr(vc):
    reader = table(vc, {1336591: (1, ("MOSHI_CLIENT=1",), ())})
    other = "/home/raul/other/herdr-client.sock"
    assert vc.detect(ONE_CLIENT_SS, other, reader) == "unsure"


def test_unreadable_process_data_is_unsure(vc):
    assert vc.detect(ONE_CLIENT_SS, SOCKET, table(vc, {})) == "unsure"
    # The client is readable but its parent is not: no marker can be shown.
    reader = table(vc, {1336591: (1336590, CLIENT_ARGS, ())})
    assert vc.detect(ONE_CLIENT_SS, SOCKET, reader) == "unsure"


def test_marker_beyond_pid_one_is_not_considered(vc):
    reader = table(
        vc,
        {1336591: (1, CLIENT_ARGS, ()), 1: (0, ("init", "MOSHI_CLIENT=1"), ())},
    )
    assert vc.detect(ONE_CLIENT_SS, SOCKET, reader) == "unsure"


def test_parent_cycle_terminates_as_unsure(vc):
    reader = table(vc, {10: (11, ("a",), ()), 11: (10, ("b",), ())})
    ss = ONE_CLIENT_SS.replace("pid=1336591", "pid=10")
    assert vc.detect(ss, SOCKET, reader) == "unsure"


@pytest.mark.parametrize(
    "ss_text",
    [
        "",
        "garbage\n\x00\xff not ss output\n",
        "Netid State Recv-Q Send-Q Local Address:Port Peer Address:Port Process\n",
        "u_str ESTAB 0 0\n",
        f"u_str ESTAB 0 0 {SOCKET} notanumber * notanumber\n",
        # Server row whose far end is missing, or listed without any process.
        f"u_str ESTAB 0 0 {SOCKET} 1 * 2 users:((\"herdr\",pid=5,fd=1))\n",
        f"u_str ESTAB 0 0 {SOCKET} 1 * 2\nu_str ESTAB 0 0 * 2 * 1\n",
    ],
)
def test_malformed_or_unusable_input_is_unsure(vc, ss_text):
    reader = table(vc, {5: (1, ("MOSHI_CLIENT=1",), ())})
    assert vc.detect(ss_text, SOCKET, reader) == "unsure"


def test_far_end_shared_by_two_processes_is_unsure(vc):
    ss = ONE_CLIENT_SS.replace(
        '("herdr",pid=1336591,fd=4)', '("herdr",pid=1336591,fd=4),("herdr",pid=99,fd=4)'
    )
    reader = table(vc, {1336591: (1, ("MOSHI_CLIENT=1",), ()), 99: (1, ("x",), ())})
    assert vc.detect(ss, SOCKET, reader) == "unsure"


# ---------- read_proc(): parsing /proc ----------


def make_proc(root: Path, pid: int, stat: str, cmdline: bytes | None, environ: bytes | None):
    d = root / str(pid)
    d.mkdir(parents=True)
    (d / "stat").write_text(stat)
    if cmdline is not None:
        (d / "cmdline").write_bytes(cmdline)
    if environ is not None:
        (d / "environ").write_bytes(environ)


def test_read_proc_parses_stat_cmdline_and_environ(vc, tmp_path):
    make_proc(
        tmp_path, 7, "7 (we ird) name) S 42 7 7 0 -1", b"a\0MOSHI_CLIENT=1\0", b"K=V\0MOSHI_CLIENT=1\0"
    )
    proc = vc.read_proc(7, tmp_path)
    assert proc.ppid == 42
    assert "MOSHI_CLIENT=1" in proc.args
    assert "MOSHI_CLIENT=1" in proc.env


def test_read_proc_tolerates_unreadable_cmdline_and_environ(vc, tmp_path):
    make_proc(tmp_path, 8, "8 (x) S 3 8 8 0 -1", None, None)
    proc = vc.read_proc(8, tmp_path)
    assert (proc.ppid, proc.args, proc.env) == (3, (), ())


@pytest.mark.parametrize("stat", ["", "garbage", "9 (x) S", "9 (x) S notanumber 1"])
def test_read_proc_unusable_stat_is_none(vc, tmp_path, stat):
    make_proc(tmp_path, 9, stat, b"", b"")
    assert vc.read_proc(9, tmp_path) is None


def test_read_proc_missing_process_is_none(vc, tmp_path):
    assert vc.read_proc(123456, tmp_path) is None


def test_read_proc_feeds_detect_through_a_fake_proc_tree(vc, tmp_path):
    make_proc(tmp_path, 1336591, "1336591 (herdr) S 1336590 1 1 0 -1", b"herdr\0", b"A=B\0")
    make_proc(tmp_path, 1336590, "1336590 (mosh-server) S 1 1 1 0 -1", b"mosh-server\0-l\0MOSHI_CLIENT=1\0", b"")
    reader = lambda pid: vc.read_proc(pid, tmp_path)  # noqa: E731
    assert vc.detect(ONE_CLIENT_SS, SOCKET, reader) == "moshi"


# ---------- socket path ----------


def test_client_socket_sits_beside_the_server_socket(vc, monkeypatch):
    monkeypatch.setenv("HERDR_SOCKET_PATH", "/run/h/herdr.sock")
    assert vc.client_socket_path() == "/run/h/herdr-client.sock"
    monkeypatch.delenv("HERDR_SOCKET_PATH")
    assert vc.client_socket_path() == os.path.expanduser("~/.config/herdr/herdr-client.sock")
    monkeypatch.setenv("HERDR_SOCKET_PATH", "")
    assert vc.client_socket_path() == os.path.expanduser("~/.config/herdr/herdr-client.sock")


# ---------- main() / the script entry point ----------


def test_main_prints_moshi_for_the_real_sample(vc, monkeypatch, capsys):
    monkeypatch.setenv("HERDR_SOCKET_PATH", "/home/raul/.config/herdr/herdr.sock")
    monkeypatch.setattr(vc, "run_ss", lambda: ONE_CLIENT_SS)
    reader = table(vc, {1336591: (1336590, CLIENT_ARGS, ()), 1336590: (1, MOSH_ARGS, ())})
    monkeypatch.setattr(vc, "read_proc", reader)
    assert vc.main() == 0
    assert capsys.readouterr().out == "moshi\n"


@pytest.mark.parametrize("exc", [OSError("no ss"), RuntimeError("boom"), ValueError("x")])
def test_main_survives_any_failure(vc, monkeypatch, capsys, exc):
    def explode():
        raise exc

    monkeypatch.setattr(vc, "run_ss", explode)
    assert vc.main() == 0
    assert capsys.readouterr().out == "unsure\n"


def test_main_survives_a_failing_process_reader(vc, monkeypatch, capsys):
    monkeypatch.setattr(vc, "run_ss", lambda: ONE_CLIENT_SS)
    monkeypatch.setattr(vc, "read_proc", lambda pid: 1 / 0)
    assert vc.main() == 0
    assert capsys.readouterr().out == "unsure\n"


def run_script(tmp_path: Path, fake_ss: str | None) -> subprocess.CompletedProcess[str]:
    """Run the real script with a fake `ss` first (and only) on PATH."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if fake_ss is not None:
        ss = bin_dir / "ss"
        ss.write_text(fake_ss)
        ss.chmod(0o755)
    env = {**os.environ, "PATH": str(bin_dir), "HERDR_SOCKET_PATH": str(tmp_path / "herdr.sock")}
    return subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, env=env, timeout=30
    )


@pytest.mark.parametrize(
    "fake_ss",
    [
        None,  # ss missing
        "#!/bin/sh\necho oops >&2\nexit 1\n",
        "#!/bin/sh\nexit 0\n",
        "#!/bin/sh\nprintf 'not ss output\\n\\377\\n'\n",
        "#!/bin/sh\nkill -9 $$\n",  # ss killed by a signal
    ],
)
def test_script_entry_point_always_exits_zero_with_one_word(tmp_path, fake_ss):
    result = run_script(tmp_path, fake_ss)
    assert result.returncode == 0
    assert result.stdout == "unsure\n"


def test_script_entry_point_answers_moshi_for_a_real_marked_process(tmp_path):
    # A live process whose argument list carries the marker stands in for the client.
    client = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)", "MOSHI_CLIENT=1"]
    )
    try:
        sock = tmp_path / "herdr-client.sock"
        ss_output = (
            f"u_str ESTAB 0 0 {sock} 20 * 10 users:((\"herdr\",pid=1,fd=1))\n"
            f"u_str ESTAB 0 0 * 10 * 20 users:((\"herdr\",pid={client.pid},fd=4))\n"
        )
        (tmp_path / "ss.txt").write_text(ss_output)
        result = run_script(tmp_path, f"#!/bin/sh\n{shutil.which('cat')} {tmp_path}/ss.txt\n")
    finally:
        client.kill()
        client.wait()
    assert (result.returncode, result.stdout) == (0, "moshi\n")


def test_script_is_executable_python3():
    assert os.access(SCRIPT, os.X_OK)
    assert SCRIPT.read_text().splitlines()[0] == "#!/usr/bin/env python3"
