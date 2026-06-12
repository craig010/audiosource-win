from audiosource_win_pkg.bridge import BridgeConfig
from audiosource_win_pkg.status import BridgeStatus, STATE_FAILED, STATE_RECONNECTING, STATE_STOPPED, STATE_STREAMING
from audiosource_win_pkg.tray import TrayApp, color_for_state, format_tooltip


class FakeController:
    def __init__(self):
        self.config = BridgeConfig()
        self.status = BridgeStatus(state=STATE_STOPPED)
        self.started = 0
        self.stopped = 0
        self.restarted = 0

    def start(self):
        self.started += 1
        self.status.state = STATE_STREAMING
        return True

    def stop(self):
        self.stopped += 1
        self.status.state = STATE_STOPPED
        return True

    def restart(self):
        self.restarted += 1
        self.status.state = STATE_RECONNECTING
        return True

    def get_status(self):
        return self.status


class FailingIcon:
    def notify(self, message, title):
        raise RuntimeError("unsupported")


def test_state_to_icon_color_mapping():
    assert color_for_state(STATE_STREAMING) == "green"
    assert color_for_state(STATE_RECONNECTING) == "gold"
    assert color_for_state(STATE_FAILED) == "red"
    assert color_for_state(STATE_STOPPED) == "gray"
    assert color_for_state("OTHER") == "royalblue"


def test_tooltip_formatting():
    status = BridgeStatus(
        state=STATE_STREAMING,
        transport="wifi",
        device_serial="192.168.1.5:5555",
        level_dbfs=-18.6,
        reconnect_count=2,
    )
    tooltip = format_tooltip(status)
    assert "AudioSource Win" in tooltip
    assert "STREAMING" in tooltip
    assert "level=-18.6dBFS" in tooltip
    assert "reconnects=2" in tooltip
    assert format_tooltip(BridgeStatus(state=STATE_STOPPED)) == "AudioSource Win\nSTOPPED"


def test_menu_actions_call_controller():
    controller = FakeController()
    app = TrayApp(controller)
    app.start_bridge()
    app.stop_bridge()
    app.reconnect_bridge()
    assert controller.started == 1
    assert controller.stopped == 1
    assert controller.restarted == 1


def test_notify_failure_does_not_raise():
    app = TrayApp(FakeController())
    app.icon = FailingIcon()
    app._notify("title", "message")
