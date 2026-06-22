"""Logging setup for console and rotating file logs."""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .runtime import error_log_path, log_path

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


def configure_logging(level: str = "INFO", log_file: str | None = None, *, console: bool = True) -> Path:
    numeric_level = parse_log_level(level)
    path = Path(log_file) if log_file else default_log_path()

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(numeric_level)

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    if console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(numeric_level)
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

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

    try:
        file_handler = RotatingFileHandler(path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8")
    except OSError as exc:
        fallback = Path.cwd() / ".audiosource-win" / "logs" / "audiosource-win.log"
        try:
            fallback.parent.mkdir(parents=True, exist_ok=True)
            print(f"[WARN] cannot open log file {path}: {exc}; using {fallback}", file=sys.stderr)
            path = fallback
            file_handler = RotatingFileHandler(path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8")
        except OSError as fallback_exc:
            print(f"[WARN] file logging disabled: {fallback_exc}", file=sys.stderr)
            return path
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # Background mode has a dedicated error log, while normal commands retain
    # the existing combined rotating log.
    if not console and path == log_path():
        error_handler = RotatingFileHandler(error_log_path(), maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8")
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(formatter)
        root.addHandler(error_handler)

    return path
