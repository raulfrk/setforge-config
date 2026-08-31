#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugins/revdiff-herdr"
PLAN_LAUNCHER = PLUGIN_ROOT / "scripts/launch-plan-review.sh"
MANUAL_LAUNCHER = PLUGIN_ROOT / "skills/revdiff/scripts/launch-revdiff.sh"
HOOK = PLUGIN_ROOT / "scripts/codex-plan-review-hook.py"
BACKEND_ENV = {
    "AGTERM_SESSION_ID",
    "AGTERM_SOCKET",
    "HERDR_ENV",
    "HERDR_WORKSPACE_ID",
    "TMUX",
    "TMUX_PANE",
    "ZELLIJ",
    "ZELLIJ_PANE_ID",
}


class RevDiffHerdrTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="revdiff-herdr-test-"))
        self.fake_bin = self.temp / "bin"
        self.fake_bin.mkdir()
        self.log = self.temp / "calls.log"
        self.log.write_text("")
        self.plan = self.temp / "plan.md"
        self.plan.write_text("# Plan\n\nReview this Markdown plan.\n")
        self.old_plan = self.temp / "old-plan.md"
        self.old_plan.write_text("# Plan\n\nOld text.\n")
        self._write_fakes()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp)

    def _write_executable(self, name: str, body: str) -> None:
        path = self.fake_bin / name
        path.write_text(textwrap.dedent(body).lstrip())
        path.chmod(0o755)

    def _write_fakes(self) -> None:
        self._write_executable(
            "revdiff",
            r"""
            #!/usr/bin/env bash
            set -euo pipefail
            printf 'revdiff' >> "${TEST_LOG:?}"
            printf ' %q' "$@" >> "$TEST_LOG"
            printf '\n' >> "$TEST_LOG"
            output=''
            for arg in "$@"; do
                case "$arg" in --output=*) output=${arg#--output=} ;; esac
            done
            if [[ -n $output ]]; then
                printf '%s' "${TEST_ANNOTATIONS:-}" > "$output"
            fi
            exit "${TEST_REVDIFF_RC:-0}"
            """,
        )
        self._write_executable(
            "herdr",
            r"""
            #!/usr/bin/env bash
            set -euo pipefail
            printf 'herdr' >> "${TEST_LOG:?}"
            printf ' %q' "$@" >> "$TEST_LOG"
            printf '\n' >> "$TEST_LOG"
            case "${1:-} ${2:-}" in
                'tab create')
                    if [[ ${TEST_HERDR_MALFORMED:-0} == 1 ]]; then
                        printf '%s\n' '{}'
                    else
                        printf '%s\n' '{"result":{"tab":{"tab_id":"w-test:t1"},"root_pane":{"pane_id":"w-test:p1"}}}'
                    fi
                    ;;
                'pane run')
                    if [[ ${TEST_HERDR_PANE_FAIL:-0} == 1 ]]; then
                        exit 7
                    fi
                    sh -c "${4:?missing pane command}"
                    ;;
                'tab close') ;;
                *) exit 8 ;;
            esac
            """,
        )
        self._write_executable(
            "tmux",
            r"""
            #!/usr/bin/env bash
            set -euo pipefail
            printf 'tmux' >> "${TEST_LOG:?}"
            printf ' %q' "$@" >> "$TEST_LOG"
            printf '\n' >> "$TEST_LOG"
            if [[ ${1:-} == -V ]]; then
                printf '%s\n' 'tmux 3.4'
                exit 0
            fi
            while (($#)); do
                if [[ $1 == -c && ${2+x} ]]; then
                    sh -c "$2"
                    exit $?
                fi
                shift
            done
            exit 9
            """,
        )
        for name in ("agtermctl", "zellij"):
            self._write_executable(
                name,
                f"""
                #!/usr/bin/env bash
                printf '{name}' >> "${{TEST_LOG:?}}"
                printf ' %q' "$@" >> "$TEST_LOG"
                printf '\\n' >> "$TEST_LOG"
                exit 91
                """,
            )

    def _env(self, **overrides: str) -> dict[str, str]:
        env = os.environ.copy()
        for name in BACKEND_ENV:
            env.pop(name, None)
        env.update(
            {
                "PATH": f"{self.fake_bin}:/usr/bin:/bin",
                "TEST_LOG": str(self.log),
                "TMPDIR": str(self.temp),
            }
        )
        env.update(overrides)
        return env

    def _mixed_herdr_env(self, **overrides: str) -> dict[str, str]:
        values = {
            "HERDR_ENV": "1",
            "HERDR_WORKSPACE_ID": "w-test",
            "TMUX": "/tmp/fake-tmux,1,0",
            "TMUX_PANE": "%9",
            "AGTERM_SESSION_ID": "agterm-test",
            "AGTERM_SOCKET": "/tmp/agterm-test.sock",
            "ZELLIJ": "1",
            "ZELLIJ_PANE_ID": "7",
        }
        values.update(overrides)
        return self._env(**values)

    def _calls(self) -> str:
        return self.log.read_text()

    def test_plan_review_prefers_focused_herdr_tab_and_returns_annotations(self) -> None:
        result = subprocess.run(
            [str(PLAN_LAUNCHER), str(self.plan)],
            env=self._mixed_herdr_env(
                TEST_ANNOTATIONS="tighten the test plan",
                TEST_REVDIFF_RC="10",
            ),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 10, result.stderr)
        self.assertEqual(result.stdout, "tighten the test plan")
        calls = self._calls()
        self.assertIn("herdr tab create", calls)
        self.assertIn("--workspace w-test", calls)
        self.assertIn("--focus", calls)
        self.assertIn("herdr tab close w-test:t1", calls)
        self.assertIn(f"--only={self.plan}", calls)
        self.assertNotRegex(calls, r"(?m)^(tmux|agtermctl|zellij) ")

    def test_plan_compare_mode_keeps_markdown_and_collapses_revision_diff(self) -> None:
        result = subprocess.run(
            [str(PLAN_LAUNCHER), str(self.plan), str(self.old_plan)],
            env=self._mixed_herdr_env(),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self._calls()
        self.assertIn(f"--compare-old={self.old_plan}", calls)
        self.assertIn(f"--compare-new={self.plan}", calls)
        self.assertIn("--collapsed", calls)
        self.assertTrue(self.plan.name.endswith(".md"))

    def test_manual_review_prefers_herdr(self) -> None:
        result = subprocess.run(
            [str(MANUAL_LAUNCHER), f"--only={self.plan}"],
            env=self._mixed_herdr_env(),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self._calls()
        self.assertIn("herdr tab create", calls)
        self.assertIn("herdr pane run w-test:p1", calls)
        self.assertIn("herdr tab close w-test:t1", calls)
        self.assertNotRegex(calls, r"(?m)^(tmux|agtermctl|zellij) ")

    def test_non_herdr_session_preserves_upstream_tmux_selection(self) -> None:
        result = subprocess.run(
            [str(PLAN_LAUNCHER), str(self.plan)],
            env=self._env(TMUX="/tmp/fake-tmux,1,0", TMUX_PANE="%1"),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self._calls()
        self.assertRegex(calls, r"(?m)^tmux display-popup ")
        self.assertNotRegex(calls, r"(?m)^herdr ")

    def test_malformed_herdr_create_fails_without_falling_back_to_tmux(self) -> None:
        result = subprocess.run(
            [str(PLAN_LAUNCHER), str(self.plan)],
            env=self._mixed_herdr_env(TEST_HERDR_MALFORMED="1"),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("did not return pane/tab ids", result.stderr)
        self.assertNotRegex(self._calls(), r"(?m)^tmux ")

    def test_pane_run_failure_closes_created_tab(self) -> None:
        result = subprocess.run(
            [str(PLAN_LAUNCHER), str(self.plan)],
            env=self._mixed_herdr_env(TEST_HERDR_PANE_FAIL="1"),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("pane run failed", result.stderr)
        self.assertIn("herdr tab close w-test:t1", self._calls())

    def test_stop_hook_extracts_markdown_and_blocks_with_annotations(self) -> None:
        event = {
            "hook_event_name": "Stop",
            "permission_mode": "plan",
            "cwd": str(REPO_ROOT),
            "last_assistant_message": (
                "<proposed_plan># Hook plan\n\nMarkdown body.</proposed_plan>"
            ),
        }
        result = subprocess.run(
            ["python3", str(HOOK)],
            input=json.dumps(event),
            env=self._mixed_herdr_env(
                PLUGIN_ROOT=str(PLUGIN_ROOT),
                TEST_ANNOTATIONS="add a rollback check",
                TEST_REVDIFF_RC="10",
            ),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["decision"], "block")
        self.assertIn("add a rollback check", payload["reason"])
        marker = re.search(r"previous revision: (.+?) -->", payload["reason"])
        self.assertIsNotNone(marker)
        snapshot = Path(marker.group(1))
        try:
            self.assertEqual(snapshot.suffix, ".md")
            self.assertEqual(snapshot.read_text(), "# Hook plan\n\nMarkdown body.")
        finally:
            snapshot.unlink(missing_ok=True)
        self.assertNotRegex(self._calls(), r"(?m)^tmux ")


if __name__ == "__main__":
    unittest.main()
