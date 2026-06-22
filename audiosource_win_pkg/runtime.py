"""Local files and process checks for the managed background bridge."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


def runtime_dir() -> Path:
    return Path.cwd() / ".audiosource-win" / "runtime"


def log_dir() -> Path:
    return Path.cwd() / ".audiosource-win" / "logs"


def pid_path() -> Path:
    return runtime_dir() / "audiosource-win.pid"


def state_path() -> Path:
    return runtime_dir() / "audiosource-win.state.json"


def lock_path() -> Path:
    return runtime_dir() / "audiosource-win.lock"


def stop_request_path() -> Path:
    return runtime_dir() / "stop.request"


def log_path() -> Path:
    return log_dir() / "audiosource-win.log"


def error_log_path() -> Path:
    return log_dir() / "audiosource-win.error.log"


@dataclass(frozen=True)
class ProcessSnapshot:
    """The process details needed for runtime ownership decisions."""

    pid: int
    parent_pid: int | None
    name: str | None
    command_line: str | None


class RuntimeClaimBlocked(RuntimeError):
    """The managed background slot belongs to another process or lock."""

    def __init__(self, reason: str, *, pid: int | None = None, command: str | None = None) -> None:
        self.reason = reason
        self.pid = pid
        self.command = command
        super().__init__(reason)


def _windows_process_snapshot(pid: int) -> ProcessSnapshot | None:
    """Return one process snapshot, or ``None`` only when the PID is absent.

    An inaccessible or failed CIM query is deliberately represented by an
    exception so callers can conservatively retain runtime state instead of
    treating a real process as stale.
    """
    command = (
        "$p=Get-CimInstance Win32_Process -Filter \"ProcessId="
        f"{pid}\" -ErrorAction Stop; "
        "if ($p) { $p | Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"Windows process lookup failed for pid={pid}: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or "PowerShell returned a non-zero exit code"
        raise RuntimeError(f"Windows process lookup failed for pid={pid}: {detail}")
    if not result.stdout.strip():
        return None
    try:
        data = json.loads(result.stdout)
        return ProcessSnapshot(
            pid=int(data["ProcessId"]),
            parent_pid=int(data["ParentProcessId"]) if data.get("ParentProcessId") is not None else None,
            name=str(data["Name"]) if data.get("Name") else None,
            command_line=str(data["CommandLine"]) if data.get("CommandLine") else None,
        )
    except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Windows process lookup returned invalid data for pid={pid}") from exc


def process_exists(pid: int) -> bool:
    """Return whether a PID exists without using ``os.kill(pid, 0)`` on Windows."""
    if pid <= 0:
        return False

    if os.name == "nt":
        try:
            return _windows_process_snapshot(pid) is not None
        except RuntimeError:
            # A failed CIM query cannot prove that a process has exited. Keeping
            # the runtime is safer than allowing a duplicate audio bridge.
            return True

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def process_is_alive(pid: int) -> bool:
    """Compatibility wrapper for callers that need process existence."""
    return process_exists(pid)


def is_audiosource_background_command(command: str | None) -> bool:
    """Recognise only our background command, never arbitrary pythonw processes."""
    if not command:
        return False
    value = command.lower()
    return (
        "--background" in value
        and "run" in value
        and ("audiosource_win_pkg" in value or "audiosource_win.py" in value)
    )


def process_command_line(pid: int) -> str | None:
    """Return a Windows process command line when it is available.

    Failure is deliberately non-fatal: a state file is still usable on systems
    where CIM is restricted, while successful lookup protects against PID reuse.
    """
    if os.name != "nt":
        return None
    try:
        snapshot = _windows_process_snapshot(pid)
    except RuntimeError:
        return None
    return snapshot.command_line if snapshot else None


def current_parent_pid() -> int | None:
    """Return the immediate parent PID when the platform exposes it."""
    parent = os.getppid()
    return parent if parent > 0 else None


def _is_current_project_background_command(command: str | None) -> bool:
    if not is_audiosource_background_command(command):
        return False
    return str(Path.cwd()).replace("/", "\\").lower() in (command or "").replace("/", "\\").lower()


def find_unmanaged_background_process(ignore_pids: set[int] | None = None) -> int | None:
    """Best-effort guard for pre-fix instances that have no state files."""
    if os.name != "nt":
        return None
    script = (
        "Get-CimInstance Win32_Process | Where-Object { $_.Name -in 'python.exe','pythonw.exe' } | "
        "ForEach-Object { \"$($_.ProcessId)`t$($_.ParentProcessId)`t$($_.CommandLine)\" }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logging.debug("unmanaged background scan unavailable: %s", exc)
        return None
    if result.returncode != 0:
        logging.debug("unmanaged background scan failed: %s", result.stderr.strip())
        return None
    ignored = set(ignore_pids or ())
    for line in result.stdout.splitlines():
        pid, parent_pid, command = line.split("\t", 2) if line.count("\t") >= 2 else ("", "", "")
        if not pid.isdigit():
            logging.debug("ignored unmanaged scan candidate: malformed row=%r", line)
            continue
        candidate_pid = int(pid)
        if candidate_pid in ignored:
            logging.debug("ignored candidate pid=%s reason=ignored-startup-chain command=%r", candidate_pid, command)
            continue
        if not command:
            logging.debug("ignored candidate pid=%s reason=empty-command-line", candidate_pid)
            continue
        if not is_audiosource_background_command(command):
            logging.debug("ignored candidate pid=%s reason=not-audiosource-background command=%r", candidate_pid, command)
            continue
        if not _is_current_project_background_command(command):
            logging.debug("ignored candidate pid=%s reason=outside-current-project command=%r", candidate_pid, command)
            continue
        logging.debug("blocked by unmanaged background process pid=%s command=%r", candidate_pid, command)
        return candidate_pid
    return None


@dataclass(frozen=True)
class RuntimeInfo:
    pid: int
    mode: str
    command: str
    python_executable: str
    cwd: str
    started_at: str
    log_path: str

    @property
    def log_file(self) -> str:  # Compatibility with v0.4 callers/tests.
        return self.log_path


def _read_json(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def read_runtime() -> RuntimeInfo | None:
    data = _read_json(state_path()) or _read_json(pid_path())
    if data is None:
        return None
    try:
        return RuntimeInfo(
            pid=int(data["pid"]),
            mode=str(data.get("mode", "background")),
            command=str(data.get("command", "")),
            python_executable=str(data.get("python_executable", "")),
            cwd=str(data.get("cwd", "")),
            started_at=str(data.get("started_at", "")),
            log_path=str(data.get("log_path", data.get("log_file", ""))),
        )
    except (KeyError, TypeError, ValueError):
        return None


def runtime_is_live(info: RuntimeInfo) -> bool:
    if not process_is_alive(info.pid):
        return False
    command = process_command_line(info.pid)
    # A live PID with an unreadable command line is retained. The state file
    # itself was atomically written by this process, while clearing it could
    # start a duplicate bridge when CIM is denied by policy.
    return command is None or is_audiosource_background_command(command)


def clear_runtime() -> None:
    for path in (pid_path(), state_path(), stop_request_path(), lock_path()):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _claim_lock() -> bool:
    try:
        with lock_path().open("x", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        return True
    except FileExistsError:
        return False


def _clear_stale_lock_without_state() -> bool:
    """Clear only a lock whose recorded owner is definitely no longer alive."""
    if state_path().exists():
        return False
    try:
        owner = int(lock_path().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    if process_is_alive(owner):
        return False
    lock_path().unlink(missing_ok=True)
    return True


def claim_runtime(mode: str, log_file: Path, command: str | None = None) -> RuntimeInfo:
    """Atomically claim the managed slot before the bridge controller starts."""
    runtime_dir().mkdir(parents=True, exist_ok=True)
    existing = read_runtime()
    if existing and runtime_is_live(existing):
        raise RuntimeClaimBlocked("existing-managed-runtime", pid=existing.pid, command=existing.command)
    if existing:
        clear_runtime()

    if not _claim_lock():
        # The other process may be between lock creation and state publication.
        for _ in range(10):
            time.sleep(0.05)
            existing = read_runtime()
            if existing and runtime_is_live(existing):
                raise RuntimeClaimBlocked("existing-managed-runtime", pid=existing.pid, command=existing.command)
        if _clear_stale_lock_without_state() and _claim_lock():
            pass
        else:
            try:
                owner = int(lock_path().read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                owner = None
            raise RuntimeClaimBlocked("runtime-lock", pid=owner)

    # State-less processes are a v0.4 regression. Do not create a second one.
    ignore_pids = {os.getpid()}
    parent = current_parent_pid()
    if parent is not None:
        parent_command = process_command_line(parent)
        if _is_current_project_background_command(parent_command):
            ignore_pids.add(parent)
            logging.debug("ignoring current launcher parent pid=%s command=%r", parent, parent_command)
    unmanaged_pid = find_unmanaged_background_process(ignore_pids=ignore_pids)
    if unmanaged_pid is not None:
        unmanaged_command = process_command_line(unmanaged_pid)
        lock_path().unlink(missing_ok=True)
        raise RuntimeClaimBlocked("unmanaged-background-process", pid=unmanaged_pid, command=unmanaged_command)

    info = RuntimeInfo(
        pid=os.getpid(),
        mode=mode,
        command=command or " ".join(sys.argv),
        python_executable=sys.executable,
        cwd=os.getcwd(),
        started_at=datetime.now(UTC).isoformat(),
        log_path=str(log_file),
    )
    payload = json.dumps(asdict(info), indent=2)
    try:
        pid_path().write_text(str(info.pid), encoding="utf-8")
        state_path().write_text(payload, encoding="utf-8")
    except OSError:
        clear_runtime()
        raise
    return info


def request_stop() -> RuntimeInfo | None:
    info = read_runtime()
    if info is None or not runtime_is_live(info):
        clear_runtime()
        return None
    runtime_dir().mkdir(parents=True, exist_ok=True)
    stop_request_path().touch()
    return info
