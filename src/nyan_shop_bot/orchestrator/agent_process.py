"""Barrier launcher with an OS-backed descendant-containment boundary."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, TextIO, cast

WINDOWS_CREATE_NEW_PROCESS_GROUP = 0x00000200
WINDOWS_DETACHED_PROCESS = 0x00000008
WINDOWS_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
WINDOWS_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9

if sys.platform == "win32":

    def _kill_posix_group(process_group: int, signal_number: int) -> None:
        raise RuntimeError("POSIX process groups are unavailable on Windows")

    def _current_posix_group() -> int:
        raise RuntimeError("POSIX process groups are unavailable on Windows")

else:

    def _kill_posix_group(process_group: int, signal_number: int) -> None:
        os.killpg(process_group, signal_number)

    def _current_posix_group() -> int:
        return os.getpgrp()


def _posix_identity(pid: int) -> str | None:
    """Bind watchdog decisions to one Linux process incarnation."""

    if not sys.platform.startswith("linux"):
        raise RuntimeError("POSIX launcher containment currently requires Linux /proc")
    try:
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    except (FileNotFoundError, ProcessLookupError):
        return None
    closing = stat.rfind(")")
    if closing < 0:
        raise RuntimeError("could not parse Linux process identity")
    fields = stat[closing + 2 :].split()
    if len(fields) < 20:
        raise RuntimeError("Linux process identity omitted its start time")
    return f"linux:{boot_id}:{fields[19]}"


def _configure_windows_job(job_name: str) -> object:
    """Open/create one named kill-on-close Job and return its retained handle."""

    import ctypes  # noqa: PLC0415 - Windows-only import
    from ctypes import wintypes  # noqa: PLC0415 - Windows-only import

    class IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimitInformation),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    ctypes_api = cast(Any, ctypes)
    kernel32 = ctypes_api.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    job = kernel32.CreateJobObjectW(None, job_name)
    if not job:
        raise ctypes_api.WinError(ctypes_api.get_last_error())
    limits = ExtendedLimitInformation()
    limits.BasicLimitInformation.LimitFlags = WINDOWS_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(
        job,
        WINDOWS_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(limits),
        ctypes.sizeof(limits),
    ):
        raise ctypes_api.WinError(ctypes_api.get_last_error())
    return job


def _join_windows_job(job_name: str) -> object:
    import ctypes  # noqa: PLC0415 - Windows-only import
    from ctypes import wintypes  # noqa: PLC0415 - Windows-only import

    ctypes_api = cast(Any, ctypes)
    kernel32 = ctypes_api.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    job = kernel32.CreateJobObjectW(None, job_name)
    if not job:
        raise ctypes_api.WinError(ctypes_api.get_last_error())
    if not kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess()):
        raise ctypes_api.WinError(ctypes_api.get_last_error())
    return job


def _windows_watchdog_main(
    *,
    target_pid: int,
    job_name: str,
    ready: Path,
    complete: Path,
    nonce: str,
) -> int:
    """Own the Job outside it, terminate it, and acknowledge an empty process set."""

    import ctypes  # noqa: PLC0415 - Windows-only import
    from ctypes import wintypes  # noqa: PLC0415 - Windows-only import

    class BasicAccountingInformation(ctypes.Structure):
        _fields_ = [
            ("TotalUserTime", ctypes.c_longlong),
            ("TotalKernelTime", ctypes.c_longlong),
            ("ThisPeriodTotalUserTime", ctypes.c_longlong),
            ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
            ("TotalPageFaultCount", wintypes.DWORD),
            ("TotalProcesses", wintypes.DWORD),
            ("ActiveProcesses", wintypes.DWORD),
            ("TotalTerminatedProcesses", wintypes.DWORD),
        ]

    synchronize = 0x00100000
    infinite = 0xFFFFFFFF
    job = _configure_windows_job(job_name)
    ctypes_api = cast(Any, ctypes)
    kernel32 = ctypes_api.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel32.TerminateJobObject.restype = wintypes.BOOL
    kernel32.QueryInformationJobObject.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
    )
    kernel32.QueryInformationJobObject.restype = wintypes.BOOL
    target = kernel32.OpenProcess(synchronize, False, target_pid)
    if not target:
        raise ctypes_api.WinError(ctypes_api.get_last_error())
    ready.write_text(job_name, encoding="utf-8")
    kernel32.WaitForSingleObject(target, infinite)
    if not kernel32.TerminateJobObject(job, 125):
        raise ctypes_api.WinError(ctypes_api.get_last_error())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        accounting = BasicAccountingInformation()
        if not kernel32.QueryInformationJobObject(
            job,
            1,
            ctypes.byref(accounting),
            ctypes.sizeof(accounting),
            None,
        ):
            raise ctypes_api.WinError(ctypes_api.get_last_error())
        if accounting.ActiveProcesses == 0:
            complete.write_text(nonce, encoding="utf-8")
            return 0
        time.sleep(0.02)
    raise RuntimeError("Windows Job still contains active processes after termination")


def _posix_cleanup_main(*, target_group: int, complete: Path, nonce: str) -> int:
    """Kill the anchored group from a separate session, then prove it disappeared."""

    try:
        _kill_posix_group(target_group, int(getattr(signal, "SIGKILL", 9)))
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            _kill_posix_group(target_group, 0)
        except ProcessLookupError:
            complete.write_text(nonce, encoding="utf-8")
            return 0
        time.sleep(0.02)
    raise RuntimeError("POSIX process group still exists after containment kill")


def _spawn_posix_cleanup(target_group: int, complete: Path, nonce: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(  # noqa: S603 - invokes this fixed local launcher
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--posix-cleanup",
            "--target-group",
            str(target_group),
            "--complete",
            str(complete),
            "--nonce",
            nonce,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _posix_watchdog_main(
    *,
    target_pid: int,
    target_identity: str,
    target_group: int,
    ready: Path,
    complete: Path,
    nonce: str,
) -> int:
    """Anchor the target PGID until an out-of-group cleanup helper takes over."""

    ready.write_text(target_identity, encoding="utf-8")
    while _posix_identity(target_pid) == target_identity:
        time.sleep(0.05)
    _spawn_posix_cleanup(target_group, complete, nonce)
    # Remaining alive keeps the old PGID unavailable for reuse until the cleanup
    # helper signals the whole group, including this watchdog.
    while True:
        time.sleep(60)


def _start_windows_watchdog(
    ready: Path, complete: Path, nonce: str
) -> tuple[subprocess.Popen[bytes], object]:
    job_name = f"NyanShopBot-{os.getpid()}-{uuid.uuid4().hex}"
    watchdog_ready = ready.with_name(f"{ready.name}.watchdog")
    watchdog_ready.unlink(missing_ok=True)
    complete.unlink(missing_ok=True)
    process = subprocess.Popen(  # noqa: S603 - invokes this fixed local launcher
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--windows-watchdog",
            "--target-pid",
            str(os.getpid()),
            "--job-name",
            job_name,
            "--ready",
            str(watchdog_ready),
            "--complete",
            str(complete),
            "--nonce",
            nonce,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=WINDOWS_CREATE_NEW_PROCESS_GROUP | WINDOWS_DETACHED_PROCESS,
    )
    _wait_for_watchdog_ready(process, watchdog_ready, job_name)
    return process, _join_windows_job(job_name)


def _start_posix_watchdog(ready: Path, complete: Path, nonce: str) -> subprocess.Popen[bytes]:
    if os.getpid() != _current_posix_group():
        raise RuntimeError("POSIX launcher must be the leader of its isolated process group")
    identity = _posix_identity(os.getpid())
    if identity is None:
        raise RuntimeError("launcher disappeared before watchdog registration")
    watchdog_ready = ready.with_name(f"{ready.name}.watchdog")
    watchdog_ready.unlink(missing_ok=True)
    complete.unlink(missing_ok=True)
    process = subprocess.Popen(  # noqa: S603 - invokes this fixed local launcher
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--posix-watchdog",
            "--target-pid",
            str(os.getpid()),
            "--target-identity",
            identity,
            "--target-group",
            str(_current_posix_group()),
            "--ready",
            str(watchdog_ready),
            "--complete",
            str(complete),
            "--nonce",
            nonce,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _wait_for_watchdog_ready(process, watchdog_ready, identity)
    return process


def _wait_for_watchdog_ready(process: subprocess.Popen[bytes], ready: Path, expected: str) -> None:
    deadline = time.monotonic() + 5
    while not ready.is_file():
        if process.poll() is not None:
            raise RuntimeError("launcher watchdog exited before registration")
        if time.monotonic() >= deadline:
            process.kill()
            raise TimeoutError("launcher watchdog did not register")
        time.sleep(0.02)
    if ready.read_text(encoding="utf-8") != expected:
        raise RuntimeError("launcher watchdog acknowledgement did not match")


def _validated_spec(path: Path) -> tuple[list[str], str | None, float]:
    value: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("launcher spec must be a JSON object")
    command = value.get("command")
    if (
        not isinstance(command, list)
        or not command
        or any(not isinstance(item, str) or not item for item in command)
    ):
        raise RuntimeError("launcher command must be a non-empty string array")
    stdin_path = value.get("stdin_path")
    if stdin_path is not None and not isinstance(stdin_path, str):
        raise RuntimeError("launcher stdin_path must be a string or null")
    deadline_epoch = value.get("deadline_epoch")
    if not isinstance(deadline_epoch, int | float):
        raise RuntimeError("launcher deadline_epoch must be a number")
    return command, stdin_path, float(deadline_epoch)


def _terminate_child(process: subprocess.Popen[str]) -> bool:
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


def _launcher_main(args: argparse.Namespace) -> int:
    if (
        args.spec is None
        or args.start is None
        or args.ready is None
        or args.complete is None
        or args.nonce is None
    ):
        raise RuntimeError("launcher spec/start/ready/complete/nonce metadata is required")
    command, stdin_path, deadline_epoch = _validated_spec(args.spec)
    watchdog: subprocess.Popen[bytes]
    containment_handle: object | None = None
    if os.name == "nt":
        watchdog, containment_handle = _start_windows_watchdog(
            args.ready, args.complete, args.nonce
        )
    else:
        watchdog = _start_posix_watchdog(args.ready, args.complete, args.nonce)
    # Keep the Job handle alive for the full Windows launcher lifetime.
    _ = containment_handle
    args.ready.write_text(args.nonce, encoding="utf-8")
    barrier_deadline = time.monotonic() + max(1.0, args.barrier_timeout)
    while not args.start.is_file():
        if watchdog.poll() is not None:
            raise RuntimeError("launcher watchdog exited at the registration barrier")
        if time.monotonic() >= barrier_deadline:
            return 124
        time.sleep(0.02)

    input_handle: TextIO | None = None
    stdin_source: Any = subprocess.DEVNULL
    if stdin_path is not None:
        input_handle = Path(stdin_path).open("r", encoding="utf-8")
        stdin_source = input_handle
    try:
        process = subprocess.Popen(command, stdin=stdin_source, text=True)
        while process.poll() is None:
            if watchdog.poll() is not None:
                _terminate_child(process)
                if os.name != "nt":
                    _spawn_posix_cleanup(_current_posix_group(), args.complete, args.nonce)
                raise RuntimeError("launcher watchdog exited while the agent was running")
            if time.time() >= deadline_epoch:
                if not _terminate_child(process):
                    raise RuntimeError("expired agent child could not be terminated")
                return 124
            time.sleep(0.2)
        return int(process.returncode)
    finally:
        if input_handle is not None:
            input_handle.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--ready", type=Path)
    parser.add_argument("--start", type=Path)
    parser.add_argument("--complete", type=Path)
    parser.add_argument("--barrier-timeout", type=float, default=30.0)
    parser.add_argument("--posix-watchdog", action="store_true")
    parser.add_argument("--posix-cleanup", action="store_true")
    parser.add_argument("--windows-watchdog", action="store_true")
    parser.add_argument("--target-pid", type=int)
    parser.add_argument("--target-identity")
    parser.add_argument("--target-group", type=int)
    parser.add_argument("--job-name")
    parser.add_argument("--nonce")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.posix_cleanup:
        if args.target_group is None or args.complete is None or args.nonce is None:
            raise RuntimeError("POSIX cleanup metadata is incomplete")
        return _posix_cleanup_main(
            target_group=args.target_group,
            complete=args.complete,
            nonce=args.nonce,
        )
    if args.posix_watchdog:
        if (
            args.target_pid is None
            or args.target_identity is None
            or args.target_group is None
            or args.ready is None
            or args.complete is None
            or args.nonce is None
        ):
            raise RuntimeError("POSIX watchdog metadata is incomplete")
        return _posix_watchdog_main(
            target_pid=args.target_pid,
            target_identity=args.target_identity,
            target_group=args.target_group,
            ready=args.ready,
            complete=args.complete,
            nonce=args.nonce,
        )
    if args.windows_watchdog:
        if (
            args.target_pid is None
            or args.job_name is None
            or args.ready is None
            or args.complete is None
            or args.nonce is None
        ):
            raise RuntimeError("Windows watchdog metadata is incomplete")
        return _windows_watchdog_main(
            target_pid=args.target_pid,
            job_name=args.job_name,
            ready=args.ready,
            complete=args.complete,
            nonce=args.nonce,
        )
    return _launcher_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
