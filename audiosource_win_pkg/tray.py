"""System tray resident mode."""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from .bridge import BridgeConfig
from .controller import BridgeController
from .diagnostics import format_results, run_doctor
from .logging_config import default_log_path
from .startup import disable_startup, enable_startup, startup_status
from .status import (
    BridgeStatus,
    STATE_ADB_OFFLINE,
    STATE_ADB_UNAUTHORIZED,
    STATE_FAILED,
    STATE_INIT,
    STATE_RECONNECTING,
    STATE_SOCKET_CONNECTING,
    STATE_STOPPED,
    STATE_STREAMING,
    format_dbfs,
)

STATE_COLORS = {
    STATE_STREAMING: "green",
    STATE_RECONNECTING: "gold",
    STATE_SOCKET_CONNECTING: "gold",
    STATE_FAILED: "red",
    STATE_ADB_OFFLINE: "red",
    STATE_ADB_UNAUTHORIZED: "red",
    STATE_STOPPED: "gray",
    STATE_INIT: "royalblue",
}


def color_for_state(state: str) -> str:
    return STATE_COLORS.get(state, "royalblue")


def create_icon_image(state: str, size: int = 64):
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = max(4, size // 8)
    draw.ellipse((margin, margin, size - margin, size - margin), fill=color_for_state(state), outline="black", width=2)
    return image


def format_tooltip(status: BridgeStatus) -> str:
    if status.state == STATE_STOPPED:
        return "AudioSource Win\nSTOPPED"
    pieces = [status.state]
    if status.transport or status.device_serial:
        pieces.append(f"{status.transport or 'unknown'} {status.device_serial or 'no-device'}")
    if status.level_dbfs is not None:
        pieces.append(f"level={format_dbfs(status.level_dbfs)}")
    if status.last_audio_age is not None and status.state != STATE_STREAMING:
        pieces.append(f"last_audio={status.last_audio_age:.1f}s")
    pieces.append(f"reconnects={status.reconnect_count}")
    return "AudioSource Win\n" + " | ".join(pieces)


class TrayApp:
    def __init__(
        self,
        controller: BridgeController,
        refresh_interval: float = 1.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self.controller = controller
        self.refresh_interval = refresh_interval
        self.logger = logger or logging.getLogger(__name__)
        self.icon: Any | None = None
        self._stop_event = threading.Event()
        self._last_notified_state: str | None = None

    def _notify(self, title: str, message: str) -> None:
        if self.icon is None or not hasattr(self.icon, "notify"):
            self.logger.info("%s: %s", title, message)
            return
        try:
            self.icon.notify(message, title)
        except Exception as exc:
            self.logger.debug("Tray notification failed: %s", exc)

    def maybe_notify_transition(self, previous: str | None, current: str) -> None:
        if previous == current or self._last_notified_state == current:
            return
        if previous == STATE_STREAMING and current == STATE_RECONNECTING:
            self._notify("AudioSource Win", "Audio stream interrupted; reconnecting.")
        elif previous == STATE_RECONNECTING and current == STATE_STREAMING:
            self._notify("AudioSource Win", "Audio stream restored.")
        elif current == STATE_FAILED:
            self._notify("AudioSource Win", "Bridge failed. Check logs for details.")
        self._last_notified_state = current

    def update_icon(self) -> None:
        if self.icon is None:
            return
        status = self.controller.get_status()
        previous = getattr(self.icon, "title", None)
        previous_state = previous.splitlines()[1].split(" | ", 1)[0] if isinstance(previous, str) and "\n" in previous else None
        self.icon.title = format_tooltip(status)
        self.icon.icon = create_icon_image(status.state)
        self.maybe_notify_transition(previous_state, status.state)

    def _update_loop(self) -> None:
        while not self._stop_event.wait(self.refresh_interval):
            self.update_icon()

    def start_bridge(self, _icon=None, _item=None) -> None:
        self.controller.start()
        self.update_icon()

    def stop_bridge(self, _icon=None, _item=None) -> None:
        self.controller.stop()
        self.update_icon()

    def reconnect_bridge(self, _icon=None, _item=None) -> None:
        self.controller.restart()
        self.update_icon()

    def run_doctor_async(self, _icon=None, _item=None) -> None:
        def worker() -> None:
            cfg = self.controller.config
            results = run_doctor(cfg.host, cfg.port, cfg.serial, cfg.device)
            text = format_results("AudioSource Win Doctor", results)
            self.logger.info("Tray doctor result:\n%s", text)
            self._notify("AudioSource Win Doctor", text.splitlines()[-1])

        threading.Thread(target=worker, name="tray-doctor", daemon=True).start()

    def open_logs(self, _icon=None, _item=None) -> None:
        log_dir = default_log_path().parent
        log_dir.mkdir(parents=True, exist_ok=True)
        if hasattr(os, "startfile"):
            os.startfile(str(log_dir))  # type: ignore[attr-defined]
        else:
            self.logger.info("Log directory: %s", log_dir)

    def open_status(self, _icon=None, _item=None) -> None:
        tooltip = format_tooltip(self.controller.get_status())
        self.logger.info("Tray status:\n%s", tooltip)
        self._notify("AudioSource Win Status", tooltip.replace("\n", " | "))

    def enable_startup(self, _icon=None, _item=None) -> None:
        path = enable_startup(start_bridge=True)
        self.logger.info("Startup enabled: %s", path)
        self._notify("AudioSource Win", "Startup enabled.")

    def disable_startup(self, _icon=None, _item=None) -> None:
        removed = disable_startup()
        self.logger.info("Startup disabled: %s", removed)
        self._notify("AudioSource Win", "Startup disabled.")

    def show_startup_status(self, _icon=None, _item=None) -> None:
        enabled = startup_status()
        self.logger.info("Startup status: %s", "enabled" if enabled else "disabled")
        self._notify("AudioSource Win", f"Startup is {'enabled' if enabled else 'disabled'}.")

    def exit(self, icon=None, _item=None) -> None:
        self._stop_event.set()
        self.controller.stop()
        target = icon or self.icon
        if target is not None:
            target.stop()

    def build_menu(self):
        import pystray

        return pystray.Menu(
            pystray.MenuItem("AudioSource Win", None, enabled=False),
            pystray.MenuItem(lambda _item: f"Status: {self.controller.get_status().state}", None, enabled=False),
            pystray.MenuItem(lambda _item: f"Device: {self.controller.get_status().device_serial or 'none'}", None, enabled=False),
            pystray.MenuItem(lambda _item: f"Output: {self.controller.get_status().audio_device or 'none'}", None, enabled=False),
            pystray.MenuItem(lambda _item: f"Level: {format_dbfs(self.controller.get_status().level_dbfs)}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Start Bridge", self.start_bridge),
            pystray.MenuItem("Stop Bridge", self.stop_bridge),
            pystray.MenuItem("Reconnect", self.reconnect_bridge),
            pystray.MenuItem("Run Doctor", self.run_doctor_async),
            pystray.MenuItem("Open Logs", self.open_logs),
            pystray.MenuItem("Open Status", self.open_status),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Enable Startup", self.enable_startup),
            pystray.MenuItem("Disable Startup", self.disable_startup),
            pystray.MenuItem("Startup Status", self.show_startup_status),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self.exit),
        )

    def run(self, start_bridge: bool = False) -> None:
        import pystray

        status = self.controller.get_status()
        self.icon = pystray.Icon("audiosource-win", create_icon_image(status.state), format_tooltip(status), self.build_menu())
        if start_bridge:
            self.controller.start()
        updater = threading.Thread(target=self._update_loop, name="tray-status", daemon=True)
        updater.start()
        try:
            self.icon.run()
        finally:
            self._stop_event.set()
            self.controller.stop()
            updater.join(timeout=2.0)


def run_tray(config: BridgeConfig, start_bridge: bool = False, refresh_interval: float = 1.0) -> None:
    TrayApp(BridgeController(config), refresh_interval=refresh_interval).run(start_bridge=start_bridge)
