from __future__ import annotations

import ctypes
import http.client
import importlib.util
import json
import os
from pathlib import Path
import re
import select
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
from typing import Any, Callable

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "plugins/revdiff-herdr-claude/scripts/web-plan-review.py"
BLOCK_RE = re.compile(r"<(h[1-6]|p|li|tr|figure|pre|blockquote)\b")
LONG_WORDS = [" ".join(["word"] * 8), " ".join(["word"] * 22)]
STALE_PAGE_MESSAGE = "this page is from an earlier review; reload it to see the current plan"
REFUSAL = 'refused: this page only answers on 127.0.0.1 or localhost (got host "{}")'

PLAN_LINES = [
    "<!-- web-plan -->",
    "<h1>Add cache layer &amp; metrics</h1>",
    "<p>" + LONG_WORDS[0],
    LONG_WORDS[1] + "</p>",
    "<h2>Steps</h2>",
    "<ul>",
    "  <li>First step</li>",
    "  <li>Second step",
    "    <ul><li>nested</li></ul></li>",
    "</ul>",
    "<table>",
    "  <tr><th>Name</th> <th>Value</th></tr>",
    "  <tr><td>alpha</td> <td>beta</td></tr>",
    "</table>",
    "<figure>",
    '  <svg viewBox="0 0 10 10"><text x="1" y="5">diagram</text></svg>',
    "  <figcaption>Cache flow</figcaption>",
    "</figure>",
    "<pre>",
    "first &lt;line&gt;",
    "  second line",
    "</pre>",
    "<blockquote>",
    "  <p>Quoted text</p>",
    "</blockquote>",
    "<p",
    '  class="note">Split start tag</p>',
    "<p>one</p><p>two</p>",
]
PLAN = "\n".join(PLAN_LINES) + "\n"

# Stand-in for `moshi-hook servers`: like the real lister it only lists a
# server it can fetch the page from. The test tells it the port through a file
# and the stand-in waits for that file, so the single check never races the test.
FAKE_MOSHI = """#!{python}
import json, os, sys, time, urllib.request

mode = os.environ.get("FAKE_MOSHI_MODE", "list")
if mode == "fail":
    sys.exit(1)
if mode == "garbage":
    print("not json")
    sys.exit(0)
servers = [{{"port": 8001, "host": "127.0.0.1"}}]
port_file = os.environ["FAKE_MOSHI_PORT_FILE"]
deadline = time.monotonic() + 10
while not os.path.exists(port_file) and time.monotonic() < deadline:
    time.sleep(0.02)
try:
    port = int(open(port_file).read())
    with urllib.request.urlopen(f"http://127.0.0.1:{{port}}/", timeout=5) as page:
        if page.status == 200:
            servers.append({{"port": port, "host": "127.0.0.1"}})
except (OSError, ValueError):
    pass
print(json.dumps({{"servers": servers}}))
"""


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def load_script() -> Any:
    spec = importlib.util.spec_from_file_location("web_plan_review", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True  # keep bytecode out of the plugin directory
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def line_of(needle: str) -> int:
    return next(i for i, text in enumerate(PLAN_LINES, 1) if needle in text)


def request_with_host(
    port: int, method: str, path: str, host: str | None, body: bytes | None = None
) -> tuple[int, http.client.HTTPMessage, bytes]:
    """Like Client.request, but with exactly this Host header (none at all when host is None)."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        if host is not None:
            conn.putheader("Host", host)
        if body is not None:
            conn.putheader("Content-Length", str(len(body)))
        conn.endheaders(body)
        response = conn.getresponse()
        return response.status, response.headers, response.read()
    finally:
        conn.close()


def script_function(page: str, header: str) -> str:
    """The body of one function in the page script, found by its declaration line."""
    match = re.search(rf"{re.escape(header)} \{{(.*?)\n  \}}", page, re.S)
    assert match, header
    return match[1]


class Client:
    """Talks to the review server on a local port."""

    def __init__(self, port: int) -> None:
        self.port = port
        self._token: str | None = None

    def request(
        self, method: str, path: str, body: bytes | None = None
    ) -> tuple[int, http.client.HTTPMessage, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, body=body)
            response = conn.getresponse()
            return response.status, response.headers, response.read()
        finally:
            conn.close()

    def page(self) -> str:
        return self.request("GET", "/")[2].decode()

    @property
    def token(self) -> str:
        if self._token is None:
            match = re.search(r'const TOKEN = "([0-9a-f]+)"', self.page())
            assert match
            self._token = match[1]
        return self._token

    def post(self, payload: Any) -> int:
        return self.request("POST", "/submit", json.dumps(payload).encode())[0]

    def submit(self, comments: list[dict[str, Any]], token: str | None = None) -> int:
        return self.post({"token": self.token if token is None else token, "comments": comments})


class Session(Client):
    """A review process started by the test, with its client."""

    def __init__(self, proc: subprocess.Popen[str], port: int) -> None:
        super().__init__(port)
        self.proc = proc

    def finish(self, timeout: float = 20) -> tuple[int, str, str]:
        out, err = self.proc.communicate(timeout=timeout)
        return self.proc.returncode, out, err


@pytest.fixture
def fake_moshi(tmp_path: Path) -> dict[str, Any]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stand_in = bin_dir / "moshi-hook"
    stand_in.write_text(FAKE_MOSHI.format(python=sys.executable))
    stand_in.chmod(0o755)
    port_file = tmp_path / "moshi-port"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "FAKE_MOSHI_PORT_FILE": str(port_file),
        "WEB_PLAN_PORT": "0",  # any free port: tests stay parallel-safe and never touch the real review port
    }
    return {"env": env, "port_file": port_file}


@pytest.fixture
def plan_file(tmp_path: Path) -> Path:
    path = tmp_path / "plan.html"
    path.write_text(PLAN)
    return path


def read_port(proc: subprocess.Popen[str]) -> int:
    assert proc.stderr is not None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        ready, _, _ = select.select([proc.stderr], [], [], 0.2)
        if not ready:
            continue
        line = proc.stderr.readline()
        assert line, f"exited before serving: {proc.wait()}"
        match = re.search(r"127\.0\.0\.1:(\d+)", line)
        if match:
            return int(match[1])
    raise AssertionError("no server address reported")


@pytest.fixture
def launch(tmp_path: Path, fake_moshi: dict[str, Any], plan_file: Path):
    procs: list[subprocess.Popen[str]] = []

    def start(
        args: list[str] | None = None,
        *,
        list_port: bool = True,
        mode: str = "list",
        env: dict[str, str] | None = None,
    ) -> Session:
        proc = subprocess.Popen(
            [sys.executable, str(SCRIPT), *(args or [f"--only={plan_file}"])],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**fake_moshi["env"], "FAKE_MOSHI_MODE": mode, **(env or {})},
        )
        procs.append(proc)
        port = read_port(proc)
        fake_moshi["port_file"].write_text(str(port) if list_port else "not listed")
        return Session(proc, port)

    yield start
    for proc in procs:
        if proc.poll() is None:
            proc.kill()
        proc.communicate()


Launch = Callable[..., Session]


def run_script(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        env=env,
        timeout=20,
        check=False,
    )


def test_script_is_executable() -> None:
    assert os.access(SCRIPT, os.X_OK)
    assert SCRIPT.read_text().splitlines()[0] == "#!/usr/bin/env python3"


def test_serves_page_at_root_with_csp_title_and_viewport(launch: Launch, plan_file: Path) -> None:
    session = launch()
    status, headers, body = session.request("GET", "/")
    page = body.decode()
    nonces = re.findall(r'<script nonce="([0-9a-f]+)"', page)
    assert status == 200
    assert headers["Content-Type"].startswith("text/html")
    assert len(nonces) == 1
    assert headers["Content-Security-Policy"] == (
        "default-src 'none'; style-src 'unsafe-inline'; "
        f"script-src 'nonce-{nonces[0]}'; connect-src 'self'; img-src data:"
    )
    assert page.startswith("<!doctype html>")
    assert '<meta charset="utf-8">' in page
    assert 'name="viewport"' in page
    assert "<title>Add cache layer &amp; metrics</title>" in page
    assert "prefers-color-scheme:dark" in page
    assert "{{" not in page
    # The plan content is served as written; only data-line stamps are added.
    assert re.sub(r' data-line="\d+"', "", page).count(PLAN.strip()) == 1
    assert session.request("GET", "/?probe=1")[0] == 200
    assert session.post({"token": session.token, "comments": []}) == 200
    assert session.finish()[0] == 0


def test_title_falls_back_without_a_heading(tmp_path: Path, launch: Launch) -> None:
    path = tmp_path / "no-heading.html"
    path.write_text("<!-- web-plan -->\n<p>Just a paragraph</p>\n")
    session = launch([f"--only={path}"])
    assert "<title>Plan review</title>" in session.page()
    session.post({"token": session.token, "comments": []})
    assert session.finish()[0] == 0


def test_other_paths_are_404(launch: Launch) -> None:
    session = launch()
    assert [session.request("GET", p)[0] for p in ("/index.html", "/submit", "/x/", "//x")] == [404] * 4
    assert session.request("POST", "/other", b"{}")[0] == 404
    assert session.proc.poll() is None
    session.post({"token": session.token, "comments": []})
    assert session.finish()[0] == 0


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "127.0.0.1:47821", "localhost", "localhost:8080", "LOCALHOST", "LocalHost:80", "[::1]", "[::1]:8080"],
)
def test_local_host_names_get_the_page_and_can_submit(launch: Launch, host: str) -> None:
    session = launch()
    status, headers, body = request_with_host(session.port, "GET", "/", host)
    assert status == 200
    assert f'const TOKEN = "{session.token}"' in body.decode()
    assert "Content-Security-Policy" in headers
    payload = json.dumps({"token": session.token, "comments": []}).encode()
    assert request_with_host(session.port, "POST", "/submit", host, payload)[0] == 200
    assert session.finish()[0] == 0


@pytest.mark.parametrize(
    "host",
    [
        "evil.example",
        "evil.example:47821",
        "10.0.0.1",
        "10.0.0.1:47821",
        "0.0.0.0",
        "127.0.0.1.evil.example",
        "localhost.evil.example",
        "user@127.0.0.1",
        "127.0.0.1@evil.example",
        "127.0.0.1:port",
        "127.0.0.1 evil.example",
        "::1",
        "[::1",
        "[::2]",
        "",
        None,
    ],
    ids=repr,
)
def test_other_host_names_are_refused_and_do_not_use_up_the_submit(launch: Launch, host: str | None) -> None:
    session = launch()
    token = session.token
    status, headers, body = request_with_host(session.port, "GET", "/", host)
    assert status == 403
    assert headers["Content-Type"] == "text/plain; charset=utf-8"
    assert "Content-Security-Policy" not in headers
    assert body.decode().startswith('refused: this page only answers on 127.0.0.1 or localhost (got host "')
    assert token not in body.decode()
    # The host is checked before the path, so even an unknown path is refused, not 404.
    assert request_with_host(session.port, "GET", "/index.html", host)[0] == 403
    # A refused submit carries the valid token and still must not be taken.
    payload = json.dumps({"token": token, "comments": [{"line": None, "text": "from a rebound page"}]}).encode()
    status, _, body = request_with_host(session.port, "POST", "/submit", host, payload)
    assert status == 403
    assert body.decode().startswith("refused: ")
    assert token not in body.decode()
    assert session.proc.poll() is None
    assert session.submit([{"line": None, "text": "the real answer"}]) == 200
    code, out, _ = session.finish()
    assert (code, out) == (10, "## plan.html (file-level)\nthe real answer\n")


def test_refusal_text_shows_the_received_host_escaped_and_cut(launch: Launch) -> None:
    session = launch()
    body = request_with_host(session.port, "GET", "/", "10.0.0.1:80")[2].decode()
    assert body == REFUSAL.format("10.0.0.1:80")
    assert request_with_host(session.port, "GET", "/", None)[2].decode() == REFUSAL.format("")
    # A control character is escaped and the value is cut to 80 characters.
    body = request_with_host(session.port, "GET", "/", "x\x01" + "a" * 200)[2].decode()
    assert body == REFUSAL.format("x\\x01" + "a" * 78)
    assert session.submit([]) == 200
    assert session.finish()[0] == 0


def test_stamped_lines_match_the_source_lines_of_the_blocks(launch: Launch) -> None:
    session = launch()
    stamped = re.findall(r'<(\w+)\b[^>]*?\bdata-line="(\d+)"', session.page())
    # Independent reading of the source: the first block tag starting on each
    # line. That covers a start tag split over two lines (stamped where it
    # begins) and a line holding two blocks (only the first is commentable).
    expected = [(m[1], i) for i, text in enumerate(PLAN_LINES, 1) if (m := BLOCK_RE.search(text))]
    assert [(tag, int(line)) for tag, line in stamped] == expected
    assert len(expected) == 14
    assert ("p", PLAN_LINES.index("<p") + 1) in expected
    assert ("p", line_of("<p>one</p>")) in expected
    session.post({"token": session.token, "comments": []})
    assert session.finish()[0] == 0


def test_comments_are_printed_with_line_quote_and_text(launch: Launch) -> None:
    session = launch()
    steps, words, nested, row = line_of("<h2>Steps"), line_of("<p>word"), line_of("Second step"), line_of("alpha")
    status = session.submit(
        [
            {"line": None, "text": "Overall fine\nwith two lines"},
            {"line": row, "text": "Check this row"},
            {"line": nested, "text": "Nested needs a test"},
            {"line": words, "text": "  Too long  "},
            {"line": steps, "text": "Rename"},
        ]
    )
    code, out, _ = session.finish()
    cut = " ".join(["word"] * 16) + "\u2026"  # whitespace collapsed, then cut to 80
    assert status == 200
    assert code == 10
    assert out == (
        f"## plan.html:{words} ( )\n> {cut}\nToo long\n\n"
        f"## plan.html:{steps} ( )\n> Steps\nRename\n\n"
        f"## plan.html:{nested} ( )\n> Second step nested\nNested needs a test\n\n"
        f"## plan.html:{row} ( )\n> alpha beta\nCheck this row\n\n"
        "## plan.html (file-level)\nOverall fine\nwith two lines\n"
    )
    assert len(cut) == 80


def test_no_comments_gives_empty_stdout_and_exit_zero(launch: Launch) -> None:
    session = launch()
    assert session.submit([]) == 200
    code, out, _ = session.finish()
    assert (code, out) == (0, "")


def test_blank_comments_are_dropped(launch: Launch) -> None:
    session = launch()
    assert session.submit([{"line": 2, "text": "   "}, {"line": None, "text": ""}]) == 200
    code, out, _ = session.finish()
    assert (code, out) == (0, "")


def test_blank_comments_are_dropped_next_to_real_ones(launch: Launch) -> None:
    session = launch()
    assert session.submit([{"line": 2, "text": " "}, {"line": None, "text": "Keep me"}]) == 200
    code, out, _ = session.finish()
    assert (code, out) == (10, "## plan.html (file-level)\nKeep me\n")


def test_wrong_token_is_rejected_and_the_review_stays_open(launch: Launch) -> None:
    session = launch()
    good = {"line": None, "text": "late but valid"}
    for payload in ({"token": "wrong", "comments": [good]}, {"comments": [good]}, {"token": 5, "comments": [good]}):
        status, _, body = session.request("POST", "/submit", json.dumps(payload).encode())
        assert (status, json.loads(body)) == (403, {"error": STALE_PAGE_MESSAGE})
    assert session.request("POST", "/submit", b"not json")[0] == 400
    assert session.proc.poll() is None
    assert session.submit([good]) == 200
    code, out, _ = session.finish()
    assert (code, out) == (10, "## plan.html (file-level)\nlate but valid\n")


# Lines 1, 4, 6, 10 and 27 exist in the file but no block starts on them.
@pytest.mark.parametrize("line", [9999, 0, -1, 1, 4, 6, 10, 27, "5", True, 5.0, [5]])
def test_unknown_line_is_rejected_and_the_review_stays_open(launch: Launch, line: Any) -> None:
    session = launch()
    assert session.submit([{"line": line, "text": "x"}]) == 400
    assert session.post({"token": session.token, "comments": "x"}) == 400
    assert session.proc.poll() is None
    assert session.submit([]) == 200
    assert session.finish()[0] == 0


def test_second_submit_is_not_accepted(launch: Launch) -> None:
    session = launch()
    outcomes: list[Any] = []

    def send(text: str) -> None:
        try:
            outcomes.append(session.submit([{"line": None, "text": text}]))
        except (OSError, http.client.HTTPException) as exc:
            outcomes.append(exc)

    threads = [threading.Thread(target=send, args=(t,)) for t in ("first answer", "second answer")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    code, out, _ = session.finish()
    assert outcomes.count(200) == 1
    assert code == 10
    assert out.count("(file-level)") == 1
    with pytest.raises((OSError, http.client.HTTPException)):
        session.submit([{"line": None, "text": "third"}])


def test_page_keeps_its_controls_and_svg_class_interface(launch: Launch) -> None:
    session = launch()
    page = session.page()
    for control in ("general", "send", "none", "status", "count", "noun"):
        assert f'id="{control}"' in page
    # Plan authors draw diagrams with these class names; the page must style each.
    for name in ("node", "dot", "ic", "lbl", "sub", "wire", "loop", "pill", "pilltxt"):
        assert re.search(rf"svg \.{name}\{{", page), name
    session.post({"token": session.token, "comments": []})
    assert session.finish()[0] == 0


def test_page_script_keeps_no_comments_off_while_text_is_typed(launch: Launch) -> None:
    # The suite has no browser, so this checks the served script; the behaviour was also run in one.
    session = launch()
    page = session.page()
    update = script_function(page, "function update()")
    busy = script_function(page, "function busy(on)")
    assert "const n = filled().length;" in update
    assert "send.disabled = n === 0;" in update
    assert "none.disabled = n > 0;" in update
    assert "const n = filled().length;" in busy
    assert "send.disabled = on || n === 0;" in busy
    assert "none.disabled = on || n > 0;" in busy
    assert session.submit([]) == 200
    assert session.finish()[0] == 0


def test_page_script_shows_only_the_server_text_for_a_refused_submit(launch: Launch) -> None:
    session = launch()
    page = session.page()
    submit = script_function(page, "async function submit(withComments)")
    assert "{status: r.status}" in submit
    assert 'const retry = e.status === 403 ? "" : ". Your text is still here; try again.";' in submit
    assert 'status.textContent = "Not sent: " + e.message + retry;' in submit
    assert page.count("Your text is still here; try again.") == 1
    assert session.submit([]) == 200
    assert session.finish()[0] == 0


def test_page_loads_nothing_external(launch: Launch) -> None:
    session = launch()
    page = session.page()
    targets = re.findall(r"url\(([^)]*)\)", page)
    assert targets
    assert all(target.startswith('"data:') for target in targets)
    assert "@import" not in page
    assert not re.search(r"<(link|img|iframe|script)\b[^>]*\b(src|href)=", page)
    session.post({"token": session.token, "comments": []})
    assert session.finish()[0] == 0


def test_aside_is_a_commentable_block(tmp_path: Path, launch: Launch) -> None:
    path = tmp_path / "aside.html"
    path.write_text(
        "<!-- web-plan -->\n<h1>Title</h1>\n<aside>Your call: keep failed files,\nor drop them?</aside>\n"
    )
    session = launch([f"--only={path}"])
    assert '<aside data-line="3">' in session.page()
    assert session.submit([{"line": 3, "text": "Drop them"}]) == 200
    code, out, _ = session.finish()
    assert (code, out) == (10, "## aside.html:3 ( )\n> Your call: keep failed files, or drop them?\nDrop them\n")


def test_default_port_is_fixed_and_the_override_is_parsed() -> None:
    script = load_script()
    assert script.DEFAULT_PORT == 47821
    assert script.configured_port({}) == script.DEFAULT_PORT
    assert script.configured_port({"WEB_PLAN_PORT": "0"}) == 0
    assert script.configured_port({"WEB_PLAN_PORT": "65535"}) == 65535


def test_port_override_is_honoured(launch: Launch) -> None:
    port = free_port()
    session = launch(env={"WEB_PLAN_PORT": str(port)})
    assert session.port == port
    assert session.request("GET", "/")[0] == 200
    session.post({"token": session.token, "comments": []})
    assert session.finish()[0] == 0


def test_busy_port_fails_with_a_clear_message(fake_moshi: dict[str, Any], plan_file: Path) -> None:
    with socket.socket() as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen()
        port = holder.getsockname()[1]
        result = run_script([f"--only={plan_file}"], {**fake_moshi["env"], "WEB_PLAN_PORT": str(port)})
    assert result.returncode == 1
    assert result.stdout == ""
    assert f"port {port} is in use; another plan review may be open" in result.stderr


@pytest.mark.parametrize("value", ["abc", "-1", "65536", "", "1.5", " 80", "0x50", "99999999", "٨٠"])
def test_invalid_port_fails_before_serving(fake_moshi: dict[str, Any], plan_file: Path, value: str) -> None:
    result = run_script([f"--only={plan_file}"], {**fake_moshi["env"], "WEB_PLAN_PORT": value})
    assert result.returncode == 1
    assert result.stdout == ""
    assert "WEB_PLAN_PORT" in result.stderr
    assert "serving" not in result.stderr


@pytest.mark.parametrize("kind", ["missing", "empty", "blank", "directory"])
def test_unusable_plan_file_fails(tmp_path: Path, fake_moshi: dict[str, Any], kind: str) -> None:
    path = tmp_path / "unusable.html"
    if kind == "directory":
        path.mkdir()
    elif kind != "missing":
        path.write_text("" if kind == "empty" else "  \n\t\n")
    result = run_script([f"--only={path}"], fake_moshi["env"])
    assert result.returncode not in (0, 10)
    assert result.stdout == ""
    assert result.stderr.strip()


def test_fails_when_moshi_does_not_list_the_port(launch: Launch) -> None:
    session = launch(list_port=False)
    code, out, err = session.finish()
    assert code not in (0, 10)
    assert out == ""
    assert "moshi-hook" in err


@pytest.mark.parametrize("mode", ["fail", "garbage"])
def test_fails_when_moshi_hook_errors(launch: Launch, mode: str) -> None:
    session = launch(mode=mode)
    code, out, err = session.finish()
    assert code not in (0, 10)
    assert out == ""
    assert "moshi-hook" in err


def test_fails_when_moshi_hook_is_missing(tmp_path: Path, plan_file: Path) -> None:
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    result = run_script([f"--only={plan_file}"], {**os.environ, "PATH": str(empty), "WEB_PLAN_PORT": "0"})
    assert result.returncode not in (0, 10)
    assert result.stdout == ""
    assert "moshi-hook is not on PATH" in result.stderr


def test_compare_form_reviews_the_new_file(tmp_path: Path, launch: Launch) -> None:
    old, new = tmp_path / "old-rev.html", tmp_path / "new-rev.html"
    old.write_text("<!-- web-plan -->\n<h1>Old title</h1>\n<p>old text</p>\n")
    new.write_text("<!-- web-plan -->\n<h1>New title</h1>\n<p>new text</p>\n")
    session = launch([f"--compare-old={old}", f"--compare-new={new}"])
    page = session.page()
    assert "<title>New title</title>" in page
    assert "old text" not in page
    assert session.submit([{"line": 3, "text": "Reword"}]) == 200
    code, out, _ = session.finish()
    assert (code, out) == (10, "## new-rev.html:3 ( )\n> new text\nReword\n")


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--bogus"],
        ["--help"],
        ["-h"],
        ["plan.html"],
        ["--only"],
        ["--only=a.html", "--compare-old=a", "--compare-new=b"],
        ["--only=a.html", "extra"],
        ["--compare-old=a"],
        ["--compare-new=b"],
    ],
)
def test_other_arguments_are_a_usage_error(fake_moshi: dict[str, Any], args: list[str]) -> None:
    result = run_script(args, fake_moshi["env"])
    assert result.returncode not in (0, 10)
    assert result.stdout == ""
    assert "usage" in result.stderr.lower()


def test_exits_by_itself_when_the_parent_is_gone(tmp_path: Path, fake_moshi: dict[str, Any], plan_file: Path) -> None:
    out_file, err_file = tmp_path / "out.txt", tmp_path / "err.txt"
    err_file.touch()
    command = (
        f"{shlex.quote(sys.executable)} {shlex.quote(str(SCRIPT))} --only={shlex.quote(str(plan_file))} "
        f"> {shlex.quote(str(out_file))} 2> {shlex.quote(str(err_file))} & echo $!; wait"
    )
    # Becoming a subreaper makes the orphan ours, so its exit status is visible.
    libc = ctypes.CDLL(None, use_errno=True)
    assert libc.prctl(36, 1, 0, 0, 0) == 0  # PR_SET_CHILD_SUBREAPER
    wrapper = subprocess.Popen(
        ["sh", "-c", command], stdout=subprocess.PIPE, text=True, env=fake_moshi["env"]
    )
    assert wrapper.stdout is not None
    pid = int(wrapper.stdout.readline())
    try:
        port = None
        deadline = time.monotonic() + 10
        while port is None and time.monotonic() < deadline:
            match = re.search(r"127\.0\.0\.1:(\d+)", err_file.read_text())
            port = int(match[1]) if match else None
            time.sleep(0.05)
        assert port
        fake_moshi["port_file"].write_text(str(port))
        session = Client(port)
        assert session.request("GET", "/")[0] == 200

        wrapper.kill()
        wrapper.wait()
        # The wrapper is dead: an answer now must not be taken.
        try:
            assert session.post({"token": session.token, "comments": []}) != 200
        except (OSError, http.client.HTTPException):
            pass

        status = None
        deadline = time.monotonic() + 10
        while status is None and time.monotonic() < deadline:
            done, raw = os.waitpid(pid, os.WNOHANG)
            status = raw if done else None
            time.sleep(0.05)
        assert status is not None, "the review kept running after its parent died"
        assert os.WIFEXITED(status) and os.WEXITSTATUS(status) not in (0, 10)
        assert out_file.read_text() == ""
        assert "parent" in err_file.read_text()
    finally:
        try:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
        except (ProcessLookupError, ChildProcessError):
            pass
        wrapper.kill()
        wrapper.wait()
        libc.prctl(36, 0, 0, 0, 0)
