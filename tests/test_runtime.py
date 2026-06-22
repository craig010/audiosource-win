import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

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
    with pytest.raises(runtime.RuntimeClaimBlocked) as exc:
        runtime.claim_runtime("background", runtime.log_path())
    assert exc.value.reason == "existing-managed-runtime"


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


def test_windows_process_exists_when_os_kill_would_reject_pid(monkeypatch):
    monkeypatch.setattr(runtime.os, "name", "nt")
    snapshot = runtime.ProcessSnapshot(27224, 1, "python.exe", "python.exe -m audiosource_win_pkg run --background --quiet")
    monkeypatch.setattr(runtime, "_windows_process_snapshot", lambda pid: snapshot)
    monkeypatch.setattr(runtime.os, "kill", lambda pid, sig: (_ for _ in ()).throw(OSError(22, "invalid parameter", None, 87)))
    assert runtime.process_exists(27224)


def test_windows_process_exists_returns_false_for_missing_pid(monkeypatch):
    monkeypatch.setattr(runtime.os, "name", "nt")
    monkeypatch.setattr(runtime, "_windows_process_snapshot", lambda pid: None)
    assert not runtime.process_exists(999999)


def test_windows_process_lookup_failure_keeps_runtime_conservatively(monkeypatch):
    monkeypatch.setattr(runtime.os, "name", "nt")
    monkeypatch.setattr(runtime, "_windows_process_snapshot", lambda pid: (_ for _ in ()).throw(RuntimeError("CIM denied")))
    assert runtime.process_exists(27224)


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


def test_runtime_is_live_accepts_unreadable_command_for_existing_pid(monkeypatch):
    info = runtime.RuntimeInfo(12, "background", "", "pythonw.exe", "D:\\code\\Audio", "now", "log")
    monkeypatch.setattr(runtime, "process_is_alive", lambda pid: True)
    monkeypatch.setattr(runtime, "process_command_line", lambda pid: None)
    assert runtime.runtime_is_live(info)


def test_find_unmanaged_process_ignores_current_and_launcher_parent(monkeypatch, caplog):
    monkeypatch.setattr(runtime.os, "name", "nt")
    caplog.set_level("DEBUG")
    project = str(Path.cwd())
    command = f'"{project}\\.venv\\Scripts\\pythonw.exe" -m audiosource_win_pkg run --background --quiet'
    output = f"100\t1\t{command}\n101\t100\t{command}\n"
    monkeypatch.setattr(runtime.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=output, stderr=""))
    assert runtime.find_unmanaged_background_process({100, 101}) is None
    assert "ignored-startup-chain" in caplog.text


def test_find_unmanaged_process_ignores_empty_voicebridge_and_other_projects(monkeypatch):
    monkeypatch.setattr(runtime.os, "name", "nt")
    project = str(Path.cwd())
    output = "\n".join(
        [
            "200\t1\t",
            '201\t1\t"D:\\code\\VoiceBridge\\voice-bridge\\.venv\\Scripts\\pythonw.exe" D:\\code\\VoiceBridge\\voice-bridge\\run.py',
            '202\t1\t"D:\\other\\.venv\\Scripts\\pythonw.exe" -m audiosource_win_pkg run --background --quiet',
            f'203\t1\t"{project}\\.venv\\Scripts\\python.exe" -m other_project run --background --quiet',
        ]
    )
    monkeypatch.setattr(runtime.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=output, stderr=""))
    assert runtime.find_unmanaged_background_process() is None


def test_find_unmanaged_process_blocks_only_current_project_background(monkeypatch):
    monkeypatch.setattr(runtime.os, "name", "nt")
    project = str(Path.cwd())
    command = f'"{project}\\.venv\\Scripts\\pythonw.exe" -m audiosource_win_pkg run --background --quiet'
    monkeypatch.setattr(runtime.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=f"456\t1\t{command}\n", stderr=""))
    assert runtime.find_unmanaged_background_process() == 456


def test_claim_runtime_ignores_matching_current_parent_launcher(monkeypatch):
    tmp_path = make_temp_dir("runtime-launcher-parent")
    configure_runtime(monkeypatch, tmp_path)
    monkeypatch.setattr(runtime, "current_parent_pid", lambda: 456)
    monkeypatch.setattr(runtime, "process_command_line", lambda pid: f'"{Path.cwd()}\\.venv\\Scripts\\pythonw.exe" -m audiosource_win_pkg run --background --quiet' if pid == 456 else None)
    captured = []
    monkeypatch.setattr(runtime, "find_unmanaged_background_process", lambda ignore_pids: captured.append(ignore_pids) or None)
    assert runtime.claim_runtime("background", runtime.log_path()) is not None
    assert os.getpid() in captured[0]
    assert 456 in captured[0]
