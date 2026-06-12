from audiosource_win_pkg.status import BridgeStatus, format_duration, format_status_line


def test_format_duration():
    assert format_duration(45296) == "12:34:56"


def test_status_line_formatting():
    status = BridgeStatus(
        state="STREAMING",
        device_serial="192.168.5.19:5555",
        transport="wifi",
        audio_device="CABLE Input",
        rx_rate_bps=176400,
        level_dbfs=-18.7,
        peak_dbfs=-6.2,
        queue_fill=3,
        queue_blocks=64,
        drop_count=1,
        underrun_count=2,
        reconnect_count=3,
        uptime=12,
    )
    line = format_status_line(status)
    assert "STREAMING" in line
    assert "wifi 192.168.5.19:5555" in line
    assert "level=-18.7dBFS" in line
    assert "queue=3/64" in line
