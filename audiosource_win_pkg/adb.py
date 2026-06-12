"""ADB helpers for Android AudioSource integration."""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

from .errors import AdbNotFound, AdbOffline, AdbUnauthorized, AndroidAppNotFound, ForwardFailed, MultipleAdbDevices, NoAdbDevice

APP_PACKAGE = "fr.dzx.audiosource"
APP_ACTIVITY = "fr.dzx.audiosource/.MainActivity"
REMOTE_SOCKET = "localabstract:audiosource"


@dataclass(frozen=True)
class AdbDevice:
    serial: str
    state: str
    transport: str
    detail: str | None = None


def infer_transport(serial: str) -> str:
    return "wifi" if ":" in serial else "usb"


def run_cmd(cmd: list[str], check: bool = False, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=check, capture_output=True, text=True, shell=False, timeout=timeout)


def find_adb() -> str:
    adb = shutil.which("adb")
    if not adb:
        raise AdbNotFound("adb not found. Install Android Platform Tools and make sure adb.exe is in PATH.")
    return adb


def adb_cmd(args: list[str], serial: Optional[str] = None, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    cmd = ["adb"]
    if serial:
        cmd.extend(["-s", serial])
    cmd.extend(args)
    return run_cmd(cmd, timeout=timeout)


def parse_adb_devices(output: str) -> list[AdbDevice]:
    devices: list[AdbDevice] = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("list of devices"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        if state == "device":
            state = "online"
        elif state not in {"offline", "unauthorized"}:
            state = "unknown"
        detail = " ".join(parts[2:]) or None
        devices.append(AdbDevice(serial=serial, state=state, transport=infer_transport(serial), detail=detail))
    return devices


def list_adb_devices(timeout: float | None = 5.0) -> list[AdbDevice]:
    find_adb()
    result = adb_cmd(["devices"], timeout=timeout)
    if result.returncode != 0:
        raise NoAdbDevice(f"adb devices failed: {(result.stderr or result.stdout).strip()}")
    return parse_adb_devices(result.stdout)


def choose_adb_device(devices: list[AdbDevice], requested_serial: str | None = None) -> AdbDevice:
    if requested_serial:
        matches = [device for device in devices if device.serial == requested_serial]
        if not matches:
            raise NoAdbDevice(f"Device {requested_serial} was not found in adb devices.")
        device = matches[0]
        if device.state == "unauthorized":
            raise AdbUnauthorized(f"Device {device.serial} is unauthorized. Allow USB debugging on the phone.")
        if device.state == "offline":
            raise AdbOffline(f"Device {device.serial} is offline.")
        if device.state != "online":
            raise NoAdbDevice(f"Device {device.serial} is not online: {device.state}.")
        return device

    online = [device for device in devices if device.state == "online"]
    if len(online) == 1:
        return online[0]
    if len(online) > 1:
        serials = ", ".join(device.serial for device in online)
        raise MultipleAdbDevices(f"Multiple Android devices are online. Select one with --serial: {serials}")
    if any(device.state == "unauthorized" for device in devices):
        raise AdbUnauthorized("Android device is unauthorized. Allow USB debugging on the phone.")
    if any(device.state == "offline" for device in devices):
        raise AdbOffline("Android device is offline.")
    raise NoAdbDevice("No Android device is online.")


def ensure_app_installed(serial: str) -> None:
    result = adb_cmd(["shell", "pm", "path", APP_PACKAGE], serial=serial, timeout=8.0)
    if result.returncode != 0 or not result.stdout.strip():
        raise AndroidAppNotFound(f"Android package {APP_PACKAGE} was not found. Install the AudioSource Android app first.")


def start_android_app(serial: str) -> subprocess.CompletedProcess[str]:
    return adb_cmd(["shell", "am", "start", "-n", APP_ACTIVITY], serial=serial, timeout=8.0)


def grant_android_permissions(serial: str) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []
    for perm in ("android.permission.RECORD_AUDIO", "android.permission.POST_NOTIFICATIONS"):
        result = adb_cmd(["shell", "pm", "grant", APP_PACKAGE, perm], serial=serial, timeout=8.0)
        message = (result.stderr or result.stdout).strip()
        ok = result.returncode == 0
        results.append((perm, ok, message))
        if ok:
            logging.info("Granted permission: %s", perm)
        elif message:
            logging.debug("Permission grant skipped: %s: %s", perm, message)
    return results


def remove_forward(port: int, serial: str) -> subprocess.CompletedProcess[str]:
    return adb_cmd(["forward", "--remove", f"tcp:{port}"], serial=serial, timeout=5.0)


def create_forward(port: int, serial: str) -> None:
    result = adb_cmd(["forward", f"tcp:{port}", REMOTE_SOCKET], serial=serial, timeout=8.0)
    if result.returncode != 0:
        raise ForwardFailed(f"adb forward failed: {(result.stderr or result.stdout).strip()}")


def prepare_android_side(port: int, serial: str | None, app_start_wait: float) -> AdbDevice:
    find_adb()
    device = choose_adb_device(list_adb_devices(), serial)
    logging.info("Selected Android device: %s (%s)", device.serial, device.transport)
    ensure_app_installed(device.serial)
    start_result = start_android_app(device.serial)
    if start_result.returncode != 0:
        raise AndroidAppNotFound(f"Failed to start Android app: {(start_result.stderr or start_result.stdout).strip()}")
    time.sleep(app_start_wait)
    grant_android_permissions(device.serial)
    remove_forward(port, device.serial)
    create_forward(port, device.serial)
    logging.info("ADB forward ready: tcp:%s -> %s", port, REMOTE_SOCKET)
    return device
