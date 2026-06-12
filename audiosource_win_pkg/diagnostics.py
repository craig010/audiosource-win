"""Environment checks and bounded end-to-end diagnostics."""

from __future__ import annotations

import importlib.util
import socket
import sys
from dataclasses import dataclass
from typing import Callable

from . import __version__
from .adb import APP_PACKAGE, REMOTE_SOCKET, choose_adb_device, create_forward, ensure_app_installed, find_adb, grant_android_permissions, list_adb_devices, remove_forward, start_android_app
from .audio import find_vb_cable_device_from_devices, query_sound_devices
from .errors import AudioSourceWinError


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    message: str
    suggestion: str | None = None


def port_available(host: str, port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def import_available(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def summarize_status(results: list[CheckResult]) -> str:
    if any(result.status == "FAIL" for result in results):
        return "FAIL"
    if any(result.status == "WARN" for result in results):
        return "WARN"
    return "OK"


def format_results(title: str, results: list[CheckResult]) -> str:
    lines = [title, "-" * len(title)]
    for result in results:
        lines.append(f"[{result.status}] {result.name}: {result.message}")
        if result.suggestion:
            lines.append(f"  {result.suggestion}")
    lines.append("")
    lines.append(f"Version: {__version__}")
    lines.append(f"Result: {summarize_status(results)}")
    return "\n".join(lines)


def run_check(host: str = "127.0.0.1", port: int = 27183) -> list[CheckResult]:
    results: list[CheckResult] = [
        CheckResult("Python", "OK", sys.version.split()[0]),
        CheckResult("numpy import", "OK" if import_available("numpy") else "FAIL", "available" if import_available("numpy") else "missing"),
        CheckResult("sounddevice import", "OK" if import_available("sounddevice") else "FAIL", "available" if import_available("sounddevice") else "missing"),
    ]

    try:
        adb_path = find_adb()
        results.append(CheckResult("adb found", "OK", adb_path))
        devices = list_adb_devices()
        online = [device for device in devices if device.state == "online"]
        unauthorized = [device for device in devices if device.state == "unauthorized"]
        offline = [device for device in devices if device.state == "offline"]
        if online:
            results.append(CheckResult("adb devices", "OK", f"{len(online)} online, {len(unauthorized)} unauthorized, {len(offline)} offline"))
        elif unauthorized:
            results.append(CheckResult("adb devices", "FAIL", "device unauthorized", "Check the phone and tap Allow USB debugging."))
        elif offline:
            results.append(CheckResult("adb devices", "WARN", "device offline", "Reconnect USB or reconnect wireless debugging."))
        else:
            results.append(CheckResult("adb devices", "WARN", "no online Android device"))
    except AudioSourceWinError as exc:
        results.append(CheckResult("adb", "FAIL", str(exc), "Install Android Platform Tools or connect a device."))
    except Exception as exc:
        results.append(CheckResult("adb", "FAIL", str(exc)))

    try:
        devices = query_sound_devices()
        candidate = find_vb_cable_device_from_devices(devices)
        if candidate is None:
            results.append(CheckResult("VB-CABLE output", "WARN", "no recommended output device found", "Install VB-CABLE or pass --device."))
        else:
            results.append(CheckResult("VB-CABLE output", "OK", f"recommended device index {candidate}"))
    except Exception as exc:
        results.append(CheckResult("audio devices", "WARN", str(exc)))

    if port_available(host, port):
        results.append(CheckResult("local port", "OK", f"{host}:{port} available"))
    else:
        results.append(CheckResult("local port", "WARN", f"{host}:{port} is already in use"))

    return results


def run_doctor(
    host: str = "127.0.0.1",
    port: int = 27183,
    serial: str | None = None,
    device: int | None = None,
    socket_factory: Callable[..., socket.socket] = socket.create_connection,
) -> list[CheckResult]:
    results: list[CheckResult] = []
    selected_serial: str | None = None

    try:
        adb_path = find_adb()
        results.append(CheckResult("adb found", "OK", adb_path))
        selected = choose_adb_device(list_adb_devices(), serial)
        selected_serial = selected.serial
        results.append(CheckResult("device", "OK", f"{selected.serial} ({selected.transport})"))
    except Exception as exc:
        results.append(CheckResult("adb/device", "FAIL", str(exc)))
        return results

    try:
        ensure_app_installed(selected_serial)
        results.append(CheckResult("Android package", "OK", APP_PACKAGE))
    except Exception as exc:
        results.append(CheckResult("Android package", "FAIL", str(exc)))
        return results

    start = start_android_app(selected_serial)
    if start.returncode == 0:
        results.append(CheckResult("app start", "OK", "start command executed"))
    else:
        results.append(CheckResult("app start", "FAIL", (start.stderr or start.stdout).strip()))
        return results

    for perm, ok, message in grant_android_permissions(selected_serial):
        status = "OK" if ok else "WARN"
        results.append(CheckResult(f"permission {perm.rsplit('.', 1)[-1]}", status, "granted" if ok else (message or "grant skipped")))

    remove_forward(port, selected_serial)
    results.append(CheckResult("remove stale forward", "OK", f"tcp:{port}"))
    try:
        create_forward(port, selected_serial)
        results.append(CheckResult("create forward", "OK", f"tcp:{port} -> {REMOTE_SOCKET}"))
    except Exception as exc:
        results.append(CheckResult("create forward", "FAIL", str(exc)))
        return results

    try:
        sock = socket_factory((host, port), timeout=3.0)
        sock.settimeout(3.0)
        try:
            data = sock.recv(4096)
        finally:
            sock.close()
        if data:
            results.append(CheckResult("audio socket", "OK", f"received {len(data)} bytes"))
        else:
            results.append(CheckResult("audio socket", "WARN", "connected but received no bytes"))
    except Exception as exc:
        results.append(CheckResult("audio socket", "FAIL", str(exc)))

    try:
        import sounddevice as sd

        with sd.OutputStream(samplerate=44100, channels=2, dtype="int16", device=device, blocksize=1024):
            pass
        results.append(CheckResult("output stream", "OK", f"device {device if device is not None else 'default'}"))
    except Exception as exc:
        results.append(CheckResult("output stream", "WARN", str(exc)))

    return results
