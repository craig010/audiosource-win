"""Safe subprocess defaults for Windows desktop integration."""

from __future__ import annotations

import os
import subprocess


def subprocess_no_window_kwargs() -> dict[str, object]:
    """Return Windows-only options that prevent child console windows.

    Capturing output does not stop Windows from creating a console for a child
    executable.  Apply this to helper commands (ADB and PowerShell/CIM) so
    background startup cannot flash a terminal while doing housekeeping.
    """
    if os.name != "nt":
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
