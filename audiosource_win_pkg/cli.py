"""Command-line interface for AudioSource Win."""

from __future__ import annotations

import argparse
import logging
import sys

from . import __version__
from .adb import list_adb_devices
from .audio import find_vb_cable_device, format_output_devices, query_sound_devices
from .bridge import BridgeConfig, AudioBridge
from .diagnostics import format_results, run_check, run_doctor
from .errors import AudioSourceWinError
from .logging_config import configure_logging
from .startup import StartupError, disable_startup, enable_startup, startup_status

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 27183
DEFAULT_BLOCKSIZE = 1024
DEFAULT_QUEUE_BLOCKS = 64
DEFAULT_GAIN = 1.0
DEFAULT_RECONNECT_INTERVAL = 2.0
DEFAULT_APP_START_WAIT = 1.5
DEFAULT_SOCKET_TIMEOUT = 5.0
DEFAULT_SILENT_TIMEOUT = 10.0
DEFAULT_STATUS_INTERVAL = 1.0
DEFAULT_SAMPLE_RATE = 44100
DEFAULT_OUTPUT_CHANNELS = 2

COMMANDS = {"run", "devices", "list-audio", "check", "doctor", "tray", "startup"}


def add_run_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default=DEFAULT_HOST, help="Local host for the ADB-forwarded socket")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Local port for the ADB-forwarded socket")
    parser.add_argument("--serial", help="ADB serial to use when multiple Android devices are connected")
    parser.add_argument("--device", type=int, help="sounddevice output device index")
    parser.add_argument("--samplerate", type=int, default=DEFAULT_SAMPLE_RATE, help="Output sample rate")
    parser.add_argument("--channels", type=int, default=DEFAULT_OUTPUT_CHANNELS, help="Output channel count")
    parser.add_argument("--blocksize", type=int, default=DEFAULT_BLOCKSIZE, help="Audio frames per block")
    parser.add_argument("--queue-blocks", type=int, default=DEFAULT_QUEUE_BLOCKS, help="Number of audio blocks to buffer")
    parser.add_argument("--gain", type=float, default=DEFAULT_GAIN, help="Software gain")
    reconnect = parser.add_mutually_exclusive_group()
    reconnect.add_argument("--reconnect", dest="reconnect", action="store_true", default=True, help="Reconnect on stream interruptions")
    reconnect.add_argument("--no-reconnect", dest="reconnect", action="store_false", help="Exit after the first stream interruption")
    parser.add_argument("--reconnect-interval", "--retry-interval", dest="reconnect_interval", type=float, default=DEFAULT_RECONNECT_INTERVAL, help="Reconnect interval in seconds")
    parser.add_argument("--max-retries", type=int, default=0, help="Maximum reconnect attempts; 0 means infinite")
    parser.add_argument("--socket-timeout", type=float, default=DEFAULT_SOCKET_TIMEOUT, help="Socket timeout in seconds")
    parser.add_argument("--silent-timeout", type=float, default=DEFAULT_SILENT_TIMEOUT, help="Reconnect if no audio arrives for this many seconds")
    parser.add_argument("--status-interval", type=float, default=DEFAULT_STATUS_INTERVAL, help="Seconds between one-line status updates")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    parser.add_argument("--log-file", help="Override rotating log file path")
    parser.add_argument("--app-start-wait", type=float, default=DEFAULT_APP_START_WAIT, help="Seconds to wait after starting the Android app")
    parser.add_argument("--no-auto-adb", action="store_true", help="Do not start the app, grant permissions, or create adb forward")
    parser.add_argument("--input-file", help="Replay a raw PCM file for offline testing")
    parser.add_argument("--verbose", action="store_true", help="Compatibility alias for --log-level DEBUG")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AudioSource Windows bridge")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Run the audio bridge")
    add_run_options(run_parser)

    devices_parser = subparsers.add_parser("devices", help="List Android devices from adb")
    devices_parser.add_argument("--log-level", default="WARNING")
    devices_parser.add_argument("--log-file")

    audio_parser = subparsers.add_parser("list-audio", help="List Windows audio output devices")
    audio_parser.add_argument("--log-level", default="WARNING")
    audio_parser.add_argument("--log-file")

    check_parser = subparsers.add_parser("check", help="Run quick environment checks")
    check_parser.add_argument("--host", default=DEFAULT_HOST)
    check_parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    check_parser.add_argument("--log-level", default="WARNING")
    check_parser.add_argument("--log-file")

    doctor_parser = subparsers.add_parser("doctor", help="Run bounded end-to-end diagnostics")
    doctor_parser.add_argument("--host", default=DEFAULT_HOST)
    doctor_parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    doctor_parser.add_argument("--serial")
    doctor_parser.add_argument("--device", type=int)
    doctor_parser.add_argument("--log-level", default="WARNING")
    doctor_parser.add_argument("--log-file")

    tray_parser = subparsers.add_parser("tray", help="Run resident system tray mode")
    add_run_options(tray_parser)
    start_bridge = tray_parser.add_mutually_exclusive_group()
    start_bridge.add_argument("--start-bridge", dest="start_bridge", action="store_true", help="Start the bridge when the tray launches")
    start_bridge.add_argument("--no-start-bridge", dest="start_bridge", action="store_false", help="Launch only the tray")
    tray_parser.set_defaults(start_bridge=False)

    startup_parser = subparsers.add_parser("startup", help="Manage login startup for tray mode")
    startup_parser.add_argument("--log-level", default="WARNING")
    startup_parser.add_argument("--log-file")
    startup_subparsers = startup_parser.add_subparsers(dest="startup_command")
    startup_subparsers.required = True

    startup_subparsers.add_parser("status", help="Show whether login startup is enabled")
    enable_parser = startup_subparsers.add_parser("enable", help="Enable current-user login startup")
    enable_start_bridge = enable_parser.add_mutually_exclusive_group()
    enable_start_bridge.add_argument("--start-bridge", dest="start_bridge", action="store_true", default=True)
    enable_start_bridge.add_argument("--no-start-bridge", dest="start_bridge", action="store_false")
    enable_parser.add_argument("--method", default="startup-folder", choices=["startup-folder", "task-scheduler"])
    disable_parser = startup_subparsers.add_parser("disable", help="Disable current-user login startup")
    disable_parser.add_argument("--method", default="startup-folder", choices=["startup-folder", "task-scheduler"])

    return parser


def normalize_argv(argv: list[str]) -> list[str]:
    if "--list-devices" in argv:
        return ["list-audio"] + [arg for arg in argv if arg != "--list-devices"]
    if not argv:
        return ["run"]
    if argv[0] in {"--help", "-h", "--version"} or argv[0] in COMMANDS:
        return argv
    return ["run"] + argv


def build_config(args: argparse.Namespace) -> BridgeConfig:
    device = args.device
    if device is None:
        try:
            device = find_vb_cable_device()
            if device is None:
                logging.warning("VB-CABLE output device was not found automatically; using the sounddevice default output.")
            else:
                logging.info("Auto-selected VB-CABLE output device index: %s", device)
        except Exception as exc:
            logging.warning("Could not query audio devices: %s; using default output.", exc)

    return BridgeConfig(
        host=args.host,
        port=args.port,
        device=device,
        serial=args.serial,
        sample_rate=args.samplerate,
        output_channels=args.channels,
        blocksize=args.blocksize,
        queue_blocks=args.queue_blocks,
        gain=args.gain,
        reconnect=args.reconnect,
        reconnect_interval=args.reconnect_interval,
        max_retries=args.max_retries,
        socket_timeout=args.socket_timeout,
        silent_timeout=args.silent_timeout,
        status_interval=args.status_interval,
        app_start_wait=args.app_start_wait,
        auto_adb=not args.no_auto_adb and not args.input_file,
        input_file=args.input_file,
    )


def cmd_devices() -> int:
    try:
        devices = list_adb_devices()
    except AudioSourceWinError as exc:
        print(f"[FAIL] {exc}")
        return 1
    except Exception as exc:
        print(f"[FAIL] adb devices failed: {exc}")
        return 1

    print("ADB devices:")
    if not devices:
        print("  none")
        return 1
    for device in devices:
        hint = ""
        if device.state == "unauthorized":
            hint = "  please allow USB debugging on phone"
        elif device.state == "offline":
            hint = "  reconnect USB or wireless debugging"
        print(f"  [{device.state}] {device.serial:<20} {device.transport}{hint}")
    return 0 if any(device.state == "online" for device in devices) else 1


def cmd_list_audio() -> int:
    try:
        for line in format_output_devices(query_sound_devices()):
            print(line)
        return 0
    except Exception as exc:
        print(f"[FAIL] audio device query failed: {exc}")
        return 1


def cmd_check(args: argparse.Namespace) -> int:
    results = run_check(args.host, args.port)
    print(format_results("AudioSource Win Check", results))
    return 1 if any(result.status == "FAIL" for result in results) else 0


def cmd_doctor(args: argparse.Namespace) -> int:
    results = run_doctor(args.host, args.port, args.serial, args.device)
    print(format_results("AudioSource Win Doctor", results))
    return 1 if any(result.status == "FAIL" for result in results) else 0


def cmd_run(args: argparse.Namespace) -> int:
    if args.verbose:
        args.log_level = "DEBUG"
    log_path = configure_logging(args.log_level, args.log_file)
    logging.info("AudioSource Win %s starting", __version__)
    logging.info("Log file: %s", log_path)
    logging.info("Startup arguments: %s", vars(args))
    config = build_config(args)
    logging.info("Bridge config: %s", config)
    try:
        AudioBridge(config).run()
        return 0
    except AudioSourceWinError as exc:
        print(f"[FAIL] {exc}")
        logging.error("%s", exc)
        return 1
    except Exception as exc:
        print(f"[FAIL] {exc}")
        logging.error("Unhandled bridge failure: %s", exc, exc_info=logging.getLogger().isEnabledFor(logging.DEBUG))
        return 1


def cmd_tray(args: argparse.Namespace) -> int:
    if args.verbose:
        args.log_level = "DEBUG"
    log_path = configure_logging(args.log_level, args.log_file)
    logging.info("AudioSource Win %s tray starting", __version__)
    logging.info("Log file: %s", log_path)
    config = build_config(args)
    try:
        from .tray import run_tray

        run_tray(config, start_bridge=args.start_bridge)
        return 0
    except ImportError as exc:
        print(f"[FAIL] tray dependencies are missing: {exc}")
        logging.error("Tray dependencies are missing: %s", exc)
        return 1
    except Exception as exc:
        print(f"[FAIL] tray failed: {exc}")
        logging.error("Tray failed: %s", exc, exc_info=logging.getLogger().isEnabledFor(logging.DEBUG))
        return 1


def cmd_startup(args: argparse.Namespace) -> int:
    if getattr(args, "method", "startup-folder") == "task-scheduler":
        print("Task Scheduler startup method is not implemented yet.")
        return 1
    try:
        if args.startup_command == "status":
            enabled = startup_status()
            print(f"Startup is {'enabled' if enabled else 'disabled'}.")
            return 0
        if args.startup_command == "enable":
            path = enable_startup(start_bridge=args.start_bridge)
            print(f"Startup enabled: {path}")
            return 0
        if args.startup_command == "disable":
            removed = disable_startup()
            print("Startup disabled." if removed else "Startup already disabled.")
            return 0
    except StartupError as exc:
        print(f"[FAIL] {exc}")
        return 1
    except OSError as exc:
        print(f"[FAIL] startup operation failed: {exc}")
        return 1
    return 1


def main(argv: list[str] | None = None) -> int:
    argv = normalize_argv(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "run"

    if command != "run":
        configure_logging(getattr(args, "log_level", "WARNING"), getattr(args, "log_file", None))

    if command == "devices":
        return cmd_devices()
    if command == "list-audio":
        return cmd_list_audio()
    if command == "check":
        return cmd_check(args)
    if command == "doctor":
        return cmd_doctor(args)
    if command == "tray":
        return cmd_tray(args)
    if command == "startup":
        return cmd_startup(args)
    return cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
