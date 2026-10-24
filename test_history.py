"""Public local-store and automatic session persistence contracts."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from history import HistoryError, HistoryStore, Record, default_path
from focus import Session, save_session


def record(**changes):
    values = dict(id="block-1", started_at="2026-12-31T23:59:00+00:00",
                  objective="Study", first_step="Read", planned_seconds=300,
                  focus_seconds=90, status="early", progress="Page one", next_step="Page two")
    values.update(changes)
    return Record(**values)


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "history.sqlite3"
        self.store = HistoryStore(self.path)

    def test_empty_append_reopen_and_idempotence(self):
        self.assertEqual(self.store.records(), [])
        item = record()
        self.assertTrue(self.store.append(item))
        self.assertFalse(self.store.append(item))
        self.assertEqual(HistoryStore(self.path).records(), [item])
        with self.assertRaises(HistoryError):
            self.store.append(replace(item, objective="Different"))
        self.assertEqual(self.store.records(), [item])

    def test_invalid_records_leave_history_and_totals_unchanged(self):
        self.store.append(record())
        for fields in [dict(id=""), dict(objective=" "), dict(first_step=""),
                       dict(planned_seconds=0), dict(focus_seconds=-1),
                       dict(focus_seconds=float("nan")), dict(focus_seconds=301),
                       dict(status="rated"), dict(status="complete"),
                       dict(started_at="2026-12-31"), dict(progress=3),
                       dict(next_step="\x1b[2J"), dict(planned_seconds=True)]:
            with self.subTest(fields=fields):
                values = {"id": "invalid", **fields}
                with self.assertRaises(HistoryError):
                    self.store.append(record(**values))
                self.assertEqual(self.store.records(), [record()])
                self.assertEqual(sum(r.focus_seconds for r in self.store.records()), 90)

    def test_corrupt_incompatible_and_unwritable_are_not_reset(self):
        for contents in (b"not sqlite", b""):
            self.path.write_bytes(contents)
            with self.assertRaises(HistoryError):
                self.store.append(record())
            self.assertEqual(self.path.read_bytes(), contents)
        import sqlite3
        other = Path(self.temp.name) / "other.sqlite3"
        with sqlite3.connect(other) as connection:
            connection.execute("CREATE TABLE unrelated (value TEXT)")
        original = other.read_bytes()
        with self.assertRaises(HistoryError):
            HistoryStore(other).append(record())
        self.assertEqual(other.read_bytes(), original)
        with self.assertRaises(HistoryError):
            HistoryStore(self.path / "child").append(record())

    def test_xdg_path_is_source_independent(self):
        with patch.dict("os.environ", {"XDG_DATA_HOME": self.temp.name}):
            self.assertEqual(default_path(), Path(self.temp.name) / "pomodoro-focus" / "history.sqlite3")
            store = HistoryStore()
            store.append(record())
            self.assertEqual(HistoryStore().records(), [record()])

    def test_invalid_existing_rows_are_not_extended_or_rewritten(self):
        self.store.append(record())
        import sqlite3
        with sqlite3.connect(self.path) as connection:
            connection.execute("UPDATE sessions SET focus_seconds=-1")
        original = self.path.read_bytes()
        with self.assertRaises(HistoryError):
            self.store.records()
        with self.assertRaises(HistoryError):
            self.store.append(record(id="new"))
        self.assertEqual(self.path.read_bytes(), original)

    def test_automatic_save_once_excludes_pause_reflection_and_break(self):
        now = [0.0]
        session = Session("Study", "Read", 5, clock=lambda: now[0])
        now[0] = 20
        session.toggle_pause()
        now[0] = 200
        session.toggle_pause()
        now[0] = 210
        session.finish()
        now[0] = 400
        session.reflect("Done", "Continue")
        self.assertIsNone(save_session(session, self.store))
        session.start_break()
        now[0] = 800
        session.remaining()
        self.assertIsNone(save_session(session, self.store))
        items = self.store.records()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].focus_seconds, 30)
        self.assertEqual(items[0].status, "early")
        self.assertEqual((items[0].progress, items[0].next_step), ("Done", "Continue"))

    def test_completed_and_interrupt_style_finish(self):
        now = [0]
        session = Session("Study", "Read", 5, clock=lambda: now[0])
        now[0] = 301
        session.remaining()
        self.assertIsNone(save_session(session, self.store))
        self.assertEqual(self.store.records()[0].status, "complete")
        self.assertEqual(self.store.records()[0].focus_seconds, 300)
        second = Session("Other", "Start", 5, clock=lambda: now[0])
        now[0] += 10
        second.finish()
        self.assertIsNone(save_session(second, self.store))
        self.assertEqual(len(self.store.records()), 2)

    def test_store_failure_is_returned_without_losing_summary(self):
        self.path.write_bytes(b"broken")
        session = Session("Study", "Read", 5)
        session.finish()
        session.reflect("Still visible", "Next")
        self.assertIsInstance(save_session(session, self.store), str)
        self.assertEqual(session.progress, "Still visible")
        self.assertEqual(self.path.read_bytes(), b"broken")


if __name__ == "__main__":
    unittest.main()
