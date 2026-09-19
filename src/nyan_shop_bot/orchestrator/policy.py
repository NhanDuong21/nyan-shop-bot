"""Fail-closed task, path, and merge policy."""

from __future__ import annotations

from fnmatch import fnmatchcase

from nyan_shop_bot.orchestrator.models import TaskSpec

PROTECTED_PATTERNS = (
    ".github/**",
    ".codex/**",
    "AGENTS.md",
    "alembic/**",
    "docs/agent-ops.md",
    "ops/agent_tasks/**",
    "pyproject.toml",
    "requirements*.lock",
    "scripts/agent_runner.py",
    "scripts/github_seed.py",
    "scripts/security_policy.py",
    "src/nyan_shop_bot/config.py",
    "src/nyan_shop_bot/orchestrator/**",
)


def path_matches(path: str, pattern: str) -> bool:
    """Match a repository path, including directory/** prefixes."""

    normalized = path.replace("\\", "/")
    if pattern.endswith("/**") and normalized.startswith(pattern[:-3] + "/"):
        return True
    return fnmatchcase(normalized, pattern)


def paths_are_allowed(changed_files: list[str], allowed_paths: list[str]) -> bool:
    return bool(changed_files) and all(
        any(path_matches(path, pattern) for pattern in allowed_paths) for path in changed_files
    )


def protected_paths(changed_files: list[str]) -> list[str]:
    return [
        path
        for path in changed_files
        if any(path_matches(path, pattern) for pattern in PROTECTED_PATTERNS)
    ]


def auto_merge_policy(task: TaskSpec, changed_files: list[str], owner_authorized: bool) -> bool:
    """Fail closed until GitHub can atomically bind both reviewed head and base."""

    del task, changed_files, owner_authorized
    return False
