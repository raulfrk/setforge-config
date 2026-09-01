from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS = REPO_ROOT / "tracked/codex/AGENTS.md"
SKILL = REPO_ROOT / "tracked/codex/skills/beads/SKILL.md"
MANIFEST = REPO_ROOT / "setforge.yaml"


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_agent_policy_uses_selective_ownership() -> None:
    policy = normalized(AGENTS)
    assert "one primary agent to own each coherent change" in policy
    assert "Delegate only bounded, independent workstreams or independent review" in policy
    assert "never from the number of available agent slots" in policy


def test_beads_skill_preserves_private_authorized_lifecycle() -> None:
    skill = normalized(SKILL)
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
    ):
        assert invariant in skill


def test_beads_skill_uses_exact_project_vocabulary() -> None:
    skill = normalized(SKILL)
    for setting in (
        "epic.mode = milestone",
        "commit.mode = per-bead",
        "commit.format = type-prefix",
        "custom.workflow.decomposition = reviewer-friendly",
        "dolt.local-only = true",
        "dolt.auto-commit = on",
        "no-git-ops = true",
    ):
        assert setting in skill
    assert "Beads parallelism" not in skill
    assert "controller" in skill


def test_setforge_registers_only_the_skill_entrypoint() -> None:
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    resource = manifest["tracked_files"]["codex_skill_beads"]
    assert resource == {
        "src": "codex/skills/beads/SKILL.md",
        "dst": "~/.codex/skills/beads/SKILL.md",
    }
    assert "codex_skill_beads" in manifest["profiles"]["codex"]["tracked_files"]
    assert [path.name for path in SKILL.parent.iterdir()] == ["SKILL.md"]


def test_beads_database_is_not_disclosed_by_tracked_gitignore() -> None:
    entries = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert not any(".beads" in entry for entry in entries)
