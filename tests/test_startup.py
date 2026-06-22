import shutil
from pathlib import Path

import pytest

from audiosource_win_pkg import startup


def make_temp_dir(name: str) -> Path:
    root = Path.cwd() / "test_tmp"
    root.mkdir(exist_ok=True)
    path = root / name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir()
    return path


def test_get_startup_folder_uses_appdata(monkeypatch):
    tmp_path = make_temp_dir("startup-folder")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    expected = tmp_path / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    assert startup.get_startup_folder() == expected


def test_appdata_missing_raises_clear_error(monkeypatch):
    monkeypatch.delenv("APPDATA", raising=False)
    with pytest.raises(startup.StartupError, match="APPDATA"):
        startup.get_startup_folder()


def test_enable_background_startup_creates_idempotent_entry(monkeypatch):
    tmp_path = make_temp_dir("enable")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(startup.sys, "executable", str(tmp_path / "python.exe"))
    (tmp_path / "pythonw.exe").write_text("", encoding="utf-8")
    first = startup.enable_startup(mode="background")
    second = startup.enable_startup(mode="background")
    assert first == second
    assert first.exists()
    content = first.read_text(encoding="utf-8")
    assert "audiosource_win_pkg run --background --quiet" in content
    assert "pythonw.exe" in content
    assert "CurrentDirectory" in content
    assert ", 0, False" in content
    assert "powershell.exe" not in content.lower()
    assert "cmd.exe" not in content.lower()
    assert startup.startup_mode() == "background"


def test_enable_tray_startup_preserves_tray_mode(monkeypatch):
    tmp_path = make_temp_dir("enable-tray")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(startup.sys, "executable", str(tmp_path / "python.exe"))
    entry = startup.enable_startup(mode="tray", start_bridge=False)
    assert "audiosource_win_pkg tray --no-start-bridge" in entry.read_text(encoding="utf-8")
    assert startup.startup_mode() == "tray"


def test_disable_startup_deletes_entry(monkeypatch):
    tmp_path = make_temp_dir("disable")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    startup.enable_startup(mode="background")
    assert startup.startup_status() is True
    assert startup.disable_startup() is True
    assert startup.startup_status() is False
    assert startup.disable_startup() is False


def test_enable_replaces_only_marked_legacy_entries_and_disable_cleans_them(monkeypatch):
    tmp_path = make_temp_dir("legacy-startup")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    folder = startup.get_startup_folder()
    folder.mkdir(parents=True)
    legacy = folder / "audiosource-win-tray.vbs"
    legacy.write_text('shell.Run "python -m audiosource_win_pkg tray"', encoding="utf-8")
    unrelated = folder / "audiosource-helper.vbs"
    unrelated.write_text('shell.Run "python -m unrelated"', encoding="utf-8")
    startup.enable_startup(mode="background")
    assert not legacy.exists()
    assert unrelated.exists()
    assert [path.name for path in folder.glob("audiosource*.vbs") if _is_ours(path)] == [startup.ENTRY_NAME]
    assert startup.disable_startup() is True
    assert not startup.get_startup_entry_path().exists()
    assert unrelated.exists()


def _is_ours(path: Path) -> bool:
    return "audiosource_win_pkg" in path.read_text(encoding="utf-8")


def test_pythonw_is_preferred_for_python_exe():
    tmp_path = make_temp_dir("pythonw")
    python = tmp_path / "python.exe"
    pythonw = tmp_path / "pythonw.exe"
    python.write_text("", encoding="utf-8")
    pythonw.write_text("", encoding="utf-8")
    assert startup.find_pythonw(str(python)) == pythonw


def test_python_exe_fallback_when_pythonw_missing():
    tmp_path = make_temp_dir("python-fallback")
    python = tmp_path / "python.exe"
    python.write_text("", encoding="utf-8")
    assert startup.find_pythonw(str(python)) == python
