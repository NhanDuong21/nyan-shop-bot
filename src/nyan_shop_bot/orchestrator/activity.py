"""Safe, compact projections of live agent protocol events."""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path
from typing import Any

from nyan_shop_bot.orchestrator.models import WorkerKind

MAX_TEXT = 800
_SECRET_PATTERNS = (
    re.compile(r"\b(?:gh[oprsu]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)
_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"password|passwd|secret|token)\b(\s*[:=]\s*)(?:bearer\s+|basic\s+)?([^\s,;]+)"
)
_CLI_SECRET_PATTERN = re.compile(
    r"(?i)(--?(?:api[-_]?key|access[-_]?token|refresh[-_]?token|password|passwd|secret|token))"
    r"(?:\s+|=)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_URL_CREDENTIAL_PATTERN = re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://[^:/@\s]+:)[^@\s]+@")
_ANSI_PATTERN = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
_CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BIDI_PATTERN = re.compile("[\u202a-\u202e\u2066-\u2069]")
_SAFE_COMMAND_WORDS = {
    "alembic",
    "build",
    "check",
    "docker",
    "git",
    "mypy",
    "npm",
    "npx",
    "pnpm",
    "pytest",
    "python",
    "python3",
    "ruff",
    "test",
    "tsc",
    "uvicorn",
    "vite",
    "yarn",
}


def redact_text(value: object, *, limit: int = MAX_TEXT) -> str:
    """Redact common credential shapes and bound one viewer field."""

    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    text = _ANSI_PATTERN.sub("", text)
    text = _CONTROL_PATTERN.sub("", text)
    text = _BIDI_PATTERN.sub("", text)
    text = _URL_CREDENTIAL_PATTERN.sub(r"\1[REDACTED]@", text)
    text = _CLI_SECRET_PATTERN.sub(r"\1 [REDACTED]", text)
    text = _ASSIGNMENT_PATTERN.sub(r"\1\2[REDACTED]", text)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    if len(text) > limit:
        return f"{text[: limit - 1]}…"
    return text


def safe_command_summary(value: object) -> str:
    """Describe a command without retaining its arbitrary argument values."""

    raw = str(value)
    try:
        words = shlex.split(raw, posix=False)
    except ValueError:
        words = raw.split()
    if not words:
        return "<empty command>"
    executable = Path(words[0].strip("\"'")).name.lower()
    if executable.endswith(".exe"):
        executable = executable[:-4]
    shown = executable if executable in _SAFE_COMMAND_WORDS else "<command>"
    safe_tail: list[str] = []
    for word in words[1:4]:
        normalized = word.strip("\"'").lower()
        if normalized in _SAFE_COMMAND_WORDS:
            safe_tail.append(normalized)
    if safe_tail:
        shown = f"{shown} {' '.join(safe_tail)}"
    return f"{shown} [arguments omitted]"


def _relative_file(value: object, worktree: Path) -> str:
    raw = Path(str(value))
    candidate = raw if raw.is_absolute() else worktree / raw
    try:
        return candidate.resolve(strict=False).relative_to(worktree.resolve()).as_posix()
    except ValueError:
        return f"<outside-worktree>/{redact_text(raw.name, limit=160)}"


def _usage_payload(raw: object) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    keys = {
        "input_tokens": "input_tokens",
        "cached_input_tokens": "cached_input_tokens",
        "cache_read_tokens": "cached_input_tokens",
        "output_tokens": "output_tokens",
        "reasoning_output_tokens": "reasoning_output_tokens",
        "thinking_tokens": "reasoning_output_tokens",
        "total_tokens": "total_tokens",
    }
    result: dict[str, int] = {}
    for source, target in keys.items():
        value = raw.get(source)
        if isinstance(value, int) and value >= 0:
            result[target] = value
    return result


def _codex_event(event: dict[str, Any], worktree: Path) -> dict[str, object]:
    event_type = event.get("type")
    payload: dict[str, object] = {"kind": redact_text(event_type or "stream.unknown", limit=120)}
    if event_type == "thread.started" and isinstance(event.get("thread_id"), str):
        payload["session_id"] = redact_text(event["thread_id"], limit=160)
        payload["summary"] = "Codex session started"
        return payload
    if event_type in {"turn.started", "turn.completed"}:
        payload["summary"] = f"Codex {str(event_type).replace('.', ' ')}"
        usage = _usage_payload(event.get("usage"))
        if usage:
            payload["usage"] = usage
        return payload
    item = event.get("item")
    if not isinstance(item, dict):
        payload["summary"] = f"Codex event {payload['kind']}"
        return payload
    item_type = redact_text(item.get("type", "unknown"), limit=120)
    payload["item_type"] = item_type
    if isinstance(item.get("status"), str):
        payload["status"] = redact_text(item["status"], limit=80)
    if item_type == "command_execution":
        payload["tool"] = "command_execution"
        if isinstance(item.get("command"), str):
            payload["command"] = safe_command_summary(item["command"])
        if isinstance(item.get("exit_code"), int):
            payload["exit_code"] = item["exit_code"]
        payload["summary"] = f"Command {payload.get('status', 'updated')}"
    elif item_type == "file_change":
        changes = item.get("changes")
        if isinstance(changes, dict):
            changes = [changes]
        projected: list[dict[str, str]] = []
        if isinstance(changes, list):
            for change in changes[:30]:
                if not isinstance(change, dict) or "path" not in change:
                    continue
                projected.append(
                    {
                        "path": _relative_file(change["path"], worktree),
                        "operation": redact_text(change.get("kind", "changed"), limit=80),
                    }
                )
        payload["files"] = projected
        payload["summary"] = f"File change {payload.get('status', 'updated')}"
    elif item_type == "agent_message":
        payload["summary"] = "Codex produced an agent message update"
    else:
        payload["summary"] = f"Codex {item_type} {payload.get('status', 'updated')}"
    return payload


def _tool_parameters(raw: object, worktree: Path) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    projected: dict[str, str] = {}
    for key, value in raw.items():
        normalized = str(key).lower().replace("_", "")
        if normalized in {"command", "commandline", "cmd"}:
            projected["command"] = safe_command_summary(value)
        elif normalized in {"path", "filepath", "filename", "targetfile"}:
            projected["path"] = _relative_file(value, worktree)
    return projected


def _antigravity_event(event: dict[str, Any], worktree: Path) -> dict[str, object]:
    event_type = event.get("event")
    payload: dict[str, object] = {"kind": redact_text(event_type or "stream.unknown", limit=120)}
    if isinstance(event.get("conversation_id"), str) and event["conversation_id"]:
        payload["session_id"] = redact_text(event["conversation_id"], limit=160)
    if event_type == "init":
        init = event.get("init")
        payload["summary"] = "Antigravity session initialized"
        if isinstance(init, dict):
            for source, target in (
                ("permission_mode", "permission_mode"),
                ("model", "model"),
                ("agent", "agent"),
            ):
                if isinstance(init.get(source), str):
                    payload[target] = redact_text(init[source], limit=160)
        return payload
    if event_type == "step_update":
        step = event.get("step_update")
        if not isinstance(step, dict):
            payload["summary"] = "Antigravity step update"
            return payload
        if isinstance(step.get("conversation_id"), str):
            payload["session_id"] = redact_text(step["conversation_id"], limit=160)
        step_type = redact_text(step.get("step_type", "unknown"), limit=120)
        payload["step_type"] = step_type
        if isinstance(step.get("state"), str):
            payload["status"] = redact_text(step["state"], limit=80)
        if step_type == "tool":
            payload["tool"] = redact_text(step.get("tool_name", "tool"), limit=160)
            tool_info = step.get("tool_info")
            if isinstance(tool_info, dict):
                payload.update(_tool_parameters(tool_info.get("parameters"), worktree))
                error = tool_info.get("error")
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    payload["error"] = (
                        "Tool reported an error; details remain in the private stream"
                    )
            payload["summary"] = f"Tool {payload['tool']} {payload.get('status', 'updated')}"
        elif step_type == "agent_response" and isinstance(step.get("text_delta"), str):
            payload["summary"] = "Antigravity produced an agent response update"
        else:
            payload["summary"] = f"Antigravity {step_type} {payload.get('status', 'updated')}"
        usage = _usage_payload(step.get("usage"))
        if usage:
            payload["usage"] = usage
        return payload
    if event_type == "result":
        result = event.get("result")
        payload["summary"] = "Antigravity result"
        if isinstance(result, dict):
            if isinstance(result.get("conversation_id"), str):
                payload["session_id"] = redact_text(result["conversation_id"], limit=160)
            if isinstance(result.get("status"), str):
                payload["status"] = redact_text(result["status"], limit=80)
            usage = _usage_payload(result.get("usage"))
            if usage:
                payload["usage"] = usage
        return payload
    payload["summary"] = f"Antigravity event {payload['kind']}"
    return payload


def normalize_stream_line(
    line: str,
    *,
    channel: str,
    worker: WorkerKind,
    worktree: Path,
) -> dict[str, object] | None:
    """Project a protocol/stderr line without persisting arbitrary raw output."""

    stripped = line.strip()
    if not stripped:
        return None
    if channel == "stderr":
        return {
            "kind": "diagnostic.stderr",
            "summary": "Agent emitted a stderr diagnostic; content remains in the private stream",
        }
    try:
        raw = json.loads(stripped)
    except json.JSONDecodeError:
        return {
            "kind": "stream.non_json",
            "summary": (
                "Agent emitted a non-JSON stdout line; raw content remains in the "
                "private protocol file"
            ),
        }
    if not isinstance(raw, dict):
        return {
            "kind": "stream.non_object",
            "summary": "Agent emitted a non-object JSON value",
        }
    if worker is WorkerKind.CODEX:
        return _codex_event(raw, worktree)
    return _antigravity_event(raw, worktree)
