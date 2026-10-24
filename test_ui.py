"""Rendering checks through a recording terminal surface."""
import unittest
from unittest.mock import patch

import ui
from focus import prompt
from i18n import translator


class TerminalSurface:
    """A fixed-width character grid exposing the curses drawing interface."""

    def __init__(self, height=30, width=100):
        self.height, self.width = height, width
        self.encoding = "utf-8"
        self.erase()

    def getmaxyx(self):
        return self.height, self.width

    def erase(self):
        self.cells = [[" "] * self.width for _ in range(self.height)]
        self.attributes = {}

    def addnstr(self, row, column, text, count, attr=0):
        assert 0 <= row < self.height
        assert 0 <= column < self.width
        for offset, character in enumerate(text[:count]):
            assert column + offset < self.width
            self.cells[row][column + offset] = character
            self.attributes[row, column + offset] = attr

    def contents(self):
        return "\n".join("".join(row) for row in self.cells)


class PresentationTests(unittest.TestCase):
    def test_panel_is_centered_and_uses_a_quiet_hierarchy(self):
        screen = TerminalSurface()
        ui.frame(screen, "UNA COSA A LA VEZ")
        rows = [i for i, line in enumerate(screen.cells) if "╭" in line]
        self.assertEqual(rows, [4])
        self.assertEqual(screen.cells[4].index("╭"), 11)
        self.assertIn("POMODORO FOCUS", screen.contents())
        self.assertIn("UNA COSA A LA VEZ", screen.contents())

    def test_countdown_is_centered_and_progress_is_bounded(self):
        screen = TerminalSurface()
        ui.frame(screen, "FOCUS")
        ui.put(screen, 10, "18:42", align="center")
        self.assertIn("18:42", "".join(screen.cells[14]))
        self.assertEqual(screen.cells[14].index("1"), 47)
        for remaining, filled in [(300, 0), (150, 12), (0, 24), (-10, 24), (400, 0)]:
            with self.subTest(remaining=remaining):
                ui.progress(screen, remaining, 300)
                line = "".join(screen.cells[15])
                self.assertEqual(line.count("━"), filled)
                self.assertEqual(line.count("─"), 24 - filled)

    def test_small_and_large_terminals_keep_controls_visible(self):
        for height, width in [(24, 80), (20, 60), (12, 35), (6, 12), (40, 160)]:
            with self.subTest(size=(height, width)):
                screen = TerminalSurface(height, width)
                ui.frame(screen, "PREPARÁ TU SESIÓN")
                ui.put(screen, 5, "A long objective " * 20)
                ui.footer(screen, "Enter: confirmar | Esc: cancelar | Retroceso: borrar")
                self.assertIn("Enter:", screen.contents())
                self.assertIn("╰", screen.contents())

    def test_long_input_keeps_the_latest_characters_and_caret_visible(self):
        screen = TerminalSurface(24, 80)
        value = "x" * 100 + "FINAL"
        screen.get_wch = iter([*value, "\n"]).__next__
        screen.refresh = lambda: None
        self.assertEqual(prompt(screen, "TITLE", "Label", translator("en")), value)
        self.assertIn("FINAL_", screen.contents())

    def test_calendar_has_gray_and_three_green_levels_with_visible_selection(self):
        with patch("ui.curses.has_colors", return_value=True), \
                patch("ui.curses.use_default_colors"), \
                patch("ui.curses.COLORS", 256, create=True), \
                patch("ui.curses.init_pair") as init_pair, \
                patch("ui.curses.color_pair", side_effect=lambda pair: pair << 8):
            ui.configure_palette()
            screen = TerminalSurface(24, 80)
            ui.frame(screen, "CALENDAR")
            for level in range(4):
                ui.activity_cell(screen, 7, 4 + level * 3, level, selected=level == 2)
            ui.activity_legend(screen, 16, "[ ] selected")
            self.assertIn(" ■  ■ [■] ■ ", screen.contents())
            attrs = [screen.attributes[8, 3 + 4 + level * 3 + 1] for level in range(4)]
            self.assertEqual(len(set(attrs)), 4)
            for pair, color in enumerate((240, 28, 34, 40), 2):
                self.assertIn(unittest.mock.call(pair, color, -1), init_pair.call_args_list)
            for label in ("0", "<25m", "25-49m", "50m+", "[ ] selected"):
                self.assertIn(label, screen.contents())
        with patch("ui.curses.has_colors", return_value=False):
            ui.configure_palette()

    def test_calendar_monochrome_levels_and_palette_failure_remain_readable(self):
        for enabled in (False, True):
            with self.subTest(colors=enabled), \
                    patch("ui.curses.has_colors", return_value=enabled), \
                    patch("ui.curses.use_default_colors", side_effect=ui.curses.error), \
                    patch("ui.curses.init_pair") as init_pair:
                ui.configure_palette()
                screen = TerminalSurface(24, 80)
                ui.frame(screen, "CALENDAR")
                for level in range(4):
                    ui.activity_cell(screen, 7, level * 3, level, selected=level == 1)
                ui.activity_legend(screen, 16, "[ ] selección")
                self.assertIn(" □ [░] ▒  █ ", screen.contents())
                self.assertIn("[ ] selección", screen.contents())
                init_pair.assert_not_called()

    def test_monochrome_fallback_does_not_require_color_support(self):
        with patch("ui.curses.has_colors", return_value=False), \
                patch("ui.curses.init_pair") as init_pair:
            ui.configure_palette()
            init_pair.assert_not_called()
        screen = TerminalSurface()
        ui.frame(screen, "FOCUS")
        ui.put(screen, 10, "25:00", align="center")
        self.assertIn("25:00", screen.contents())


if __name__ == "__main__":
    unittest.main()
