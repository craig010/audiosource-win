"""Current-user Windows Startup Folder integration."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ENTRY_NAME = "audiosource-win-startup.vbs"
LEGACY_ENTRY_NAMES = ("audiosource-win-tray.vbs",)


class StartupError(RuntimeError):
    """Raised when startup integration cannot be configured clearly."""


def get_startup_folder() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise StartupError("APPDATA is not set; cannot locate the current user's Startup Folder.")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def get_startup_entry_path() -> Path:
    return get_startup_folder() / ENTRY_NAME


def _is_managed_legacy_vbs(path: Path) -> bool:
    """Recognize only a VBS entry that unambiguously launches this project."""
    if path.suffix.lower() != ".vbs" or not path.name.lower().startswith("audiosource"):
        return False
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return "audiosource_win_pkg" in content or "audiosource_win.py" in content


def _managed_startup_entries(folder: Path) -> list[Path]:
    entries = [folder / ENTRY_NAME, *(folder / name for name in LEGACY_ENTRY_NAMES)]
    try:
        entries.extend(path for path in folder.glob("audiosource*.vbs") if _is_managed_legacy_vbs(path))
    except OSError:
        pass
    return list(dict.fromkeys(entries))


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
    # Replace only known/marked legacy entries; do not touch other programs.
    for candidate in _managed_startup_entries(folder):
        if candidate != entry:
            candidate.unlink(missing_ok=True)
    entry.write_text(build_vbs_content(mode, start_bridge), encoding="utf-8")
    return entry


def disable_startup() -> bool:
    removed = False
    for entry in _managed_startup_entries(get_startup_folder()):
        if entry.exists():
            entry.unlink()
            removed = True
    return removed


def startup_status() -> bool:
    return get_startup_entry_path().exists()


def startup_mode() -> str | None:
    try:
        content = get_startup_entry_path().read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    return "background" if "run --background" in content else "tray" if " tray" in content else "unknown"
