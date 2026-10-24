"""Exercise the executable entry point without installing it or using real history."""
import errno
import fcntl
import os
from pathlib import Path
import pty
import select
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest


ROOT = Path(__file__).resolve().parent
LAUNCHER = ROOT / "pomofocus"


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pomofocus launcher ")
        self.addCleanup(self.temp.cleanup)
        self.scratch = Path(self.temp.name)
        self.data = self.scratch / "data"
        self.data.mkdir()
        self.environment = {**os.environ, "XDG_DATA_HOME": str(self.data),
                            "PYTHONDONTWRITEBYTECODE": "1"}

    def run_cli(self, command, flags, cwd):
        return subprocess.run([*command, *flags], cwd=cwd, env=self.environment,
                              text=True, capture_output=True, timeout=3)

    def assert_cli_parity(self, command, cwd):
        cases = [([], 1), (["--history"], 1), (["--lang", "en"], 1),
                 (["--lang", "es", "--history"], 1),
                 (["--lang", "en", "--history"], 1),
                 (["--help"], 0), (["--lang", "es", "--help"], 0),
                 (["--help", "--lang", "en"], 0),
                 (["--lang", "en", "--he"], 0), (["--h"], 0),
                 (["--unknown"], 2), (["--lang", "fr"], 2),
                 (["--lang"], 2), (["--lang", "en", "--unknown"], 2)]
        for flags, code in cases:
            with self.subTest(command=command, flags=flags):
                baseline = self.run_cli([sys.executable, str(ROOT / "focus.py")], flags, cwd)
                result = self.run_cli(command, flags, cwd)
                self.assertEqual(baseline.returncode, code)
                self.assertEqual(result.returncode, code)
                # argparse uses argv[0]'s basename; no other output may change.
                self.assertEqual(result.stdout, baseline.stdout.replace("focus.py", "pomofocus"))
                # The noninteractive diagnostic names focus.py literally, not argv[0].
                expected_error = baseline.stderr if code == 1 else baseline.stderr.replace("focus.py", "pomofocus")
                self.assertEqual(result.stderr, expected_error)
                self.assertEqual(list(self.data.iterdir()), [])

    def test_direct_executable_cli_parity(self):
        self.assertTrue(LAUNCHER.is_file(), "Project launcher is missing")
        self.assertTrue(os.access(LAUNCHER, os.X_OK), "Project launcher must be executable")
        self.assertEqual(LAUNCHER.read_text().splitlines()[0], "#!/usr/bin/env python3")
        self.assert_cli_parity(["./pomofocus"], ROOT)

    def make_symlink(self):
        self.assertTrue(LAUNCHER.is_file(), "Project launcher is missing")
        source = self.scratch / "source with spaces"
        source.mkdir()
        for name in ("pomofocus", "focus.py", "history.py", "history_views.py", "i18n.py", "ui.py"):
            shutil.copy2(ROOT / name, source / name)
        binary = self.scratch / "bin with spaces"
        binary.mkdir()
        link = binary / "pomofocus"
        link.symlink_to(source / "pomofocus")
        unrelated = self.scratch / "unrelated working directory"
        unrelated.mkdir()
        return link, unrelated

    def test_absolute_symlink_cli_parity_from_unrelated_cwd(self):
        link, cwd = self.make_symlink()
        self.assert_cli_parity([str(link)], cwd)

    def test_symlink_opens_home_and_q_exits(self):
        link, cwd = self.make_symlink()
        for flags, label in [([], "2: Historial y análisis"),
                             (["--lang", "en"], "2: History and analysis")]:
            with self.subTest(flags=flags):
                master, slave = pty.openpty()
                self.addCleanup(os.close, master)
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
                try:
                    process = subprocess.Popen([str(link), *flags], cwd=cwd,
                                               stdin=slave, stdout=slave, stderr=subprocess.PIPE,
                                               env={**self.environment, "TERM": "xterm-256color",
                                                    "LC_ALL": "C.UTF-8"})
                finally:
                    os.close(slave)
                try:
                    output = bytearray()
                    deadline = time.monotonic() + 3
                    while label.encode() not in output and time.monotonic() < deadline:
                        if select.select([master], [], [], max(0, deadline - time.monotonic()))[0]:
                            try:
                                output.extend(os.read(master, 65536))
                            except OSError as error:
                                if error.errno == errno.EIO:
                                    break
                                raise
                    self.assertIn(label.encode(), output)
                    os.write(master, b"q")
                    self.assertEqual(process.wait(timeout=3), 0)
                    self.assertEqual(process.stderr.read(), b"")
                    self.assertEqual(list(self.data.iterdir()), [])
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
                    process.stderr.close()


if __name__ == "__main__":
    unittest.main()
