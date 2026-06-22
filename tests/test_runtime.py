import json
import shutil
from pathlib import Path

from audiosource_win_pkg import runtime


def configure_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, "runtime_dir", lambda: tmp_path / "runtime")
    monkeypatch.setattr(runtime, "log_dir", lambda: tmp_path / "logs")


def make_temp_dir(name: str) -> Path:
    path = Path.cwd() / "test_tmp" / name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


def test_claim_runtime_creates_and_clears_pid_file(monkeypatch):
    tmp_path = make_temp_dir("runtime-claim")
    configure_runtime(monkeypatch, tmp_path)
    info = runtime.claim_runtime("background", runtime.log_path())
    assert info is not None
    assert runtime.read_runtime() == info
    assert runtime.pid_path().read_text(encoding="utf-8") == str(info.pid)
    state = json.loads(runtime.state_path().read_text(encoding="utf-8"))
    assert state["pid"] == info.pid
    assert state["mode"] == "background"
    assert state["log_path"] == str(runtime.log_path())
    assert runtime.lock_path().exists()
    runtime.clear_runtime()
    assert runtime.read_runtime() is None
    assert not runtime.lock_path().exists()


def test_stale_pid_is_replaced(monkeypatch):
    tmp_path = make_temp_dir("runtime-stale")
    configure_runtime(monkeypatch, tmp_path)
    runtime.runtime_dir().mkdir(parents=True)
    runtime.pid_path().write_text(json.dumps({"pid": 999999, "mode": "background", "log_file": "old.log"}), encoding="utf-8")
    monkeypatch.setattr(runtime, "process_is_alive", lambda pid: False)
    info = runtime.claim_runtime("background", runtime.log_path())
    assert info is not None
    assert runtime.read_runtime().pid == info.pid


def test_live_pid_refuses_second_instance(monkeypatch):
    tmp_path = make_temp_dir("runtime-live")
    configure_runtime(monkeypatch, tmp_path)
    runtime.runtime_dir().mkdir(parents=True)
    runtime.pid_path().write_text(json.dumps({"pid": 12, "mode": "background", "log_file": "active.log"}), encoding="utf-8")
    monkeypatch.setattr(runtime, "process_is_alive", lambda pid: True)
    assert runtime.claim_runtime("background", runtime.log_path()) is None


def test_stale_lock_without_state_is_recovered(monkeypatch):
    tmp_path = make_temp_dir("runtime-stale-lock")
    configure_runtime(monkeypatch, tmp_path)
    runtime.runtime_dir().mkdir(parents=True)
    runtime.lock_path().write_text("999999", encoding="utf-8")
    monkeypatch.setattr(runtime, "process_is_alive", lambda pid: False)
    assert runtime.claim_runtime("background", runtime.log_path()) is not None


def test_request_stop_creates_signal(monkeypatch):
    tmp_path = make_temp_dir("runtime-stop")
    configure_runtime(monkeypatch, tmp_path)
    runtime.runtime_dir().mkdir(parents=True)
    runtime.pid_path().write_text(json.dumps({"pid": 12, "mode": "background", "log_file": "active.log"}), encoding="utf-8")
    monkeypatch.setattr(runtime, "process_is_alive", lambda pid: True)
    assert runtime.request_stop() is not None
    assert runtime.stop_request_path().exists()


def test_pythonw_package_background_command_is_recognized():
    command = '"D:\\code\\Audio\\.venv\\Scripts\\pythonw.exe" -m audiosource_win_pkg run --background --quiet'
    assert runtime.is_audiosource_background_command(command)


def test_voicebridge_pythonw_command_is_not_recognized():
    command = '"D:\\code\\VoiceBridge\\voice-bridge\\.venv\\Scripts\\pythonw.exe" "D:\\code\\VoiceBridge\\voice-bridge\\run.py"'
    assert not runtime.is_audiosource_background_command(command)


def test_runtime_is_live_accepts_pythonw_process(monkeypatch):
    info = runtime.RuntimeInfo(12, "background", "", "pythonw.exe", "D:\\code\\Audio", "now", "log")
    monkeypatch.setattr(runtime, "process_is_alive", lambda pid: True)
    monkeypatch.setattr(runtime, "process_command_line", lambda pid: 'pythonw.exe -m audiosource_win_pkg run --background --quiet')
    assert runtime.runtime_is_live(info)


def test_runtime_is_live_rejects_voicebridge_pid_reuse(monkeypatch):
    info = runtime.RuntimeInfo(12, "background", "", "pythonw.exe", "D:\\code\\Audio", "now", "log")
    monkeypatch.setattr(runtime, "process_is_alive", lambda pid: True)
    monkeypatch.setattr(runtime, "process_command_line", lambda pid: 'pythonw.exe D:\\code\\VoiceBridge\\voice-bridge\\run.py')
    assert not runtime.runtime_is_live(info)
