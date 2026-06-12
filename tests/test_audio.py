import numpy as np

from audiosource_win_pkg.audio import apply_gain, find_vb_cable_device_from_devices, mono_to_channels, peak_dbfs, rms_dbfs


def test_vb_cable_keyword_detection():
    devices = [
        {"name": "Speakers", "max_output_channels": 2},
        {"name": "CABLE Input (VB-Audio Virtual Cable)", "max_output_channels": 2},
    ]
    assert find_vb_cable_device_from_devices(devices) == 1


def test_input_only_device_ignored():
    devices = [{"name": "CABLE Input (VB-Audio Virtual Cable)", "max_output_channels": 0}]
    assert find_vb_cable_device_from_devices(devices) is None


def test_int16_pcm_rms_dbfs():
    samples = np.array([32767, -32768], dtype=np.int16)
    assert -0.1 <= rms_dbfs(samples) <= 0.1


def test_silence_pcm_does_not_crash():
    samples = np.zeros(1024, dtype=np.int16)
    assert rms_dbfs(samples) == -120.0
    assert peak_dbfs(samples) == -120.0


def test_peak_dbfs():
    samples = np.array([0, 16384], dtype=np.int16)
    assert -6.1 <= peak_dbfs(samples) <= -5.9


def test_mono_to_stereo():
    samples = np.array([1, 2], dtype=np.int16)
    stereo = mono_to_channels(samples, 2)
    assert stereo.tolist() == [[1, 1], [2, 2]]


def test_gain_clipping():
    samples = np.array([20000, -20000], dtype=np.int16)
    gained = apply_gain(samples, 2.0)
    assert gained.tolist() == [32767, -32768]
