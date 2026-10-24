"""Validated append-only local history. No network or schema upgrades."""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
import math
import os
from pathlib import Path
import sqlite3


class HistoryError(Exception):
    """The store cannot safely fulfill the requested operation."""


@dataclass(frozen=True)
class Record:
    id: str
    started_at: str
    objective: str
    first_step: str
    planned_seconds: float
    focus_seconds: float
    status: str
    progress: str = ""
    next_step: str = ""

    @property
    def day(self):
        # Attribute the whole block to its local start date, even across midnight.
        return datetime.fromisoformat(self.started_at).date()

    def validate(self):
        for name in ("id", "started_at", "objective", "first_step", "status", "progress", "next_step"):
            value = getattr(self, name)
            if not isinstance(value, str) or len(value) > 10000:
                raise HistoryError("Invalid text field: " + name)
            if any(ord(char) < 32 and char not in "\n\t" or ord(char) == 127 for char in value):
                raise HistoryError("Invalid control character: " + name)
        if not all(getattr(self, name).strip() for name in ("id", "objective", "first_step")):
            raise HistoryError("Missing required field")
        try:
            started = datetime.fromisoformat(self.started_at)
            if started.utcoffset() is None:
                raise ValueError("Timestamp needs a local offset")
        except ValueError as error:
            raise HistoryError("Invalid timestamp") from error
        for value in (self.planned_seconds, self.focus_seconds):
            if type(value) not in (int, float) or not math.isfinite(value):
                raise HistoryError("Invalid duration")
        if not 0 <= self.focus_seconds <= self.planned_seconds or self.planned_seconds <= 0:
            raise HistoryError("Invalid duration range")
        expected = "complete" if self.focus_seconds == self.planned_seconds else "early"
        if self.status != expected:
            raise HistoryError("Invalid completion status")


def default_path():
    root = os.environ.get("XDG_DATA_HOME")
    base = Path(root) if root and Path(root).is_absolute() else Path.home() / ".local" / "share"
    return base / "pomodoro-focus" / "history.sqlite3"


SCHEMA = """CREATE TABLE sessions (
    id TEXT PRIMARY KEY NOT NULL,
    started_at TEXT NOT NULL,
    objective TEXT NOT NULL,
    first_step TEXT NOT NULL,
    planned_seconds REAL NOT NULL,
    focus_seconds REAL NOT NULL,
    status TEXT NOT NULL,
    progress TEXT NOT NULL,
    next_step TEXT NOT NULL
)"""
FIELDS = tuple(Record.__dataclass_fields__)


class HistoryStore:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else default_path()

    @contextmanager
    def connection(self, create=False):
        connection = None
        try:
            if not self.path.exists():
                if not create:
                    yield None
                    return
                self.path.parent.mkdir(parents=True, exist_ok=True)
                # Exclusive creation prevents initializing an existing empty or
                # incompatible file. A competing initializer may fail safely.
                try:
                    descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                except FileExistsError:
                    fresh = False
                else:
                    os.close(descriptor)
                    fresh = True
            else:
                fresh = False
            uri = self.path.resolve().as_uri() + ("?mode=rw" if create else "?mode=ro")
            connection = sqlite3.connect(uri, uri=True, timeout=1)
            if create:
                connection.execute("BEGIN IMMEDIATE")
            if fresh:
                connection.execute(SCHEMA)
                connection.execute("PRAGMA user_version=1")
            schema = connection.execute("SELECT name, sql FROM sqlite_master WHERE type != 'index' ORDER BY name").fetchall()
            if connection.execute("PRAGMA user_version").fetchone()[0] != 1 or schema != [("sessions", SCHEMA)]:
                raise HistoryError("Incompatible history format")
            # Validate existing rows too, before allowing any new append.
            for row in connection.execute("SELECT * FROM sessions"):
                Record(*row).validate()
            yield connection
            if create:
                connection.commit()
        except (OSError, sqlite3.Error, ValueError, TypeError) as error:
            raise HistoryError(str(error)) from error
        finally:
            if connection is not None:
                connection.close()  # Rolls back unsuccessful transactions.

    def records(self):
        with self.connection() as connection:
            if connection is None:
                return []
            return [Record(*row) for row in connection.execute("SELECT * FROM sessions ORDER BY started_at, id")]

    def append(self, record):
        record.validate()
        with self.connection(create=True) as connection:
            existing = connection.execute("SELECT * FROM sessions WHERE id=?", (record.id,)).fetchone()
            if existing is not None:
                if Record(*existing) != record:
                    raise HistoryError("Session identifier already has different content")
                return False
            connection.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?)", tuple(asdict(record).values()))
            return True
