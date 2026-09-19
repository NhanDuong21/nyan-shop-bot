"""Verified local CLI adapters for real worker and reviewer processes."""

from __future__ import annotations

import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from nyan_shop_bot.orchestrator.activity import redact_text
from nyan_shop_bot.orchestrator.models import (
    AgentInvocation,
    DesiredState,
    ReviewResult,
    Usage,
    WorkerKind,
    WorkerResult,
)

ControlReader = Callable[[], DesiredState]
ProcessStarted = Callable[[int, str, str, str], None]
ProcessFinished = Callable[[int, str, str, str], None]
StreamLine = Callable[[str, str, int], None]
WINDOWS_CREATE_NEW_PROCESS_GROUP = 0x00000200
ACTIVITY_QUEUE_CAPACITY = 512
SUPPORTED_ANTIGRAVITY_VERSION = "1.2.7"


@dataclass(frozen=True)
class ActivityDelivery:
    """Best-effort live projection delivery; raw protocol files remain authoritative."""

    delivered: int = 0
    dropped: int = 0
    errors: int = 0
    clean_shutdown: bool = True

    @property
    def degraded(self) -> bool:
        return self.dropped > 0 or self.errors > 0 or not self.clean_shutdown


if sys.platform == "win32":

    def _kill_process_group(pid: int, signal_number: int) -> None:
        raise RuntimeError("POSIX process groups are unavailable on Windows")

else:

    def _kill_process_group(pid: int, signal_number: int) -> None:
        os.killpg(pid, signal_number)


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


class AgentPaused(RuntimeError):
    """Raised after an owner pause safely contains an active agent process tree."""


def process_is_running(pid: int) -> bool:
    """Return whether a PID still represents an executing process."""

    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes  # noqa: PLC0415 - Windows-only import

        process_query_limited_information = 0x1000
        synchronize = 0x00100000
        still_active = 259
        wait_object_0 = 0
        wait_timeout = 258
        kernel32 = cast(Any, ctypes).windll.kernel32
        handle = kernel32.OpenProcess(process_query_limited_information | synchronize, False, pid)
        if not handle:
            return False
        exit_code = ctypes.c_ulong()
        try:
            wait_result = int(kernel32.WaitForSingleObject(handle, 0))
            if wait_result == wait_object_0:
                return False
            if wait_result != wait_timeout:
                return False
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def process_identity(pid: int) -> str | None:
    """Return an OS creation identity that changes when a PID is reused."""

    if pid <= 0:
        return None
    if os.name == "nt":
        import ctypes  # noqa: PLC0415 - Windows-only import
        from ctypes import wintypes  # noqa: PLC0415 - Windows-only import

        process_query_limited_information = 0x1000
        synchronize = 0x00100000
        ctypes_api = cast(Any, ctypes)
        kernel32 = ctypes_api.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetProcessTimes.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        )
        kernel32.GetProcessTimes.restype = wintypes.BOOL
        kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel32.OpenProcess(process_query_limited_information | synchronize, False, pid)
        if not handle:
            error_code = ctypes_api.get_last_error()
            if error_code in {6, 87}:
                return None
            raise PermissionError(error_code, f"cannot inspect Windows PID {pid}")
        created = wintypes.FILETIME()
        exited = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        exit_code = wintypes.DWORD()
        try:
            wait_result = int(kernel32.WaitForSingleObject(handle, 0))
            if wait_result == 0:
                return None
            if wait_result != 258:
                raise RuntimeError(
                    f"could not read wait state for Windows PID {pid}: result {wait_result}"
                )
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                raise RuntimeError(
                    f"could not read exit state for Windows PID {pid}: "
                    f"error {ctypes_api.get_last_error()}"
                )
            if int(exit_code.value) != 259:
                return None
            if not kernel32.GetProcessTimes(
                handle,
                ctypes.byref(created),
                ctypes.byref(exited),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ):
                raise RuntimeError(
                    f"could not read creation identity for Windows PID {pid}: "
                    f"error {ctypes_api.get_last_error()}"
                )
            ticks = (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)
            return f"windows:{ticks}"
        finally:
            kernel32.CloseHandle(handle)
    if sys.platform.startswith("linux"):
        try:
            boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        except (FileNotFoundError, ProcessLookupError):
            return None
        except PermissionError as error:
            raise PermissionError(f"cannot inspect Linux PID {pid}") from error
        closing = stat.rfind(")")
        if closing < 0:
            raise RuntimeError("could not parse Linux process identity")
        fields = stat[closing + 2 :].split()
        if len(fields) < 20:
            raise RuntimeError("Linux process identity omitted its start time")
        return f"linux:{boot_id}:{fields[19]}"
    raise RuntimeError(f"durable process identity is unsupported on {sys.platform}")


def process_matches(pid: int, expected_identity: str) -> bool:
    """Refuse PID-only decisions by checking the recorded process incarnation."""

    return process_identity(pid) == expected_identity


def _terminate_windows_verified(pid: int, expected_identity: str) -> bool:
    import ctypes  # noqa: PLC0415 - Windows-only import
    from ctypes import wintypes  # noqa: PLC0415 - Windows-only import

    process_terminate = 0x0001
    process_query_limited_information = 0x1000
    synchronize = 0x00100000
    ctypes_api = cast(Any, ctypes)
    kernel32 = ctypes_api.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    )
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel32.TerminateProcess.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel32.OpenProcess(
        process_terminate | process_query_limited_information | synchronize,
        False,
        pid,
    )
    if not handle:
        error_code = ctypes_api.get_last_error()
        if error_code in {6, 87}:
            return True
        raise PermissionError(error_code, f"cannot terminate Windows PID {pid}")
    created = wintypes.FILETIME()
    exited = wintypes.FILETIME()
    kernel = wintypes.FILETIME()
    user = wintypes.FILETIME()
    try:
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            raise ctypes_api.WinError(ctypes_api.get_last_error())
        ticks = (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)
        if f"windows:{ticks}" != expected_identity:
            return True
        if not kernel32.TerminateProcess(handle, 125):
            error_code = ctypes_api.get_last_error()
            if error_code != 5:
                raise ctypes_api.WinError(error_code)
        kernel32.WaitForSingleObject(handle, 3000)
        return True
    finally:
        kernel32.CloseHandle(handle)


def _terminate_linux_verified(pid: int, expected_identity: str) -> bool:
    pidfd_open = getattr(os, "pidfd_open", None)
    pidfd_send_signal = getattr(signal, "pidfd_send_signal", None)
    if pidfd_open is None or pidfd_send_signal is None:
        raise RuntimeError("Linux pidfd support is required for PID-safe termination")
    try:
        pidfd = int(pidfd_open(pid))
    except ProcessLookupError:
        return True
    try:
        if process_identity(pid) != expected_identity:
            return True
        pidfd_send_signal(pidfd, signal.SIGTERM)
    finally:
        os.close(pidfd)
    return True


def terminate_process_tree(
    pid: int,
    *,
    expected_identity: str,
    grace_seconds: float = 3.0,
) -> bool:
    """Terminate the registered launcher and every CLI process below it."""

    if pid <= 0:
        return True
    if os.name == "nt":
        if not _terminate_windows_verified(pid, expected_identity):
            return False
    elif sys.platform.startswith("linux"):
        if not _terminate_linux_verified(pid, expected_identity):
            return False
    else:
        raise RuntimeError(f"PID-safe termination is unsupported on {sys.platform}")
    deadline = time.monotonic() + max(0.1, grace_seconds)
    while time.monotonic() < deadline:
        if not process_matches(pid, expected_identity):
            return True
        time.sleep(0.05)
    return False


def _terminate_attached_process(process: subprocess.Popen[str]) -> bool:
    """Terminate a child tree and reap its registered launcher."""

    if process.poll() is not None:
        return True
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            return False
    return True


def sanitized_environment(
    isolation_dir: Path | None = None,
    *,
    isolate_antigravity: bool = False,
    antigravity_workspace: Path | None = None,
    antigravity_write_root: Path | None = None,
) -> dict[str, str]:
    """Allow only process basics and force non-production application endpoints."""

    if isolate_antigravity and isolation_dir is None:
        raise ValueError("isolated Antigravity runs require an isolation directory")
    if not isolate_antigravity and (
        antigravity_workspace is not None or antigravity_write_root is not None
    ):
        raise ValueError("Antigravity permission roots require profile isolation")
    clean = {
        name: value for name, value in os.environ.items() if name.upper() in SAFE_INHERITED_ENV
    }
    runtime_dir = str(Path(sys.executable).absolute().parent)
    inherited_path = clean.get("PATH")
    clean["PATH"] = (
        os.pathsep.join((runtime_dir, inherited_path)) if inherited_path else runtime_dir
    )
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
        temporary_dir = isolation_dir / "tmp"
        temporary_dir.mkdir(exist_ok=True)
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
                "TEMP": str(temporary_dir),
                "TMP": str(temporary_dir),
                "TMPDIR": str(temporary_dir),
            }
        )
        if isolate_antigravity:
            if antigravity_workspace is None or antigravity_write_root is None:
                raise ValueError(
                    "isolated Antigravity runs require an exact workspace and write root"
                )
            workspace = antigravity_workspace.resolve(strict=True)
            write_root = antigravity_write_root.resolve(strict=True)
            if not workspace.is_dir() or not write_root.is_dir():
                raise ValueError("Antigravity permission roots must be existing directories")
            try:
                relative_write_root = write_root.relative_to(workspace)
            except ValueError as error:
                raise ValueError(
                    "Antigravity write root must resolve inside its workspace"
                ) from error
            if not relative_write_root.parts:
                raise ValueError("Antigravity write root cannot be the whole workspace")
            permission_targets = (workspace.as_posix(), write_root.as_posix())
            if any(
                character in target
                for target in permission_targets
                for character in ("\n", "\r", "(", ")")
            ):
                raise ValueError("Antigravity permission paths contain unsupported syntax")
            clean.pop("CODEX_HOME", None)
            clean["NYAN_UI_ALLOWED_WRITE_ROOT"] = relative_write_root.as_posix()
            profile = isolation_dir / "antigravity-profile"
            settings_dir = profile / ".gemini" / "antigravity-cli"
            settings_dir.mkdir(parents=True, exist_ok=True)
            (settings_dir / "settings.json").write_text(
                json.dumps(
                    {
                        "allowNonWorkspaceAccess": False,
                        "artifactReviewPolicy": "asks-for-review",
                        "enableTelemetry": False,
                        "enableTerminalSandbox": True,
                        "permissions": {
                            "allow": [
                                f"read_file({permission_targets[0]})",
                                f"write_file({permission_targets[1]})",
                            ],
                            "deny": [
                                "command(*)",
                                "unsandboxed(*)",
                                "read_url(*)",
                                "execute_url(*)",
                                "mcp(*)",
                            ],
                        },
                        "toolPermission": "request-review",
                        "useG1Credits": False,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            roaming = profile / "AppData" / "Roaming"
            local = profile / "AppData" / "Local"
            roaming.mkdir(parents=True, exist_ok=True)
            local.mkdir(parents=True, exist_ok=True)
            clean.update(
                {
                    "APPDATA": str(roaming),
                    "HOME": str(profile),
                    "LOCALAPPDATA": str(local),
                    "USERPROFILE": str(profile),
                    "XDG_CACHE_HOME": str(profile / ".cache"),
                    "XDG_CONFIG_HOME": str(profile / ".config"),
                    "XDG_DATA_HOME": str(profile / ".local" / "share"),
                }
            )
            if os.name == "nt":
                clean["HOMEDRIVE"] = profile.drive
                clean["HOMEPATH"] = str(profile)[len(profile.drive) :]
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
    on_stream_line: StreamLine | None = None,
    isolate_antigravity: bool = False,
    antigravity_write_root: Path | None = None,
) -> ActivityDelivery:
    launch_stem = stdout_path.stem
    launch_spec = stdout_path.parent / f"{launch_stem}.launch.json"
    launch_stdin = stdout_path.parent / f"{launch_stem}.stdin.txt"
    launch_ready = stdout_path.parent / f"{launch_stem}.launcher-ready"
    launch_start = stdout_path.parent / f"{launch_stem}.launcher-start"
    launch_complete = stdout_path.parent / f"{launch_stem}.launcher-contained"
    containment_nonce = uuid.uuid4().hex
    launch_ready.unlink(missing_ok=True)
    launch_start.unlink(missing_ok=True)
    launch_complete.unlink(missing_ok=True)
    if stdin_text is None:
        launch_stdin.unlink(missing_ok=True)
        stdin_path: str | None = None
    else:
        launch_stdin.write_text(stdin_text, encoding="utf-8")
        stdin_path = str(launch_stdin)
    launch_spec.write_text(
        json.dumps(
            {
                "command": command,
                "stdin_path": stdin_path,
                "deadline_epoch": time.time() + timeout_seconds,
            }
        ),
        encoding="utf-8",
    )
    launcher = Path(__file__).with_name("agent_process.py")
    wrapped_command = [
        sys.executable,
        str(launcher),
        "--spec",
        str(launch_spec),
        "--ready",
        str(launch_ready),
        "--start",
        str(launch_start),
        "--complete",
        str(launch_complete),
        "--nonce",
        containment_nonce,
    ]
    started = time.monotonic()
    activity_queue: queue.Queue[tuple[str, str, int]] = queue.Queue(maxsize=ACTIVITY_QUEUE_CAPACITY)
    activity_stop = threading.Event()
    tail_stop = threading.Event()
    finish_called = threading.Event()
    activity_lock = threading.Lock()
    activity_counts = {"delivered": 0, "dropped": 0, "errors": 0}

    def count(name: str, amount: int = 1) -> None:
        with activity_lock:
            activity_counts[name] += amount

    def enqueue_activity(channel: str, line: str, sequence: int) -> None:
        try:
            activity_queue.put_nowait((channel, line, sequence))
        except queue.Full:
            count("dropped")

    def dispatch_activity() -> None:
        while not activity_stop.is_set():
            try:
                item = activity_queue.get(timeout=0.05)
            except queue.Empty:
                continue
            if activity_stop.is_set():
                count("dropped")
                return
            if on_stream_line is None:
                count("delivered")
                continue
            try:
                on_stream_line(*item)
                count("delivered")
            except BaseException:
                # Visibility is deliberately fail-open. The raw stream is still durable and
                # service-level catch-up can ingest it after the child exits or on resume.
                count("errors")

    def tail_output(path: Path, channel: str, process: subprocess.Popen[str]) -> None:
        buffer = ""
        sequence = 0
        try:
            with path.open("r", encoding="utf-8", errors="replace") as stream:
                while not tail_stop.is_set():
                    chunk = stream.read(65_536)
                    if chunk:
                        buffer += chunk
                        lines = buffer.splitlines(keepends=True)
                        buffer = ""
                        for line in lines:
                            if line.endswith(("\n", "\r")):
                                sequence += 1
                                enqueue_activity(channel, line, sequence)
                            else:
                                buffer = line
                    elif process.poll() is not None:
                        if buffer:
                            sequence += 1
                            enqueue_activity(channel, buffer, sequence)
                        return
                    else:
                        time.sleep(0.02)
        except BaseException:
            count("errors")

    with (
        stdout_path.open("w", encoding="utf-8") as stdout_file,
        stderr_path.open("w", encoding="utf-8") as stderr_file,
    ):
        process = subprocess.Popen(  # noqa: S603 - executable is resolved and arguments are fixed
            wrapped_command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
            encoding="utf-8",
            env=sanitized_environment(
                stdout_path.parent / "isolated-environment",
                isolate_antigravity=isolate_antigravity,
                antigravity_workspace=cwd if isolate_antigravity else None,
                antigravity_write_root=antigravity_write_root,
            ),
            creationflags=WINDOWS_CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
        dispatcher = threading.Thread(
            target=dispatch_activity,
            name=f"{launch_stem}-activity-dispatch",
            daemon=True,
        )
        stdout_tailer = threading.Thread(
            target=tail_output,
            args=(stdout_path, "stdout", process),
            name=f"{launch_stem}-stdout-tail",
            daemon=True,
        )
        stderr_tailer = threading.Thread(
            target=tail_output,
            args=(stderr_path, "stderr", process),
            name=f"{launch_stem}-stderr-tail",
            daemon=True,
        )
        dispatcher.start()
        stdout_tailer.start()
        stderr_tailer.start()

        def finish_activity() -> ActivityDelivery:
            if finish_called.is_set():
                with activity_lock:
                    return ActivityDelivery(
                        delivered=activity_counts["delivered"],
                        dropped=activity_counts["dropped"],
                        errors=activity_counts["errors"],
                        clean_shutdown=not any(
                            thread.is_alive()
                            for thread in (stdout_tailer, stderr_tailer, dispatcher)
                        ),
                    )
            finish_called.set()
            deadline = time.monotonic() + 0.75
            for tailer in (stdout_tailer, stderr_tailer):
                tailer.join(timeout=max(0.0, deadline - time.monotonic()))
            if stdout_tailer.is_alive() or stderr_tailer.is_alive():
                tail_stop.set()
                count("errors")
            while (
                not activity_queue.empty() and dispatcher.is_alive() and time.monotonic() < deadline
            ):
                dispatcher.join(timeout=min(0.05, max(0.0, deadline - time.monotonic())))
            if not activity_queue.empty():
                count("dropped", activity_queue.qsize())
            activity_stop.set()
            dispatcher.join(timeout=0.1)
            clean_shutdown = not any(
                thread.is_alive() for thread in (stdout_tailer, stderr_tailer, dispatcher)
            )
            if not clean_shutdown:
                count("errors")
            with activity_lock:
                report = ActivityDelivery(
                    delivered=activity_counts["delivered"],
                    dropped=activity_counts["dropped"],
                    errors=activity_counts["errors"],
                    clean_shutdown=clean_shutdown,
                )
            return report

        launcher_identity = process_identity(process.pid)
        if launcher_identity is None:
            process.kill()
            process.wait(timeout=5)
            finish_activity()
            raise RuntimeError("could not capture launcher creation identity")
        process_attached = False
        containment_confirmed = False
        try:
            ready_deadline = time.monotonic() + 10
            while not launch_ready.is_file():
                if process.poll() is not None:
                    raise RuntimeError(
                        f"agent launcher exited {process.returncode} before registration"
                    )
                if time.monotonic() >= ready_deadline:
                    raise TimeoutError("agent launcher did not reach its registration barrier")
                time.sleep(0.02)
            if launch_ready.read_text(encoding="utf-8") != containment_nonce:
                raise RuntimeError("launcher readiness nonce did not match")
            if on_process_start is not None:
                on_process_start(
                    process.pid,
                    launcher_identity,
                    str(launch_complete),
                    containment_nonce,
                )
                process_attached = True
            desired = control()
            if desired is DesiredState.PAUSED:
                if not _terminate_attached_process(process):
                    raise RuntimeError("could not pause the registered launcher at its barrier")
                raise AgentPaused("owner pause prevented the agent process from starting")
            if desired is DesiredState.STOPPED:
                if not _terminate_attached_process(process):
                    raise RuntimeError("could not stop the registered launcher at its barrier")
                raise AgentStopped("owner stop prevented the agent process from starting")
            if time.monotonic() - started > timeout_seconds:
                if not _terminate_attached_process(process):
                    raise RuntimeError("expired registered launcher is still alive at its barrier")
                raise TimeoutError(f"agent exceeded {timeout_seconds}s invocation limit")
            launch_start.write_text("start", encoding="utf-8")
            while process.poll() is None:
                desired = control()
                if desired is DesiredState.PAUSED:
                    if not _terminate_attached_process(process):
                        raise RuntimeError("could not pause the registered agent process tree")
                    raise AgentPaused("owner pause terminated the active agent process tree")
                if desired is DesiredState.STOPPED:
                    if not _terminate_attached_process(process):
                        raise RuntimeError("could not terminate the registered agent process tree")
                    raise AgentStopped("owner stop terminated the active agent process tree")
                if time.monotonic() - started > timeout_seconds:
                    if not _terminate_attached_process(process):
                        raise RuntimeError("timed-out agent process tree is still alive")
                    raise TimeoutError(f"agent exceeded {timeout_seconds}s invocation limit")
                time.sleep(1)
            containment_deadline = time.monotonic() + 5
            while (
                not launch_complete.is_file()
                or launch_complete.read_text(encoding="utf-8") != containment_nonce
            ):
                if time.monotonic() >= containment_deadline:
                    raise RuntimeError(
                        "launcher exited without watchdog containment acknowledgement"
                    )
                time.sleep(0.02)
            containment_confirmed = True
            if process.returncode != 0:
                tail = stderr_path.read_text(encoding="utf-8", errors="replace")[-4000:]
                raise RuntimeError(
                    f"agent exited {process.returncode}: {redact_text(tail, limit=4000)}"
                )
        finally:
            try:
                if process.poll() is None:
                    _terminate_attached_process(process)
                if process_attached and process.poll() is not None and not containment_confirmed:
                    containment_deadline = time.monotonic() + 5
                    while time.monotonic() < containment_deadline:
                        if (
                            launch_complete.is_file()
                            and launch_complete.read_text(encoding="utf-8") == containment_nonce
                        ):
                            containment_confirmed = True
                            break
                        time.sleep(0.02)
                if (
                    process_attached
                    and containment_confirmed
                    and process.poll() is not None
                    and on_process_end is not None
                ):
                    on_process_end(
                        process.pid,
                        launcher_identity,
                        str(launch_complete),
                        containment_nonce,
                    )
            finally:
                activity_report = finish_activity()
    return activity_report


def _load_final[ResultModel: BaseModel](path: Path, model: type[ResultModel]) -> ResultModel:
    if not path.is_file():
        raise RuntimeError(f"agent did not create final result: {path}")
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def _parse_codex_events(path: Path) -> tuple[str, Usage]:
    session_id: str | None = None
    terminal = False
    usage = Usage()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
            session_id = str(event["thread_id"])
        if event.get("type") == "turn.completed":
            terminal = True
            if isinstance(event.get("usage"), dict):
                raw = event["usage"]
                usage = Usage(
                    input_tokens=int(raw.get("input_tokens", 0)),
                    cached_input_tokens=int(raw.get("cached_input_tokens", 0)),
                    output_tokens=int(raw.get("output_tokens", 0)),
                    reasoning_output_tokens=int(raw.get("reasoning_output_tokens", 0)),
                )
    if session_id is None:
        raise RuntimeError("Codex JSONL did not expose thread.started.thread_id")
    if not terminal:
        raise RuntimeError("Codex JSONL did not expose a terminal turn.completed event")
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
        on_stream_line: StreamLine | None = None,
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
        if sandbox == "read-only":
            temporary_dir = run_dir / "isolated-environment" / "tmp"
            temporary_dir.mkdir(parents=True, exist_ok=True)
            command.extend(("--add-dir", str(temporary_dir)))
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

        activity = _run_monitored(
            command,
            cwd=worktree,
            stdin_text=prompt,
            stdout_path=events_path,
            stderr_path=stderr_path,
            control=control,
            timeout_seconds=timeout_seconds,
            on_process_start=on_process_start,
            on_process_end=on_process_end,
            on_stream_line=on_stream_line,
        )
        if activity is None:  # compatibility with narrow unit-test fakes
            activity = ActivityDelivery()
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
            activity_delivered=activity.delivered,
            activity_dropped=activity.dropped,
            activity_errors=activity.errors,
            activity_clean_shutdown=activity.clean_shutdown,
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
        on_stream_line: StreamLine | None = None,
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
            on_stream_line=on_stream_line,
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
        on_stream_line: StreamLine | None = None,
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
            on_stream_line=on_stream_line,
        )


def _parse_antigravity_events(path: Path) -> tuple[str, Usage, dict[str, Any]]:
    conversation_id: str | None = None
    usage = Usage()
    structured_output: dict[str, Any] | None = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise RuntimeError("Antigravity stdout contained malformed JSON") from error
        if not isinstance(event, dict):
            raise RuntimeError("Antigravity stdout contained a non-object JSON value")
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
                    reported_total_tokens=(
                        int(raw_usage["total_tokens"]) if "total_tokens" in raw_usage else None
                    ),
                )
            raw_output = result.get("structured_output")
            if isinstance(raw_output, dict):
                structured_output = raw_output
    if conversation_id is None:
        raise RuntimeError("Antigravity stream did not expose a conversation_id")
    if structured_output is None:
        raise RuntimeError("Antigravity stream did not expose structured_output")
    return conversation_id, usage, structured_output


def _validate_antigravity_context(
    path: Path,
    *,
    worktree: Path,
    expected_model: str | None,
    expected_schema: dict[str, Any],
    require_result: bool = True,
) -> None:
    """Reject a full or resumable write stream with broader/different context."""

    init_events: list[dict[str, Any]] = []
    result_events: list[dict[str, Any]] = []
    step_conversations: list[object] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise RuntimeError("Antigravity stdout contained malformed JSON") from error
        if not isinstance(event, dict):
            raise RuntimeError("Antigravity stdout contained a non-object JSON value")
        step_update = event.get("step_update")
        if isinstance(step_update, dict):
            step_conversations.append(step_update.get("conversation_id"))
            if step_update.get("subagent_info") is not None:
                raise RuntimeError("Antigravity UI writer attempted to delegate to a subagent")
        if event.get("event") == "init":
            init_events.append(event)
        elif event.get("event") == "result":
            result_events.append(event)
    if len(init_events) != 1:
        raise RuntimeError("Antigravity stream must contain exactly one init")
    if len(result_events) > 1 or (require_result and len(result_events) != 1):
        raise RuntimeError("Antigravity stream has an invalid terminal result count")
    init_event = init_events[0]
    conversation_id = init_event.get("conversation_id")
    if not isinstance(conversation_id, str) or not conversation_id:
        raise RuntimeError("Antigravity init omitted its conversation ID")
    try:
        uuid.UUID(conversation_id)
    except ValueError as error:
        raise RuntimeError("Antigravity conversation ID is not a UUID") from error
    if any(value != conversation_id for value in step_conversations):
        raise RuntimeError("Antigravity step conversation did not match init")
    init = init_event.get("init")
    if not isinstance(init, dict):
        raise RuntimeError("Antigravity init payload is missing")
    observed_cwd = init.get("cwd")
    if not isinstance(observed_cwd, str) or os.path.normcase(
        str(Path(observed_cwd).resolve(strict=False))
    ) != os.path.normcase(str(worktree.resolve())):
        raise RuntimeError("Antigravity observed a different workspace root")
    permission_mode = init.get("permission_mode")
    if permission_mode not in {"request-review", "strict"}:
        raise RuntimeError(
            f"Antigravity permission mode is not least-privilege: {permission_mode!r}"
        )
    if expected_model is not None and init.get("model") != expected_model:
        raise RuntimeError("Antigravity did not use the pinned task model")
    if init.get("json_schema") != expected_schema:
        raise RuntimeError("Antigravity did not bind the exact requested JSON schema")
    if not result_events:
        return
    result = result_events[0].get("result")
    if not isinstance(result, dict) or result.get("conversation_id") != conversation_id:
        raise RuntimeError("Antigravity result conversation did not match init")
    if result.get("json_schema") != expected_schema:
        raise RuntimeError("Antigravity did not bind the exact requested JSON schema")
    raw_usage = result.get("usage")
    if not isinstance(raw_usage, dict) or int(raw_usage.get("total_tokens", 0)) <= 0:
        raise RuntimeError("Antigravity generation did not report positive token usage")


def _build_antigravity_command(
    executable: str,
    *,
    prompt: str,
    schema_path: Path,
    timeout_minutes: int,
    resume_session_id: str | None,
    model: str | None,
) -> list[str]:
    """Build an exact headless command and create a project only for the first turn."""

    command = [executable, "-p", prompt]
    if resume_session_id is None:
        # agy 1.2.7 does not hydrate workspace rules/hooks in print mode until the
        # workspace is registered as a project. A resumed conversation already
        # carries that project and must not be replaced with a new one.
        command.append("--new-project")
    else:
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
    return command


class AntigravityAdapter:
    """Google agy 1.2.7 print-mode adapter; no GUI or internal endpoint automation."""

    def __init__(self) -> None:
        executable = shutil.which("agy")
        if executable is None:
            raise RuntimeError("Antigravity agy CLI is not installed")
        completed = subprocess.run(
            (executable, "--version"),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=sanitized_environment(),
            timeout=10,
        )
        observed_version = completed.stdout.strip()
        if completed.returncode or observed_version != SUPPORTED_ANTIGRAVITY_VERSION:
            raise RuntimeError(
                "Antigravity CLI version changed; revalidate its stream/permission contract "
                f"before use (expected {SUPPORTED_ANTIGRAVITY_VERSION}, observed "
                f"{observed_version or 'unavailable'})"
            )
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
        allowed_write_root: Path,
        resume_session_id: str | None = None,
        model: str | None = None,
        on_process_start: ProcessStarted | None = None,
        on_process_end: ProcessFinished | None = None,
        on_stream_line: StreamLine | None = None,
    ) -> tuple[WorkerResult, AgentInvocation]:
        run_dir.mkdir(parents=True, exist_ok=True)
        schema_path = run_dir / f"{name}.schema.json"
        events_path = run_dir / f"{name}.events.jsonl"
        stderr_path = run_dir / f"{name}.stderr.log"
        result_path = run_dir / f"{name}.result.json"
        write_schema(WorkerResult, schema_path)
        result_path.unlink(missing_ok=True)
        timeout_minutes = max(1, min(60, (timeout_seconds + 59) // 60))
        command = _build_antigravity_command(
            self.executable,
            prompt=prompt,
            schema_path=schema_path,
            timeout_minutes=timeout_minutes,
            resume_session_id=resume_session_id,
            model=model,
        )
        activity = _run_monitored(
            command,
            cwd=worktree,
            stdin_text=None,
            stdout_path=events_path,
            stderr_path=stderr_path,
            control=control,
            timeout_seconds=timeout_seconds,
            on_process_start=on_process_start,
            on_process_end=on_process_end,
            on_stream_line=on_stream_line,
            isolate_antigravity=True,
            antigravity_write_root=allowed_write_root,
        )
        if activity is None:  # compatibility with narrow unit-test fakes
            activity = ActivityDelivery()
        _validate_antigravity_context(
            events_path,
            worktree=worktree,
            expected_model=model,
            expected_schema=WorkerResult.model_json_schema(),
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
            activity_delivered=activity.delivered,
            activity_dropped=activity.dropped,
            activity_errors=activity.errors,
            activity_clean_shutdown=activity.clean_shutdown,
        )
        return result, invocation


def recover_completed_invocation(path: Path, worker: WorkerKind) -> tuple[str, Usage]:
    """Parse durable terminal events without launching another model process."""

    if worker is WorkerKind.CODEX:
        return _parse_codex_events(path)
    session_id, usage, _ = _parse_antigravity_events(path)
    return session_id, usage


def _codex_terminal_output(path: Path) -> str | None:
    terminal = False
    message: str | None = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "turn.completed":
            terminal = True
        item = event.get("item")
        if (
            event.get("type") == "item.completed"
            and isinstance(item, dict)
            and item.get("type") == "agent_message"
            and isinstance(item.get("text"), str)
        ):
            message = str(item["text"])
    if not terminal:
        return None
    if message is None:
        raise RuntimeError("completed Codex stream did not expose its final agent message")
    return message


def _codex_has_terminal_turn(path: Path) -> bool:
    if not path.is_file():
        return False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("type") == "turn.completed":
            return True
    return False


def _antigravity_has_terminal_result(path: Path) -> bool:
    if not path.is_file():
        return False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(event, dict)
            and event.get("event") == "result"
            and isinstance(event.get("result"), dict)
        ):
            return True
    return False


def recover_completed_result[ResultModel: BaseModel](
    *,
    events_path: Path,
    result_path: Path,
    worker: WorkerKind,
    result_model: type[ResultModel],
) -> tuple[ResultModel, str, Usage] | None:
    """Recover a terminal structured result without launching another agent."""

    if result_path.is_file():
        if worker is WorkerKind.CODEX and not _codex_has_terminal_turn(events_path):
            return None
        if worker is WorkerKind.ANTIGRAVITY and not _antigravity_has_terminal_result(events_path):
            return None
        result = result_model.model_validate_json(result_path.read_text(encoding="utf-8"))
        session_id, usage = recover_completed_invocation(events_path, worker)
        return result, session_id, usage
    if not events_path.is_file():
        return None
    if worker is WorkerKind.CODEX:
        final_text = _codex_terminal_output(events_path)
        if final_text is None:
            return None
        result = result_model.model_validate_json(final_text)
        session_id, usage = _parse_codex_events(events_path)
    else:
        if not _antigravity_has_terminal_result(events_path):
            return None
        session_id, usage, structured_output = _parse_antigravity_events(events_path)
        result = result_model.model_validate(structured_output)
    result_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return result, session_id, usage
