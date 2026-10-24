"""Real Windows curses backend smoke, with synthetic input (not a manual UI test).

The Actions shell has redirected streams. A bounded child gets its own Windows
console and explicitly binds the C/Python standard descriptors to that console.
Only synthetic history and a small result JSON live in session temporary state.
"""
import curses
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def supervise(command, result, **options):
    """Require both a clean child exit and an affirmative, readable receipt."""
    with subprocess.Popen(command, **options) as child:
        try:
            code = child.wait(timeout=20)
        except subprocess.TimeoutExpired as error:
            child.kill()
            child.wait()
            raise RuntimeError("Windows console child timed out") from error
    if code:
        raise RuntimeError(f"Windows console child exit {code}")
    if not result.is_file():
        raise RuntimeError("Windows console child missing result")
    try:
        receipt = json.loads(result.read_text(encoding="utf-8"))
    except (ValueError, OSError) as error:
        raise RuntimeError("Windows console child invalid result") from error
    if not isinstance(receipt, dict) or receipt.get("ok") is not True:
        raise RuntimeError("Windows console child reported failure")
    return receipt


class ScriptedScreen:
    """Forward all rendering to the real window; inject one checked key at a time."""

    def __init__(self, screen, steps):
        self.screen = screen
        self.steps = iter(steps)
        self.consumed = 0

    def __getattr__(self, name):
        return getattr(self.screen, name)

    def get_wch(self):
        try:
            key, check = next(self.steps)
        except StopIteration as error:
            raise AssertionError("input script exhausted") from error
        check(self.screen)
        curses.ungetch(ord(key) if isinstance(key, str) else key)
        observed = self.screen.get_wch()
        assert observed == key, f"backend key decoding mismatch at step {self.consumed}"
        self.consumed += 1
        return observed

    def assert_finished(self, expected):
        assert self.consumed == expected, "app exited before consuming input script"
        assert next(self.steps, None) is None, "unconsumed scripted input"


def bind_console():
    """CREATE_NEW_CONSOLE alone does not guarantee usable inherited std handles."""
    import ctypes
    from ctypes import wintypes
    import msvcrt

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.SetStdHandle.argtypes = [wintypes.DWORD, wintypes.HANDLE]
    kernel.SetStdHandle.restype = wintypes.BOOL
    kernel.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetConsoleMode.restype = wintypes.BOOL
    for descriptor, name, mode, standard in (
            (0, "CONIN$", "rb", -10), (1, "CONOUT$", "wb", -11),
            (2, "CONOUT$", "wb", -12)):
        with open(name, mode, buffering=0) as console:
            os.dup2(console.fileno(), descriptor)
        handle = msvcrt.get_osfhandle(descriptor)
        console_mode = wintypes.DWORD()
        if not kernel.SetStdHandle(standard & 0xffffffff, handle):
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel.GetConsoleMode(handle, ctypes.byref(console_mode)):
            raise ctypes.WinError(ctypes.get_last_error())
    assert sys.stdin.isatty() and sys.stdout.isatty(), "new console is not interactive"


def exercise(screen):
    from datetime import datetime, timedelta
    from focus import app
    from history import HistoryStore, Record
    from history_views import activity_days, duration
    from i18n import translator
    import ui

    assert screen.getmaxyx()[0] >= 24 and screen.getmaxyx()[1] >= 80, "console smaller than 80x24"
    screen.encoding = "utf-8"
    # Blocking input is safe: exactly one key is pushed immediately before each read.
    screen.timeout(-1)
    store = HistoryStore()
    now = datetime.now().astimezone().replace(microsecond=0)
    today = now.date()
    for index, seconds in enumerate((90, 1500, 3000)):
        started = now - timedelta(days=index)
        store.append(Record(str(index), started.isoformat(), f"Goal {index}", f"Step {index}",
                            3000, seconds, "complete" if seconds == 3000 else "early"))
    before = store.records()
    original_bytes = store.path.read_bytes()
    capabilities = []

    def lines(window):
        return [window.instr(row, 0).decode("utf-8")
                for row in range(window.getmaxyx()[0])]

    for language in ("en", "es"):
        tr = translator(language)

        def view(title, *labels, literal=False):
            def check(window):
                text = "\n".join(lines(window))
                for label in (title if literal else tr(title), *labels):
                    assert label in text, f"{language}: missing rendered {label!r}"
                assert "╭" in text and "╯" in text, "frame glyphs missing"
            return check

        def listing(index):
            return view("HISTORY", f"> {before[2-index].day} "
                        f"{duration(before[2-index].focus_seconds)} Goal {index}")

        def calendar(day):
            def check(window):
                total = next((item.focus_seconds for item in before if item.day == day), 0)
                view("ACTIVITY CALENDAR", tr("Selected day: {date} | {time}").format(
                    date=day, time=duration(total)))(window)
                top, left, _, _ = ui.bounds(window)
                cells = activity_days(before, day)
                index = next(i for i, (date, _) in enumerate(cells) if date == day)
                level = 0 if total == 0 else 1 if total < 1500 else 2 if total < 3000 else 3
                symbol = "■" if ui.ACTIVITY_COLORS is not None else ("□", "░", "▒", "█")[level]
                row, column = top + 7 + index % 7, left + 6 + index // 7 * 3
                assert lines(window)[row][column:column+3] == f"[{symbol}]", "selected cell glyph mismatch"
                # Read actual cell attributes, not source or intended draw calls.
                mask = curses.A_COLOR | curses.A_BOLD | curses.A_DIM
                expected = (ui.ACTIVITY_COLORS[level] if ui.ACTIVITY_COLORS is not None
                            else ui.MUTED if level == 0 else 0)
                assert window.inch(row, column) & mask == expected & mask, "selected palette mismatch"
                # All four legend levels must render with their real palette attributes.
                offset = 0
                for density, caption in enumerate(("0", "<25m", "25-49m", "50m+")):
                    glyph = "■" if ui.ACTIVITY_COLORS is not None else ("□", "░", "▒", "█")[density]
                    x = left + 2 + offset
                    assert lines(window)[top+16][x:x+3] == f" {glyph} ", "legend glyph mismatch"
                    attr = (ui.ACTIVITY_COLORS[density] if ui.ACTIVITY_COLORS is not None
                            else ui.MUTED if density == 0 else 0)
                    # The adjacent ASCII space has the same attributes without
                    # wide-character codepoint bits overlapping chtype's color mask.
                    assert window.inch(top+16, x) & mask == attr & mask, "legend palette mismatch"
                    offset += 3 + len(caption) + 2
            return check

        steps = [
            ("2", view("HOME", tr("1: New session"), tr("2: History and analysis"))),
            (curses.KEY_DOWN, listing(0)),
            ("\n", listing(1)),
            ("q", view("SESSION DETAIL", tr("Objective: ") + "Goal 1")),
            ("c", listing(1)),
            (curses.KEY_LEFT, calendar(today)),
            (curses.KEY_RIGHT, calendar(today - timedelta(days=7))),
            (curses.KEY_UP, calendar(today)),
            ("\n", calendar(today - timedelta(days=1))),
            ("\n", view(str(today - timedelta(days=1)), "Goal 1", literal=True)),
            ("q", view("SESSION DETAIL", tr("Objective: ") + "Goal 1")),
            ("q", view(str(today - timedelta(days=1)), "Goal 1", literal=True)),
            ("q", calendar(today - timedelta(days=1))),
            ("q", view("HOME", tr("q: exit"))),
        ]
        proxy = ScriptedScreen(screen, steps)
        app(proxy, tr)
        proxy.assert_finished(len(steps))
        assert store.records() == before, "probe changed stored records"
        assert store.path.read_bytes() == original_bytes, "probe rewrote history"
        capabilities.append({"language": language,
                             "palette": "color" if ui.ACTIVITY_COLORS is not None else "monochrome",
                             "has_colors": curses.has_colors(), "steps": proxy.consumed})
    return capabilities


def child_main(result):
    receipt = {"ok": False}
    try:
        bind_console()
        sys.path.insert(0, str(ROOT))
        receipt = {"ok": True, "checks": curses.wrapper(exercise)}
    finally:
        # Written even on an exception; nonzero exit remains authoritative.
        result.write_text(json.dumps(receipt), encoding="utf-8")


def main():
    if sys.platform != "win32":
        print("Windows console smoke unavailable: requires Windows.", file=sys.stderr)
        return 1
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        child_main(Path(sys.argv[2]))
        return 0
    try:
        with tempfile.TemporaryDirectory(prefix="pomodoro-console-") as directory:
            result = Path(directory) / "result.json"
            environment = dict(os.environ, XDG_DATA_HOME=directory,
                               PYTHONDONTWRITEBYTECODE="1")
            receipt = supervise([sys.executable, str(Path(__file__).resolve()), "--child", str(result)],
                                result, env=environment, close_fds=True,
                                creationflags=subprocess.CREATE_NEW_CONSOLE)
            print("WINDOWS_CURSES_PROBE=" + json.dumps(receipt, sort_keys=True))
    except (OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
