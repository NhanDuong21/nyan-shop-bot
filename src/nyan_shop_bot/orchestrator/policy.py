"""Fail-closed task, path, and merge policy."""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import PurePosixPath

from nyan_shop_bot.orchestrator.models import TaskSpec

PROTECTED_PATTERNS = (
    ".agents/**",
    ".github/**",
    ".codex/**",
    "AGENTS.md",
    "GEMINI.md",
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


def forbidden_ui_worker_paths(changed_files: list[str]) -> list[str]:
    """Reject nested policy/build/config files even inside an allowed feature root."""

    forbidden: list[str] = []
    exact_names = {
        ".env",
        ".gitattributes",
        ".gitignore",
        ".gitmodules",
        ".npmrc",
        "agents.md",
        "gemini.md",
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
    }
    config_prefixes = (
        "eslint.config.",
        "tsconfig",
        "vite.config.",
        "vitest.config.",
    )
    for value in changed_files:
        parts = PurePosixPath(value.replace("\\", "/")).parts
        name = parts[-1].lower() if parts else ""
        lowered_parts = {part.lower() for part in parts}
        if (
            lowered_parts.intersection(
                {
                    ".agent",
                    ".agents",
                    ".codex",
                    ".git",
                    ".github",
                    "_agent",
                    "_agents",
                }
            )
            or name.startswith(".env")
            or name in exact_names
            or name.startswith(config_prefixes)
        ):
            forbidden.append(value)
    return forbidden


def auto_merge_policy(task: TaskSpec, changed_files: list[str], owner_authorized: bool) -> bool:
    """Fail closed until GitHub can atomically bind both reviewed head and base."""

    del task, changed_files, owner_authorized
    return False
