from __future__ import annotations

import json
import hashlib
import os
import re
import shlex
import shutil
import stat
import subprocess
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS = REPO_ROOT / "tracked/codex/AGENTS.md"
SKILLS = REPO_ROOT / "tracked/codex/skills"
BASE_SKILL = SKILLS / "beads/SKILL.md"
BOOTSTRAP_SKILL = SKILLS / "beads-bootstrap/SKILL.md"
ADAPT_SKILL = SKILLS / "beads-adapt/SKILL.md"
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


def holder_preflight_script() -> str:
    match = re.search(
        r"## Prove there are no holders.*?```sh\n(.*?)```",
        ADAPT_SKILL.read_text(encoding="utf-8"),
        flags=re.DOTALL,
    )
    assert match is not None
    return match.group(1)


def apply_sync_remote_fallback(config_path: Path, value: str) -> None:
    original = f"sync:\n    remote: {value}"
    contents = config_path.read_text(encoding="utf-8")
    assert contents.count(original) == 1
    config_path.write_text(contents.replace(original, "sync:"), encoding="utf-8")


def initialize_repo(
    tmp_path: Path, name: str = "project"
) -> tuple[Path, dict[str, str]]:
    env = isolated_env(tmp_path)
    repo = tmp_path / name
    repo.mkdir()
    run(["git", "init", "--quiet"], cwd=repo, env=env)
    run(["git", "config", "user.name", "Test User"], cwd=repo, env=env)
    run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, env=env)
    return repo, env


def initialize_beads(repo: Path, env: dict[str, str], prefix: str = "project") -> None:
    run(
        [
            "bd",
            "init",
            "--stealth",
            "--non-interactive",
            "--skip-agents",
            "--skip-hooks",
            "--prefix",
            prefix,
        ],
        cwd=repo,
        env=env,
    )


def issue_snapshot(repo: Path, env: dict[str, str]) -> list[dict[str, object]]:
    result = run(
        [
            "bd",
            "--readonly",
            "list",
            "--all",
            "--limit",
            "0",
            "--include-gates",
            "--include-infra",
            "--include-templates",
            "--json",
        ],
        cwd=repo,
        env=env,
    )
    issues = json.loads(result.stdout)
    for issue in issues:
        issue["dependencies"] = sorted(
            issue.get("dependencies", []),
            key=lambda dependency: (
                dependency.get("issue_id", ""),
                dependency.get("depends_on_id", dependency.get("id", "")),
            ),
        )
    return sorted(issues, key=lambda issue: issue["id"])


def tree_manifest(root: Path) -> list[tuple[str, str, int, int, str]]:
    manifest = []
    for path in sorted(root.rglob("*")):
        metadata = path.lstat()
        relative = path.relative_to(root).as_posix()
        if stat.S_ISDIR(metadata.st_mode):
            kind = "directory"
            digest = ""
        elif stat.S_ISLNK(metadata.st_mode):
            kind = "symlink"
            digest = hashlib.sha256(os.readlink(path).encode()).hexdigest()
        else:
            kind = "file"
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest.append(
            (relative, kind, stat.S_IMODE(metadata.st_mode), metadata.st_size, digest)
        )
    return manifest


def test_agent_policy_uses_selective_ownership_and_beads_discovery() -> None:
    policy = normalized(AGENTS)
    assert "one primary agent to own each coherent change" in policy
    assert (
        "Delegate only bounded, independent workstreams or independent review" in policy
    )
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
    for meaning in (
        "leaf Beads own implementation",
        "`feat:`, `fix:`, `docs:`-style prefixes and omit private Bead IDs",
        "Keep `sync.remote` absent and configure no Dolt remotes",
        "after each successful embedded database write",
        "changing Git state or installing Git hooks",
    ):
        assert meaning in reference
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
        "codex_skill_beads_adapt": {
            "src": "codex/skills/beads-adapt/SKILL.md",
            "dst": "~/.codex/skills/beads-adapt/SKILL.md",
        },
    }
    profile_files = manifest["profiles"]["codex"]["tracked_files"]
    for name, resource in expected.items():
        assert manifest["tracked_files"][name] == resource
        assert name in profile_files


def test_skill_reference_links_resolve_in_source_and_deployed_layout(
    tmp_path: Path,
) -> None:
    assert (BASE_SKILL.parent / "references/project-config.md").resolve() == REFERENCE
    assert (
        BOOTSTRAP_SKILL.parent / "../beads/references/project-config.md"
    ).resolve() == REFERENCE
    assert (
        ADAPT_SKILL.parent / "../beads/references/project-config.md"
    ).resolve() == REFERENCE

    deployed = tmp_path / ".codex/skills"
    deployed_reference = deployed / "beads/references/project-config.md"
    deployed_reference.parent.mkdir(parents=True)
    deployed_reference.write_text(
        REFERENCE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    assert (
        deployed / "beads-bootstrap/../beads/references/project-config.md"
    ).resolve() == deployed_reference
    assert (
        deployed / "beads-adapt/../beads/references/project-config.md"
    ).resolve() == deployed_reference


def test_real_bd_bootstrap_reaches_canonical_private_state(tmp_path: Path) -> None:
    repo, env = initialize_repo(tmp_path)

    absent = run(["bd", "where", "--json"], cwd=repo, env=env, check=False)
    assert absent.returncode == 1
    assert json.loads(absent.stdout)["error"] == "no_beads_directory"

    initialize_beads(repo, env)
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


def test_adaptation_skill_is_fail_closed_and_preserves_before_mutation() -> None:
    skill = normalized(ADAPT_SKILL)
    for invariant in (
        "return without creating a backup or changing anything",
        "Stop on staged divergence",
        "set -o pipefail",
        'beads_dir=$(realpath -- "$git_root/.beads") || exit 1',
        "test \"$holders\" = '[]' ||",
        "Any holder, missing tool, command failure, or parse failure",
        "Pinned Beads 1.1.2 can report success without persisting this removal",
        "use `apply_patch` to remove only the detected `remote:`",
        "prove it is outside the Git worktree",
        "Do not mutate anything if a comparison fails",
        "Every `bd` mutation uses `--sandbox`",
        "exact `.beads/` line is absent",
        "git ls-files -z -- .beads",
        "Only when that enumeration is nonempty",
        "non-forced",
        "that `sync.remote` is absent",
        "every live byte hash is unchanged",
    ):
        assert invariant in skill
    assert skill.index("require exactly one such line") < skill.index(
        "Remove only the approved exact Beads-only `.gitignore` lines"
    )
    assert skill.index(
        "immediately require `git check-ignore --no-index -v .beads`"
    ) < skill.index("uninstall only positively identified Beads hooks")
    assert CANONICAL_PREFIX not in ADAPT_SKILL.read_text(encoding="utf-8")


def test_real_lsfd_holder_query_detects_open_database_file(tmp_path: Path) -> None:
    repo, env = initialize_repo(tmp_path)
    initialize_beads(repo, env)
    beads_dir = str((repo / ".beads").resolve())
    query = (
        '[.lsfd[] | select(((.name // "") == $root) or '
        '((.name // "") | startswith($root + "/")))]'
    )

    closed = run(["lsfd", "-J", "-o", "PID,NAME"], cwd=repo, env=env)
    closed_holders = subprocess.run(
        ["jq", "-ce", "--arg", "root", beads_dir, query],
        cwd=repo,
        env=env,
        input=closed.stdout,
        check=True,
        text=True,
        capture_output=True,
    )
    assert json.loads(closed_holders.stdout) == []

    with (repo / ".beads/metadata.json").open("rb"):
        opened = run(["lsfd", "-J", "-o", "PID,NAME"], cwd=repo, env=env)
        open_holders = subprocess.run(
            ["jq", "-ce", "--arg", "root", beads_dir, query],
            cwd=repo,
            env=env,
            input=opened.stdout,
            check=True,
            text=True,
            capture_output=True,
        )
    holders = json.loads(open_holders.stdout)
    assert holders
    assert all(holder["name"].startswith(f"{beads_dir}/") for holder in holders)


def test_holder_preflight_fails_closed_before_backup_or_mutation(
    tmp_path: Path,
) -> None:
    repo, env = initialize_repo(tmp_path)
    initialize_beads(repo, env)
    marker = repo / "unchanged"
    marker.write_text("original\n", encoding="utf-8")
    backup_root = tmp_path / "state/beads/adaptation-backups"

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    for command in ("jq", "realpath"):
        executable = shutil.which(command)
        assert executable is not None
        (fake_bin / command).symlink_to(executable)

    isolated_path_env = env.copy()
    isolated_path_env["PATH"] = str(fake_bin)
    isolated_path_env["git_root"] = str(repo)
    missing_lsfd = subprocess.run(
        ["/bin/bash", "-c", holder_preflight_script()],
        cwd=repo,
        env=isolated_path_env,
        text=True,
        capture_output=True,
    )
    assert missing_lsfd.returncode != 0
    assert "holder inspection failed" in missing_lsfd.stderr
    assert not backup_root.exists()
    assert marker.read_text(encoding="utf-8") == "original\n"

    fake_lsfd = fake_bin / "lsfd"
    fake_lsfd.write_text("#!/bin/sh\nprintf 'not-json\\n'\n", encoding="utf-8")
    fake_lsfd.chmod(0o755)
    malformed_json = subprocess.run(
        ["/bin/bash", "-c", holder_preflight_script()],
        cwd=repo,
        env=isolated_path_env,
        text=True,
        capture_output=True,
    )
    assert malformed_json.returncode != 0
    assert "holder inspection failed" in malformed_json.stderr
    assert not backup_root.exists()
    assert marker.read_text(encoding="utf-8") == "original\n"


def test_conformant_adaptation_preflight_is_a_noop(tmp_path: Path) -> None:
    repo, env = initialize_repo(tmp_path)
    initialize_beads(repo, env)
    run(canonical_command(), cwd=repo, env=env)

    before_tree = tree_manifest(repo / ".beads")
    before_status = run(
        ["git", "status", "--short", "--untracked-files=all"], cwd=repo, env=env
    ).stdout
    backup_root = tmp_path / "state/beads/adaptation-backups"

    metadata = json.loads((repo / ".beads/metadata.json").read_text(encoding="utf-8"))
    config = run(["bd", "config", "show"], cwd=repo, env=env).stdout
    hooks = run(["bd", "hooks", "list"], cwd=repo, env=env).stdout
    remotes = json.loads(
        run(["bd", "dolt", "remote", "list", "--json"], cwd=repo, env=env).stdout
    )
    ignore = run(["git", "check-ignore", "-v", ".beads"], cwd=repo, env=env)
    tracked = run(["git", "ls-files", ".beads"], cwd=repo, env=env).stdout

    assert metadata["dolt_mode"] == "embedded"
    for setting in (
        "epic.mode",
        "commit.mode",
        "commit.format",
        "custom.workflow.decomposition",
        "dolt.local-only",
        "dolt.auto-commit",
        "no-git-ops",
    ):
        assert setting in config
    assert "sync.remote" not in config
    assert hooks.count("not installed") == 5
    assert remotes == []
    assert tracked == ""
    assert ".git/info/exclude" in ignore.stdout

    assert not backup_root.exists()
    assert tree_manifest(repo / ".beads") == before_tree
    assert (
        run(
            ["git", "status", "--short", "--untracked-files=all"],
            cwd=repo,
            env=env,
        ).stdout
        == before_status
    )


def test_real_bd_legacy_state_is_archived_and_converges_without_data_loss(
    tmp_path: Path,
) -> None:
    repo, env = initialize_repo(tmp_path)
    initialize_beads(repo, env, prefix="legacy")
    run(canonical_command(), cwd=repo, env=env)

    exclude = repo / ".git/info/exclude"
    original_exclude = exclude.read_text(encoding="utf-8")
    exclude.write_text(
        "\n".join(line for line in original_exclude.splitlines() if line != ".beads/")
        + "\n",
        encoding="utf-8",
    )
    assert ".beads/" not in exclude.read_text(encoding="utf-8").splitlines()

    parent_id = run(
        ["bd", "--sandbox", "create", "Parent", "--type", "epic", "--silent"],
        cwd=repo,
        env=env,
    ).stdout.strip()
    child_id = run(
        ["bd", "--sandbox", "create", "Child", "--parent", parent_id, "--silent"],
        cwd=repo,
        env=env,
    ).stdout.strip()
    blocker_id = run(
        ["bd", "--sandbox", "create", "Blocker", "--silent"], cwd=repo, env=env
    ).stdout.strip()
    run(["bd", "--sandbox", "dep", "add", child_id, blocker_id], cwd=repo, env=env)
    before_issues = issue_snapshot(repo, env)

    run(["bd", "--sandbox", "hooks", "install"], cwd=repo, env=env)
    run(
        ["bd", "--sandbox", "dolt", "remote", "add", "legacy", "file:///tmp/legacy"],
        cwd=repo,
        env=env,
    )
    run(
        ["bd", "--sandbox", "config", "set", "sync.remote", "legacy"], cwd=repo, env=env
    )
    run(["bd", "--sandbox", "config", "set", "epic.mode", "legacy"], cwd=repo, env=env)
    run(["bd", "--sandbox", "config", "set", "no-git-ops", "false"], cwd=repo, env=env)

    gitignore = repo / ".gitignore"
    gitignore.write_text("keep-this-line\n.beads/\n", encoding="utf-8")
    run(["git", "add", ".gitignore"], cwd=repo, env=env)
    tracked = [".beads/metadata.json", ".beads/config.yaml"]
    run(["git", "add", "--force", "--", *tracked], cwd=repo, env=env)
    run(["git", "commit", "--quiet", "-m", "test: legacy state"], cwd=repo, env=env)

    source_manifest = tree_manifest(repo / ".beads")
    source_metadata = (repo / ".beads/metadata.json").read_bytes()
    backup_root = tmp_path / "state/beads/adaptation-backups/legacy-backup"
    backup_root.mkdir(parents=True)
    backup_beads = backup_root / ".beads"
    run(["cp", "-a", ".beads", str(backup_beads)], cwd=repo, env=env)
    assert repo.resolve() not in backup_root.resolve().parents
    assert tree_manifest(backup_beads) == source_manifest
    assert (backup_beads / "metadata.json").read_bytes() == source_metadata
    assert issue_snapshot(backup_root, env) == before_issues

    with exclude.open("a", encoding="utf-8") as stream:
        stream.write(".beads/\n")
    assert exclude.read_text(encoding="utf-8").splitlines().count(".beads/") == 1
    gitignore.write_text("keep-this-line\n", encoding="utf-8")
    assert (
        ".git/info/exclude"
        in run(
            ["git", "check-ignore", "--no-index", "-v", ".beads"],
            cwd=repo,
            env=env,
        ).stdout
    )
    run(["bd", "--sandbox", "hooks", "uninstall"], cwd=repo, env=env)
    run(["bd", "--sandbox", "dolt", "remote", "remove", "legacy"], cwd=repo, env=env)
    run(["bd", "--sandbox", "config", "unset", "sync.remote"], cwd=repo, env=env)
    apply_sync_remote_fallback(repo / ".beads/config.yaml", "legacy")
    assert (
        json.loads(
            run(["bd", "dolt", "remote", "list", "--json"], cwd=repo, env=env).stdout
        )
        == []
    )
    run(canonical_command(), cwd=repo, env=env)

    tracked_output = run(
        ["git", "ls-files", "-z", "--", ".beads"], cwd=repo, env=env
    ).stdout
    tracked_paths = [path for path in tracked_output.split("\0") if path]
    before_hashes = {
        path: hashlib.sha256((repo / path).read_bytes()).hexdigest()
        for path in tracked_paths
    }
    run(["git", "rm", "-r", "--cached", "--", *tracked_paths], cwd=repo, env=env)
    after_hashes = {
        path: hashlib.sha256((repo / path).read_bytes()).hexdigest()
        for path in tracked_paths
    }

    assert after_hashes == before_hashes
    assert issue_snapshot(repo, env) == before_issues
    assert gitignore.read_text(encoding="utf-8") == "keep-this-line\n"
    assert (
        ".git/info/exclude"
        in run(["git", "check-ignore", "-v", ".beads"], cwd=repo, env=env).stdout
    )
    assert run(["git", "ls-files", ".beads"], cwd=repo, env=env).stdout == ""
    assert (
        json.loads(
            run(["bd", "dolt", "remote", "list", "--json"], cwd=repo, env=env).stdout
        )
        == []
    )
    hooks = run(["bd", "hooks", "list"], cwd=repo, env=env).stdout
    assert hooks.count("not installed") == 5


def test_untracked_orphaned_sync_remote_is_archived_and_converges(
    tmp_path: Path,
) -> None:
    repo, env = initialize_repo(tmp_path)
    initialize_beads(repo, env)
    run(canonical_command(), cwd=repo, env=env)
    run(
        ["bd", "--sandbox", "config", "set", "sync.remote", "missing"],
        cwd=repo,
        env=env,
    )

    assert (
        json.loads(
            run(["bd", "dolt", "remote", "list", "--json"], cwd=repo, env=env).stdout
        )
        == []
    )
    tracked_output = run(
        ["git", "ls-files", "-z", "--", ".beads"], cwd=repo, env=env
    ).stdout
    assert tracked_output == ""
    assert "sync.remote" in run(["bd", "config", "show"], cwd=repo, env=env).stdout

    backup_root = tmp_path / "state/beads/adaptation-backups/orphan-backup"
    backup_root.mkdir(parents=True)
    backup_beads = backup_root / ".beads"
    run(["cp", "-a", ".beads", str(backup_beads)], cwd=repo, env=env)
    assert tree_manifest(backup_beads) == tree_manifest(repo / ".beads")

    run(["bd", "--sandbox", "config", "unset", "sync.remote"], cwd=repo, env=env)
    apply_sync_remote_fallback(repo / ".beads/config.yaml", "missing")
    run(canonical_command(), cwd=repo, env=env)
    tracked_paths = [path for path in tracked_output.split("\0") if path]
    if tracked_paths:
        run(["git", "rm", "-r", "--cached", "--", *tracked_paths], cwd=repo, env=env)

    config = run(["bd", "config", "show"], cwd=repo, env=env).stdout
    assert "sync.remote" not in config
    assert run(["git", "ls-files", ".beads"], cwd=repo, env=env).stdout == ""
    assert backup_beads.is_dir()


def test_staged_database_divergence_is_detected_before_adaptation(
    tmp_path: Path,
) -> None:
    repo, env = initialize_repo(tmp_path)
    initialize_beads(repo, env)
    run(["git", "add", "--force", ".beads/metadata.json"], cwd=repo, env=env)
    result = run(
        ["git", "diff", "--cached", "--quiet", "--", ".beads"],
        cwd=repo,
        env=env,
        check=False,
    )
    assert result.returncode == 1


def test_beads_database_is_not_disclosed_by_tracked_gitignore() -> None:
    entries = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert not any(".beads" in entry for entry in entries)
