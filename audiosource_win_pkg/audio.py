"""Audio device and PCM helpers."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

VB_CABLE_KEYWORDS = ("cable input", "vb-audio", "vb-cable", "virtual cable")
DBFS_FLOOR = -120.0


def is_output_device(device: dict[str, Any]) -> bool:
    return int(device.get("max_output_channels", 0) or 0) > 0


def is_vb_cable_device(name: str) -> bool:
    lowered = name.lower()
    return any(keyword in lowered for keyword in VB_CABLE_KEYWORDS)


def output_devices(devices: Any) -> list[tuple[int, dict[str, Any]]]:
    return [(index, device) for index, device in enumerate(devices) if is_output_device(device)]


def find_vb_cable_device_from_devices(devices: Any) -> int | None:
    candidates: list[tuple[int, str]] = []
    for index, device in output_devices(devices):
        name = str(device.get("name", ""))
        if is_vb_cable_device(name):
            candidates.append((index, name))
    if not candidates:
        return None
    wasapi = [(index, name) for index, name in candidates if "wasapi" in name.lower()]
    return (wasapi[0] if wasapi else candidates[0])[0]


def query_sound_devices() -> Any:
    import sounddevice as sd

    return sd.query_devices()


def find_vb_cable_device() -> int | None:
    return find_vb_cable_device_from_devices(query_sound_devices())


def format_output_devices(devices: Any) -> list[str]:
    lines: list[str] = ["Audio output devices:"]
    found = False
    for index, device in output_devices(devices):
        found = True
        name = str(device.get("name", ""))
        recommended = "  recommended" if is_vb_cable_device(name) else ""
        lines.append(f"  [{index}] {name}{recommended}")
    if not found:
        lines.append("  no output-capable audio devices found")
    return lines


def rms_dbfs(samples: np.ndarray) -> float:
    if samples.size == 0:
        return DBFS_FLOOR
    values = samples.astype(np.float64) / 32768.0
    rms = float(np.sqrt(np.mean(values * values)))
    if rms <= 0.0:
        return DBFS_FLOOR
    return max(DBFS_FLOOR, 20.0 * math.log10(rms))


def peak_dbfs(samples: np.ndarray) -> float:
    if samples.size == 0:
        return DBFS_FLOOR
    peak = float(np.max(np.abs(samples.astype(np.float64))) / 32768.0)
    if peak <= 0.0:
        return DBFS_FLOOR
    return max(DBFS_FLOOR, 20.0 * math.log10(peak))


def apply_gain(samples: np.ndarray, gain: float) -> np.ndarray:
    if gain == 1.0:
        return samples
    gained = samples.astype(np.float32) * gain
    return np.clip(gained, -32768, 32767).astype(np.int16)


def mono_to_channels(samples: np.ndarray, channels: int) -> np.ndarray:
    if channels == 1:
        return samples.reshape(-1, 1)
    return np.repeat(samples.reshape(-1, 1), channels, axis=1)
