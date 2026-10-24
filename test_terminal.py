"""Exercise the real CLI in a pseudo-terminal, without changing system state."""
import errno
import fcntl
import os
from pathlib import Path
import pty
import select
import struct
import subprocess
import sys
import termios
import time
import tempfile
import unittest
from unittest.mock import patch

from history import HistoryStore


ROOT = Path(__file__).resolve().parent


class TerminalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        environment = patch.dict(os.environ, {"XDG_DATA_HOME": self.temp.name})
        environment.start()
        self.addCleanup(environment.stop)

    def test_help_and_noninteractive_error(self):
        help_result = subprocess.run([sys.executable, "focus.py", "--lang", "en", "--help"], cwd=ROOT,
                                     text=True, capture_output=True)
        self.assertEqual(help_result.returncode, 0)
        self.assertIn("Interactive focus sessions", help_result.stdout)
        self.assertEqual(help_result.stderr, "")
        result = subprocess.run([sys.executable, "focus.py", "--lang", "en"], cwd=ROOT,
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "Pomodoro Focus needs an interactive terminal. Run: python3 focus.py\n")

    def test_english_help_accepts_either_argument_order_and_existing_abbreviation(self):
        for flags in (["--help", "--lang", "en"], ["--lang", "en", "--he"],
                      ["--lang", "en", "--h"]):
            with self.subTest(flags=flags):
                result = subprocess.run([sys.executable, "focus.py", *flags], cwd=ROOT,
                                        text=True, capture_output=True)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stderr, "")
                self.assertIn("Interactive focus sessions", result.stdout)
                self.assertIn("options:", result.stdout)

    def test_spanish_is_default_and_explicit(self):
        for flags in ([], ["--lang", "es"]):
            with self.subTest(flags=flags):
                help_result = subprocess.run([sys.executable, "focus.py", *flags, "--help"],
                                             cwd=ROOT, text=True, capture_output=True)
                self.assertEqual(help_result.returncode, 0)
                self.assertEqual(help_result.stderr, "")
                self.assertIn("Sesiones de concentración", help_result.stdout)
                self.assertIn("--lang", help_result.stdout)
                self.assertIn("opciones:", help_result.stdout)
                result = subprocess.run([sys.executable, "focus.py", *flags],
                                        cwd=ROOT, text=True, capture_output=True)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, "")
                self.assertEqual(result.stderr, "Pomodoro Focus necesita una terminal interactiva. Ejecutá: python3 focus.py\n")

    def test_language_validation(self):
        for flags, expected in [(["--lang", "fr"], "Idioma inválido: fr. Usá es o en."),
                                (["--lang"], "--lang requiere un valor: es o en.")]:
            with self.subTest(flags=flags):
                result = subprocess.run([sys.executable, "focus.py", *flags],
                                        cwd=ROOT, text=True, capture_output=True)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn(expected, result.stderr)

    def test_real_interactive_session(self):
        self.run_interactive_session("en", ["--lang", "en"])

    def test_spanish_interactive_session(self):
        self.run_interactive_session("es", [])

    def test_interrupt_saves_without_extra_prompts(self):
        self.run_interactive_session("en", ["--lang", "en"], interrupt=True)

    def test_new_block_does_not_resave_previous_block(self):
        self.run_interactive_session("en", ["--lang", "en"], new_block=True)

    def test_failed_interrupt_reports_error(self):
        path = Path(self.temp.name) / "pomodoro-focus"
        path.mkdir()
        (path / "history.sqlite3").write_bytes(b"corrupt")
        self.run_interactive_session("en", ["--lang", "en"], interrupt=True, failed_store=True)
        self.assertEqual((path / "history.sqlite3").read_bytes(), b"corrupt")

    def test_direct_history_in_both_languages(self):
        for language, flags in [("en", ["--lang", "en"]), ("es", [])]:
            with self.subTest(language=language):
                self.run_interactive_session(language, flags + ["--history"], history_only=True)

    def test_home_history_and_cancel_return_in_both_languages(self):
        for language, flags in [("en", ["--lang", "en"]), ("es", [])]:
            with self.subTest(language=language):
                # Keep each language's full session in its own data directory.
                with tempfile.TemporaryDirectory() as data, patch.dict(os.environ, {"XDG_DATA_HOME": data}):
                    self.run_interactive_session(language, flags, browse_home=True)

    def test_failed_save_keeps_summary_usable(self):
        path = Path(self.temp.name) / "pomodoro-focus"
        path.mkdir()
        (path / "history.sqlite3").write_bytes(b"corrupt")
        self.run_interactive_session("en", ["--lang", "en"], failed_store=True)
        self.assertEqual((path / "history.sqlite3").read_bytes(), b"corrupt")

    def run_interactive_session(self, language, flags, interrupt=False, history_only=False, failed_store=False, new_block=False, browse_home=False):
        messages = {
            "en": ["What do you want", "first concrete step", "CHOOSE A BLOCK",
                   "ONE THING AT A TIME", "PAUSED", "No rush", "PARK A DISTRACTION",
                   "What did you accomplish", "LEAVE A STARTING POINT", "A BREAK IS PART",
                   "REST", "scroll summary", "LEAVE THIS BLOCK?"],
            "es": ["¿Qué querés lograr?", "primer paso concreto", "ELEGÍ UN BLOQUE",
                   "UNA COSA A LA VEZ", "EN PAUSA", "Sin apuro", "ANOTÁ UNA DISTRACCIÓN",
                   "¿Qué avanzaste?", "DEJÁ UN PUNTO DE PARTIDA", "s: omitir descanso",
                   "Espacio: pausa/seguir", "recorrer resumen", "¿QUERÉS CERRAR ESTE BLOQUE?"],
        }[language]
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        process = subprocess.Popen([sys.executable, "focus.py", *flags], cwd=ROOT,
                                   stdin=slave, stdout=slave, stderr=slave,
                                   env={**os.environ, "TERM": "xterm-256color", "LC_ALL": "C.UTF-8"})
        os.close(slave)
        transcript = bytearray()

        def expect(text):
            deadline = time.monotonic() + 3
            output = bytearray()
            while time.monotonic() < deadline:
                if select.select([master], [], [], max(0, deadline - time.monotonic()))[0]:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError as error:
                        if error.errno == errno.EIO:
                            break
                        raise
                    output.extend(chunk)
                    transcript.extend(chunk)
                    if text.encode() in output:
                        return
            self.fail(f"Missing terminal output {text!r}: {output!r}")

        try:
            if history_only:
                expect("No sessions yet" if language == "en" else "Todavía no hay sesiones")
                os.write(master, b"w")
                expect("This week:" if language == "en" else "Esta semana:")
                os.write(master, b"c")
                expect("[ ] selected" if language == "en" else "[ ] selección")
                os.write(master, b"q")
                self.assertEqual(process.wait(timeout=3), 0)
                return
            home_label = "2: History and analysis" if language == "en" else "2: Historial y análisis"
            expect(home_label)
            if browse_home:
                for back in (b"q", b"\x1b"):
                    os.write(master, b"2")
                    expect("No sessions yet" if language == "en" else "Todavía no hay sesiones")
                    self.assertEqual(HistoryStore().records(), [])
                    os.write(master, back)
                    expect(home_label)
                # Cancel before a block exists, then choose New session again.
                os.write(master, b"1")
                expect(messages[0])
                os.write(master, b"\x1b")
                expect(home_label)
                self.assertEqual(HistoryStore().records(), [])
            os.write(master, b"1")
            expect(messages[0])
            os.write(master, b"Solve capacitors\n")
            expect(messages[1])
            os.write(master, b"Draw the circuit\n")
            expect(messages[2])
            if not failed_store:
                os.write(master, b"h")
                expect("No sessions yet" if language == "en" else "Todavía no hay sesiones")
                os.write(master, b"q")
                expect(messages[2])
            os.write(master, b"1")
            expect(messages[3])
            if interrupt:
                process.send_signal(__import__("signal").SIGINT)
                if failed_store:
                    expect("Interrupted block could not be saved.")
                    self.assertEqual(process.wait(timeout=3), 1)
                    return
                self.assertEqual(process.wait(timeout=3), 0)
                items = HistoryStore().records()
                self.assertEqual(len(items), 1)
                self.assertEqual(items[0].status, "early")
                self.assertEqual(items[0].progress, "")
                return
            os.write(master, b" ")
            expect(messages[4])
            os.write(master, b" ")
            expect(messages[5])
            os.write(master, b"d")
            expect(messages[6])
            os.write(master, b"Reply later\n")
            expect(messages[3])
            os.write(master, b"q")
            expect(messages[12])
            os.write(master, b"n")
            expect(messages[3])
            os.write(master, b"q")
            expect(messages[12])
            os.write(master, b"y")
            expect(messages[7])
            os.write(master, b"Solved one\n")
            expect(messages[8])
            os.write(master, b"Exercise two\n")
            expect(messages[9])
            if not failed_store:
                items = HistoryStore().records()
                self.assertEqual(len(items), 1)  # Saved before the break.
                self.assertEqual(items[0].progress, "Solved one")
                self.assertEqual(items[0].next_step, "Exercise two")
                self.assertEqual(items[0].status, "early")
            else:
                # The title may arrive in a separate PTY chunk from its body.
                if b"History not saved" not in transcript:
                    expect("History not saved")
                self.assertIn(b"History not saved", transcript)
            os.write(master, b"b")
            expect(messages[10])
            os.write(master, b"f")
            expect(messages[11])
            self.assertIn("╭".encode(), transcript)
            self.assertIn("╰".encode(), transcript)
            self.assertIn(b"Reply later", transcript)
            self.assertIn(b"Solved one", transcript)
            self.assertIn(b"Exercise two", transcript)
            if not failed_store:
                os.write(master, b"h")
                expect("HISTORY" if language == "en" else "HISTORIAL")
                os.write(master, b"q")
                expect(messages[11])
            if new_block:
                os.write(master, b"n")
                expect(messages[0])
                os.write(master, b"New objective\n")
                expect(messages[1])
                os.write(master, b"New first step\n")
                expect(messages[2])
                os.write(master, b"1")
                expect(messages[3])
                process.send_signal(__import__("signal").SIGINT)
                self.assertEqual(process.wait(timeout=3), 0)
                later = HistoryStore().records()
                self.assertEqual(len(later), 2)
                self.assertIn(items[0], later)
                return
            os.write(master, b"q")
            self.assertEqual(process.wait(timeout=3), 0)
            if not failed_store:
                self.assertEqual(HistoryStore().records(), items)
            for unwanted in (b"Rate your", b"Concentration rating", "Puntuá".encode()):
                self.assertNotIn(unwanted, transcript)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            os.close(master)


if __name__ == "__main__":
    unittest.main()
