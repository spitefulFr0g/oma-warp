"""The Panel's Job record watch, run in a real headless Quickshell.

The watch must re-poll the moment a Job writes or removes job.json, even when
the runtime folder does not exist yet when the shell starts, and must not turn
other files in that folder into polls.
"""
import os
from pathlib import Path
from queue import Empty, Queue
import shutil
import subprocess
import tempfile
from threading import Thread
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
# Quickshell only resolves types inside its config folder, so the harness and
# the watch's sources are assembled into a throwaway one.
HARNESS = '''import QtQuick
import Quickshell

ShellRoot {
  JobRecordWatch {
    runtimeDir: Quickshell.env("OMA_WARP_TEST_RUNTIME_DIR")
    onPollNeeded: console.info("oma-warp-harness: poll")
  }

  // Lets the watch take its first look before the test changes files.
  Timer {
    interval: 300
    running: true
    onTriggered: console.info("oma-warp-harness: ready")
  }
}
'''
SOURCES = ('JobRecordWatch.qml', 'PanelLogic.js')
MARKER = 'oma-warp-harness: '
EVENT = 2.0   # generous: inotify delivers within milliseconds
QUIET = 0.6


class Harness:
    def __init__(self, runtime_dir, home):
        # Quickshell's own state goes to a throwaway home, never the session's.
        env = {**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'OMA_WARP_TEST_RUNTIME_DIR': str(runtime_dir)}
        for name in ('XDG_RUNTIME_DIR', 'XDG_CACHE_HOME', 'XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'XDG_DATA_HOME'):
            path = Path(home) / name.lower()
            path.mkdir(mode=0o700)
            env[name] = str(path)
        config = Path(home) / 'shell'
        config.mkdir()
        (config / 'shell.qml').write_text(HARNESS)
        for name in SOURCES:
            shutil.copyfile(ROOT / name, config / name)
        self.process = subprocess.Popen([shutil.which('qs') or 'qs', '-p', str(config)], env=env,
                                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, errors='replace')
        self.lines = Queue()
        Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.process.stdout:
            if MARKER in line:
                self.lines.put(line.split(MARKER, 1)[1].strip())

    def next(self, timeout):
        try:
            return self.lines.get(timeout=timeout)
        except Empty:
            return None

    def polls_within(self, timeout):
        """Polls requested within timeout, ending QUIET after the first."""
        deadline = time.monotonic() + timeout
        count = 0
        while (remaining := deadline - time.monotonic()) > 0:
            event = self.next(remaining)
            if event == 'poll':
                count += 1
                # Drain the burst one change can raise, then stop waiting.
                deadline = min(deadline, time.monotonic() + QUIET)
        return count

    def close(self):
        self.process.kill()
        self.process.wait(timeout=10)
        self.process.stdout.close()


class JobRecordWatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='oma-warp-watch-')
        self.addCleanup(self.tmp.cleanup)
        self.runtime = Path(self.tmp.name) / 'runtime'
        self.runtime.mkdir(mode=0o700)
        self.home = Path(self.tmp.name) / 'home'
        self.home.mkdir()
        self.folder = self.runtime / 'oma-warp'

    def start(self):
        harness = Harness(self.runtime, self.home)
        self.addCleanup(harness.close)
        self.assertEqual(harness.next(10), 'ready', 'the harness shell did not start')
        return harness

    # As the backend writes it: folder, lock, then the record via temp file and rename.
    def write_record(self):
        self.folder.mkdir(mode=0o700, exist_ok=True)
        (self.folder / 'job.lock').touch()
        temporary = self.folder / 'tmp-record'
        temporary.write_text('{}')
        os.replace(temporary, self.folder / 'job.json')

    def remove_record(self):
        (self.folder / 'job.json').unlink()

    def assert_job_start_and_end_poll(self, harness):
        self.write_record()
        self.assertGreaterEqual(harness.polls_within(EVENT), 1, 'a Job starting did not re-poll')
        self.remove_record()
        self.assertGreaterEqual(harness.polls_within(EVENT), 1, 'a Job ending did not re-poll')

    def test_first_job_re_polls_when_the_runtime_folder_already_exists(self):
        self.folder.mkdir(mode=0o700)
        self.assert_job_start_and_end_poll(self.start())

    def test_first_job_re_polls_when_the_runtime_folder_appears_after_start(self):
        self.assert_job_start_and_end_poll(self.start())

    def test_jobs_re_poll_after_the_runtime_folder_is_removed_and_recreated(self):
        harness = self.start()
        self.assert_job_start_and_end_poll(harness)
        shutil.rmtree(self.folder)
        harness.polls_within(QUIET)
        self.assert_job_start_and_end_poll(harness)

    def test_other_files_in_the_runtime_folder_never_poll(self):
        self.folder.mkdir(mode=0o700)
        harness = self.start()
        for index in range(5):
            temporary = self.folder / 'tmp-probe'
            temporary.write_text(str(index))
            os.replace(temporary, self.folder / 'probe.json')
            (self.runtime / f'other-{index}').touch()
        (self.folder / 'probe.json').unlink()
        self.assertEqual(harness.polls_within(QUIET), 0)


if __name__ == '__main__':
    unittest.main()
