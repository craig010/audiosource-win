"""Windows bridge for the Android AudioSource microphone stream."""

import argparse
import logging
import queue
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np


__version__ = "0.1.0"

APP_PACKAGE = "fr.dzx.audiosource"
APP_ACTIVITY = "fr.dzx.audiosource/.MainActivity"
REMOTE_SOCKET = "localabstract:audiosource"

INPUT_SAMPLE_RATE = 44100
INPUT_CHANNELS = 1
BYTES_PER_SAMPLE = 2

OUTPUT_SAMPLE_RATE = 44100
OUTPUT_CHANNELS = 2
OUTPUT_DTYPE = "int16"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 27183
DEFAULT_BLOCKSIZE = 1024
DEFAULT_QUEUE_BLOCKS = 64
DEFAULT_GAIN = 1.0
DEFAULT_RETRY_INTERVAL = 1.0
DEFAULT_APP_START_WAIT = 1.5


@dataclass
class BridgeConfig:
    host: str
    port: int
    device: Optional[int]
    serial: Optional[str]
    blocksize: int
    queue_blocks: int
    gain: float
    retry_interval: float
    app_start_wait: float
    auto_adb: bool
    input_file: Optional[str]


@dataclass
class BridgeStats:
    socket_reconnects: int = 0
    dropped_blocks: int = 0
    underruns: int = 0
    callback_errors: int = 0
    received_blocks: int = 0


def run_cmd(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=check,
        capture_output=True,
        text=True,
        shell=False,
    )


def adb_cmd(args: list[str], serial: Optional[str] = None) -> subprocess.CompletedProcess[str]:
    cmd = ["adb"]
    if serial:
        cmd.extend(["-s", serial])
    cmd.extend(args)
    return run_cmd(cmd)


def ensure_adb_exists() -> None:
    if shutil.which("adb") is None:
        raise RuntimeError("adb was not found. Install Android Platform Tools and make sure adb is in PATH.")


def get_adb_devices() -> list[str]:
    result = adb_cmd(["devices"])
    if result.returncode != 0:
        raise RuntimeError(f"adb devices failed:\n{result.stderr}")

    serials: list[str] = []
    for line in result.stdout.strip().splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


def choose_adb_serial(requested_serial: Optional[str]) -> str:
    serials = get_adb_devices()
    if requested_serial:
        if requested_serial not in serials:
            raise RuntimeError(f"Device {requested_serial} is not online. Online devices: {', '.join(serials) or 'none'}")
        return requested_serial
    if not serials:
        raise RuntimeError("No Android device is online. Enable USB debugging and check that adb devices shows device.")
    if len(serials) > 1:
        raise RuntimeError(f"Multiple Android devices detected. Select one with --serial: {', '.join(serials)}")
    return serials[0]


def ensure_app_installed(serial: str) -> None:
    result = adb_cmd(["shell", "pm", "path", APP_PACKAGE], serial)
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f"Android package {APP_PACKAGE} was not found. Install the AudioSource Android app first.")


def grant_android_permissions(serial: str) -> None:
    for perm in ("android.permission.RECORD_AUDIO", "android.permission.POST_NOTIFICATIONS"):
        result = adb_cmd(["shell", "pm", "grant", APP_PACKAGE, perm], serial)
        if result.returncode == 0:
            logging.info("Granted permission: %s", perm)
            continue

        msg = (result.stderr or result.stdout).strip()
        if msg:
            logging.debug("Permission grant skipped: %s: %s", perm, msg)


def setup_adb_forward(config: BridgeConfig, serial: str) -> None:
    adb_cmd(["forward", "--remove", f"tcp:{config.port}"], serial)
    result = adb_cmd(["forward", f"tcp:{config.port}", REMOTE_SOCKET], serial)
    if result.returncode != 0:
        raise RuntimeError(f"adb forward failed:\n{result.stderr}")


def prepare_android_side(config: BridgeConfig) -> None:
    ensure_adb_exists()
    serial = choose_adb_serial(config.serial)
    logging.info("Android device online: %s", serial)

    wait_result = adb_cmd(["wait-for-device"], serial)
    if wait_result.returncode != 0:
        raise RuntimeError(f"adb wait-for-device failed:\n{wait_result.stderr}")

    ensure_app_installed(serial)
    start_result = adb_cmd(["shell", "am", "start", "-n", APP_ACTIVITY], serial)
    if start_result.returncode != 0:
        raise RuntimeError(f"Failed to start Android app:\n{start_result.stderr}")

    time.sleep(config.app_start_wait)
    grant_android_permissions(serial)
    setup_adb_forward(config, serial)
    logging.info("ADB forward ready: tcp:%s -> %s", config.port, REMOTE_SOCKET)


def list_devices() -> None:
    import sounddevice as sd

    print(sd.query_devices())


def find_vb_cable_device() -> Optional[int]:
    import sounddevice as sd

    devices = sd.query_devices()
    candidates: list[tuple[int, str]] = []

    for index, device in enumerate(devices):
        name = str(device.get("name", ""))
        max_output_channels = int(device.get("max_output_channels", 0))
        if max_output_channels <= 0:
            continue

        lowered = name.lower()
        if "cable input" in lowered or "vb-audio" in lowered:
            candidates.append((index, name))

    if not candidates:
        return None

    wasapi_candidates = [(idx, name) for idx, name in candidates if "wasapi" in name.lower()]
    selected = wasapi_candidates[0] if wasapi_candidates else candidates[0]
    logging.info("Auto-selected output device: [%s] %s", selected[0], selected[1])
    return selected[0]


class AudioBridge:
    def __init__(self, config: BridgeConfig) -> None:
        self.config = config
        self.audio_queue: queue.Queue[bytes] = queue.Queue(maxsize=config.queue_blocks)
        self.stop_event = threading.Event()
        self.socket_lock = threading.Lock()
        self.current_socket: Optional[socket.socket] = None
        self.stats = BridgeStats()

    def close_current_socket(self) -> None:
        with self.socket_lock:
            if self.current_socket is None:
                return
            try:
                self.current_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self.current_socket.close()
            except OSError:
                pass
            self.current_socket = None

    def connect_socket(self) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((self.config.host, self.config.port))
        sock.settimeout(None)
        return sock

    def recv_exact(self, sock: socket.socket, size: int) -> bytes:
        buf = bytearray()
        while len(buf) < size and not self.stop_event.is_set():
            chunk = sock.recv(size - len(buf))
            if not chunk:
                raise ConnectionError("socket disconnected")
            buf.extend(chunk)
        return bytes(buf)

    def enqueue_block(self, raw: bytes) -> None:
        if self.audio_queue.full():
            try:
                self.audio_queue.get_nowait()
                self.stats.dropped_blocks += 1
            except queue.Empty:
                pass

        try:
            self.audio_queue.put_nowait(raw)
            self.stats.received_blocks += 1
        except queue.Full:
            self.stats.dropped_blocks += 1

    def socket_receiver(self) -> None:
        bytes_per_block = self.config.blocksize * INPUT_CHANNELS * BYTES_PER_SAMPLE

        while not self.stop_event.is_set():
            try:
                if self.config.auto_adb:
                    prepare_android_side(self.config)

                logging.info("Connecting audio stream: %s:%s", self.config.host, self.config.port)
                sock = self.connect_socket()
                with self.socket_lock:
                    self.current_socket = sock
                self.stats.socket_reconnects += 1
                logging.info("Audio stream connected")

                while not self.stop_event.is_set():
                    self.enqueue_block(self.recv_exact(sock, bytes_per_block))

            except Exception as exc:
                logging.warning("Audio stream interrupted: %s", exc)
            finally:
                self.close_current_socket()

            if not self.stop_event.is_set():
                time.sleep(self.config.retry_interval)

    def file_receiver(self) -> None:
        assert self.config.input_file is not None
        bytes_per_block = self.config.blocksize * INPUT_CHANNELS * BYTES_PER_SAMPLE
        logging.info("Playing PCM from file: %s", self.config.input_file)

        with open(self.config.input_file, "rb") as file:
            while not self.stop_event.is_set():
                raw = file.read(bytes_per_block)
                if not raw:
                    file.seek(0)
                    continue
                if len(raw) < bytes_per_block:
                    raw = raw + bytes(bytes_per_block - len(raw))
                self.enqueue_block(raw)
                time.sleep(self.config.blocksize / INPUT_SAMPLE_RATE)

    def audio_callback(self, outdata, frames, time_info, status) -> None:
        if status:
            logging.debug("audio status: %s", status)

        try:
            raw = self.audio_queue.get_nowait()
        except queue.Empty:
            self.stats.underruns += 1
            outdata.fill(0)
            return

        try:
            mono = np.frombuffer(raw, dtype=np.int16)
            if mono.size != frames:
                if mono.size < frames:
                    padded = np.zeros(frames, dtype=np.int16)
                    padded[:mono.size] = mono
                    mono = padded
                else:
                    mono = mono[:frames]

            if self.config.gain != 1.0:
                mono_f = mono.astype(np.float32) * self.config.gain
                mono_f = np.clip(mono_f, -32768, 32767)
                mono = mono_f.astype(np.int16)

            outdata[:] = np.repeat(mono.reshape(-1, 1), OUTPUT_CHANNELS, axis=1)
        except Exception as exc:
            self.stats.callback_errors += 1
            logging.warning("audio callback error: %s", exc)
            outdata.fill(0)

    def log_stats(self) -> None:
        while not self.stop_event.is_set():
            time.sleep(5.0)
            logging.info(
                "stats received=%s dropped=%s underruns=%s callback_errors=%s queue=%s/%s",
                self.stats.received_blocks,
                self.stats.dropped_blocks,
                self.stats.underruns,
                self.stats.callback_errors,
                self.audio_queue.qsize(),
                self.config.queue_blocks,
            )

    def run(self) -> None:
        import sounddevice as sd

        receiver_target = self.file_receiver if self.config.input_file else self.socket_receiver
        receiver = threading.Thread(target=receiver_target, name="receiver", daemon=True)
        reporter = threading.Thread(target=self.log_stats, name="stats", daemon=True)
        receiver.start()
        reporter.start()

        try:
            with sd.OutputStream(
                samplerate=OUTPUT_SAMPLE_RATE,
                channels=OUTPUT_CHANNELS,
                dtype=OUTPUT_DTYPE,
                device=self.config.device,
                blocksize=self.config.blocksize,
                callback=self.audio_callback,
            ):
                logging.info("Streaming to the Windows audio device. Press Ctrl+C to exit.")
                while not self.stop_event.is_set():
                    time.sleep(1.0)
        except KeyboardInterrupt:
            print("\nInterrupted, exiting...")
        finally:
            self.stop_event.set()
            self.close_current_socket()
            receiver.join(timeout=2.0)
            reporter.join(timeout=1.0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AudioSource Windows bridge")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Local host for the ADB-forwarded socket")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Local port for the ADB-forwarded socket")
    parser.add_argument("--device", type=int, help="sounddevice output device index")
    parser.add_argument("--serial", help="ADB serial to use when multiple Android devices are connected")
    parser.add_argument("--blocksize", type=int, default=DEFAULT_BLOCKSIZE, help="Audio frames per block")
    parser.add_argument("--queue-blocks", type=int, default=DEFAULT_QUEUE_BLOCKS, help="Number of audio blocks to buffer")
    parser.add_argument("--gain", type=float, default=DEFAULT_GAIN, help="Software gain")
    parser.add_argument("--retry-interval", type=float, default=DEFAULT_RETRY_INTERVAL, help="Reconnect interval in seconds")
    parser.add_argument("--app-start-wait", type=float, default=DEFAULT_APP_START_WAIT, help="Seconds to wait after starting the Android app")
    parser.add_argument("--no-auto-adb", action="store_true", help="Do not start the app, grant permissions, or create adb forward")
    parser.add_argument("--list-devices", action="store_true", help="List sounddevice devices and exit")
    parser.add_argument("--input-file", help="Replay a raw PCM file for offline testing")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return parser.parse_args()


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


def build_config(args: argparse.Namespace) -> BridgeConfig:
    device = args.device
    if device is None and not args.list_devices:
        device = find_vb_cable_device()
        if device is None:
            logging.warning("VB-CABLE output device was not found automatically; using the sounddevice default output.")

    return BridgeConfig(
        host=args.host,
        port=args.port,
        device=device,
        serial=args.serial,
        blocksize=args.blocksize,
        queue_blocks=args.queue_blocks,
        gain=args.gain,
        retry_interval=args.retry_interval,
        app_start_wait=args.app_start_wait,
        auto_adb=not args.no_auto_adb and not args.input_file,
        input_file=args.input_file,
    )


def main() -> None:
    args = parse_args()
    configure_logging(args.verbose)

    if args.list_devices:
        list_devices()
        return

    config = build_config(args)
    logging.info(
        "Config: host=%s port=%s device=%s blocksize=%s queue_blocks=%s gain=%s auto_adb=%s input_file=%s",
        config.host,
        config.port,
        config.device,
        config.blocksize,
        config.queue_blocks,
        config.gain,
        config.auto_adb,
        config.input_file,
    )

    AudioBridge(config).run()


if __name__ == "__main__":
    main()
