"""History analysis and interactive views through their public interfaces."""
import curses
from datetime import date
import tempfile
from pathlib import Path
import unittest

from history import HistoryStore
from history_views import activity_days, day_records, weekly_summary, dashboard
from i18n import translator
from test_history import record
from test_ui import TerminalSurface


class HistoryViewTests(unittest.TestCase):
    def test_week_boundaries_zero_baseline_and_midnight_attribution(self):
        items = [record(started_at="2026-12-31T23:59:00-03:00"),
                 record(id="two", started_at="2027-01-04T00:01:00-03:00",
                        focus_seconds=300, status="complete")]
        summary = weekly_summary(items, date(2027, 1, 3))
        self.assertEqual(summary["start"], date(2026, 12, 28))
        self.assertEqual((summary["count"], summary["seconds"], summary["complete"], summary["early"]), (1, 90, 0, 1))
        self.assertEqual(summary["previous_seconds"], 0)
        self.assertEqual(summary["delta_seconds"], 90)
        self.assertEqual(weekly_summary(items, date(2027, 1, 4))["previous_seconds"], 90)
        self.assertEqual(day_records(items, date(2026, 12, 31)), [items[0]])
        self.assertEqual(day_records(items, date(2027, 1, 1)), [])
        cells = activity_days(items, date(2027, 1, 3))
        self.assertEqual(len(cells), 84)
        self.assertEqual(cells[0][0].weekday(), 0)
        self.assertIn((date(2026, 12, 31), 90), cells)
        self.assertEqual(cells[-1][0], date(2027, 1, 3))

    def screen(self, keys):
        screen = TerminalSurface(24, 80)
        screen.get_wch = iter(keys).__next__
        screen.pages = []
        screen.refresh = lambda: screen.pages.append(screen.contents())
        return screen

    def test_no_history_in_both_languages_and_all_views(self):
        with tempfile.TemporaryDirectory() as temp:
            store = HistoryStore(Path(temp) / "history.sqlite3")
            for lang, expected in [("en", "No sessions yet"), ("es", "Todavía no hay sesiones")]:
                screen = self.screen(["q"])
                dashboard(screen, store, translator(lang), today=date(2027, 1, 3))
                self.assertIn(expected, screen.contents())
                screen = self.screen(["w", "[", "]", "c", "q"])
                dashboard(screen, store, translator(lang), today=date(2027, 1, 3))
                self.assertIn("□ 0", screen.contents())
                self.assertIn("2027-01-03", screen.contents())

    def test_daily_selection_and_long_detail_paging(self):
        with tempfile.TemporaryDirectory() as temp:
            store = HistoryStore(Path(temp) / "history.sqlite3")
            store.append(record(objective="Long objective " * 16, progress="progress " * 100))
            screen = self.screen(["c", "h", "h", "h", "\n", "\n", "j", "k", "q", "q", "q"])
            dashboard(screen, store, translator("en"), today=date(2027, 1, 3))
            self.assertIn("2026-12-31", screen.contents())
            detail = [page for page in screen.pages if "SESSION DETAIL" in page]
            self.assertEqual(len(detail), 3)
            self.assertIn("Objective: Long objective", detail[0])
            self.assertIn("progress progress", detail[1])
            self.assertEqual(detail[0], detail[2])
            selected_list = [page for page in screen.pages if "Long objective" in page and "SESSION DETAIL" not in page]
            self.assertTrue(any("23:59" in page for page in selected_list))
            screen = self.screen(["\n", "q", "q"])
            dashboard(screen, store, translator("es"), today=date(2027, 1, 3))
            self.assertTrue(any("Objetivo:" in page and "DETALLE DE SESIÓN" in page for page in screen.pages))

    def test_zero_week_comparison_has_no_percentage_or_score(self):
        result = weekly_summary([], date(2027, 1, 4))
        for field in ("count", "seconds", "complete", "early", "previous_count", "previous_seconds", "delta_seconds"):
            self.assertEqual(result[field], 0)
        with tempfile.TemporaryDirectory() as temp:
            screen = self.screen(["w", "q"])
            dashboard(screen, HistoryStore(Path(temp) / "history.sqlite3"), translator("en"), today=date(2027, 1, 4))
            self.assertIn("Previous: 0 sessions | 0m 0s", screen.contents())
            self.assertIn("Time change: +0m 0s", screen.contents())
            self.assertNotIn("%", screen.contents())

    def test_list_arrows_match_jk_with_paging_boundaries_and_details(self):
        navigation = ["k", "j", "j", "k", "\n", "q", *(["j"] * 20), "\n", "q",
                      *(["k"] * 20), "\n", "q", "q"]
        arrows = [{"j": curses.KEY_DOWN, "k": curses.KEY_UP}.get(key, key)
                  for key in navigation]
        with tempfile.TemporaryDirectory() as temp:
            store = HistoryStore(Path(temp) / "history.sqlite3")
            for index in range(14):
                store.append(record(id=str(index), objective=f"Session {index:02d}",
                                    started_at=f"2026-12-31T00:{index:02d}:00-03:00"))
            before = store.records()
            for language in ("es", "en"):
                for daily in (False, True):
                    with self.subTest(language=language, daily=daily):
                        prefix, suffix = (["c", "\n"], ["q"]) if daily else ([], [])
                        old = self.screen([*prefix, *navigation, *suffix])
                        new = self.screen([*prefix, *arrows, *suffix])
                        for screen in (old, new):
                            dashboard(screen, store, translator(language), today=date(2026, 12, 31))
                        self.assertEqual(new.pages, old.pages)
                        title = "DETALLE DE SESIÓN" if language == "es" else "SESSION DETAIL"
                        details = [page for page in new.pages if title in page]
                        self.assertEqual(len(details), 3)
                        for page, expected in zip(details, ("Session 12", "Session 00", "Session 13")):
                            self.assertIn(expected, page)
                        self.assertIn("↑/↓", new.pages[len(prefix)])
                        self.assertEqual(store.records(), before)

    def test_empty_lists_accept_arrows_without_creating_records(self):
        with tempfile.TemporaryDirectory() as temp:
            store = HistoryStore(Path(temp) / "history.sqlite3")
            for language in ("es", "en"):
                for daily in (False, True):
                    with self.subTest(language=language, daily=daily):
                        prefix, suffix = (["c", "\n"], ["q"]) if daily else ([], [])
                        screen = self.screen([*prefix, curses.KEY_DOWN, curses.KEY_UP, "\n", "q", *suffix])
                        dashboard(screen, store, translator(language), today=date(2026, 12, 31))
                        self.assertEqual(store.records(), [])
                        self.assertFalse(store.path.exists())

    def test_calendar_arrows_follow_grid_and_preserve_legacy_keys(self):
        arrow_keys = [curses.KEY_UP, curses.KEY_DOWN, curses.KEY_LEFT, curses.KEY_RIGHT,
                      curses.KEY_UP, "\n", "\n", "q", "q", "w", "q"]
        legacy_keys = ["h", "l", "k", "j", "h", "\n", "\n", "q", "q", "w", "q"]
        with tempfile.TemporaryDirectory() as temp:
            store = HistoryStore(Path(temp) / "history.sqlite3")
            store.append(record(started_at="2027-01-02T12:00:00-03:00", objective="Selected day task"))
            before = store.records()
            for language in ("es", "en"):
                with self.subTest(language=language):
                    arrows = self.screen(["c", *arrow_keys])
                    legacy = self.screen(["c", *legacy_keys])
                    for screen in (arrows, legacy):
                        dashboard(screen, store, translator(language), today=date(2027, 1, 3))
                    self.assertEqual(len(arrows.pages), len(legacy.pages))
                    for index, (actual, expected) in enumerate(zip(arrows.pages, legacy.pages)):
                        self.assertEqual(actual, expected, f"Frame {index}")
                    for index, expected in ((2, "2027-01-02"), (3, "2027-01-03"),
                                            (4, "2026-12-27"), (5, "2027-01-03")):
                        self.assertIn(expected, arrows.pages[index].splitlines()[16])
                    title = "DETALLE DE SESIÓN" if language == "es" else "SESSION DETAIL"
                    self.assertTrue(any(title in page and "Selected day task" in page for page in arrows.pages))
                    self.assertIn("2026-12-28 — 2027-01-03", arrows.pages[-1])
                    self.assertEqual(store.records(), before)

    def test_calendar_explains_cells_columns_and_months_in_both_languages(self):
        with tempfile.TemporaryDirectory() as temp:
            store = HistoryStore(Path(temp) / "history.sqlite3")
            for language, explanation, months, selected in [
                    ("es", "12 semanas | celda: día | columna: semana", ("Oct", "Nov", "Dic", "Ene"), "Día elegido:"),
                    ("en", "12 weeks | cell: day | column: week", ("Oct", "Nov", "Dec", "Jan"), "Selected day:")]:
                with self.subTest(language=language):
                    screen = self.screen(["c", "q"])
                    dashboard(screen, store, translator(language), today=date(2027, 1, 11))
                    self.assertIn(explanation, screen.contents())
                    self.assertIn(selected + " 2027-01-11 | 0m 0s", screen.contents())
                    self.assertIn("↑↓:", screen.contents())
                    self.assertIn("←→:", screen.contents())
                    for month in months:
                        self.assertIn(month, "".join(screen.cells[7]))
                    self.assertNotIn("…", screen.contents())
                    self.assertFalse(store.path.exists())

    def test_read_failure_is_visible_and_can_exit(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "broken"
            path.write_bytes(b"bad")
            screen = self.screen(["q"])
            dashboard(screen, HistoryStore(path), translator("es"))
            self.assertIn("No se pudo leer", screen.contents())
            self.assertEqual(path.read_bytes(), b"bad")


if __name__ == "__main__":
    unittest.main()
