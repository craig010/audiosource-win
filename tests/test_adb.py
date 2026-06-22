from types import SimpleNamespace

import pytest

from audiosource_win_pkg import adb
from audiosource_win_pkg import subprocess_utils
from audiosource_win_pkg.adb import AdbDevice, choose_adb_device, infer_transport, parse_adb_devices
from audiosource_win_pkg.errors import MultipleAdbDevices, NoAdbDevice


def test_parse_adb_devices_empty_output():
    assert parse_adb_devices("List of devices attached\n\n") == []


def test_parse_one_online_usb_device():
    devices = parse_adb_devices("List of devices attached\nR5CR123456 device\n")
    assert devices == [AdbDevice(serial="R5CR123456", state="online", transport="usb")]


def test_parse_one_online_wifi_device():
    devices = parse_adb_devices("List of devices attached\n192.168.1.10:5555 device\n")
    assert devices[0].state == "online"
    assert devices[0].transport == "wifi"


def test_parse_unauthorized_device():
    devices = parse_adb_devices("List of devices attached\nR5CR123456 unauthorized\n")
    assert devices[0].state == "unauthorized"


def test_parse_offline_device():
    devices = parse_adb_devices("List of devices attached\nR5CR123456 offline\n")
    assert devices[0].state == "offline"


def test_classify_wifi_transport_from_host_port():
    assert infer_transport("192.168.5.19:5555") == "wifi"


def test_choose_device_no_devices_errors():
    with pytest.raises(NoAdbDevice):
        choose_adb_device([])


def test_choose_device_multiple_online_without_serial_errors():
    devices = [
        AdbDevice("one", "online", "usb"),
        AdbDevice("two", "online", "usb"),
    ]
    with pytest.raises(MultipleAdbDevices):
        choose_adb_device(devices)


def test_choose_device_requested_serial_success_and_failure():
    devices = [AdbDevice("one", "online", "usb")]
    assert choose_adb_device(devices, "one").serial == "one"
    with pytest.raises(NoAdbDevice):
        choose_adb_device(devices, "missing")


def test_adb_commands_use_create_no_window_on_windows(monkeypatch):
    captured = {}
    monkeypatch.setattr(subprocess_utils.os, "name", "nt")
    monkeypatch.setattr(adb.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(
        adb.subprocess,
        "run",
        lambda *args, **kwargs: captured.update(kwargs) or SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    adb.run_cmd(["adb", "forward", "tcp:27183", "localabstract:audiosource"])
    assert captured["creationflags"] == 0x08000000
