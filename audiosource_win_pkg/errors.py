"""Typed user-facing errors for AudioSource Win."""


class AudioSourceWinError(Exception):
    """Base class for expected AudioSource Win failures."""


class AdbNotFound(AudioSourceWinError):
    """adb.exe was not found in PATH."""


class NoAdbDevice(AudioSourceWinError):
    """No usable Android device is available."""


class AdbUnauthorized(AudioSourceWinError):
    """The selected Android device is unauthorized."""


class AdbOffline(AudioSourceWinError):
    """The selected Android device is offline."""


class MultipleAdbDevices(AudioSourceWinError):
    """More than one online Android device exists and no serial was selected."""


class ForwardFailed(AudioSourceWinError):
    """adb forward failed."""


class SocketConnectFailed(AudioSourceWinError):
    """The forwarded socket could not be reached."""


class AudioDeviceNotFound(AudioSourceWinError):
    """No matching Windows audio output device was found."""


class AudioStreamFailed(AudioSourceWinError):
    """The Windows audio output stream failed."""


class AndroidAppNotFound(AudioSourceWinError):
    """The Android AudioSource package is not installed."""

