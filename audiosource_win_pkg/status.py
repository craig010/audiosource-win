"""Runtime status model and formatting."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


STATE_INIT = "INIT"
STATE_CHECKING = "CHECKING"
STATE_ADB_OFFLINE = "ADB_OFFLINE"
STATE_ADB_UNAUTHORIZED = "ADB_UNAUTHORIZED"
STATE_ADB_ONLINE = "ADB_ONLINE"
STATE_APP_STARTING = "APP_STARTING"
STATE_FORWARDING = "FORWARDING"
STATE_SOCKET_CONNECTING = "SOCKET_CONNECTING"
STATE_STREAMING = "STREAMING"
STATE_SILENT = "SILENT"
STATE_RECONNECTING = "RECONNECTING"
STATE_STOPPING = "STOPPING"
STATE_STOPPED = "STOPPED"
STATE_FAILED = "FAILED"


@dataclass
class BridgeStatus:
    state: str = STATE_INIT
    device_serial: str | None = None
    transport: str | None = None
    audio_device: str | int | None = None
    sample_rate: int = 44100
    input_channels: int = 1
    output_channels: int = 2
    blocksize: int = 1024
    queue_blocks: int = 64
    queue_fill: int = 0
    rx_bytes_total: int = 0
    rx_rate_bps: float = 0.0
    level_dbfs: float | None = None
    peak_dbfs: float | None = None
    drop_count: int = 0
    underrun_count: int = 0
    callback_error_count: int = 0
    reconnect_count: int = 0
    last_audio_age: float | None = None
    uptime: float = 0.0
    last_error: str | None = None
    start_time: float = field(default_factory=time.monotonic, repr=False)
    last_rx_time: float | None = field(default=None, repr=False)
    _rate_time: float = field(default_factory=time.monotonic, repr=False)
    _rate_bytes: int = field(default=0, repr=False)

    def mark_received(self, byte_count: int, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self.rx_bytes_total += byte_count
        self.last_rx_time = now
        elapsed = now - self._rate_time
        if elapsed >= 0.5:
            self.rx_rate_bps = (self.rx_bytes_total - self._rate_bytes) / elapsed
            self._rate_time = now
            self._rate_bytes = self.rx_bytes_total
        self.last_audio_age = 0.0

    def refresh(self, queue_fill: int | None = None, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self.uptime = max(0.0, now - self.start_time)
        if queue_fill is not None:
            self.queue_fill = queue_fill
        if self.last_rx_time is not None:
            self.last_audio_age = max(0.0, now - self.last_rx_time)


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_rate(bytes_per_second: float) -> str:
    if bytes_per_second >= 1024 * 1024:
        return f"{bytes_per_second / (1024 * 1024):.1f}MB/s"
    if bytes_per_second >= 1024:
        return f"{bytes_per_second / 1024:.0f}KB/s"
    return f"{bytes_per_second:.0f}B/s"


def format_dbfs(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f}dBFS"


def format_status_line(status: BridgeStatus) -> str:
    device = status.audio_device if status.audio_device is not None else "default output"
    transport = status.transport or "unknown"
    serial = status.device_serial or "no-device"
    parts = [
        status.state,
        f"{transport} {serial}",
        str(device),
        f"{status.sample_rate / 1000:.1f}kHz {status.input_channels}ch->{status.output_channels}ch",
        f"rx={format_rate(status.rx_rate_bps)}",
        f"level={format_dbfs(status.level_dbfs)}",
        f"peak={format_dbfs(status.peak_dbfs)}",
        f"queue={status.queue_fill}/{status.queue_blocks}",
        f"drops={status.drop_count}",
        f"underruns={status.underrun_count}",
        f"reconnects={status.reconnect_count}",
        f"uptime={format_duration(status.uptime)}",
    ]
    if status.last_audio_age is not None:
        parts.append(f"last_audio={status.last_audio_age:.1f}s")
    if status.last_error:
        parts.append(f"error={status.last_error}")
    return " | ".join(parts)
