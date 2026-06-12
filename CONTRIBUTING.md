# Contributing

Contributions are welcome. This project is intentionally small, so changes should stay focused and easy to review.

## Development Setup

```powershell
pip install -e ".[dev]"
```

## Checks

Before opening a pull request, run:

```powershell
python -m compileall .
python -m pytest -q
python audiosource_win.py --help
python audiosource_win.py run --help
python audiosource_win.py tray --help
python audiosource_win.py startup --help
python audiosource_win.py startup status
python audiosource_win.py check
python audiosource_win.py devices
python audiosource_win.py list-audio
```

If you change audio device handling and have local hardware, also verify:

```powershell
python audiosource_win.py doctor
python audiosource_win.py run --serial <device-serial>
```

Tray and startup tests must mock pystray, the bridge controller, APPDATA, startup entries, and OS shell integrations. They must not require a real Windows notification area, a real display, a real Android phone, real ADB, or a real VB-CABLE device.

Hardware-dependent tests with a real Android phone, wireless debugging, VB-CABLE, tray UI, and Startup Folder are manual checks. They should not block the mock-based automated test suite.

## Pull Request Guidelines

- Keep unrelated refactors out of feature or bug-fix pull requests.
- Document behavior changes in `README.md`.
- Add or update `CHANGELOG.md` for user-visible changes.
- Do not commit local audio captures, device logs, virtual environments, or build outputs.

## Project Scope

AudioSource Win focuses on the Windows bridge:

- Android AudioSource stream over ADB
- PCM handling
- Windows audio output through VB-CABLE
- practical diagnostics for setup and runtime issues

Android app changes belong in the upstream AudioSource project unless they are specifically needed for Windows compatibility.
