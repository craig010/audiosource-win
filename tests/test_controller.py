import time

from audiosource_win_pkg.bridge import BridgeConfig
from audiosource_win_pkg.controller import BridgeController
from audiosource_win_pkg.status import BridgeStatus, STATE_STOPPED, STATE_STREAMING


class FakeBridge:
    def __init__(self, config):
        self.config = config
        self.status = BridgeStatus(state=STATE_STREAMING)
        self.stopped = False

    def run(self):
        while not self.stopped:
            time.sleep(0.01)
        self.status.state = STATE_STOPPED

    def stop(self):
        self.stopped = True


def test_start_only_starts_once():
    created = []

    def factory(config):
        bridge = FakeBridge(config)
        created.append(bridge)
        return bridge

    controller = BridgeController(BridgeConfig(), bridge_factory=factory)
    assert controller.start() is True
    assert controller.start() is False
    assert len(created) == 1
    controller.stop()


def test_stop_can_be_repeated():
    controller = BridgeController(BridgeConfig(), bridge_factory=FakeBridge)
    assert controller.stop() is False
    assert controller.start() is True
    assert controller.stop() is True
    assert controller.stop() is False


def test_restart_stops_and_starts():
    controller = BridgeController(BridgeConfig(), bridge_factory=FakeBridge)
    assert controller.start() is True
    assert controller.restart() is True
    assert controller.is_running() is True
    controller.stop()


def test_get_status_returns_status():
    controller = BridgeController(BridgeConfig(), bridge_factory=FakeBridge)
    assert controller.get_status().state == STATE_STOPPED
    controller.start()
    assert controller.get_status().state == STATE_STREAMING
    controller.stop()
