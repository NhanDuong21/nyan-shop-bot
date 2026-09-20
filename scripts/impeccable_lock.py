"""Generate or verify the committed project-local Impeccable payload lock."""

from __future__ import annotations

import argparse
import json
import subprocess
from hashlib import sha256
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / ".impeccable" / "lock.json"
TREE_PREFIXES = (
    ".agents/skills/impeccable",
    ".agent/skills/impeccable",
)
EXPECTED_SOURCE: dict[str, Any] = {
    "engine_version": "0.1.5",
    "install_command": (
        "npx --yes impeccable@4.1.0 install -y "
        "--providers=codex,antigravity --scope=project --no-hooks"
    ),
    "npm_dist_integrity": (
        "sha512-hnfdoUK/Xg3qPtL0/5xzh92qKOtmREOZloCmFgnC1nYh3M81ihwCQEL2QWKntYl8qg1OG+"
        "jQ7wubR634PgTDIw=="
    ),
    "package": "impeccable@4.1.0",
    "providers": ["codex", "antigravity"],
    "scope": "project",
    "skill_version": "4.3.1",
}


def git_bytes(*arguments: str) -> bytes:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout


def committed_payload() -> dict[str, str]:
    raw_tree = git_bytes("ls-tree", "-r", "-z", "HEAD", "--", *TREE_PREFIXES)
    payload: dict[str, str] = {}
    for raw_entry in (entry for entry in raw_tree.split(b"\0") if entry):
        metadata, raw_relative = raw_entry.split(b"\t", 1)
        mode, kind, _object_id = metadata.decode("ascii").split()
        relative = raw_relative.decode("utf-8")
        if mode not in {"100644", "100755"} or kind != "blob":
            raise RuntimeError(f"Impeccable payload is not a regular blob: {relative}")
        payload[relative] = sha256(git_bytes("show", f"HEAD:{relative}")).hexdigest()
    if not payload:
        raise RuntimeError("Impeccable payload is absent from HEAD")
    return dict(sorted(payload.items()))


def lock_document() -> dict[str, Any]:
    return {
        "files": committed_payload(),
        "schema_version": 1,
        "source": EXPECTED_SOURCE,
    }


def write_lock() -> None:
    dirty = git_bytes("status", "--porcelain=v1", "--", *TREE_PREFIXES).decode("utf-8")
    if dirty:
        raise RuntimeError("Impeccable payload must be committed and clean before locking")
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCK_PATH.write_text(
        json.dumps(lock_document(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"Wrote {LOCK_PATH.relative_to(ROOT)}")


def check_lock() -> None:
    try:
        actual = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("Impeccable payload lock is missing or invalid") from error
    expected = lock_document()
    if actual != expected:
        raise RuntimeError("Impeccable payload lock differs from committed HEAD")
    print(
        "Impeccable payload lock passed: "
        f"{len(expected['files'])} committed files, exact npm provenance and SHA-256 digests."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="replace the lock from committed HEAD")
    arguments = parser.parse_args()
    if arguments.write:
        write_lock()
    else:
        check_lock()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
