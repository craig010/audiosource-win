from pathlib import Path

import logging
import shutil
from pathlib import Path

from audiosource_win_pkg.logging_config import configure_logging, default_log_path, parse_log_level
from audiosource_win_pkg import runtime


def test_default_log_path_under_appdata(monkeypatch):
    monkeypatch.setenv("APPDATA", r"C:\Users\Craig\AppData\Roaming")
    path = default_log_path()
    assert str(path).endswith(r"audiosource-win\logs\audiosource-win.log")
    assert str(path).startswith(r"C:\Users\Craig\AppData\Roaming")


def test_home_fallback_log_path(monkeypatch):
    monkeypatch.delenv("APPDATA", raising=False)
    home = Path(r"C:\Users\Craig")
    monkeypatch.setattr(Path, "home", lambda: home)
    assert default_log_path() == home / ".audiosource-win" / "logs" / "audiosource-win.log"


def test_parse_log_level():
    assert parse_log_level("debug") == 10


def test_background_logging_uses_files_without_console(monkeypatch):
    tmp_path = Path.cwd() / "test_tmp" / "background-logging"
    if tmp_path.exists():
        shutil.rmtree(tmp_path)
    tmp_path.mkdir(parents=True)
    monkeypatch.setattr(runtime, "log_dir", lambda: tmp_path / "logs")
    path = runtime.log_path()
    configure_logging("INFO", str(path), console=False)
    logging.error("background failure")
    assert path.exists()
    assert runtime.error_log_path().exists()
    assert "background failure" in runtime.error_log_path().read_text(encoding="utf-8")
    assert not any(isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler) for handler in logging.getLogger().handlers)
