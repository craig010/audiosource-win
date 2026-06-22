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
