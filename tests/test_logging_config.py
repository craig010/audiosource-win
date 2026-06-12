from pathlib import Path

from audiosource_win_pkg.logging_config import default_log_path, parse_log_level


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
