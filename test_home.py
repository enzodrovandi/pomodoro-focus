"""Home routing through the public app and a recording 80x24 terminal."""
import os
import tempfile
import unittest
from unittest.mock import patch

from focus import app
from history import HistoryStore
from i18n import translator
from test_ui import TerminalSurface


class HomeSurface(TerminalSurface):
    def __init__(self, keys):
        super().__init__(24, 80)
        self.keys = iter(keys)
        self.frames = []

    def refresh(self):
        self.frames.append(self.contents())

    def get_wch(self):
        return next(self.keys)

    def keypad(self, enabled):
        pass

    def timeout(self, delay):
        pass


class HomeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        environment = patch.dict(os.environ, {"XDG_DATA_HOME": self.temp.name})
        environment.start()
        self.addCleanup(environment.stop)

    def run_app(self, language, keys, direct=False):
        screen = HomeSurface(keys)
        with patch("focus.configure_palette"), patch("focus.curses.curs_set"):
            self.assertIsNone(app(screen, translator(language), direct))
        return screen.frames

    def assert_empty_history(self):
        self.assertEqual(HistoryStore().records(), [])

    def test_home_labels_and_separate_exit_are_visible_in_both_languages(self):
        for language, labels in [("es", ("INICIO", "1: Nueva sesión", "2: Historial y análisis", "q: salir")),
                                 ("en", ("HOME", "1: New session", "2: History and analysis", "q: exit"))]:
            with self.subTest(language=language):
                frames = self.run_app(language, "q")
                self.assertEqual(len(frames), 1)
                for label in labels:
                    self.assertIn(label, frames[0])
                self.assertLess(frames[0].index(labels[2]), frames[0].index(labels[3]))
                self.assertNotIn("…", frames[0])
                self.assert_empty_history()

    def test_history_and_analysis_return_home_without_preparing_or_saving(self):
        for language in ("es", "en"):
            for back in ("q", "\x1b"):
                with self.subTest(language=language, back=back):
                    frames = self.run_app(language, ["2", "w", "c", back, "q"])
                    self.assertEqual(frames[0], frames[-1])
                    self.assertIn("Todavía no hay sesiones" if language == "es" else "No sessions yet", frames[1])
                    self.assertIn("RESUMEN SEMANAL" if language == "es" else "WEEKLY SUMMARY", frames[2])
                    self.assertIn("CALENDARIO DE ACTIVIDAD" if language == "es" else "ACTIVITY CALENDAR", frames[3])
                    self.assertEqual(len(frames), 5)
                    self.assert_empty_history()

    def test_cancel_each_unstarted_preparation_returns_home(self):
        for language in ("es", "en"):
            for preparation in (["1"], ["1", *"Goal\n"], ["1", *"Goal\nStep\n"]):
                with self.subTest(language=language, preparation=preparation):
                    frames = self.run_app(language, [*preparation, "\x1b", "q"])
                    self.assertEqual(frames[0], frames[-1])
                    self.assertIn("PREPARÁ TU SESIÓN" if language == "es" else "PREPARE YOUR SESSION", frames[1])
                    self.assert_empty_history()

    def test_duration_history_returns_to_prepared_goal_and_q_still_exits(self):
        for language in ("es", "en"):
            with self.subTest(language=language):
                frames = self.run_app(language, ["1", *"Goal\nStep\n", "h", "q", "q"])
                title = "ELEGÍ UN BLOQUE" if language == "es" else "CHOOSE A BLOCK"
                duration_frames = [frame for frame in frames if title in frame]
                self.assertEqual(len(duration_frames), 2)
                self.assertEqual(*duration_frames)
                self.assert_empty_history()

    def test_finished_summary_can_return_home_without_resaving(self):
        for language in ("es", "en"):
            with self.subTest(language=language), tempfile.TemporaryDirectory() as data, \
                    patch.dict(os.environ, {"XDG_DATA_HOME": data}):
                frames = self.run_app(language, ["1", *"Capacitors\nDraw circuit\n",
                                                "1", "f", "\n", "\n", "s", "m",
                                                "2", "\n", "q", "q", "q"])
                self.assertEqual(frames[0], frames[-1])
                summary = "SESIÓN COMPLETA" if language == "es" else "SESSION COMPLETE"
                hint = "m: inicio" if language == "es" else "m: home"
                summaries = [frame for frame in frames if summary in frame]
                self.assertTrue(summaries)
                self.assertIn(hint, summaries[0])
                detail = "DETALLE DE SESIÓN" if language == "es" else "SESSION DETAIL"
                self.assertTrue(any(detail in frame and "Capacitors" in frame for frame in frames))
                items = HistoryStore().records()
                self.assertEqual(len(items), 1)
                self.assertEqual(items[0].objective, "Capacitors")
                self.assertEqual(items[0].first_step, "Draw circuit")
                self.assertEqual(items[0].status, "early")
                self.assertEqual((items[0].progress, items[0].next_step), ("", ""))

    def test_direct_history_still_exits_without_showing_home(self):
        for language in ("es", "en"):
            with self.subTest(language=language):
                frames = self.run_app(language, "q", direct=True)
                self.assertEqual(len(frames), 1)
                self.assertIn("Todavía no hay sesiones" if language == "es" else "No sessions yet", frames[0])
                self.assert_empty_history()


if __name__ == "__main__":
    unittest.main()
