"""Portable probe contracts; these do not claim Windows backend coverage."""
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_history
from test_ui import TerminalSurface


class ExerciseScreen(TerminalSurface):
    """Recording drawing surface with a checked, single-key backend queue."""

    def __init__(self):
        super().__init__(24, 80)
        self.pending = []
        self.reads = 0

    def instr(self, row, column):
        return "".join(self.cells[row][column:]).encode("utf-8")

    def inch(self, row, column):
        return self.attributes.get((row, column), 0) | (ord(self.cells[row][column]) & 0xff)

    def ungetch(self, key):
        assert not self.pending, "previous scripted key was not consumed"
        self.pending.append(key)

    def get_wch(self):
        assert len(self.pending) == 1, "read without scripted input"
        self.reads += 1
        key = self.pending.pop()
        return chr(key) if key < 256 else key

    def keypad(self, enabled):
        assert enabled is True

    def timeout(self, delay):
        assert delay == -1

    def refresh(self):
        pass

SCRIPT = Path(__file__).parent / ".github/scripts/windows_console_smoke.py"


def load_probe():
    spec = importlib.util.spec_from_file_location("windows_console_smoke", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WindowsProbeTests(unittest.TestCase):
    def test_exercise_recording_screen_runs_both_languages(self):
        import ui

        probe = load_probe()
        screen = ExerciseScreen()
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, XDG_DATA_HOME=directory), \
                patch.object(probe.curses, "has_colors", return_value=False), \
                patch.object(probe.curses, "curs_set"), \
                patch.object(probe.curses, "ungetch", side_effect=screen.ungetch), \
                patch.object(ui, "ACCENT", ui.ACCENT), \
                patch.object(ui, "ACTIVITY_COLORS", ui.ACTIVITY_COLORS):
            checks = probe.exercise(screen)
        self.assertEqual([check["language"] for check in checks], ["en", "es"])
        self.assertEqual([check["steps"] for check in checks], [14, 14])
        self.assertEqual(screen.reads, 28)
        self.assertEqual(screen.pending, [])

    @unittest.skipUnless(os.name == "posix", "requires a POSIX ncurses PTY")
    def test_exercise_real_ncurses_pty_runs_both_languages(self):
        import errno
        import fcntl
        import pty
        import select
        import struct
        import termios
        import time

        child_script = """
import curses
import importlib.util
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
sys.path.insert(0, str(path.resolve().parents[2]))
spec = importlib.util.spec_from_file_location("probe", path)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
checks = curses.wrapper(probe.exercise)
Path(sys.argv[2]).write_text(json.dumps(checks), encoding="utf-8")
"""
        with tempfile.TemporaryDirectory() as directory:
            result = Path(directory) / "checks.json"
            environment = dict(os.environ, XDG_DATA_HOME=directory,
                               TERM="xterm-256color", LANG="C.UTF-8", LC_ALL="C.UTF-8",
                               PYTHONDONTWRITEBYTECODE="1")
            master, slave = pty.openpty()
            child = None
            try:
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
                child = subprocess.Popen(
                    [sys.executable, "-c", child_script, str(SCRIPT.resolve()), str(result)],
                    stdin=slave, stdout=slave, stderr=subprocess.PIPE, env=environment)
                os.close(slave)
                slave = None
                output, errors = bytearray(), bytearray()
                streams = {master: output, child.stderr.fileno(): errors}
                deadline = time.monotonic() + 10
                while streams:
                    remaining = deadline - time.monotonic()
                    self.assertGreater(remaining, 0, "ncurses exercise timed out")
                    ready, _, _ = select.select(list(streams), [], [], remaining)
                    self.assertTrue(ready, "ncurses exercise timed out")
                    for descriptor in ready:
                        try:
                            chunk = os.read(descriptor, 65536)
                        except OSError as error:
                            if descriptor != master or error.errno != errno.EIO:
                                raise
                            chunk = b""  # Linux PTYs signal slave closure with EIO.
                        if chunk:
                            streams[descriptor].extend(chunk)
                        else:
                            del streams[descriptor]
                code = child.wait(timeout=max(0.01, deadline - time.monotonic()))
                self.assertEqual(code, 0, errors.decode("utf-8"))
                self.assertEqual(errors, b"")
                self.assertTrue(output, "ncurses emitted no terminal output")
                output.decode("utf-8")  # Unreadable terminal output must fail too.
                checks = json.loads(result.read_text(encoding="utf-8"))
                self.assertEqual([check["language"] for check in checks], ["en", "es"])
                self.assertEqual([check["steps"] for check in checks], [14, 14])
                self.assertEqual([check["palette"] for check in checks], ["color", "color"])
            finally:
                if child is not None:
                    if child.poll() is None:
                        child.kill()
                    child.wait()
                    child.stderr.close()
                os.close(master)
                if slave is not None:
                    os.close(slave)

    def test_fixture_connections_are_closed_after_transactions(self):
        connect = sqlite3.connect
        for name in ("test_corrupt_incompatible_and_unwritable_are_not_reset",
                     "test_invalid_existing_rows_are_not_extended_or_rewritten"):
            connections = []

            def track(*args, **kwargs):
                connection = connect(*args, **kwargs)
                connections.append(connection)
                return connection

            case = test_history.HistoryTests(name)
            result = unittest.TestResult()
            try:
                with patch("sqlite3.connect", side_effect=track):
                    case.run(result)
                self.assertEqual(result.errors, [])
                self.assertEqual(result.failures, [])
                for connection in connections:
                    with self.assertRaises(sqlite3.ProgrammingError):
                        connection.execute("SELECT 1")
            finally:
                for connection in connections:
                    connection.close()

    def test_exhausted_script_fails_without_reading_or_injecting(self):
        probe = load_probe()
        with patch.object(probe.curses, "ungetch") as inject:
            screen = probe.ScriptedScreen(object(), [])
            with self.assertRaisesRegex(AssertionError, "input script exhausted"):
                screen.get_wch()
            inject.assert_not_called()

    def test_supported_injection_checks_observed_rendering_and_decoded_key(self):
        probe = load_probe()
        from unittest.mock import Mock
        real = Mock()
        real.get_wch.return_value = "q"
        check = Mock()
        screen = probe.ScriptedScreen(real, [("q", check)])
        with patch.object(probe.curses, "ungetch") as inject:
            self.assertEqual(screen.get_wch(), "q")
            inject.assert_called_once_with(ord("q"))
        check.assert_called_once_with(real)
        screen.refresh()
        real.refresh.assert_called_once_with()
        screen.assert_finished(1)

    def test_render_or_decode_failure_and_premature_exit_are_not_success(self):
        probe = load_probe()
        from unittest.mock import Mock
        real = Mock()
        real.get_wch.return_value = "x"
        check = Mock(side_effect=AssertionError("render failed"))
        screen = probe.ScriptedScreen(real, [("q", check)])
        with patch.object(probe.curses, "ungetch") as inject:
            with self.assertRaisesRegex(AssertionError, "render failed"):
                screen.get_wch()
            inject.assert_not_called()
        screen = probe.ScriptedScreen(real, [("q", lambda window: None)])
        with self.assertRaisesRegex(AssertionError, "before consuming"):
            screen.assert_finished(1)
        with patch.object(probe.curses, "ungetch"):
            with self.assertRaisesRegex(AssertionError, "decoding mismatch"):
                screen.get_wch()

    def test_supervisor_requires_successful_exit_and_valid_result(self):
        probe = load_probe()
        cases = [
            ("", "missing result"),
            ("p.write_text('not json')", "invalid result"),
            ("p.write_text('{\"ok\": false}')", "child reported failure"),
            ("p.write_text('{\"ok\": true}'); raise SystemExit(7)", "exit 7"),
            ("raise AssertionError('synthetic child failure')", "exit 1"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            for index, (body, message) in enumerate(cases):
                with self.subTest(message=message):
                    result = Path(directory) / f"{index}.json"
                    command = [sys.executable, "-c",
                               f"from pathlib import Path; p=Path({str(result)!r}); {body}"]
                    with self.assertRaisesRegex(RuntimeError, message):
                        probe.supervise(command, result, stderr=subprocess.DEVNULL)
            result = Path(directory) / "success.json"
            command = [sys.executable, "-c",
                       f"from pathlib import Path; Path({str(result)!r}).write_text('{{\"ok\": true}}')"]
            self.assertEqual(probe.supervise(command, result), {"ok": True})

    def test_timeout_kills_and_reaps_child(self):
        probe = load_probe()
        with patch.object(probe.subprocess, "Popen") as popen:
            child = popen.return_value.__enter__.return_value
            child.wait.side_effect = [subprocess.TimeoutExpired("probe", 20), -9]
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                probe.supervise(["probe"], Path("unused"))
            child.kill.assert_called_once_with()
            self.assertEqual(child.wait.call_count, 2)

    @unittest.skipIf(sys.platform == "win32", "Linux unavailability contract")
    def test_non_windows_cli_is_explicitly_unavailable(self):
        result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True,
                                timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "Windows console smoke unavailable: requires Windows.\n")
