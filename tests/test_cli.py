import pytest
from pathlib import Path
import shutil

from audiosource_win_pkg import cli
from audiosource_win_pkg.errors import AdbNotFound


def test_cli_help_exits_successfully():
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0


def test_run_help_exits_successfully():
    with pytest.raises(SystemExit) as exc:
        cli.main(["run", "--help"])
    assert exc.value.code == 0


def test_background_run_options_parse():
    args = cli.build_parser().parse_args(["run", "--background", "--quiet"])
    assert args.background is True
    assert args.quiet is True


def test_tray_help_exits_successfully():
    with pytest.raises(SystemExit) as exc:
        cli.main(["tray", "--help"])
    assert exc.value.code == 0


def test_startup_help_exits_successfully():
    with pytest.raises(SystemExit) as exc:
        cli.main(["startup", "--help"])
    assert exc.value.code == 0


def test_startup_status_runs_in_mock_environment(monkeypatch, capsys):
    tmp_path = Path.cwd() / "test_tmp" / "cli-startup"
    if tmp_path.exists():
        shutil.rmtree(tmp_path)
    tmp_path.mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    exit_code = cli.main(["startup", "status"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Startup is disabled." in captured.out
    assert "Mode: n/a" in captured.out


def test_startup_enable_modes(monkeypatch, capsys):
    tmp_path = Path.cwd() / "test_tmp" / "cli-startup-modes"
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert cli.main(["startup", "enable", "--mode", "background"]) == 0
    assert "background" in capsys.readouterr().out
    assert cli.main(["startup", "enable", "--mode", "tray"]) == 0
    assert "tray" in capsys.readouterr().out


def test_status_and_stop_without_runtime(monkeypatch, capsys):
    monkeypatch.setattr("audiosource_win_pkg.cli.read_runtime", lambda: None)
    assert cli.main(["status"]) == 0
    assert "Running: no" in capsys.readouterr().out
    assert cli.main(["stop"]) == 0
    assert "No managed" in capsys.readouterr().out


def test_check_handles_adb_missing_without_traceback(monkeypatch, capsys):
    def fake_find_adb():
        raise AdbNotFound("adb not found")

    monkeypatch.setattr("audiosource_win_pkg.diagnostics.find_adb", fake_find_adb)
    monkeypatch.setattr("audiosource_win_pkg.diagnostics.query_sound_devices", lambda: [])
    exit_code = cli.main(["check"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "[FAIL] adb" in captured.out
    assert "Traceback" not in captured.out


def test_devices_command_handles_mocked_adb(monkeypatch, capsys):
    monkeypatch.setattr("audiosource_win_pkg.cli.list_adb_devices", lambda: [])
    exit_code = cli.main(["devices"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "ADB devices:" in captured.out
