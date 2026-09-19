"""Verified local CLI adapters for real worker and reviewer processes."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from nyan_shop_bot.orchestrator.models import (
    AgentInvocation,
    DesiredState,
    ReviewResult,
    Usage,
    WorkerKind,
    WorkerResult,
)

ControlReader = Callable[[], DesiredState]
ProcessStarted = Callable[[int], None]
ProcessFinished = Callable[[int], None]

SAFE_INHERITED_ENV = {
    "APPDATA",
    "CODEX_HOME",
    "COLORTERM",
    "COMSPEC",
    "HOME",
    "HOMEDRIVE",
    "HOMEPATH",
    "LANG",
    "LC_ALL",
    "LOCALAPPDATA",
    "LOGONSERVER",
    "NUMBER_OF_PROCESSORS",
    "OS",
    "PATH",
    "PATHEXT",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PROGRAMW6432",
    "PSMODULEPATH",
    "PUBLIC",
    "SHELL",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TERM",
    "TMP",
    "TMPDIR",
    "USERDOMAIN",
    "USERNAME",
    "USERPROFILE",
    "VIRTUAL_ENV",
    "WINDIR",
    "XDG_CACHE_HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
}


class AgentStopped(RuntimeError):
    """Raised when an owner stop request terminates an active agent."""


def sanitized_environment(isolation_dir: Path | None = None) -> dict[str, str]:
    """Allow only process basics and force non-production application endpoints."""

    clean = {
        name: value for name, value in os.environ.items() if name.upper() in SAFE_INHERITED_ENV
    }
    clean.update(
        {
            "APP_ENV": "local",
            "DATABASE_URL": (
                "postgresql+asyncpg://nyan_agent:nyan_agent_local_only@"
                "127.0.0.1:55432/nyan_shop_bot_agent_test"
            ),
            "SUPPLIER_MODE": "mock",
            "PAYMENT_MODE": "disabled",
            "ALLOW_REAL_PURCHASES": "false",
            "TELEGRAM_BOT_TOKEN": "",
            "GIT_TERMINAL_PROMPT": "0",
            "NO_COLOR": "1",
        }
    )
    if isolation_dir is not None:
        isolation_dir.mkdir(parents=True, exist_ok=True)
        empty_config = isolation_dir / "empty.config"
        empty_config.touch(exist_ok=True)
        docker_config = isolation_dir / "docker"
        docker_config.mkdir(exist_ok=True)
        clean.update(
            {
                "AWS_CONFIG_FILE": str(empty_config),
                "AWS_SHARED_CREDENTIALS_FILE": str(empty_config),
                "AZURE_CONFIG_DIR": str(isolation_dir / "azure"),
                "CLOUDSDK_CONFIG": str(isolation_dir / "gcloud"),
                "DOCKER_CONFIG": str(docker_config),
                "GH_CONFIG_DIR": str(isolation_dir / "gh"),
                "GIT_CONFIG_GLOBAL": str(empty_config),
                "GIT_CONFIG_NOSYSTEM": "1",
                "KUBECONFIG": str(empty_config),
                "NPM_CONFIG_USERCONFIG": str(empty_config),
                "PGPASSFILE": str(empty_config),
                "PIP_CONFIG_FILE": str(empty_config),
            }
        )
    return clean


def recover_session_id(path: Path, worker: WorkerKind) -> str | None:
    """Recover an explicit CLI session from a partially written event stream."""

    if not path.is_file():
        return None
    session_id: str | None = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if worker is WorkerKind.CODEX:
            if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
                session_id = str(event["thread_id"])
        elif isinstance(event.get("conversation_id"), str):
            session_id = str(event["conversation_id"])
        result = event.get("result")
        if (
            worker is WorkerKind.ANTIGRAVITY
            and isinstance(result, dict)
            and isinstance(result.get("conversation_id"), str)
        ):
            session_id = str(result["conversation_id"])
    return session_id


def write_schema(model: type[BaseModel], path: Path) -> None:
    path.write_text(json.dumps(model.model_json_schema(), indent=2), encoding="utf-8")


def _run_monitored(
    command: list[str],
    *,
    cwd: Path,
    stdin_text: str | None,
    stdout_path: Path,
    stderr_path: Path,
    control: ControlReader,
    timeout_seconds: int,
    on_process_start: ProcessStarted | None = None,
    on_process_end: ProcessFinished | None = None,
) -> None:
    started = time.monotonic()
    with (
        stdout_path.open("w", encoding="utf-8") as stdout_file,
        stderr_path.open("w", encoding="utf-8") as stderr_file,
    ):
        process = subprocess.Popen(  # noqa: S603 - executable is resolved and arguments are fixed
            command,
            cwd=cwd,
            stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
            encoding="utf-8",
            env=sanitized_environment(stdout_path.parent / "isolated-environment"),
        )
        process_attached = False
        try:
            if on_process_start is not None:
                on_process_start(process.pid)
                process_attached = True
            if stdin_text is not None:
                if process.stdin is None:
                    raise RuntimeError("agent stdin was not created")
                process.stdin.write(stdin_text)
                process.stdin.close()
            while process.poll() is None:
                # Pause/stop are cooperative for an active model turn: finish this bounded
                # invocation, persist its result, then stop at the next safe checkpoint.
                # CI waits stop immediately because they have no partial model state.
                control()
                if time.monotonic() - started > timeout_seconds:
                    raise TimeoutError(f"agent exceeded {timeout_seconds}s invocation limit")
                time.sleep(1)
            if process.returncode != 0:
                tail = stderr_path.read_text(encoding="utf-8", errors="replace")[-4000:]
                raise RuntimeError(f"agent exited {process.returncode}: {tail}")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            if process_attached and on_process_end is not None:
                on_process_end(process.pid)


def _load_final[ResultModel: BaseModel](path: Path, model: type[ResultModel]) -> ResultModel:
    if not path.is_file():
        raise RuntimeError(f"agent did not create final result: {path}")
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def _parse_codex_events(path: Path) -> tuple[str, Usage]:
    session_id: str | None = None
    usage = Usage()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if not isinstance(event, dict):
            continue
        if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
            session_id = str(event["thread_id"])
        if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            raw = event["usage"]
            usage = Usage(
                input_tokens=int(raw.get("input_tokens", 0)),
                cached_input_tokens=int(raw.get("cached_input_tokens", 0)),
                output_tokens=int(raw.get("output_tokens", 0)),
                reasoning_output_tokens=int(raw.get("reasoning_output_tokens", 0)),
            )
    if session_id is None:
        raise RuntimeError("Codex JSONL did not expose thread.started.thread_id")
    return session_id, usage


class CodexAdapter:
    """Codex CLI 0.153 non-interactive adapter using saved local ChatGPT auth."""

    def __init__(self) -> None:
        executable = shutil.which("codex")
        if executable is None:
            raise RuntimeError("Codex CLI is not installed")
        self.executable = executable

    def invoke[ResultModel: BaseModel](
        self,
        *,
        worktree: Path,
        run_dir: Path,
        name: str,
        prompt: str,
        result_model: type[ResultModel],
        sandbox: str,
        control: ControlReader,
        timeout_seconds: int,
        resume_session_id: str | None = None,
        model: str | None = None,
        on_process_start: ProcessStarted | None = None,
        on_process_end: ProcessFinished | None = None,
    ) -> tuple[ResultModel, AgentInvocation]:
        run_dir.mkdir(parents=True, exist_ok=True)
        schema_path = run_dir / f"{name}.schema.json"
        result_path = run_dir / f"{name}.result.json"
        events_path = run_dir / f"{name}.events.jsonl"
        stderr_path = run_dir / f"{name}.stderr.log"
        write_schema(result_model, schema_path)
        result_path.unlink(missing_ok=True)

        command = [
            self.executable,
            "-C",
            str(worktree),
            "-s",
            sandbox,
            "-a",
            "never",
            "exec",
        ]
        if resume_session_id is not None:
            command.extend(("resume", "--strict-config"))
        else:
            command.append("--strict-config")
        if model is not None:
            command.extend(("--model", model))
        command.extend(
            (
                "--json",
                "--output-schema",
                str(schema_path),
                "-o",
                str(result_path),
            )
        )
        if resume_session_id is not None:
            command.append(resume_session_id)
        command.append("-")

        _run_monitored(
            command,
            cwd=worktree,
            stdin_text=prompt,
            stdout_path=events_path,
            stderr_path=stderr_path,
            control=control,
            timeout_seconds=timeout_seconds,
            on_process_start=on_process_start,
            on_process_end=on_process_end,
        )
        result = _load_final(result_path, result_model)
        session_id, usage = _parse_codex_events(events_path)
        if resume_session_id is not None and session_id != resume_session_id:
            raise RuntimeError("Codex resumed a different session than requested")
        invocation = AgentInvocation(
            session_id=session_id,
            result_path=str(result_path),
            events_path=str(events_path),
            stderr_path=str(stderr_path),
            usage=usage,
        )
        return result, invocation

    def worker(
        self,
        *,
        worktree: Path,
        run_dir: Path,
        name: str,
        prompt: str,
        control: ControlReader,
        timeout_seconds: int,
        resume_session_id: str | None = None,
        model: str | None = None,
        on_process_start: ProcessStarted | None = None,
        on_process_end: ProcessFinished | None = None,
    ) -> tuple[WorkerResult, AgentInvocation]:
        return self.invoke(
            worktree=worktree,
            run_dir=run_dir,
            name=name,
            prompt=prompt,
            result_model=WorkerResult,
            sandbox="workspace-write",
            control=control,
            timeout_seconds=timeout_seconds,
            resume_session_id=resume_session_id,
            model=model,
            on_process_start=on_process_start,
            on_process_end=on_process_end,
        )

    def reviewer(
        self,
        *,
        worktree: Path,
        run_dir: Path,
        name: str,
        prompt: str,
        control: ControlReader,
        timeout_seconds: int,
        model: str | None = None,
        on_process_start: ProcessStarted | None = None,
        on_process_end: ProcessFinished | None = None,
    ) -> tuple[ReviewResult, AgentInvocation]:
        return self.invoke(
            worktree=worktree,
            run_dir=run_dir,
            name=name,
            prompt=prompt,
            result_model=ReviewResult,
            sandbox="read-only",
            control=control,
            timeout_seconds=timeout_seconds,
            model=model,
            on_process_start=on_process_start,
            on_process_end=on_process_end,
        )


def _parse_antigravity_events(path: Path) -> tuple[str, Usage, dict[str, Any]]:
    conversation_id: str | None = None
    usage = Usage()
    structured_output: dict[str, Any] | None = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if not isinstance(event, dict):
            continue
        if isinstance(event.get("conversation_id"), str):
            conversation_id = str(event["conversation_id"])
        if event.get("event") == "result" and isinstance(event.get("result"), dict):
            result = event["result"]
            if result.get("status") != "SUCCESS":
                raise RuntimeError(f"Antigravity terminal status was {result.get('status')!r}")
            if isinstance(result.get("conversation_id"), str):
                conversation_id = str(result["conversation_id"])
            raw_usage = result.get("usage")
            if isinstance(raw_usage, dict):
                usage = Usage(
                    input_tokens=int(raw_usage.get("input_tokens", 0)),
                    cached_input_tokens=int(raw_usage.get("cache_read_tokens", 0)),
                    output_tokens=int(raw_usage.get("output_tokens", 0)),
                    reasoning_output_tokens=int(raw_usage.get("thinking_tokens", 0)),
                )
            raw_output = result.get("structured_output")
            if isinstance(raw_output, dict):
                structured_output = raw_output
    if conversation_id is None:
        raise RuntimeError("Antigravity stream did not expose a conversation_id")
    if structured_output is None:
        raise RuntimeError("Antigravity stream did not expose structured_output")
    return conversation_id, usage, structured_output


class AntigravityAdapter:
    """Google agy 1.2.7 print-mode adapter; no GUI or internal endpoint automation."""

    def __init__(self) -> None:
        executable = shutil.which("agy")
        if executable is None:
            raise RuntimeError("Antigravity agy CLI is not installed")
        self.executable = executable

    def worker(
        self,
        *,
        worktree: Path,
        run_dir: Path,
        name: str,
        prompt: str,
        control: ControlReader,
        timeout_seconds: int,
        resume_session_id: str | None = None,
        model: str | None = None,
        on_process_start: ProcessStarted | None = None,
        on_process_end: ProcessFinished | None = None,
    ) -> tuple[WorkerResult, AgentInvocation]:
        run_dir.mkdir(parents=True, exist_ok=True)
        schema_path = run_dir / f"{name}.schema.json"
        events_path = run_dir / f"{name}.events.jsonl"
        stderr_path = run_dir / f"{name}.stderr.log"
        result_path = run_dir / f"{name}.result.json"
        write_schema(WorkerResult, schema_path)
        result_path.unlink(missing_ok=True)
        timeout_minutes = max(1, min(60, (timeout_seconds + 59) // 60))
        command = [
            self.executable,
            "-p",
            prompt,
        ]
        if resume_session_id is not None:
            command.extend(("--conversation", resume_session_id))
        if model is not None:
            command.extend(("--model", model))
        command.extend(
            (
                "--effort",
                "low",
                "--mode",
                "accept-edits",
                "--sandbox",
                "--disable-slash-commands",
                "--output-format",
                "stream-json",
                "--json-schema",
                str(schema_path),
                "--print-timeout",
                f"{timeout_minutes}m",
            )
        )
        _run_monitored(
            command,
            cwd=worktree,
            stdin_text=None,
            stdout_path=events_path,
            stderr_path=stderr_path,
            control=control,
            timeout_seconds=timeout_seconds,
            on_process_start=on_process_start,
            on_process_end=on_process_end,
        )
        session_id, usage, raw_output = _parse_antigravity_events(events_path)
        if resume_session_id is not None and session_id != resume_session_id:
            raise RuntimeError("Antigravity resumed a different conversation than requested")
        result_path.write_text(json.dumps(raw_output, indent=2), encoding="utf-8")
        result = WorkerResult.model_validate(raw_output)
        invocation = AgentInvocation(
            session_id=session_id,
            result_path=str(result_path),
            events_path=str(events_path),
            stderr_path=str(stderr_path),
            usage=usage,
        )
        return result, invocation
