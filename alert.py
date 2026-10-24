"""Interruptible generated alert tones, without audio packages or session data."""
import math
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import wave


RATE = 22050


def tone(seconds):
    """Mono signed little-endian PCM, alternating pitches with soft edges."""
    samples = bytearray()
    for index in range(round(RATE * seconds)):
        position = (index / RATE) % 0.3
        frequency = 660 if int(index / RATE / 0.3) % 2 == 0 else 880
        envelope = min(1, position / 0.01, (0.3 - position) / 0.01)
        value = round(6500 * envelope * math.sin(2 * math.pi * frequency * index / RATE))
        samples.extend(struct.pack("<h", value))
    return bytes(samples)


def _u32(value):
    return b"L" + struct.pack("!I", value)


def _string(value):
    return b"N" if value is None else b"t" + value.encode() + b"\0"


class PulseTone:
    """Small local-only Pulse native v8 playback client (no cookies or TCP)."""

    def __init__(self):
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.settimeout(0.2)

    def close(self):
        try:
            # shutdown wakes a blocked send; close() alone can wait out the timeout.
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.socket.close()

    def _packet(self, payload, channel=0xffffffff):
        self.socket.sendall(struct.pack("!IIIII", len(payload), channel, 0, 0, 0) + payload)

    def _read(self, size):
        result = bytearray()
        while len(result) < size:
            chunk = self.socket.recv(size - len(result))
            if not chunk:
                raise OSError("Pulse server closed the connection")
            result.extend(chunk)
        return bytes(result)

    def _reply(self, tag):
        while True:
            size, channel, _, _, _ = struct.unpack("!IIIII", self._read(20))
            if size > 65536:
                raise OSError("Oversized Pulse reply")
            payload = self._read(size)
            if channel == 0xffffffff and payload[:1] == b"L" and payload[5:6] == b"L":
                command = struct.unpack("!I", payload[1:5])[0]
                reply_tag = struct.unpack("!I", payload[6:10])[0]
                if reply_tag == tag:
                    if command != 2:
                        raise OSError(f"Pulse command rejected: {payload.hex()}")
                    return payload[10:]

    def connect(self):
        server = os.environ.get("PULSE_SERVER")
        if server:
            path = server.removeprefix("unix:")
            if not path.startswith("/"):
                raise OSError("Only local Unix Pulse sockets are supported")
        else:
            runtime = os.environ.get("XDG_RUNTIME_DIR")
            if not runtime:
                raise OSError("No local Pulse socket configured")
            path = os.path.join(runtime, "pulse", "native")
        self.socket.connect(path)
        # Protocol v8 avoids SHM, properties and newer optional stream fields.
        self._packet(_u32(8) + _u32(1) + _u32(8) + b"x" + struct.pack("!I", 256) + bytes(256))
        self._reply(1)
        self._packet(_u32(9) + _u32(3) + _string("Pomodoro Focus"))
        self._reply(3)
        sample_spec = b"a" + bytes((3, 1)) + struct.pack("!I", RATE)
        channel_map = b"m\x01\x00"
        volume = b"v\x01" + struct.pack("!I", 65536)
        fields = (_string("Pomodoro alert") + sample_spec + channel_map +
                  _u32(0xffffffff) + _string(None) + _u32(65536) + b"0" +
                  _u32(4410) + _u32(0) + _u32(2204) + _u32(0) + volume)
        self._packet(_u32(3) + _u32(2) + fields)
        reply = self._reply(2)
        if reply[:1] != b"L":
            raise OSError("Missing Pulse stream channel")
        self.channel = struct.unpack("!I", reply[1:5])[0]

    def write(self, pcm):
        self._packet(pcm, self.channel)


class AlertPlayer:
    """Nonblocking start(duration)/stop() interface; failures degrade to BEL."""

    def __init__(self):
        self.cancel = threading.Event()
        self.needs_bell = False
        self.thread = None
        self.process = None
        self.pulse = None

    def start(self, duration):
        self.deadline = time.monotonic() + duration
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.cancel.set()
        if self.pulse is not None:
            self.pulse.close()
        if self.process is not None and self.process.poll() is None:
            try:
                self.process.terminate()
            except OSError:
                pass
        if self.thread is not None:
            self.thread.join(timeout=0.3)

    def _active(self):
        return not self.cancel.is_set() and time.monotonic() < self.deadline

    def _run(self):
        try:
            if sys.platform == "win32":
                # winsound does not exist on Unix; keep the import platform-local.
                import winsound
                pitch = 660
                while self._active():
                    winsound.Beep(pitch, 100)
                    pitch = 880 if pitch == 660 else 660
            elif sys.platform == "darwin":
                self._mac()
            else:
                command = next((name for name in ("paplay", "pw-play", "aplay")
                                if shutil.which(name)), None)
                if command:
                    self._command(command)
                else:
                    self._native()
        except Exception:
            # The UI thread owns curses. Signal it instead of beeping here.
            if self._active():
                self.needs_bell = True

    def _native(self):
        self.pulse = PulseTone()
        try:
            self.pulse.connect()
            pattern = tone(0.6)
            chunks = [pattern[i:i + 4410] for i in range(0, len(pattern), 4410)]
            index = 0
            while self._active():
                self.pulse.write(chunks[index % len(chunks)])
                index += 1
                self.cancel.wait(min(0.1, max(0, self.deadline - time.monotonic())))
        finally:
            self.pulse.close()

    def _command(self, command):
        options = {
            "paplay": ["--raw", "--format=s16le", "--rate=22050", "--channels=1"],
            "pw-play": ["--raw", "--format=s16", "--rate=22050", "--channels=1", "-"],
            "aplay": ["-q", "-t", "raw", "-f", "S16_LE", "-r", "22050", "-c", "1"],
        }
        self.process = subprocess.Popen([command, *options[command]], stdin=subprocess.PIPE,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            pattern = tone(0.6)
            while self._active():
                self.process.stdin.write(pattern)
                self.process.stdin.flush()
                self.cancel.wait(min(0.6, max(0, self.deadline - time.monotonic())))
        finally:
            self._reap()

    def _mac(self):
        # afplay needs a seekable file. It contains only a generated tone, never notes.
        with tempfile.NamedTemporaryFile(suffix=".wav") as audio:
            with wave.open(audio, "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(RATE)
                output.writeframes(tone(max(0, self.deadline - time.monotonic())))
            audio.flush()
            self.process = subprocess.Popen(["/usr/bin/afplay", audio.name],
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                while self._active():
                    if self.process.poll() is not None:
                        raise OSError("afplay stopped before the alert deadline")
                    self.cancel.wait(0.05)
            finally:
                self._reap()

    def _reap(self):
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        if self.process.stdin is not None:
            self.process.stdin.close()

