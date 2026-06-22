"""Local files and process checks for the managed background bridge."""

from __future__ import annotations

import json
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


def process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


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
    command = (
        "$p=Get-CimInstance Win32_Process -Filter \"ProcessId="
        f"{pid}\" -ErrorAction SilentlyContinue; "
        "if ($p) { [Console]::Write($p.CommandLine) }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def find_unmanaged_background_process() -> int | None:
    """Best-effort guard for pre-fix instances that have no state files."""
    if os.name != "nt":
        return None
    script = (
        "Get-CimInstance Win32_Process -Filter \"name='pythonw.exe'\" | "
        "ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in result.stdout.splitlines():
        pid, separator, command = line.partition("\t")
        if separator and pid.isdigit() and is_audiosource_background_command(command):
            return int(pid)
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


def claim_runtime(mode: str, log_file: Path, command: str | None = None) -> RuntimeInfo | None:
    """Atomically claim the managed slot before the bridge controller starts."""
    runtime_dir().mkdir(parents=True, exist_ok=True)
    existing = read_runtime()
    if existing and runtime_is_live(existing):
        return None
    if existing:
        clear_runtime()

    if not _claim_lock():
        # The other process may be between lock creation and state publication.
        for _ in range(10):
            time.sleep(0.05)
            existing = read_runtime()
            if existing and runtime_is_live(existing):
                return None
        if _clear_stale_lock_without_state() and _claim_lock():
            pass
        else:
            return None

    # State-less processes are a v0.4 regression. Do not create a second one.
    unmanaged_pid = find_unmanaged_background_process()
    if unmanaged_pid is not None and unmanaged_pid != os.getpid():
        lock_path().unlink(missing_ok=True)
        return None

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
