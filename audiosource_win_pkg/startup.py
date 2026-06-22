"""Current-user Windows Startup Folder integration."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ENTRY_NAME = "audiosource-win-startup.vbs"


class StartupError(RuntimeError):
    """Raised when startup integration cannot be configured clearly."""


def get_startup_folder() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise StartupError("APPDATA is not set; cannot locate the current user's Startup Folder.")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def get_startup_entry_path() -> Path:
    return get_startup_folder() / ENTRY_NAME


def find_pythonw(executable: str | None = None) -> Path:
    path = Path(executable or sys.executable)
    if path.name.lower() == "python.exe":
        candidate = path.with_name("pythonw.exe")
        if candidate.exists():
            return candidate
    return path


def _vbs_quote(value: str) -> str:
    return value.replace('"', '""')


def build_startup_command(mode: str = "background", start_bridge: bool = True, executable: str | None = None) -> str:
    pythonw = find_pythonw(executable)
    if mode == "background":
        args = ["-m", "audiosource_win_pkg", "run", "--background", "--quiet"]
    elif mode == "tray":
        args = ["-m", "audiosource_win_pkg", "tray"]
        args.append("--start-bridge" if start_bridge else "--no-start-bridge")
    else:
        raise StartupError(f"unsupported startup mode: {mode}")
    return " ".join([f'"{pythonw}"', *args])


def build_vbs_content(mode: str = "background", start_bridge: bool = True, executable: str | None = None) -> str:
    command = build_startup_command(mode, start_bridge, executable)
    return "\n".join(
        [
            'Set shell = CreateObject("WScript.Shell")',
            f'shell.CurrentDirectory = "{_vbs_quote(str(Path.cwd()))}"',
            f'shell.Run "{_vbs_quote(command)}", 0, False',
            "",
        ]
    )


def enable_startup(mode: str = "background", start_bridge: bool = True) -> Path:
    folder = get_startup_folder()
    folder.mkdir(parents=True, exist_ok=True)
    entry = get_startup_entry_path()
    entry.write_text(build_vbs_content(mode, start_bridge), encoding="utf-8")
    return entry


def disable_startup() -> bool:
    entry = get_startup_entry_path()
    if not entry.exists():
        return False
    entry.unlink()
    return True


def startup_status() -> bool:
    return get_startup_entry_path().exists()


def startup_mode() -> str | None:
    try:
        content = get_startup_entry_path().read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    return "background" if "run --background" in content else "tray" if " tray" in content else "unknown"
