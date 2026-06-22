"""Local runtime files used to manage the background bridge process."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


def runtime_dir() -> Path:
    return Path.cwd() / ".audiosource-win" / "runtime"


def log_dir() -> Path:
    return Path.cwd() / ".audiosource-win" / "logs"


def pid_path() -> Path:
    return runtime_dir() / "audiosource-win.pid"


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


@dataclass(frozen=True)
class RuntimeInfo:
    pid: int
    mode: str
    log_file: str


def read_runtime() -> RuntimeInfo | None:
    try:
        data = json.loads(pid_path().read_text(encoding="utf-8"))
        return RuntimeInfo(pid=int(data["pid"]), mode=str(data["mode"]), log_file=str(data["log_file"]))
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def clear_runtime() -> None:
    for path in (pid_path(), stop_request_path()):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def claim_runtime(mode: str, log_file: Path) -> RuntimeInfo | None:
    """Claim the background slot, returning None while an owned process is alive."""
    runtime_dir().mkdir(parents=True, exist_ok=True)
    existing = read_runtime()
    if existing and process_is_alive(existing.pid):
        return None
    clear_runtime()
    info = RuntimeInfo(pid=os.getpid(), mode=mode, log_file=str(log_file))
    pid_path().write_text(json.dumps(info.__dict__), encoding="utf-8")
    return info


def request_stop() -> RuntimeInfo | None:
    info = read_runtime()
    if info is None or not process_is_alive(info.pid):
        clear_runtime()
        return None
    runtime_dir().mkdir(parents=True, exist_ok=True)
    stop_request_path().touch()
    return info
