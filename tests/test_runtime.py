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
    runtime.clear_runtime()
    assert runtime.read_runtime() is None


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


def test_request_stop_creates_signal(monkeypatch):
    tmp_path = make_temp_dir("runtime-stop")
    configure_runtime(monkeypatch, tmp_path)
    runtime.runtime_dir().mkdir(parents=True)
    runtime.pid_path().write_text(json.dumps({"pid": 12, "mode": "background", "log_file": "active.log"}), encoding="utf-8")
    monkeypatch.setattr(runtime, "process_is_alive", lambda pid: True)
    assert runtime.request_stop() is not None
    assert runtime.stop_request_path().exists()
