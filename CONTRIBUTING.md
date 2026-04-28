# Contributing

Contributions are welcome. This project is intentionally small, so changes should stay focused and easy to review.

## Development Setup

```powershell
pip install -e .
```

## Checks

Before opening a pull request, run:

```powershell
python -m py_compile audiosource_win.py
python audiosource_win.py --help
```

If you change audio device handling, also verify:

```powershell
python audiosource_win.py --list-devices
```

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
