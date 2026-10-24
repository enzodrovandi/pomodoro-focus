"""Small descriptive history views; minutes are activity, not concentration."""
import curses
from datetime import date, timedelta
import textwrap

from history import HistoryError
from ui import activity_cell, activity_legend, content_width, footer, frame, put, summary_page_size


def day_records(records, day):
    return sorted((item for item in records if item.day == day),
                  key=lambda item: item.started_at, reverse=True)


def weekly_summary(records, day):
    start = day - timedelta(days=day.weekday())
    current = [item for item in records if start <= item.day < start + timedelta(days=7)]
    previous = [item for item in records if start - timedelta(days=7) <= item.day < start]
    seconds = sum(item.focus_seconds for item in current)
    previous_seconds = sum(item.focus_seconds for item in previous)
    return dict(start=start, count=len(current), seconds=seconds,
                complete=sum(item.status == "complete" for item in current),
                early=sum(item.status == "early" for item in current),
                previous_count=len(previous), previous_seconds=previous_seconds,
                previous_complete=sum(item.status == "complete" for item in previous),
                previous_early=sum(item.status == "early" for item in previous),
                delta_seconds=seconds - previous_seconds)


def activity_days(records, day):
    end = day - timedelta(days=day.weekday()) + timedelta(days=6)
    start = end - timedelta(days=83)
    totals = {}
    for item in records:
        totals[item.day] = totals.get(item.day, 0) + item.focus_seconds
    return [(start + timedelta(days=index), totals.get(start + timedelta(days=index), 0))
            for index in range(84)]


def duration(seconds):
    seconds = int(seconds)
    return f"{seconds // 60}m {seconds % 60}s"


def paged(screen, title, lines, tr):
    page = 0
    while True:
        wrapped = [part for line in lines for part in (textwrap.wrap(line, content_width(screen)) or [""])]
        size = summary_page_size(screen)
        page = min(page, max(0, (len(wrapped) - 1) // size))
        frame(screen, title)
        for row, line in enumerate(wrapped[page * size:(page + 1) * size], 5):
            put(screen, row, line)
        footer(screen, tr("j/k: page | q/Esc: back"))
        screen.refresh()
        key = screen.get_wch()
        if key in ("q", "\x1b"):
            return
        if key == "j":
            page = min(max(0, (len(wrapped) - 1) // size), page + 1)
        elif key == "k":
            page = max(0, page - 1)


def session_detail(screen, item, tr):
    paged(screen, tr("SESSION DETAIL"), [item.started_at,
          tr("Objective: ") + item.objective, tr("First step: ") + item.first_step,
          tr("Planned: ") + duration(item.planned_seconds),
          tr("Effective: ") + duration(item.focus_seconds), tr(item.status),
          tr("Progress: ") + (item.progress or tr("Not recorded")),
          tr("Next step: ") + (item.next_step or tr("Not recorded"))], tr)


def session_list(screen, records, title, tr):
    selected = 0
    while True:
        size = summary_page_size(screen)
        frame(screen, title)
        if not records:
            put(screen, 5, tr("No sessions yet"))
        for row, item in enumerate(records[(selected // size) * size:(selected // size + 1) * size], 5):
            index = (selected // size) * size + row - 5
            put(screen, row, ("> " if index == selected else "  ") + item.started_at[:16] +
                " " + duration(item.focus_seconds) + " " + item.objective)
        footer(screen, tr("↑/↓ or j/k: select | Enter: details | q/Esc: back"))
        screen.refresh()
        key = screen.get_wch()
        if key in ("q", "\x1b"):
            return
        if key in ("j", curses.KEY_DOWN):
            selected = min(max(0, len(records) - 1), selected + 1)
        elif key in ("k", curses.KEY_UP):
            selected = max(0, selected - 1)
        elif key in ("\n", "\r", curses.KEY_ENTER) and records:
            session_detail(screen, records[selected], tr)


def dashboard(screen, store, tr, today=None):
    today = today or date.today()
    selected_day = today
    week = today
    mode = "list"
    selected = 0
    try:
        records = sorted(store.records(), key=lambda item: item.started_at, reverse=True)
    except HistoryError:
        paged(screen, tr("HISTORY"), [tr("Could not read history. Existing data was not reset.")], tr)
        return
    while True:
        frame(screen, tr("HISTORY") if mode == "list" else tr("WEEKLY SUMMARY") if mode == "week" else tr("ACTIVITY CALENDAR"))
        size = summary_page_size(screen)
        if mode == "list":
            if not records:
                put(screen, 5, tr("No sessions yet"))
            offset = selected // size * size
            for row, item in enumerate(records[offset:offset + size], 5):
                put(screen, row, ("> " if row - 5 + offset == selected else "  ") +
                    str(item.day) + " " + duration(item.focus_seconds) + " " + item.objective)
            hints = tr("↑/↓ or j/k: select | Enter: details | w: week | c: calendar | q: back")
        elif mode == "week":
            summary = weekly_summary(records, week)
            start = summary["start"]
            lines = [f"{start} — {start + timedelta(days=6)}",
                     tr("This week: {count} sessions | {time}").format(count=summary["count"], time=duration(summary["seconds"])),
                     tr("Complete: {complete} | Early: {early}").format(**summary),
                     tr("Previous: {count} sessions | {time}").format(count=summary["previous_count"], time=duration(summary["previous_seconds"])),
                     tr("Complete: {complete} | Early: {early}").format(complete=summary["previous_complete"], early=summary["previous_early"]),
                     tr("Time change: {delta}").format(delta=("+" if summary["delta_seconds"] >= 0 else "-") + duration(abs(summary["delta_seconds"]))),
                     tr("Activity totals, not a measure of concentration.")]
            for row, line in enumerate(lines, 5):
                put(screen, row, line)
            hints = tr("[/]: previous/next week | l: list | c: calendar | q: back")
        else:
            cells = activity_days(records, selected_day)
            put(screen, 4, tr("12 weeks | cell: day | column: week"))
            put(screen, 5, f"{cells[0][0]} — {cells[-1][0]}")
            months = tr("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec").split()
            month_labels = []
            previous_month = None
            for column in range(12):
                month = cells[column * 7][0].month
                month_labels.append(months[month - 1] if month != previous_month else "   ")
                previous_month = month
            put(screen, 6, "    " + "".join(month_labels))
            for weekday in range(7):
                put(screen, 7 + weekday, tr("Mon Tue Wed Thu Fri Sat Sun").split()[weekday])
                for column in range(12):
                    day, seconds = cells[column * 7 + weekday]
                    level = 0 if seconds == 0 else 1 if seconds < 1500 else 2 if seconds < 3000 else 3
                    activity_cell(screen, 7 + weekday, 4 + column * 3, level, selected=day == selected_day)
            total = next(seconds for day, seconds in cells if day == selected_day)
            put(screen, 15, tr("Selected day: {date} | {time}").format(date=selected_day, time=duration(total)))
            activity_legend(screen, 16, tr("[ ] selected"))
            hints = tr("↑↓: day | ←→: week | Enter: sessions | w: totals | q: back")
        footer(screen, hints)
        screen.refresh()
        key = screen.get_wch()
        if key in ("q", "\x1b"):
            return
        if key == "c":
            mode = "calendar"
        elif key == "w":
            week = selected_day
            mode = "week"
        elif key == "l" and mode != "calendar":
            mode = "list"
        elif mode == "list":
            if key in ("j", curses.KEY_DOWN):
                selected = min(max(0, len(records) - 1), selected + 1)
            elif key in ("k", curses.KEY_UP):
                selected = max(0, selected - 1)
            elif key in ("\n", "\r", curses.KEY_ENTER) and records:
                session_detail(screen, records[selected], tr)
        elif mode == "week" and key in ("[", "]"):
            week += timedelta(days=-7 if key == "[" else 7)
        elif mode == "calendar":
            moves = {"h": -1, "l": 1, "j": 7, "k": -7, "[": -7, "]": 7,
                     curses.KEY_UP: -1, curses.KEY_DOWN: 1,
                     curses.KEY_LEFT: -7, curses.KEY_RIGHT: 7}
            if key in moves:
                selected_day += timedelta(days=moves[key])
            elif key in ("\n", "\r", curses.KEY_ENTER):
                session_list(screen, day_records(records, selected_day), str(selected_day), tr)
