# Changelog

All notable changes to this project will be documented in this file.

## 0.4.0 - 2026-06-22

Added:
- Silent `run --background` mode with PID-file single-instance protection and stale PID recovery.
- `status`, `stop`, and `logs` commands for the managed background bridge.
- Login startup modes: `background` (default) and the existing visible `tray` mode.
- Dedicated background error log and mock-based runtime management tests.

Changed:
- Startup Folder entries use `pythonw.exe` when available and set the repository working directory before launch.
- Background startup launches without a console window, tray icon, or notifications.

## 0.3.0 - 2026-06-12

Added:
- System tray mode.
- Tray controls for start, stop, reconnect, doctor, logs, status, startup, and exit.
- Tray status tooltip and state-colored generated icons.
- Startup management commands for status, enable, and disable.
- Login startup integration using the current user's Startup Folder.
- Tests for tray, startup, and bridge controller behavior.

Changed:
- CLI now includes tray and startup subcommands.
- Documentation now covers tray and startup workflows.
- Runtime dependencies now include pystray and Pillow for tray mode.

## 0.2.0 - 2026-06-12

Added:
- CLI subcommands for run, devices, list-audio, check, and doctor.
- Runtime status display with audio level, queue, drop, underrun, reconnect, and uptime metrics.
- Automatic reconnect for socket, ADB, and audio stream interruptions.
- Rotating file logging.
- Mock-based automated tests.

Changed:
- Improved error messages for ADB, socket, and audio device failures.
- Updated development checks.
- Moved implementation into an internal package while preserving `python audiosource_win.py`.

Fixed:
- Reduced risk of silent failure when the audio stream disconnects.

## 0.1.0 - 2026-04-28

- Add Windows bridge for the Android AudioSource microphone stream.
- Add automatic ADB setup, Android app startup, permission grant attempt, and socket forwarding.
- Add VB-CABLE output device auto-detection.
- Add command-line options for device selection, ADB serial, gain, queue size, block size, and verbose logs.
- Add manual ADB mode with `--no-auto-adb`.
- Add basic runtime audio statistics.
