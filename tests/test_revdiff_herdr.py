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
FORMATTER = PLUGIN_ROOT / "scripts/plan_review_format.py"
BACKEND_ENV = {
    "AGTERM_SESSION_ID",
    "AGTERM_SOCKET",
    "HERDR_ENV",
    "HERDR_TAB_ID",
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
            stdin_mode=0
            compare_old=''
            compare_new=''
            for arg in "$@"; do
                case "$arg" in
                    --output=*) output=${arg#--output=} ;;
                    --stdin) stdin_mode=1 ;;
                    --compare-old=*) compare_old=${arg#--compare-old=} ;;
                    --compare-new=*) compare_new=${arg#--compare-new=} ;;
                esac
            done
            if [[ $stdin_mode == 1 ]]; then
                if [[ -n ${TEST_STDIN_CAPTURE:-} ]]; then
                    cat > "$TEST_STDIN_CAPTURE"
                else
                    cat >/dev/null
                fi
            fi
            if [[ -n $compare_old && -n ${TEST_OLD_CAPTURE:-} ]]; then
                cp "$compare_old" "$TEST_OLD_CAPTURE"
            fi
            if [[ -n $compare_new && -n ${TEST_NEW_CAPTURE:-} ]]; then
                cp "$compare_new" "$TEST_NEW_CAPTURE"
            fi
            if [[ -n $output ]]; then
                printf '%s' "${TEST_ANNOTATIONS:-}" > "$output"
            fi
            if [[ -n ${TEST_REVDIFF_SLEEP:-} ]]; then
                sleep "$TEST_REVDIFF_SLEEP"
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
                'pane process-info')
                    printf '%s\n' '{"result":{"process_info":{"foreground_processes":[{"name":"revdiff"}]}}}'
                    ;;
                'pane send-keys') ;;
                'tab close') ;;
                'tab focus')
                    if [[ ${TEST_HERDR_FOCUS_FAIL:-0} == 1 ]]; then
                        exit 12
                    fi
                    ;;
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
            "HERDR_TAB_ID": "w-test:t-caller",
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

    def test_plan_review_prefers_focused_herdr_tab_and_returns_annotations(
        self,
    ) -> None:
        capture = self.temp / "first-review.md"
        result = subprocess.run(
            [str(PLAN_LAUNCHER), str(self.plan)],
            env=self._mixed_herdr_env(
                TEST_ANNOTATIONS="tighten the test plan",
                TEST_REVDIFF_RC="10",
                TEST_STDIN_CAPTURE=str(capture),
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
        self.assertIn("herdr tab focus w-test:t-caller", calls)
        self.assertIn("--stdin", calls)
        self.assertIn("--stdin-name=codex-plan.md", calls)
        self.assertNotIn("--only=", calls)
        self.assertEqual(
            capture.read_text(),
            "Plan\n====\n\nReview this Markdown plan.\n",
        )
        self.assertNotRegex(calls, r"(?m)^(tmux|agtermctl|zellij) ")
        lines = calls.splitlines()
        self.assertLess(
            lines.index("herdr tab close w-test:t1"),
            lines.index("herdr tab focus w-test:t-caller"),
        )

    def test_plan_compare_mode_keeps_markdown_and_collapses_revision_diff(self) -> None:
        old_capture = self.temp / "old-review.md"
        new_capture = self.temp / "new-review.md"
        result = subprocess.run(
            [str(PLAN_LAUNCHER), str(self.plan), str(self.old_plan)],
            env=self._mixed_herdr_env(
                TEST_OLD_CAPTURE=str(old_capture),
                TEST_NEW_CAPTURE=str(new_capture),
            ),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self._calls()
        self.assertRegex(calls, r"--compare-old=.*/previous-plan\.md")
        self.assertRegex(calls, r"--compare-new=.*/codex-plan\.md")
        self.assertIn("--collapsed", calls)
        self.assertEqual(old_capture.read_text(), "Plan\n====\n\nOld text.\n")
        self.assertEqual(
            new_capture.read_text(),
            "Plan\n====\n\nReview this Markdown plan.\n",
        )

    def test_narrow_plan_review_wraps_naturally_and_hides_tree(self) -> None:
        self.plan.write_text(
            "# Phone plan\n\n"
            "- Review this deliberately long list item at natural word boundaries "
            "without losing its hanging indentation.\n"
        )
        capture = self.temp / "phone-review.md"
        result = subprocess.run(
            [str(PLAN_LAUNCHER), str(self.plan)],
            env=self._mixed_herdr_env(
                COLUMNS="69",
                TEST_STDIN_CAPTURE=str(capture),
                TEST_REVDIFF_SLEEP="0.4",
            ),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        rendered = capture.read_text()
        self.assertIn("• Review this deliberately long list item at natural", rendered)
        self.assertIn("  word boundaries without losing its hanging", rendered)
        self.assertTrue(all(len(line) <= 56 for line in rendered.splitlines()))
        self.assertIn("herdr pane send-keys w-test:p1 t", self._calls())

    def test_projection_preserves_code_tables_links_and_inline_markdown(self) -> None:
        source = self.temp / "structures.md"
        output = self.temp / "structures-view.md"
        mapping = self.temp / "structures-map.json"
        source.write_text(
            "## Details\n\n"
            "Use `inline_code()` and **emphasis** while wrapping this paragraph cleanly.\n\n"
            "```python\nprint('a very long code line that must remain exactly intact')\n```\n\n"
            "| Name | Value |\n| --- | --- |\n| long | untouched |\n\n"
            "[docs]: https://example.test/a-very-long-unbreakable-token\n"
        )
        result = subprocess.run(
            [
                "python3",
                str(FORMATTER),
                "render",
                f"--source={source}",
                f"--output={output}",
                f"--map={mapping}",
                "--width=32",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        rendered = output.read_text()
        self.assertIn("Details\n-------", rendered)
        self.assertIn("`inline_code()`", rendered)
        self.assertIn(
            "print('a very long code line that must remain exactly intact')", rendered
        )
        self.assertIn("| Name | Value |", rendered)
        self.assertIn(
            "[docs]: https://example.test/a-very-long-unbreakable-token", rendered
        )
        payload = json.loads(mapping.read_text())
        self.assertEqual(len(payload["line_map"]), len(rendered.splitlines()))

    def test_projection_annotations_map_back_to_canonical_plan_lines(self) -> None:
        result = subprocess.run(
            [str(PLAN_LAUNCHER), str(self.plan)],
            env=self._mixed_herdr_env(
                TEST_ANNOTATIONS="## codex-plan.md:2 ( )\nclarify the heading",
                TEST_REVDIFF_RC="10",
            ),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 10, result.stderr)
        self.assertEqual(
            result.stdout,
            f"## {self.plan.name}:1 ( )\nclarify the heading",
        )

    def test_compare_annotations_use_the_matching_canonical_revision(self) -> None:
        result = subprocess.run(
            [str(PLAN_LAUNCHER), str(self.plan), str(self.old_plan)],
            env=self._mixed_herdr_env(
                TEST_ANNOTATIONS=(
                    "## previous-plan.md:2 (-)\nold heading note\n\n"
                    "## codex-plan.md:2 (+)\nnew heading note"
                ),
                TEST_REVDIFF_RC="10",
            ),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 10, result.stderr)
        self.assertEqual(
            result.stdout,
            f"## {self.old_plan.name}:1 (-)\nold heading note\n\n"
            f"## {self.plan.name}:1 (+)\nnew heading note",
        )

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
        self.assertIn("herdr tab focus w-test:t-caller", calls)
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
        calls = self._calls()
        self.assertIn("herdr tab focus w-test:t-caller", calls)
        self.assertNotRegex(calls, r"(?m)^tmux ")

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
        calls = self._calls()
        self.assertIn("herdr tab close w-test:t1", calls)
        self.assertIn("herdr tab focus w-test:t-caller", calls)

    def test_focus_failure_does_not_replace_annotations_or_exit_status(self) -> None:
        result = subprocess.run(
            [str(PLAN_LAUNCHER), str(self.plan)],
            env=self._mixed_herdr_env(
                TEST_ANNOTATIONS="keep this annotation",
                TEST_HERDR_FOCUS_FAIL="1",
                TEST_REVDIFF_RC="10",
            ),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 10, result.stderr)
        self.assertEqual(result.stdout, "keep this annotation")
        self.assertIn("herdr tab focus w-test:t-caller", self._calls())

    def test_missing_caller_tab_id_skips_focus_restoration(self) -> None:
        result = subprocess.run(
            [str(PLAN_LAUNCHER), str(self.plan)],
            env=self._mixed_herdr_env(HERDR_TAB_ID=""),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("herdr tab focus", self._calls())

    def test_stop_hook_extracts_markdown_and_blocks_with_annotations(self) -> None:
        event = {
            "hook_event_name": "Stop",
            "permission_mode": "bypassPermissions",
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

    def test_stop_hook_accepts_tagged_plan_in_default_permission_mode(self) -> None:
        event = {
            "hook_event_name": "Stop",
            "permission_mode": "default",
            "cwd": str(REPO_ROOT),
            "last_assistant_message": "<proposed_plan># Default plan</proposed_plan>",
        }
        result = subprocess.run(
            ["python3", str(HOOK)],
            input=json.dumps(event),
            env=self._mixed_herdr_env(PLUGIN_ROOT=str(PLUGIN_ROOT)),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {})
        self.assertRegex(self._calls(), r"(?m)^revdiff ")

    def test_stop_hook_does_not_launch_without_completed_plan(self) -> None:
        cases = (
            (
                "ordinary reply",
                {
                    "hook_event_name": "Stop",
                    "permission_mode": "bypassPermissions",
                    "last_assistant_message": "No completed plan here.",
                },
            ),
            (
                "incomplete plan",
                {
                    "hook_event_name": "Stop",
                    "permission_mode": "bypassPermissions",
                    "last_assistant_message": "<proposed_plan># Still drafting",
                },
            ),
            (
                "non-Stop event",
                {
                    "hook_event_name": "UserPromptSubmit",
                    "permission_mode": "bypassPermissions",
                    "last_assistant_message": (
                        "<proposed_plan># Wrong event</proposed_plan>"
                    ),
                },
            ),
        )
        for label, event in cases:
            with self.subTest(label=label):
                self.log.write_text("")
                result = subprocess.run(
                    ["python3", str(HOOK)],
                    input=json.dumps(event),
                    env=self._mixed_herdr_env(PLUGIN_ROOT=str(PLUGIN_ROOT)),
                    text=True,
                    capture_output=True,
                    check=False,
                )

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotRegex(self._calls(), r"(?m)^revdiff ")

    def test_stop_hook_uses_current_turn_transcript_fallback(self) -> None:
        session_id = "session-test"
        turn_id = "turn-test"
        transcript = self.temp / f"rollout-{session_id}.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": (
                                    "<proposed_plan># Transcript plan\n\n"
                                    "Fallback Markdown.</proposed_plan>"
                                ),
                            }
                        ],
                        "internal_chat_message_metadata_passthrough": {
                            "turn_id": turn_id
                        },
                    },
                }
            )
            + "\n"
        )
        event = {
            "hook_event_name": "Stop",
            "permission_mode": "bypassPermissions",
            "cwd": str(REPO_ROOT),
            "session_id": session_id,
            "turn_id": turn_id,
            "transcript_path": str(transcript),
            "last_assistant_message": None,
        }
        result = subprocess.run(
            ["python3", str(HOOK)],
            input=json.dumps(event),
            env=self._mixed_herdr_env(
                PLUGIN_ROOT=str(PLUGIN_ROOT),
                TEST_ANNOTATIONS="check transcript fallback",
                TEST_REVDIFF_RC="10",
            ),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["decision"], "block")
        marker = re.search(r"previous revision: (.+?) -->", payload["reason"])
        self.assertIsNotNone(marker)
        snapshot = Path(marker.group(1))
        try:
            self.assertEqual(
                snapshot.read_text(),
                "# Transcript plan\n\nFallback Markdown.",
            )
        finally:
            snapshot.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
