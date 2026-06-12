"""Logging setup for console and rotating file logs."""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 5


def default_log_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "audiosource-win" / "logs" / "audiosource-win.log"
    return Path.home() / ".audiosource-win" / "logs" / "audiosource-win.log"


def parse_log_level(level: str) -> int:
    value = getattr(logging, level.upper(), None)
    if not isinstance(value, int):
        raise ValueError(f"invalid log level: {level}")
    return value


def configure_logging(level: str = "INFO", log_file: str | None = None) -> Path:
    numeric_level = parse_log_level(level)
    path = Path(log_file) if log_file else default_log_path()

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(numeric_level)

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    console = logging.StreamHandler()
    console.setLevel(numeric_level)
    console.setFormatter(formatter)
    root.addHandler(console)

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        fallback = Path.cwd() / ".audiosource-win" / "logs" / "audiosource-win.log"
        try:
            fallback.parent.mkdir(parents=True, exist_ok=True)
            print(f"[WARN] cannot create log directory {path.parent}: {exc}; using {fallback}", file=sys.stderr)
            path = fallback
        except OSError as fallback_exc:
            print(f"[WARN] file logging disabled: {fallback_exc}", file=sys.stderr)
            return path

    file_handler = RotatingFileHandler(path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8")
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    return path
