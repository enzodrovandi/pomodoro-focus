"""Quiet terminal presentation, separate from session timing and input handling."""
import curses
import textwrap


ACCENT = curses.A_BOLD
MUTED = curses.A_DIM
ACTIVITY_COLORS = None


def configure_palette():
    """Use one accent on the terminal's own background, or plain attributes."""
    global ACCENT, ACTIVITY_COLORS
    ACCENT = curses.A_BOLD
    ACTIVITY_COLORS = None
    try:
        if curses.has_colors():
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_CYAN, -1)
            ACCENT |= curses.color_pair(1)
            rich_color = getattr(curses, "COLORS", 0) >= 256
            colors = (240, 28, 34, 40) if rich_color else (curses.COLOR_WHITE,) + (curses.COLOR_GREEN,) * 3
            attributes = []
            for pair, foreground in enumerate(colors, 2):
                curses.init_pair(pair, foreground, -1)
                attributes.append(curses.color_pair(pair))
            if not rich_color:
                attributes[0] |= MUTED
                attributes[1] |= MUTED
                attributes[3] |= curses.A_BOLD
            ACTIVITY_COLORS = tuple(attributes)
    except curses.error:
        pass  # Monochrome remains fully usable, including on limited terminals.


def bounds(screen):
    height, width = screen.getmaxyx()
    panel_height = max(1, min(22, height - 2))
    panel_width = max(1, min(78, width - 2))
    return ((height - panel_height) // 2, (width - panel_width) // 2,
            panel_height, panel_width)


def draw(screen, row, column, text, attr=0):
    height, width = screen.getmaxyx()
    if 0 <= row < height and 0 <= column < width:
        try:
            screen.addnstr(row, column, text, max(0, width - column - 1), attr)
        except curses.error:
            pass  # A resize can invalidate coordinates between calls.


def content_width(screen):
    return max(1, bounds(screen)[3] - 4)


def put(screen, row, text, attr=0, align="left"):
    top, left, height, width = bounds(screen)
    if not 0 < row < height - 1:
        return
    available = content_width(screen)
    if len(text) > available:
        text = text[:max(0, available - 1)] + "…"
    column = left + ((width - len(text)) // 2 if align == "center" else 2)
    draw(screen, top + row, column, text, attr)


def frame(screen, title):
    screen.erase()
    top, left, height, width = bounds(screen)
    if width < 2 or height < 2:
        return
    draw(screen, top, left, "╭" + "─" * (width - 2) + "╮", MUTED)
    for row in range(top + 1, top + height - 1):
        draw(screen, row, left, "│", MUTED)
        draw(screen, row, left + width - 1, "│", MUTED)
    draw(screen, top + height - 1, left, "╰" + "─" * (width - 2) + "╯", MUTED)
    put(screen, 1, "POMODORO FOCUS", MUTED)
    put(screen, 3, title, ACCENT)


def footer(screen, text):
    """Anchor hints to the panel bottom; wrap rather than hide common keys."""
    height = bounds(screen)[2]
    lines = textwrap.wrap(text, width=content_width(screen))
    count = min(2, max(0, height - 2))
    for offset, line in enumerate(lines[:count]):
        put(screen, height - 1 - count + offset, line, MUTED)


def progress(screen, remaining, duration):
    fraction = max(0, min(1, 1 - remaining / duration)) if duration > 0 else 1
    width = min(24, content_width(screen))
    filled = int(width * fraction)
    put(screen, 11, "━" * filled + "─" * (width - filled), ACCENT, align="center")


def activity_cell(screen, row, column, level, selected=False):
    """One calendar day: a colored square or a distinct monochrome density."""
    top, left, height, _ = bounds(screen)
    if not 0 < row < height - 1 or not 0 <= column <= content_width(screen) - 3:
        return
    symbol = "■" if ACTIVITY_COLORS is not None else ("□", "░", "▒", "█")[level]
    attr = ACTIVITY_COLORS[level] if ACTIVITY_COLORS is not None else (MUTED if level == 0 else 0)
    text = f"[{symbol}]" if selected else f" {symbol} "
    draw(screen, top + row, left + 2 + column, text, attr)


def activity_legend(screen, row, selected_label):
    """Use the same cell palette in the legend and the calendar itself."""
    top, left, height, _ = bounds(screen)
    if not 0 < row < height - 1:
        return
    column = 0
    for level, caption in enumerate(("0", "<25m", "25-49m", "50m+")):
        activity_cell(screen, row, column, level)
        available = max(0, content_width(screen) - column - 3)
        if available:
            draw(screen, top + row, left + 2 + column + 3, caption[:available], MUTED)
        column += 3 + len(caption) + 2
    available = max(0, content_width(screen) - column)
    if available:
        draw(screen, top + row, left + 2 + column, selected_label[:available], MUTED)


def summary_page_size(screen):
    # Rows 5 onward, leaving a breathing row before two lines of footer hints.
    return max(1, bounds(screen)[2] - 10)
