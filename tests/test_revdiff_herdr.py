#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
import textwrap
import time
import fcntl

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugins/revdiff-herdr"
PLAN_LAUNCHER = PLUGIN_ROOT / "scripts/launch-plan-review.sh"
MANUAL_LAUNCHER = PLUGIN_ROOT / "skills/revdiff/scripts/launch-revdiff.sh"
HOOK = PLUGIN_ROOT / "scripts/codex-plan-review-hook.py"
FORMATTER = PLUGIN_ROOT / "scripts/plan_review_format.py"
RUNTIME = PLUGIN_ROOT / "scripts/plan-review-runtime.py"
sys.path.insert(0, str(FORMATTER.parent))
from plan_review_format import (  # noqa: E402
    project_annotations,
    remap_annotations,
    review_width,
)


def _load_plan_runtime():
    spec = importlib.util.spec_from_file_location("plan_review_runtime", RUNTIME)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PLAN_RUNTIME = _load_plan_runtime()
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


class TestRevDiffHerdr:
    def setup_method(self) -> None:
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

    def teardown_method(self) -> None:
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
            only=''
            preload=''
            history_dir=''
            for arg in "$@"; do
                case "$arg" in
                    --output=*) output=${arg#--output=} ;;
                    --only=*) only=${arg#--only=} ;;
                    --annotations=*) preload=${arg#--annotations=} ;;
                    --history-dir=*) history_dir=${arg#--history-dir=} ;;
                esac
            done
            printf '%s' "$$" > "${TEST_REVDIFF_PID_FILE:?}"
            count=0
            if [[ -n ${TEST_REFLOW_COUNT:-} ]]; then
                [[ -f $TEST_REFLOW_COUNT ]] && count=$(cat "$TEST_REFLOW_COUNT")
                printf '%s' "$((count + 1))" > "$TEST_REFLOW_COUNT"
            fi
            if [[ -n $only && -n ${TEST_ONLY_CAPTURE:-} ]]; then
                cp "$only" "$TEST_ONLY_CAPTURE"
            fi
            if [[ -n ${TEST_OLD_CAPTURE:-} && -d .git ]]; then
                git show HEAD:codex-plan.md > "$TEST_OLD_CAPTURE"
            fi
            if [[ -n $only && -n ${TEST_NEW_CAPTURE:-} && -d .git ]]; then
                cp "$only" "$TEST_NEW_CAPTURE"
            fi
            if [[ -n $preload && -n ${TEST_PRELOAD_CAPTURE:-} ]]; then
                cp "$preload" "$TEST_PRELOAD_CAPTURE"
            fi
            if [[ -n ${TEST_GENERATION_DIR:-} ]]; then
                cp "$only" "${TEST_GENERATION_DIR:?}/generation-$((count + 1)).txt"
            fi
            on_term() {
                if [[ -n $history_dir ]]; then
                    annotations=${TEST_REFLOW_ANNOTATIONS:-}
                    if [[ -n $annotations ]]; then
                        repo=$(basename "$PWD")
                        mkdir -p "$history_dir/$repo"
                        {
                            printf '# Review: now\npath: %s\n\n## Annotations\n\n' "$PWD"
                            printf '%s\n' "$annotations"
                        } > "$history_dir/$repo/review.md"
                    fi
                fi
                if [[ -n ${TEST_DELETE_AFTER_HANDOFF:-} ]]; then
                    rm -f -- "$TEST_DELETE_AFTER_HANDOFF"
                fi
                exit 0
            }
            trap on_term TERM
            if [[ -n ${TEST_WAIT_FOR_REFLOW:-} && $count -eq 0 ]]; then
                while :; do sleep 0.05; done
            fi
            if [[ -n $output ]]; then
                printf '%s' "${TEST_FINAL_ANNOTATIONS:-${TEST_ANNOTATIONS:-}}" > "$output"
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
                    sh -c "${4:?missing pane command}" &
                    ;;
                'pane process-info')
                    if [[ ${TEST_PROCESS_INFO_FAIL:-0} == 1 ]]; then
                        exit 9
                    fi
                    pid=$(cat "${TEST_REVDIFF_PID_FILE:?}")
                    if [[ -n ${TEST_FOREGROUND_PID_OFFSET:-} ]]; then
                        pid=$((pid + TEST_FOREGROUND_PID_OFFSET))
                    fi
                    printf '{"result":{"process_info":{"foreground_processes":[{"name":"%s","pid":%s}]}}}\n' "${TEST_FOREGROUND_NAME:-revdiff}" "$pid"
                    ;;
                'pane read')
                    if [[ ${TEST_PANE_READ_FAIL:-0} == 1 ]]; then
                        exit 10
                    fi
                    if [[ -n ${TEST_MODAL_FILE:-} && -f $TEST_MODAL_FILE ]]; then
                        printf '%s\n' '[enter] save' '[esc] cancel'
                    else
                        printf '%s\n' 'ordinary revdiff status'
                    fi
                    ;;
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
                "TEST_REVDIFF_PID_FILE": str(self.temp / "revdiff.pid"),
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

    def _run_resize_runtime(
        self,
        annotation: str,
        *,
        old: Path | None = None,
        initial_columns: int = 120,
        resize_columns: tuple[int, ...] = (69,),
        modal: bool = False,
        expect_reflow: bool = True,
        **overrides: str,
    ) -> tuple[int, Path, Path, Path]:
        output = self.temp / "runtime-output.md"
        count = self.temp / "runtime-count"
        generations = self.temp / "generations"
        generations.mkdir()
        modal_file = self.temp / "annotation-modal"
        if modal:
            modal_file.touch()
        master, slave = os.openpty()
        env = self._mixed_herdr_env(
            HERDR_PANE_ID="w-test:p1",
            TEST_WAIT_FOR_REFLOW="1",
            TEST_REFLOW_COUNT=str(count),
            TEST_GENERATION_DIR=str(generations),
            TEST_REFLOW_ANNOTATIONS=annotation,
            TEST_FINAL_ANNOTATIONS=annotation,
            TEST_REVDIFF_RC="10" if annotation else "0",
            TEST_MODAL_FILE=str(modal_file),
            **overrides,
        )
        env.pop("COLUMNS", None)
        env.pop("LINES", None)
        command = [
            "python3",
            str(RUNTIME),
            f"--revdiff={self.fake_bin / 'revdiff'}",
            f"--new={self.plan}",
            f"--output={output}",
        ]
        if old is not None:
            command.append(f"--old={old}")
        try:
            fcntl.ioctl(
                slave,
                termios.TIOCSWINSZ,
                struct.pack("HHHH", 24, initial_columns, 0, 0),
            )
            process = subprocess.Popen(
                command,
                env=env,
                stdin=slave,
                stdout=slave,
                stderr=slave,
            )
            deadline = time.monotonic() + 5
            while (
                (not count.exists() or count.read_text() != "1")
                and time.monotonic() < deadline
            ):
                time.sleep(0.05)
            assert count.exists() and count.read_text() == "1"
            for columns in resize_columns:
                fcntl.ioctl(
                    master,
                    termios.TIOCSWINSZ,
                    struct.pack("HHHH", 24, columns, 0, 0),
                )
                time.sleep(0.15)

            if modal or not expect_reflow:
                time.sleep(1.0)
                assert count.read_text() == "1"
            if modal:
                modal_file.unlink()
            if not expect_reflow:
                os.kill(int((self.temp / "revdiff.pid").read_text()), 15)

            return process.wait(timeout=10), output, count, generations
        finally:
            os.close(slave)
            os.close(master)

    def test_plan_review_prefers_focused_herdr_tab_and_returns_annotations(
        self,
    ) -> None:
        capture = self.temp / "first-review.md"
        result = subprocess.run(
            [str(PLAN_LAUNCHER), str(self.plan)],
            env=self._mixed_herdr_env(
                TEST_ANNOTATIONS="tighten the test plan",
                TEST_REVDIFF_RC="10",
                TEST_ONLY_CAPTURE=str(capture),
            ),
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 10, result.stderr
        assert result.stdout == "tighten the test plan"
        calls = self._calls()
        assert "herdr tab create" in calls
        assert "--workspace w-test" in calls
        assert "--focus" in calls
        assert "herdr tab close w-test:t1" in calls
        assert "herdr tab focus w-test:t-caller" in calls
        assert "--only=" in calls
        assert "--stdin" not in calls
        assert capture.read_text() == "# Plan\n\nReview this Markdown plan.\n"
        assert not re.search(r"(?m)^(tmux|agtermctl|zellij) ", calls)
        lines = calls.splitlines()
        assert lines.index("herdr tab close w-test:t1") < lines.index(
            "herdr tab focus w-test:t-caller"
        )

    def test_plan_compare_mode_uses_a_native_git_diff(self) -> None:
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

        assert result.returncode == 0, result.stderr
        calls = self._calls()
        assert "--only=codex-plan.md" in calls
        assert "--compare-old" not in calls
        assert old_capture.read_text() == "# Plan\n\nOld text.\n"
        assert (
            new_capture.read_text()
            == "# Plan\n\nReview this Markdown plan.\n"
        )

    def test_narrow_plan_review_wraps_naturally_and_keeps_markdown_toc(self) -> None:
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
                TEST_ONLY_CAPTURE=str(capture),
                TEST_REVDIFF_SLEEP="0.4",
            ),
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        rendered = capture.read_text()
        assert "- Review this deliberately long list item at natural" in rendered
        assert "  word boundaries without losing its hanging" in rendered
        assert all(len(line) <= 56 for line in rendered.splitlines())
        assert "pane send-keys" not in self._calls()

    @pytest.mark.parametrize(
        ("columns", "expected"),
        [(70, 57), (89, 76), (90, 80), (120, 80), (180, 80)],
    )
    def test_review_width(self, columns: int, expected: int) -> None:
        assert review_width(columns) == expected

    @pytest.mark.parametrize(
        ("columns", "expected"),
        [
            (30, (32, 0)),
            (70, (57, 0)),
            (89, (76, 0)),
            (90, (80, 1)),
            (120, (80, 16)),
            (180, (80, 46)),
        ],
    )
    def test_projection_geometry_captures_all_render_dimensions(
        self, columns: int, expected: tuple[int, int]
    ) -> None:
        assert PLAN_RUNTIME.projection_geometry(columns) == expected

    @pytest.mark.parametrize(
        ("screen", "expected"),
        [
            ("[enter] save  [esc] cancel", True),
            ("[enter] save\n[esc] cancel", True),
            ("[enter] save", False),
            ("ordinary status", False),
        ],
    )
    def test_annotation_input_detection_handles_wrapped_status(
        self, screen: str, expected: bool
    ) -> None:
        assert PLAN_RUNTIME.annotation_input_active(screen) is expected

    def test_history_annotation_extraction_ignores_metadata_and_diff(self) -> None:
        history = (
            "# Review: now\n"
            "path: /tmp/repo\n"
            "commit: abc123\n\n"
            "## Annotations\n\n"
            "## codex-plan.md:2 (+)\nkeep this\n\n"
            "---\n\n## Diff\n\ndiff --git a/codex-plan.md b/codex-plan.md\n"
        )

        assert PLAN_RUNTIME.extract_history_annotations(history) == (
            "## codex-plan.md:2 (+)\nkeep this"
        )

    def test_normal_empty_exit_clears_stale_canonical_output(self) -> None:
        output = self.temp / "canonical-output.md"
        output.write_text("stale annotation")

        result = subprocess.run(
            [
                "python3",
                str(RUNTIME),
                f"--revdiff={self.fake_bin / 'revdiff'}",
                f"--new={self.plan}",
                f"--output={output}",
            ],
            env=self._mixed_herdr_env(HERDR_PANE_ID="w-test:p1"),
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert not output.exists()

    def test_normal_annotated_exit_replaces_stale_canonical_output(self) -> None:
        output = self.temp / "canonical-output.md"
        output.write_text("stale annotation")

        result = subprocess.run(
            [
                "python3",
                str(RUNTIME),
                f"--revdiff={self.fake_bin / 'revdiff'}",
                f"--new={self.plan}",
                f"--output={output}",
            ],
            env=self._mixed_herdr_env(
                HERDR_PANE_ID="w-test:p1",
                TEST_ANNOTATIONS="## codex-plan.md:2 ( )\nreplacement",
                TEST_REVDIFF_RC="10",
            ),
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 10, result.stderr
        assert output.read_text() == f"## {self.plan.name}:1 ( )\nreplacement"

    def test_unexpected_exit_retains_stale_canonical_checkpoint(self) -> None:
        output = self.temp / "canonical-output.md"
        output.write_text("last known good")

        result = subprocess.run(
            [
                "python3",
                str(RUNTIME),
                f"--revdiff={self.fake_bin / 'revdiff'}",
                f"--new={self.plan}",
                f"--output={output}",
            ],
            env=self._mixed_herdr_env(
                HERDR_PANE_ID="w-test:p1",
                TEST_ANNOTATIONS="partial failure output",
                TEST_REVDIFF_RC="7",
            ),
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 7, result.stderr
        assert output.read_text() == "last known good"

    def test_plan_launcher_never_injects_revdiff_keys(self) -> None:
        launcher = (
            PLUGIN_ROOT / "scripts/launch-plan-review-herdr.sh"
        ).read_text()
        assert "pane send-keys" not in launcher

    def test_desktop_plan_is_centered_at_an_80_column_reading_width(self) -> None:
        capture = self.temp / "desktop-review.txt"
        result = subprocess.run(
            [str(PLAN_LAUNCHER), str(self.plan)],
            env=self._mixed_herdr_env(
                COLUMNS="120",
                TEST_ONLY_CAPTURE=str(capture),
            ),
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        lines = capture.read_text().splitlines()
        assert lines[0] == " " * 16 + "# Plan"
        assert lines[1] == ""
        assert lines[2] == " " * 16 + "Review this Markdown plan."

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

        assert result.returncode == 0, result.stderr
        rendered = output.read_text()
        assert "## Details" in rendered
        assert "`inline_code()`" in rendered
        assert "print('a very long code line that must remain exactly intact')" in rendered
        assert "| Name | Value |" in rendered
        assert "[docs]: https://example.test/a-very-long-unbreakable-token" in rendered
        payload = json.loads(mapping.read_text())
        assert len(payload["line_map"]) == len(rendered.splitlines())

    def test_projection_joins_soft_wraps_and_preserves_explicit_breaks(self) -> None:
        source = self.temp / "paragraphs.md"
        output = self.temp / "paragraphs-view.md"
        mapping = self.temp / "paragraphs-map.json"
        source.write_text(
            "First soft-wrapped line\n"
            "continues as one logical paragraph.\n\n"
            "Keep this explicit break.  \n"
            "This starts a new rendered line.\n\n"
            "Do the same with a slash.\\\n"
            "This also remains separate.\n"
        )

        subprocess.run(
            [
                "python3",
                str(FORMATTER),
                "render",
                f"--source={source}",
                f"--output={output}",
                f"--map={mapping}",
                "--width=80",
            ],
            check=True,
        )

        assert output.read_text() == (
            "First soft-wrapped line continues as one logical paragraph.\n\n"
            "Keep this explicit break.  \n"
            "This starts a new rendered line.\n\n"
            "Do the same with a slash.\\\n"
            "This also remains separate.\n"
        )
        line_map = json.loads(mapping.read_text())["line_map"]
        assert line_map == [1, 3, 4, 5, 6, 7, 8]

    @pytest.mark.parametrize("underline", ["=====", "-----"])
    def test_projection_preserves_setext_headings(self, underline: str) -> None:
        source = self.temp / "setext.md"
        output = self.temp / "setext-view.md"
        mapping = self.temp / "setext-map.json"
        source.write_text(
            f"Intro paragraph.\nHeading\n{underline}\n\nBody text.\n"
        )

        subprocess.run(
            [
                "python3",
                str(FORMATTER),
                "render",
                f"--source={source}",
                f"--output={output}",
                f"--map={mapping}",
                "--width=80",
            ],
            check=True,
        )

        assert output.read_text() == (
            f"Intro paragraph.\nHeading\n{underline}\n\nBody text.\n"
        )
        assert json.loads(mapping.read_text())["line_map"] == [1, 2, 3, 4, 5]

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

        assert result.returncode == 10, result.stderr
        assert result.stdout == f"## {self.plan.name}:1 ( )\nclarify the heading"

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

        assert result.returncode == 10, result.stderr
        assert result.stdout == (
            f"## {self.old_plan.name}:1 (-)\nold heading note\n\n"
            f"## {self.plan.name}:1 (+)\nnew heading note"
        )

    def test_shared_comparison_path_round_trips_current_and_deletion_lines(self) -> None:
        new_map = {
            "source": str(self.plan),
            "projected": "codex-plan.md",
            "line_map": [1, 1, 2, 3],
        }
        old_map = {
            "source": str(self.old_plan),
            "projected": "codex-plan.md",
            "line_map": [1, 1, 2, 3],
        }
        projected = (
            "## codex-plan.md:1-2 ( )\ncurrent\n\n"
            "## codex-plan.md:1-2 (-)\ndeleted"
        )

        canonical = remap_annotations(projected, new_map, old_map)
        assert canonical == (
            f"## {self.plan.name}:1 ( )\ncurrent\n\n"
            f"## {self.old_plan.name}:1 (-)\ndeleted"
        )
        reprojected = project_annotations(
            canonical, new_map, old_map, "codex-plan.md"
        )
        assert reprojected == (
            "## codex-plan.md:1 ( )\ncurrent\n\n"
            "## codex-plan.md:1 (-)\ndeleted"
        )

    def test_ranges_and_file_annotations_round_trip(self) -> None:
        mapping = {
            "source": str(self.plan),
            "projected": "codex-plan.md",
            "line_map": [1, 2, 3, 4],
        }
        projected = (
            "## codex-plan.md:1-3 (+)\nrange\n\n"
            "## codex-plan.md (file-level)\nwhole file"
        )

        canonical = remap_annotations(projected, mapping)
        assert canonical == (
            f"## {self.plan.name}:1-3 (+)\nrange\n\n"
            f"## {self.plan.name} (file-level)\nwhole file"
        )
        assert project_annotations(
            canonical, mapping, projected_name="codex-plan.md"
        ) == projected

    def test_annotated_reflow_restarts_and_preloads_without_losing_output(self) -> None:
        preload = self.temp / "preload.md"
        annotation = "## codex-plan.md:2 ( )\nkeep this"
        rc, output, count, _ = self._run_resize_runtime(
            annotation,
            TEST_PRELOAD_CAPTURE=str(preload),
        )

        assert rc == 10
        assert output.read_text() == f"## {self.plan.name}:1 ( )\nkeep this"
        assert count.read_text() == "2"
        assert preload.read_text().endswith(":1 ( )\nkeep this")
        assert "pane send-keys" not in self._calls()

    def test_comparison_reflow_uses_temp_git_and_preserves_deletion_side(self) -> None:
        preload = self.temp / "comparison-preload.md"
        annotation = "## codex-plan.md:2 (-)\nkeep deletion"
        before = subprocess.run(
            ["git", "status", "--porcelain=v1"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=True,
        ).stdout
        rc, output, count, _ = self._run_resize_runtime(
            annotation,
            old=self.old_plan,
            TEST_PRELOAD_CAPTURE=str(preload),
        )
        after = subprocess.run(
            ["git", "status", "--porcelain=v1"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=True,
        ).stdout

        assert rc == 10
        assert output.read_text() == f"## {self.old_plan.name}:1 (-)\nkeep deletion"
        assert count.read_text() == "2"
        assert "## codex-plan.md:1 (-)" in preload.read_text()
        assert after == before

    def test_comparison_ignores_host_git_hooks(self) -> None:
        hooks = self.temp / "hooks"
        hooks.mkdir()
        marker = self.temp / "hook-ran"
        self._write_executable(
            "host-pre-commit",
            f"""
            #!/usr/bin/env bash
            : > {marker}
            exit 93
            """,
        )
        (hooks / "pre-commit").symlink_to(self.fake_bin / "host-pre-commit")

        result = subprocess.run(
            [str(PLAN_LAUNCHER), str(self.plan), str(self.old_plan)],
            env=self._mixed_herdr_env(
                GIT_CONFIG_COUNT="1",
                GIT_CONFIG_KEY_0="core.hooksPath",
                GIT_CONFIG_VALUE_0=str(hooks),
            ),
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert not marker.exists()

    @pytest.mark.parametrize(
        ("annotation", "expected"),
        [
            ("", ""),
            (
                "## codex-plan.md:4 ( )\nkeep after resize",
                "## plan.md:3 ( )\nkeep after resize",
            ),
        ],
    )
    def test_automatic_resize_reflows_and_preserves_annotations(
        self, annotation: str, expected: str
    ) -> None:
        self.plan.write_text(
            "# Plan\n\n"
            "Review this deliberately long paragraph across desktop and narrow "
            "layouts while keeping an annotation attached to this source line.\n"
        )
        rc, output, count, generations = self._run_resize_runtime(annotation)
        assert rc == (10 if annotation else 0)

        desktop = (generations / "generation-1.txt").read_text()
        narrow = (generations / "generation-2.txt").read_text()
        assert desktop != narrow
        assert desktop.startswith(" " * 16 + "# Plan")
        assert narrow.startswith("# Plan")
        assert count.read_text() == "2"
        assert (output.read_text() if output.exists() else "") == expected
        assert "pane send-keys" not in self._calls()

    def test_resize_oscillation_collapses_to_one_reflow(self) -> None:
        annotation = "## codex-plan.md:2 ( )\nstill here"
        rc, output, count, _ = self._run_resize_runtime(
            annotation,
            resize_columns=(69, 120, 69),
        )

        assert rc == 10
        assert output.read_text() == f"## {self.plan.name}:1 ( )\nstill here"
        assert count.read_text() == "2"

    def test_raw_width_change_with_identical_geometry_does_not_reflow(self) -> None:
        rc, output, count, _ = self._run_resize_runtime(
            "",
            initial_columns=30,
            resize_columns=(20,),
            expect_reflow=False,
        )

        assert rc == 0
        assert not output.exists()
        assert count.read_text() == "1"

    def test_centering_change_reflows_even_when_wrap_width_is_unchanged(self) -> None:
        rc, output, count, generations = self._run_resize_runtime(
            "", resize_columns=(180,)
        )

        assert rc == 0
        assert not output.exists()
        assert count.read_text() == "2"
        assert (generations / "generation-1.txt").read_text().startswith(
            " " * 16 + "# Plan"
        )
        assert (generations / "generation-2.txt").read_text().startswith(
            " " * 46 + "# Plan"
        )

    def test_active_annotation_defers_resize_until_modal_closes(self) -> None:
        annotation = "## codex-plan.md:2 ( )\nfinish first"
        rc, output, count, _ = self._run_resize_runtime(annotation, modal=True)

        assert rc == 10
        assert count.read_text() == "2"
        assert output.read_text() == f"## {self.plan.name}:1 ( )\nfinish first"

    @pytest.mark.parametrize(
        "guard",
        [
            {"TEST_PROCESS_INFO_FAIL": "1"},
            {"TEST_PANE_READ_FAIL": "1"},
            {"TEST_FOREGROUND_NAME": "vim"},
            {"TEST_FOREGROUND_PID_OFFSET": "1"},
        ],
    )
    def test_unknown_or_non_revdiff_pane_state_defers_reflow(
        self, guard: dict[str, str]
    ) -> None:
        rc, output, count, _ = self._run_resize_runtime(
            "", expect_reflow=False, **guard
        )

        assert rc == 0
        assert not output.exists()
        assert count.read_text() == "1"

    def test_reflow_failure_returns_the_last_canonical_flush(self) -> None:
        annotation = "## codex-plan.md:2 ( )\nrecover me"
        rc, output, _, _ = self._run_resize_runtime(
            annotation,
            TEST_DELETE_AFTER_HANDOFF=str(self.plan),
        )

        assert rc == 10
        assert output.read_text() == f"## {self.plan.name}:1 ( )\nrecover me"

    def test_annotation_free_review_does_not_restart_or_invent_output(self) -> None:
        result = subprocess.run(
            [str(PLAN_LAUNCHER), str(self.plan)],
            env=self._mixed_herdr_env(),
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout == ""
        assert sum(
            line.startswith("revdiff ") for line in self._calls().splitlines()
        ) == 1

    def test_manual_review_prefers_herdr(self) -> None:
        result = subprocess.run(
            [str(MANUAL_LAUNCHER), f"--only={self.plan}"],
            env=self._mixed_herdr_env(),
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        calls = self._calls()
        assert "herdr tab create" in calls
        assert "herdr pane run w-test:p1" in calls
        assert "herdr tab close w-test:t1" in calls
        assert "herdr tab focus w-test:t-caller" in calls
        assert not re.search(r"(?m)^(tmux|agtermctl|zellij) ", calls)

    def test_public_launcher_routes_markdown_comparison_and_description(self) -> None:
        result = subprocess.run(
            [
                str(MANUAL_LAUNCHER),
                f"--compare-old={self.old_plan}",
                f"--compare-new={self.plan}",
                "--description=# Review notes",
            ],
            env=self._mixed_herdr_env(),
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        calls = self._calls()
        assert "--only=codex-plan.md" in calls
        assert "--description=#\\ Review\\ notes" in calls
        assert "--compare-old" not in calls

    def test_public_launcher_routes_markdown_suffix_without_herdr_environment(self) -> None:
        document = self.temp / "notes.markdown"
        previous = self.temp / "previous.markdown"
        document.write_text("# Notes\n\nCurrent.\n")
        previous.write_text("# Notes\n\nPrevious.\n")

        context = subprocess.run(
            [str(MANUAL_LAUNCHER), f"--only={document}"],
            env=self._env(),
            text=True,
            capture_output=True,
            check=False,
        )
        assert context.returncode == 0, context.stderr
        assert "--only=codex-plan.md" in self._calls()
        assert "herdr tab create" in self._calls()

        self.log.write_text("")
        comparison = subprocess.run(
            [
                str(MANUAL_LAUNCHER),
                f"--compare-old={previous}",
                f"--compare-new={document}",
            ],
            env=self._env(),
            text=True,
            capture_output=True,
            check=False,
        )
        assert comparison.returncode == 0, comparison.stderr
        assert "--only=codex-plan.md" in self._calls()
        assert "--compare-old" not in self._calls()

    def test_public_launcher_preserves_source_review_arguments(self) -> None:
        source = self.temp / "example.py"
        source.write_text("answer = 42\n")
        result = subprocess.run(
            [
                str(MANUAL_LAUNCHER),
                f"--only={source}",
                "--description=Review Python",
            ],
            env=self._mixed_herdr_env(
                TEST_ANNOTATIONS="code annotation",
                TEST_REVDIFF_RC="10",
            ),
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 10, result.stderr
        assert result.stdout == "code annotation"
        calls = self._calls()
        assert f"--only={source}" in calls
        assert "--description=Review\\ Python" in calls
        assert "codex-plan.md" not in calls

    def test_public_launcher_falls_through_unsupported_markdown_combinations(self) -> None:
        result = subprocess.run(
            [str(MANUAL_LAUNCHER), f"--only={self.plan}", "--staged"],
            env=self._mixed_herdr_env(),
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        calls = self._calls()
        assert f"--only={self.plan}" in calls
        assert "--staged" in calls
        assert "codex-plan.md" not in calls

    @pytest.mark.parametrize("arguments", [(), ("--staged",), ("HEAD~1",)])
    def test_public_launcher_preserves_vcs_review_arguments(
        self, arguments: tuple[str, ...]
    ) -> None:
        result = subprocess.run(
            [str(MANUAL_LAUNCHER), *arguments],
            env=self._mixed_herdr_env(),
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        revdiff_call = next(
            line for line in self._calls().splitlines() if line.startswith("revdiff ")
        )
        for argument in arguments:
            assert argument in revdiff_call
        assert "codex-plan.md" not in revdiff_call

    def test_non_herdr_session_preserves_upstream_tmux_selection(self) -> None:
        result = subprocess.run(
            [str(PLAN_LAUNCHER), str(self.plan)],
            env=self._env(TMUX="/tmp/fake-tmux,1,0", TMUX_PANE="%1"),
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        calls = self._calls()
        assert re.search(r"(?m)^tmux display-popup ", calls)
        assert not re.search(r"(?m)^herdr ", calls)

    def test_malformed_herdr_create_fails_without_falling_back_to_tmux(self) -> None:
        result = subprocess.run(
            [str(PLAN_LAUNCHER), str(self.plan)],
            env=self._mixed_herdr_env(TEST_HERDR_MALFORMED="1"),
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 1
        assert "did not return pane/tab ids" in result.stderr
        calls = self._calls()
        assert "herdr tab focus w-test:t-caller" in calls
        assert not re.search(r"(?m)^tmux ", calls)

    def test_pane_run_failure_closes_created_tab(self) -> None:
        result = subprocess.run(
            [str(PLAN_LAUNCHER), str(self.plan)],
            env=self._mixed_herdr_env(TEST_HERDR_PANE_FAIL="1"),
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 1
        assert "pane run failed" in result.stderr
        calls = self._calls()
        assert "herdr tab close w-test:t1" in calls
        assert "herdr tab focus w-test:t-caller" in calls

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

        assert result.returncode == 10, result.stderr
        assert result.stdout == "keep this annotation"
        assert "herdr tab focus w-test:t-caller" in self._calls()

    def test_missing_caller_tab_id_skips_focus_restoration(self) -> None:
        result = subprocess.run(
            [str(PLAN_LAUNCHER), str(self.plan)],
            env=self._mixed_herdr_env(HERDR_TAB_ID=""),
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "herdr tab focus" not in self._calls()

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

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["decision"] == "block"
        assert "add a rollback check" in payload["reason"]
        marker = re.search(r"previous revision: (.+?) -->", payload["reason"])
        assert marker is not None
        snapshot = Path(marker.group(1))
        try:
            assert snapshot.suffix == ".md"
            assert snapshot.read_text() == "# Hook plan\n\nMarkdown body."
        finally:
            snapshot.unlink(missing_ok=True)
        assert not re.search(r"(?m)^tmux ", self._calls())

    def test_stop_hook_accepts_tagged_plan_in_default_permission_mode(self) -> None:
        capture = self.temp / "hook-context.md"
        committed = self.temp / "hook-committed.md"
        event = {
            "hook_event_name": "Stop",
            "permission_mode": "default",
            "cwd": str(REPO_ROOT),
            "last_assistant_message": "<proposed_plan># Default plan</proposed_plan>",
        }
        result = subprocess.run(
            ["python3", str(HOOK)],
            input=json.dumps(event),
            env=self._mixed_herdr_env(
                PLUGIN_ROOT=str(PLUGIN_ROOT),
                TEST_ONLY_CAPTURE=str(capture),
                TEST_OLD_CAPTURE=str(committed),
            ),
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == {}
        calls = self._calls()
        assert re.search(r"(?m)^revdiff ", calls)
        assert "--only=codex-plan.md" in calls
        assert capture.read_text() == "# Default plan\n"
        assert committed.read_text() == capture.read_text()

    def test_stop_hook_revision_uses_responsive_markdown_comparison(self) -> None:
        previous = self.temp / "plan-rev-previous.md"
        previous.write_text("# Previous plan\n\nOld body.")
        old_capture = self.temp / "hook-old.md"
        new_capture = self.temp / "hook-new.md"
        event = {
            "hook_event_name": "Stop",
            "permission_mode": "default",
            "cwd": str(REPO_ROOT),
            "last_assistant_message": (
                "<proposed_plan>"
                f"<!-- previous revision: {previous} -->\n"
                "# Revised plan\n\nNew body."
                "</proposed_plan>"
            ),
        }

        result = subprocess.run(
            ["python3", str(HOOK)],
            input=json.dumps(event),
            env=self._mixed_herdr_env(
                PLUGIN_ROOT=str(PLUGIN_ROOT),
                TEST_OLD_CAPTURE=str(old_capture),
                TEST_NEW_CAPTURE=str(new_capture),
            ),
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == {}
        assert old_capture.read_text().startswith("# Previous plan")
        assert new_capture.read_text().startswith("# Revised plan")
        assert "--only=codex-plan.md" in self._calls()
        assert not previous.exists()

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
            self.log.write_text("")
            result = subprocess.run(
                ["python3", str(HOOK)],
                input=json.dumps(event),
                env=self._mixed_herdr_env(PLUGIN_ROOT=str(PLUGIN_ROOT)),
                text=True,
                capture_output=True,
                check=False,
            )

            assert result.returncode == 0, f"{label}: {result.stderr}"
            assert not re.search(r"(?m)^revdiff ", self._calls()), label

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

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["decision"] == "block"
        marker = re.search(r"previous revision: (.+?) -->", payload["reason"])
        assert marker is not None
        snapshot = Path(marker.group(1))
        try:
            assert snapshot.read_text() == "# Transcript plan\n\nFallback Markdown."
        finally:
            snapshot.unlink(missing_ok=True)
