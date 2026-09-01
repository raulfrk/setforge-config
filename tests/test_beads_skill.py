from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS = REPO_ROOT / "tracked/codex/AGENTS.md"
SKILLS = REPO_ROOT / "tracked/codex/skills"
BASE_SKILL = SKILLS / "beads/SKILL.md"
BOOTSTRAP_SKILL = SKILLS / "beads-bootstrap/SKILL.md"
REFERENCE = SKILLS / "beads/references/project-config.md"
MANIFEST = REPO_ROOT / "setforge.yaml"
CANONICAL_PREFIX = "bd --sandbox config set-many "


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=check,
        text=True,
        capture_output=True,
    )


def isolated_env(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(tmp_path / "config"),
            "XDG_STATE_HOME": str(tmp_path / "state"),
            "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
        }
    )
    return env


def canonical_command() -> list[str]:
    lines = REFERENCE.read_text(encoding="utf-8").splitlines()
    command = next(line for line in lines if line.startswith(CANONICAL_PREFIX))
    return shlex.split(command)


def test_agent_policy_uses_selective_ownership_and_beads_discovery() -> None:
    policy = normalized(AGENTS)
    assert "one primary agent to own each coherent change" in policy
    assert "Delegate only bounded, independent workstreams or independent review" in policy
    assert "never from the number of available agent slots" in policy
    assert "run `bd where --json` from that root" in policy
    assert "returned canonical `path` equals `<git-root>/.beads`" in policy
    assert "continue normally without initializing or proposing Beads" in policy


def test_base_skill_preserves_private_authorized_lifecycle() -> None:
    skill = normalized(BASE_SKILL)
    for invariant in (
        "Never initialize a database or create a Bead",
        "receiving user approval",
        "bd init --stealth --non-interactive --skip-agents --skip-hooks",
        "bd update <id> --claim",
        "only after the checks succeed",
        "repository-local `.git/info/exclude`",
        "Do not place Bead IDs, commands, or mechanics",
        "at most three nesting levels",
        "one leaf Bead produces one coherent commit",
        "Do not parse `bd info --json`",
    ):
        assert invariant in skill


def test_reference_is_the_single_complete_configuration_contract() -> None:
    reference = normalized(REFERENCE)
    for setting in (
        "epic.mode=milestone",
        "commit.mode=per-bead",
        "commit.format=type-prefix",
        "custom.workflow.decomposition=reviewer-friendly",
        "dolt.local-only=true",
        "dolt.auto-commit=on",
        "no-git-ops=true",
    ):
        assert setting in reference
    rows = [
        line
        for line in REFERENCE.read_text(encoding="utf-8").splitlines()
        if line.startswith("| `")
    ]
    assert len(rows) == 7
    assert "The only `custom.*` setting" in reference
    assert REFERENCE.read_text(encoding="utf-8").count(CANONICAL_PREFIX) == 1
    assert CANONICAL_PREFIX not in BASE_SKILL.read_text(encoding="utf-8")
    assert CANONICAL_PREFIX not in BOOTSTRAP_SKILL.read_text(encoding="utf-8")


def test_bootstrap_skill_routes_existing_state_and_requires_approval() -> None:
    skill = normalized(BOOTSTRAP_SKILL)
    for invariant in (
        "Treat `no beads project found` as absence",
        "If a database exists, do not initialize",
        "route drift to the `beads-adapt` skill",
        "Obtain explicit user approval immediately before running either command",
        "`.git/info/exclude`",
        "remote list must be empty",
        "no Beads hook may be installed",
    ):
        assert invariant in skill


def test_setforge_registers_bootstrap_and_shared_reference() -> None:
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    expected = {
        "codex_skill_beads": {
            "src": "codex/skills/beads/SKILL.md",
            "dst": "~/.codex/skills/beads/SKILL.md",
        },
        "codex_skill_beads_reference_project_config": {
            "src": "codex/skills/beads/references/project-config.md",
            "dst": "~/.codex/skills/beads/references/project-config.md",
        },
        "codex_skill_beads_bootstrap": {
            "src": "codex/skills/beads-bootstrap/SKILL.md",
            "dst": "~/.codex/skills/beads-bootstrap/SKILL.md",
        },
    }
    profile_files = manifest["profiles"]["codex"]["tracked_files"]
    for name, resource in expected.items():
        assert manifest["tracked_files"][name] == resource
        assert name in profile_files


def test_skill_reference_links_resolve_in_source_and_deployed_layout(tmp_path: Path) -> None:
    assert (BASE_SKILL.parent / "references/project-config.md").resolve() == REFERENCE
    assert (BOOTSTRAP_SKILL.parent / "../beads/references/project-config.md").resolve() == REFERENCE

    deployed = tmp_path / ".codex/skills"
    deployed_reference = deployed / "beads/references/project-config.md"
    deployed_reference.parent.mkdir(parents=True)
    deployed_reference.write_text(REFERENCE.read_text(encoding="utf-8"), encoding="utf-8")
    assert (
        deployed / "beads-bootstrap/../beads/references/project-config.md"
    ).resolve() == deployed_reference


def test_real_bd_bootstrap_reaches_canonical_private_state(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    repo = tmp_path / "project"
    repo.mkdir()
    run(["git", "init", "--quiet"], cwd=repo, env=env)
    run(["git", "config", "user.name", "Test User"], cwd=repo, env=env)
    run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, env=env)

    absent = run(["bd", "where", "--json"], cwd=repo, env=env, check=False)
    assert absent.returncode == 1
    assert json.loads(absent.stdout)["error"] == "no_beads_directory"

    run(
        [
            "bd",
            "init",
            "--stealth",
            "--non-interactive",
            "--skip-agents",
            "--skip-hooks",
            "--prefix",
            "project",
        ],
        cwd=repo,
        env=env,
    )
    run(canonical_command(), cwd=repo, env=env)

    ignore = run(["git", "check-ignore", "-v", ".beads"], cwd=repo, env=env)
    assert ".git/info/exclude" in ignore.stdout
    assert run(["git", "ls-files", ".beads"], cwd=repo, env=env).stdout == ""
    status = run(
        ["git", "status", "--short", "--untracked-files=all"], cwd=repo, env=env
    ).stdout
    assert ".beads" not in status
    remotes = run(["bd", "dolt", "remote", "list", "--json"], cwd=repo, env=env)
    assert remotes.stdout.strip() == "[]"

    hooks = run(["bd", "hooks", "list"], cwd=repo, env=env).stdout
    assert hooks.count("not installed") == 5
    assert "✓" not in hooks

    config = run(["bd", "config", "show"], cwd=repo, env=env).stdout
    parsed = {}
    for line in config.splitlines():
        match = re.match(r"^\s*(\S+)\s*=\s*(.*?)\s+\(([^)]+)\)\s*$", line)
        if match:
            parsed[match.group(1)] = (match.group(2), match.group(3))
    expected_config = {
        "epic.mode": ("milestone", "database"),
        "commit.mode": ("per-bead", "database"),
        "commit.format": ("type-prefix", "database"),
        "custom.workflow.decomposition": ("reviewer-friendly", "database"),
        "dolt.auto-commit": ("on", "config.yaml"),
        "dolt.local-only": ("true", "config.yaml"),
        "no-git-ops": ("true", "config.yaml"),
    }
    for key, expected in expected_config.items():
        assert parsed[key] == expected


def test_beads_database_is_not_disclosed_by_tracked_gitignore() -> None:
    entries = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert not any(".beads" in entry for entry in entries)
