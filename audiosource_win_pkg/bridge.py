"""Core audio bridge runtime."""

from __future__ import annotations

import logging
import queue
import socket
import threading
import time
from dataclasses import dataclass

import numpy as np

from .adb import prepare_android_side, remove_forward
from .audio import apply_gain, mono_to_channels, peak_dbfs, rms_dbfs
from .status import BridgeStatus, STATE_CHECKING, STATE_FAILED, STATE_RECONNECTING, STATE_SILENT, STATE_SOCKET_CONNECTING, STATE_STOPPED, STATE_STOPPING, STATE_STREAMING, format_status_line

INPUT_CHANNELS = 1
BYTES_PER_SAMPLE = 2
OUTPUT_DTYPE = "int16"


@dataclass
class BridgeConfig:
    host: str = "127.0.0.1"
    port: int = 27183
    device: int | None = None
    serial: str | None = None
    sample_rate: int = 44100
    input_channels: int = 1
    output_channels: int = 2
    blocksize: int = 1024
    queue_blocks: int = 64
    gain: float = 1.0
    reconnect: bool = True
    reconnect_interval: float = 2.0
    max_retries: int = 0
    socket_timeout: float = 5.0
    silent_timeout: float = 10.0
    status_interval: float = 1.0
    app_start_wait: float = 1.5
    auto_adb: bool = True
    input_file: str | None = None


class AudioBridge:
    def __init__(self, config: BridgeConfig) -> None:
        self.config = config
        self.audio_queue: queue.Queue[bytes] = queue.Queue(maxsize=config.queue_blocks)
        self.stop_event = threading.Event()
        self.socket_lock = threading.Lock()
        self.current_socket: socket.socket | None = None
        self.status = BridgeStatus(
            audio_device=config.device,
            sample_rate=config.sample_rate,
            input_channels=config.input_channels,
            output_channels=config.output_channels,
            blocksize=config.blocksize,
            queue_blocks=config.queue_blocks,
        )
        self._last_status_line: str | None = None

    def set_state(self, state: str, error: str | None = None) -> None:
        if self.status.state != state:
            logging.info("Status transition: %s -> %s", self.status.state, state)
        self.status.state = state
        self.status.last_error = error

    def clear_queue(self) -> None:
        while True:
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                return

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
        self.set_state(STATE_SOCKET_CONNECTING)
        try:
            sock = socket.create_connection((self.config.host, self.config.port), timeout=self.config.socket_timeout)
            sock.settimeout(self.config.socket_timeout)
            return sock
        except OSError as exc:
            raise ConnectionError(f"socket connect failed: {exc}") from exc

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
                self.status.drop_count += 1
            except queue.Empty:
                pass
        try:
            self.audio_queue.put_nowait(raw)
            self.status.mark_received(len(raw))
        except queue.Full:
            self.status.drop_count += 1

    def _should_stop_reconnecting(self, attempts: int) -> bool:
        return not self.config.reconnect or (self.config.max_retries > 0 and attempts >= self.config.max_retries)

    def socket_receiver(self) -> None:
        bytes_per_block = self.config.blocksize * self.config.input_channels * BYTES_PER_SAMPLE
        attempts = 0

        while not self.stop_event.is_set():
            sock: socket.socket | None = None
            try:
                self.set_state(STATE_CHECKING)
                if self.config.auto_adb:
                    device = prepare_android_side(self.config.port, self.config.serial, self.config.app_start_wait)
                    self.status.device_serial = device.serial
                    self.status.transport = device.transport

                sock = self.connect_socket()
                with self.socket_lock:
                    self.current_socket = sock
                self.set_state(STATE_STREAMING)
                logging.info("Audio stream connected: %s:%s", self.config.host, self.config.port)

                while not self.stop_event.is_set():
                    raw = self.recv_exact(sock, bytes_per_block)
                    self.enqueue_block(raw)
                    if self.status.last_audio_age and self.status.last_audio_age > self.config.silent_timeout:
                        raise TimeoutError(f"silent stream timeout after {self.status.last_audio_age:.1f}s")

            except (socket.timeout, ConnectionResetError, BrokenPipeError, OSError, ConnectionError, TimeoutError) as exc:
                attempts += 1
                self.status.reconnect_count += 1
                self.set_state(STATE_RECONNECTING if self.config.reconnect else STATE_FAILED, str(exc))
                logging.warning("Audio stream interrupted: %s", exc, exc_info=logging.getLogger().isEnabledFor(logging.DEBUG))
            except Exception as exc:
                attempts += 1
                self.status.reconnect_count += 1
                self.set_state(STATE_RECONNECTING if self.config.reconnect else STATE_FAILED, str(exc))
                logging.warning("Bridge preparation failed: %s", exc, exc_info=logging.getLogger().isEnabledFor(logging.DEBUG))
            finally:
                self.close_current_socket()
                self.clear_queue()
                if self.config.auto_adb and self.status.device_serial:
                    try:
                        remove_forward(self.config.port, self.status.device_serial)
                    except Exception:
                        logging.debug("Failed to remove stale adb forward", exc_info=True)

            if self.stop_event.is_set() or self._should_stop_reconnecting(attempts):
                break
            time.sleep(self.config.reconnect_interval)

    def file_receiver(self) -> None:
        assert self.config.input_file is not None
        bytes_per_block = self.config.blocksize * self.config.input_channels * BYTES_PER_SAMPLE
        logging.info("Playing PCM from file: %s", self.config.input_file)
        self.status.transport = "file"
        self.status.device_serial = self.config.input_file
        self.set_state(STATE_STREAMING)

        with open(self.config.input_file, "rb") as file:
            while not self.stop_event.is_set():
                raw = file.read(bytes_per_block)
                if not raw:
                    file.seek(0)
                    continue
                if len(raw) < bytes_per_block:
                    raw = raw + bytes(bytes_per_block - len(raw))
                self.enqueue_block(raw)
                time.sleep(self.config.blocksize / self.config.sample_rate)

    def audio_callback(self, outdata, frames, time_info, stream_status) -> None:
        if stream_status:
            logging.debug("audio status: %s", stream_status)

        try:
            raw = self.audio_queue.get_nowait()
        except queue.Empty:
            self.status.underrun_count += 1
            outdata.fill(0)
            return

        try:
            mono = np.frombuffer(raw, dtype=np.int16)
            if mono.size != frames:
                if mono.size < frames:
                    padded = np.zeros(frames, dtype=np.int16)
                    padded[: mono.size] = mono
                    mono = padded
                else:
                    mono = mono[:frames]
            mono = apply_gain(mono, self.config.gain)
            self.status.level_dbfs = rms_dbfs(mono)
            self.status.peak_dbfs = peak_dbfs(mono)
            outdata[:] = mono_to_channels(mono, self.config.output_channels)
        except Exception as exc:
            self.status.callback_error_count += 1
            logging.warning("audio callback error: %s", exc, exc_info=logging.getLogger().isEnabledFor(logging.DEBUG))
            outdata.fill(0)

    def status_reporter(self) -> None:
        while not self.stop_event.is_set():
            time.sleep(self.config.status_interval)
            self.status.refresh(queue_fill=self.audio_queue.qsize())
            if self.status.last_audio_age is not None and self.status.last_audio_age > self.config.silent_timeout and self.status.state == STATE_STREAMING:
                self.set_state(STATE_SILENT, f"no audio for {self.status.last_audio_age:.1f}s")
                self.close_current_socket()
            line = format_status_line(self.status)
            print(line, flush=True)
            if line != self._last_status_line:
                logging.info("status %s", line)
                self._last_status_line = line

    def run(self) -> None:
        import sounddevice as sd

        receiver_target = self.file_receiver if self.config.input_file else self.socket_receiver
        receiver = threading.Thread(target=receiver_target, name="receiver", daemon=True)
        reporter = threading.Thread(target=self.status_reporter, name="status", daemon=True)
        receiver.start()
        reporter.start()

        try:
            with sd.OutputStream(
                samplerate=self.config.sample_rate,
                channels=self.config.output_channels,
                dtype=OUTPUT_DTYPE,
                device=self.config.device,
                blocksize=self.config.blocksize,
                callback=self.audio_callback,
            ):
                logging.info("Streaming to the Windows audio device. Press Ctrl+C to exit.")
                while receiver.is_alive() and not self.stop_event.is_set():
                    time.sleep(0.5)
        except KeyboardInterrupt:
            print("\nInterrupted, exiting...")
        except Exception as exc:
            self.set_state(STATE_FAILED, str(exc))
            logging.error("Audio output failed: %s", exc, exc_info=logging.getLogger().isEnabledFor(logging.DEBUG))
            raise
        finally:
            self.set_state(STATE_STOPPING)
            self.stop_event.set()
            self.close_current_socket()
            receiver.join(timeout=2.0)
            reporter.join(timeout=1.0)
            self.set_state(STATE_STOPPED)
