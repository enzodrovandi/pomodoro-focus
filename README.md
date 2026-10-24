# Pomodoro Focus

A quiet terminal app for working on one concrete goal at a time. Choose a short focus block, park distractions, and leave yourself a next step. No accounts, cloud services, ratings, streaks, or external Python dependencies.

- **Start small:** choose 5, 25, or 50 minutes, then take an optional 5-minute break.
- **Stay in the terminal:** pause, record distractions, and finish early when needed.
- **Look back locally:** browse session details, weekly totals, and a 12-week activity calendar.
- **Choose your language:** Spanish by default, or English for any run.

Illustrative English preview (synthetic text, not a screenshot):

```text
╭──────────────────────────────────────────────╮
│             ONE THING AT A TIME               │
│                                              │
│  Read a chapter                              │
│  First step: Open the first page              │
│                    24:59                     │
│          No rush. Stay with this step.        │
│                                              │
│  Space: pause/resume | d: distraction          │
│  f: finish | q: leave                         │
╰──────────────────────────────────────────────╯
```

## Quick start

Requires **Linux, macOS, or Windows**, **Python 3.10+**, and an interactive terminal. Linux and macOS use standard-library `curses`. Windows first needs the optional dependency in `requirements-windows.txt`: Use **80 columns × 24 rows or larger** for the full interface; smaller windows may truncate content. No package installation is needed when Python and curses are available.

```sh
git clone https://github.com/enzodrovandi/pomodoro-focus.git
cd pomodoro-focus
./pomofocus
```

The Unix launcher uses `python3` from your current `PATH`. You can also run `python3 focus.py` from the source directory.

On Windows, from the source directory:

```bat
py -3 -m pip install -r requirements-windows.txt
pomofocus.cmd
```

Use Windows Terminal for arrow keys and color. `pomofocus.cmd` forwards arguments to `py -3 focus.py`; the Unix `pomofocus` launcher is not a native Windows command.

```sh
./pomofocus --lang en           # English for this run
./pomofocus --lang es           # Spanish explicitly (the default)
./pomofocus --history           # Browse history without starting a block
./pomofocus --lang en --help    # English help
./pomofocus --help              # Spanish help
```

Only `es` and `en` are accepted. Language selection is not saved and never translates your goals or notes.

### Optional user-local command

To run `pomofocus` from other directories, optionally create a symlink while in the cloned source directory. This example refuses to replace an existing file or symlink:

```sh
source_path="$PWD/pomofocus"
mkdir -p "$HOME/.local/bin"
if [ -e "$HOME/.local/bin/pomofocus" ] || [ -L "$HOME/.local/bin/pomofocus" ]; then
    printf '%s\n' 'Not installed: destination already exists.'
else
    ln -s "$source_path" "$HOME/.local/bin/pomofocus"
fi
```

Keep the source directory in place: moving or removing it breaks the link. If `~/.local/bin` is not on your `PATH`, keep using `./pomofocus` from the source directory or consult your shell's documentation. The app does not edit shell configuration or `PATH`.

## A session

From home, press **`1` for New session** or **`2` for History and analysis**; `q` exits. History requires no goal or command-line option.

1. Enter an observable goal and a concrete first step.
2. Choose a 5-, 25-, or 50-minute block.
3. Focus, pausing or parking distractions as needed.
4. Optionally record progress and a next step, then take or skip a break.

Reflection fields are optional. Pauses, exit confirmation, reflection, and breaks do not count as effective focus time. The timer continues while you write a distraction. Distractions appear in the current summary only; they are not stored in history.

## Controls

Shortcuts are the same in both languages, including `y` to confirm closing a block.

| Screen | Keys |
| --- | --- |
| Home | `1`: new session; `2`: history; `q`: exit |
| Text input | Enter: confirm; Backspace: erase; Esc: cancel (or skip a reflection field) |
| Duration | `1`/`2`/`3`: 5/25/50 minutes; `h`: history, then return to preparation; Esc: home; `q`: exit |
| Timer | Space: pause/resume; `d`: park a distraction during focus; `f`: finish early; `q`: ask before closing |
| Close confirmation | `y`: close and reflect; `n`: resume |
| Break selection | `b`: take a break; `s`: skip |
| Summary | `m`: home; `n`: new session; `h`: history; `j`/`k`: page notes; `q`: exit |
| History and daily lists | ↑/↓ or `j`/`k`: select; Enter: details; main history also has `w`: weekly totals, `c`: calendar |
| Session detail | `j`/`k`: page text; `q`/Esc: back |
| Weekly totals | `[`/`]`: previous/next week; `l`: history list; `c`: calendar |
| Calendar | ↑/↓: previous/next day; ←/→: previous/next week; `h`/`l`: previous/next day; `k`/`j` or `[`/`]`: previous/next week; Enter: day's sessions; `w`: week's totals |
| History views | `q`/Esc: return to caller (home, preparation, or summary); with `--history`, exit |
| Anywhere | Ctrl+C: exit without extra prompts, attempting to save an active block |

Esc during goal, first-step, or duration entry returns home without saving an unstarted block.

## History and calendar

Blocks are saved once, **before the optional break**, with the local start timestamp, goal, first step, planned duration, effective focus time, complete/early status, and optional progress and next step. Browsing never starts or resets a timer.

Weeks run **Monday–Sunday**. A block crossing midnight belongs entirely to its local start date, using the offset recorded at the start. Weekly totals compare session counts, complete/early counts, and effective time with the previous week, including an absolute time difference.

The calendar is a rolling **12-week view, not a month**: each **cell is a day**, each **column is a week**, and rows are weekdays. It ends on the selected week's Sunday and follows your selection across month and year boundaries. Brackets mark the selected day. Gray-to-green levels show no time, under 25 minutes, 25 to under 50 minutes, and 50 minutes or more; text symbols distinguish levels without color. Empty days remain selectable and carry no penalty.

These are descriptive activity totals, **not a measure of concentration**. The app does not block other applications, play music, or claim that a particular block length improves focus.

## Local storage and privacy

- History lives at `$XDG_DATA_HOME/pomodoro-focus/history.sqlite3` when `XDG_DATA_HOME` is absolute; otherwise it uses `~/.local/share/pomodoro-focus/history.sqlite3`. Storage is independent of the source directory.
- There is **no telemetry, network communication, cloud sync, or account system**.
- Data is **unencrypted**: anyone with access to your user files may read goals and reflections. New database files request owner-only permissions, subject to filesystem semantics.
- Records are validated and appended transactionally, not edited or deleted. Existing corrupt, empty, or incompatible databases are not reset or automatically upgraded. Save/read errors are shown rather than silently discarding existing data; failed saves are not automatically retried.
- Ordinary Ctrl+C attempts to save an active block and confirmed reflections. A failed interrupt-time save reports an error and exits with status 1. **Hard termination, power loss, or interruption during saving can lose an unsaved block.** There are no periodic checkpoints, backups, or recovery tools. Interrupted first-time initialization can leave an incompatible file that is not overwritten.

Avoid putting sensitive information into goals or reflections. Repository ignore rules exclude common local databases, secrets, development artifacts, and images, but are not a substitute for checking files before sharing them. Share source and synthetic examples, not real history or session screenshots.

## Development checks

```sh
python3 -m unittest -v
./pomofocus --help
```

Tests use isolated temporary state, never real user history. Interactive tests use Unix pseudo-terminals. The suite covers the launcher, bilingual CLI, session timing, navigation, local storage, calendar, and interruption behavior.

## License

[MIT](LICENSE) — copyright 2026 Pomodoro Focus contributors. Provided without warranty; see the license for the full terms.
