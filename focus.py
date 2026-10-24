#!/usr/bin/env python3
"""A quiet, dependency-free terminal for focused work."""

import argparse
import curses
import math
import sys
import time
from datetime import datetime
from uuid import uuid4

from history import HistoryError, HistoryStore, Record
from history_views import dashboard
from i18n import translator
from ui import configure_palette, content_width, footer, frame, progress, put, summary_page_size


class Session:
    """Monotonic countdown with explicit focus, reflection and break phases."""

    def __init__(self, objective, first_step, minutes, clock=time.monotonic):
        if not objective.strip() or not first_step.strip() or minutes <= 0:
            raise ValueError("An objective, first step and positive duration are required.")
        self.objective = objective.strip()
        self.first_step = first_step.strip()
        self.clock = clock
        self.duration = minutes * 60
        self.deadline = clock() + self.duration
        self.paused = False
        self.paused_remaining = self.duration
        self.phase = "focus"
        self.distractions = []
        self.progress = ""
        self.next_step = ""
        self.focus_seconds = 0
        self.history_id = str(uuid4())
        self.started_at = datetime.now().astimezone().isoformat()
        self.save_attempted = False
        self.save_error = None

    def remaining(self):
        if self.phase not in ("focus", "break"):
            return 0
        value = self.paused_remaining if self.paused else max(0, self.deadline - self.clock())
        if value <= 0:
            if self.phase == "focus":
                self.focus_seconds = self.duration
                self.phase = "reflection"
            else:
                self.phase = "done"
        return math.ceil(value)

    def toggle_pause(self):
        if self.phase not in ("focus", "break"):
            return
        remaining = self.remaining()
        if remaining == 0:
            return
        if self.paused:
            self.deadline = self.clock() + self.paused_remaining
        else:
            self.paused_remaining = max(0, self.deadline - self.clock())
        self.paused = not self.paused

    def add_distraction(self, text):
        if text.strip():
            self.distractions.append(text.strip())

    def finish(self):
        if self.phase == "focus":
            remaining = self.paused_remaining if self.paused else max(0, self.deadline - self.clock())
            self.focus_seconds = self.duration - remaining
            self.phase = "reflection"
        elif self.phase == "break":
            self.phase = "done"

    def reflect(self, progress, next_step):
        self.progress = progress.strip()
        self.next_step = next_step.strip()

    def start_break(self):
        self.phase = "break"
        self.paused = False
        self.deadline = self.clock() + 300


def prompt(screen, title, label, tr, required=False, session=None):
    """Inline editor; countdown continues while a distraction is being written."""
    value = ""
    while True:
        frame(screen, title)
        put(screen, 5, label)
        width = max(1, content_width(screen) - 3)
        put(screen, 7, "> " + value[-width:] + "_", curses.A_BOLD)
        footer(screen, tr("Enter: confirm | Esc: cancel | Backspace: erase"))
        if session is not None:
            left = session.remaining()
            put(screen, 12, tr("Time left: {minutes:02d}:{seconds:02d}").format(minutes=left // 60, seconds=left % 60))
        screen.refresh()
        key = screen.get_wch()
        if key in ("\n", "\r", curses.KEY_ENTER):
            if value.strip() or not required:
                return value.strip()
        elif key == "\x1b":
            return None
        elif key in (curses.KEY_BACKSPACE, "\x7f", "\b"):
            value = value[:-1]
        elif isinstance(key, str) and key.isprintable() and len(value) < 240:
            value += key


def choose(screen, title, lines, choices, hints=None):
    while True:
        frame(screen, title)
        for row, line in enumerate(lines, 5):
            put(screen, row, line)
        if hints:
            footer(screen, hints)
        screen.refresh()
        key = screen.get_wch()
        if isinstance(key, str) and key.lower() in choices:
            return key.lower()


def home(screen, tr):
    """Two direct routes, with exit kept separate from the main choices."""
    return choose(screen, tr("HOME"),
                  [tr("1: New session"), tr("2: History and analysis")],
                  "12q", hints=tr("q: exit"))


def run_timer(screen, session, tr):
    screen.timeout(200)
    try:
        while session.phase in ("focus", "break"):
            left = session.remaining()
            if session.phase not in ("focus", "break"):
                break
            frame(screen, tr("REST") if session.phase == "break" else tr("ONE THING AT A TIME"))
            put(screen, 5, session.objective, curses.A_BOLD)
            put(screen, 7, tr("First step: ") + session.first_step)
            put(screen, 10, f"{left // 60:02d}:{left % 60:02d}", curses.A_BOLD, align="center")
            progress(screen, left, session.duration if session.phase == "focus" else 300)
            put(screen, 12, tr("PAUSED - resume when ready") if session.paused else tr("No rush. Stay with this step."), align="center")
            put(screen, 14, tr("Distractions parked: {count}").format(count=len(session.distractions)), curses.A_DIM)
            footer(screen, tr("Space: pause/resume | d: distraction | f: finish | q: leave"))
            screen.refresh()
            try:
                key = screen.get_wch()
            except curses.error:
                continue
            if key == " ":
                session.toggle_pause()
            elif key == "d" and session.phase == "focus":
                screen.timeout(-1)
                note = prompt(screen, tr("PARK A DISTRACTION"), tr("Write it down, then return to your task:"), tr, session=session)
                if note:
                    session.add_distraction(note)
                screen.timeout(200)
            elif key == "f":
                session.finish()
            elif key == "q":
                # Pause while deciding; cancellation must not consume focus time.
                was_paused = session.paused
                if not was_paused:
                    session.toggle_pause()
                screen.timeout(-1)
                answer = choose(screen, tr("LEAVE THIS BLOCK?"), [tr("y: close block and reflect"), tr("n: return to timer")], "yn")
                if answer == "y":
                    session.finish()
                elif not was_paused:
                    session.toggle_pause()
                screen.timeout(200)
    finally:
        screen.timeout(-1)


def save_session(session, store):
    """Attempt one append per block; never count reflection or rest as focus."""
    if session.save_attempted:
        return session.save_error
    session.finish()
    session.save_attempted = True
    record = Record(session.history_id, session.started_at, session.objective,
                    session.first_step, session.duration, session.focus_seconds,
                    "complete" if session.focus_seconds == session.duration else "early",
                    session.progress, session.next_step)
    try:
        store.append(record)
    except HistoryError as error:
        session.save_error = str(error)
    return session.save_error


class HistoryInterrupted(KeyboardInterrupt):
    """An interrupted block could not be saved."""


def close_block(screen, session, tr, store):
    try:
        run_timer(screen, session, tr)
        progress = prompt(screen, tr("CLOSE YOUR BLOCK"), tr("What did you accomplish? (optional)"), tr)
        session.reflect(progress or "", "")
        next_step = prompt(screen, tr("LEAVE A STARTING POINT"), tr("What is your next step? (optional)"), tr)
        session.reflect(progress or "", next_step or "")
    except KeyboardInterrupt:
        error = save_session(session, store)
        if error:
            raise HistoryInterrupted(error)
        raise
    return save_session(session, store)


def app(screen, tr, open_history=False):
    configure_palette()
    curses.curs_set(0)
    screen.keypad(True)
    store = HistoryStore()
    if open_history:
        dashboard(screen, store, tr)
        return
    new_session = False
    while True:
        if not new_session:
            route = home(screen, tr)
            if route == "q":
                return
            if route == "2":
                dashboard(screen, store, tr)
                continue
        new_session = False
        objective = prompt(screen, tr("PREPARE YOUR SESSION"), tr("What do you want to accomplish?"), tr, required=True)
        if objective is None:
            continue
        first_step = prompt(screen, tr("MAKE IT EASY TO START"), tr("What is the first concrete step?"), tr, required=True)
        if first_step is None:
            continue
        while True:
            duration = choose(screen, tr("CHOOSE A BLOCK"), [tr("1: just start - 5 minutes"), tr("2: focus - 25 minutes"), tr("3: deep work - 50 minutes"), tr("h: history"), tr("q: exit")], "123qh\x1b",
                              hints=tr("Esc: home"))
            if duration != "h":
                break
            dashboard(screen, store, tr)
        if duration == "q":
            return
        if duration == "\x1b":
            continue
        session = Session(objective, first_step, {"1": 5, "2": 25, "3": 50}[duration])
        save_error = close_block(screen, session, tr, store)
        warning = [tr("History not saved. Summary remains available.")] if save_error else []
        answer = choose(screen, tr("A BREAK IS PART OF THE WORK"), warning + [tr("b: take a 5-minute break"), tr("s: skip break")], "bs")
        if answer == "b":
            session.start_break()
            run_timer(screen, session, tr)
        lines = warning + [tr("Focused time: {minutes}m {seconds}s").format(minutes=int(session.focus_seconds) // 60, seconds=int(session.focus_seconds) % 60),
                 tr("Progress: ") + (session.progress or tr("Not recorded")),
                 tr("Next step: ") + (session.next_step or tr("Not recorded")),
                 tr("Parked distractions:")]
        lines.extend("- " + note for note in session.distractions)
        # Paginate notes so small terminals never hide the exit controls.
        page = 0
        while True:
            page_size = summary_page_size(screen)
            page = min(page, (len(lines) - 1) // page_size)
            visible = lines[page * page_size:(page + 1) * page_size]
            action = choose(screen, tr("SESSION COMPLETE - NO SCORES, NO STREAKS"), visible, "nqjkhm",
                            hints=tr("n: new session | m: home | q: exit | j/k: scroll summary | h: history"))
            if action == "h":
                dashboard(screen, store, tr)
                continue
            if action == "q":
                return
            if action == "m":
                break
            if action == "n":
                new_session = True
                break
            page = min((len(lines) - 1) // page_size, page + 1) if action == "j" else max(0, page - 1)


class LocalizedParser(argparse.ArgumentParser):
    """Localize argparse labels and errors without global gettext mutations."""

    def __init__(self, language, **kwargs):
        self.language = language
        super().__init__(**kwargs)

    def format_help(self):
        text = super().format_help()
        if self.language == "es":
            text = text.replace("usage: ", "uso: ", 1).replace("options:\n", "opciones:\n")
        return text

    def format_usage(self):
        text = super().format_usage()
        return text.replace("usage: ", "uso: ", 1) if self.language == "es" else text

    def error(self, message):
        if self.language == "es":
            message = message.replace("argument --lang: expected one argument", "--lang requiere un valor: es o en.")
            message = message.replace("unrecognized arguments:", "argumentos no reconocidos:")
            message = message.replace("ambiguous option:", "opción ambigua:")
        super().error(message)


def main():
    # Read language before constructing help, so --help --lang en also works.
    preliminary = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    preliminary.add_argument("--lang", nargs="?", default="es", const="es")
    selected, _ = preliminary.parse_known_args()
    language = "en" if selected.lang == "en" else "es"
    tr = translator(language)
    parser = LocalizedParser(language, add_help=False,
                             description=tr("Interactive focus sessions with goals, distractions and optional breaks."))
    parser.add_argument("-h", "--help", action="help", help=tr("show this help message and exit"))
    # --h was an accepted help abbreviation before --history existed.
    parser.add_argument("--h", action="help", help=argparse.SUPPRESS)

    def valid_language(value):
        if value not in ("es", "en"):
            message = (f"Idioma inválido: {value}. Usá es o en." if language == "es"
                       else f"Invalid language: {value}. Use es or en.")
            raise argparse.ArgumentTypeError(message)
        return value

    parser.add_argument("--lang", type=valid_language, default="es", metavar="{es,en}",
                        help=tr("Interface language: es (Spanish, default) or en (English)."))
    parser.add_argument("--history", action="store_true", help=tr("Open local history without starting a block."))
    args = parser.parse_args()
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        command = "py -3 focus.py" if sys.platform == "win32" else "python3 focus.py"
        print(tr("Pomodoro Focus needs an interactive terminal. Run: {command}").format(command=command), file=sys.stderr)
        return 1
    try:
        curses.wrapper(app, tr, args.history)
    except HistoryInterrupted:
        print(tr("Interrupted block could not be saved."), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    except curses.error:
        print(tr("Unable to initialize the terminal. Check TERM and terminal support."), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
