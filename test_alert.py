"""Timer alerts through the public timer, editor and application paths."""
import curses
import unittest
from unittest.mock import patch

from focus import Session, app, run_timer
from i18n import translator
from test_ui import TerminalSurface


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Player:
    def __init__(self, clock, fail=False):
        self.clock, self.fail = clock, fail
        self.starts, self.stops = [], []

    def start(self, duration):
        self.starts.append((self.clock(), duration))
        if self.fail:
            raise OSError("Audio unavailable")

    def stop(self):
        self.stops.append(self.clock())


class AlertSurface(TerminalSurface):
    def __init__(self, clock, events=()):
        super().__init__(24, 100)
        self.clock = clock
        self.events = iter(events)
        self.frames, self.delays = [], []
        self.delay = -1

    def timeout(self, delay):
        self.delay = delay
        self.delays.append(delay)

    def refresh(self):
        self.frames.append(self.contents())

    def keypad(self, enabled):
        pass

    def get_wch(self):
        advance, key = next(self.events, (self.delay / 1000, None))
        if advance < 0:
            raise AssertionError("Editor blocked instead of checking expiry")
        self.clock.now += advance
        if key is None:
            raise curses.error()
        return key


class TimerAlertTests(unittest.TestCase):
    def setup_timer(self, events=(), fail=False):
        clock = Clock()
        session = Session("Goal", "Step", 5, clock=clock)
        return clock, session, AlertSurface(clock, events), Player(clock, fail)

    def test_natural_focus_and_break_expiry_alert_once_with_bilingual_notice(self):
        labels = {
            "en": ("FOCUS TIME IS UP", "BREAK TIME IS UP", "Press any key to stop the alert."),
            "es": ("TERMINÓ EL TIEMPO DE CONCENTRACIÓN", "TERMINÓ EL DESCANSO", "Presioná cualquier tecla para detener la alerta."),
        }
        for language, (focus_text, break_text, hint) in labels.items():
            for phase, text, final, focused in (("focus", focus_text, "reflection", 300),
                                               ("break", break_text, "done", 40)):
                with self.subTest(language=language, phase=phase):
                    clock, session, screen, player = self.setup_timer([(0, "x")])
                    if phase == "break":
                        clock.now = 40
                        session.finish()
                        session.start_break()
                    clock.now += 300
                    start = clock.now
                    run_timer(screen, session, translator(language), player=player)
                    self.assertEqual(player.starts, [(start, 10)])
                    self.assertEqual(player.stops, [start])
                    self.assertEqual(session.phase, final)
                    self.assertEqual(session.focus_seconds, focused)
                    self.assertIn(text, screen.frames[-1])
                    self.assertIn(hint, screen.frames[-1])
                    self.assertEqual(screen.delays[-1], -1)
                    run_timer(screen, session, translator(language), player=player)
                    self.assertEqual(len(player.starts), 1)

    def test_key_interrupts_and_no_key_waits_exactly_ten_seconds_even_without_audio(self):
        for events, elapsed, fail in (([(1.25, curses.KEY_LEFT)], 1.25, False),
                                      ([], 10, False), ([], 10, True)):
            with self.subTest(elapsed=elapsed, fail=fail):
                clock, session, screen, player = self.setup_timer(events, fail)
                clock.now = 300
                run_timer(screen, session, translator("en"), player=player)
                self.assertEqual(player.starts, [(300, 10)])
                self.assertAlmostEqual(player.stops[0], 300 + elapsed)
                self.assertEqual(len(player.stops), 1)
                self.assertEqual(session.phase, "reflection")
                self.assertEqual(session.focus_seconds, 300)
                self.assertIn("FOCUS TIME IS UP", screen.frames[-1])

    def test_distraction_expiry_keeps_typed_note_and_leaves_editor(self):
        clock, session, screen, player = self.setup_timer(
            [(0, "d"), (1, "N"), (1, "o"), (298, None), (0, "x")])
        run_timer(screen, session, translator("en"), player=player)
        self.assertEqual(session.distractions, ["No"])
        self.assertEqual(session.phase, "reflection")
        self.assertEqual(session.focus_seconds, 300)
        self.assertEqual(player.starts, [(300, 10)])
        self.assertEqual(player.stops, [300])
        self.assertIn("FOCUS TIME IS UP", screen.frames[-1])

    def test_early_finish_and_confirmed_leave_never_alert_or_count_paused_time(self):
        for events in ([(40, "f")], [(40, "q"), (500, "y")],
                       [(40, "q"), (500, "n"), (10, "f")]):
            with self.subTest(events=events):
                clock, session, screen, player = self.setup_timer(events)
                run_timer(screen, session, translator("en"), player=player)
                self.assertEqual(player.starts, [])
                self.assertEqual(player.stops, [])
                self.assertEqual(session.phase, "reflection")
                self.assertEqual(session.focus_seconds, 50 if events[-1] == (10, "f") else 40)

    def test_skipped_break_keeps_existing_summary_without_alert(self):
        clock = Clock()
        screen = AlertSurface(clock, [(0, k) for k in "1Goal\nStep\n1f\n\nsq"])
        with patch("focus.configure_palette"), patch("focus.curses.curs_set"), \
                patch("focus.HistoryStore"), patch("focus.save_session"), \
                patch("focus.show_alert") as alert:
            app(screen, translator("en"))
        alert.assert_not_called()
        self.assertIn("SESSION COMPLETE", screen.frames[-1])
        self.assertIn("Focused time: 0m 0s", screen.frames[-1])


if __name__ == "__main__":
    unittest.main()
