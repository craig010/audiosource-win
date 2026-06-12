"""Background bridge controller for tray and resident workflows."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from .bridge import AudioBridge, BridgeConfig
from .status import BridgeStatus, STATE_FAILED, STATE_STOPPED


class BridgeController:
    def __init__(
        self,
        config: BridgeConfig,
        logger: logging.Logger | None = None,
        bridge_factory: Callable[[BridgeConfig], AudioBridge] = AudioBridge,
    ) -> None:
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.bridge_factory = bridge_factory
        self._lock = threading.RLock()
        self._bridge: AudioBridge | None = None
        self._thread: threading.Thread | None = None
        self._last_status = BridgeStatus(state=STATE_STOPPED)

    def _run_bridge(self, bridge: AudioBridge) -> None:
        try:
            bridge.run()
        except Exception as exc:
            self.logger.error("Bridge thread failed: %s", exc, exc_info=self.logger.isEnabledFor(logging.DEBUG))
            bridge.status.state = STATE_FAILED
            bridge.status.last_error = str(exc)
        finally:
            with self._lock:
                self._last_status = bridge.status
                if self._bridge is bridge:
                    self._bridge = None
                self._thread = None

    def start(self) -> bool:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            bridge = self.bridge_factory(self.config)
            self._bridge = bridge
            self._last_status = bridge.status
            self._thread = threading.Thread(target=self._run_bridge, args=(bridge,), name="bridge-controller", daemon=True)
            self._thread.start()
            return True

    def stop(self, timeout: float = 3.0) -> bool:
        with self._lock:
            bridge = self._bridge
            thread = self._thread
        if bridge is None:
            return False
        bridge.stop()
        if thread is not None:
            thread.join(timeout=timeout)
        with self._lock:
            self._last_status = bridge.status
        return True

    def restart(self) -> bool:
        self.stop()
        return self.start()

    def get_status(self) -> BridgeStatus:
        with self._lock:
            if self._bridge is not None:
                return self._bridge.status
            return self._last_status

    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()
