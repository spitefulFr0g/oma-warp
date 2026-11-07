"""The injectable boundary for all product effects."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request


class System:
    @property
    def runtime_dir(self):
        value = os.environ.get('XDG_RUNTIME_DIR')
        return Path(value) / 'oma-warp' if value else None

    @property
    def cache_dir(self):
        return Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'oma-warp'

    def now(self):
        return datetime.now(timezone.utc)

    def run(self, argv, *, timeout):
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                              env={**os.environ, 'LC_ALL': 'C', 'TZ': 'UTC'}, check=False)

    def fetch(self, url, *, timeout, limit=1048576):
        if not url.startswith('https://'):
            raise ValueError('HTTPS required')
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                raise ValueError('redirect refused')
        with urllib.request.build_opener(NoRedirect).open(url, timeout=timeout) as response:
            body = response.read(limit + 1)
            if len(body) > limit:
                raise ValueError('response too large')
            return body

    @property
    def plugin_dir(self):
        # omarchy plugin remove uses this location, independent of XDG_CONFIG_HOME.
        return Path.home() / '.config' / 'omarchy' / 'plugins' / 'spitefulfr0g.oma-warp'

    def confirm(self, prompt):
        return input(prompt + ' [y/N] ').strip().lower() in ('y', 'yes')

    def write(self, message):
        print(message, flush=True)

    def run_terminal(self, argv):
        # Inherit stdin/stdout/stderr and allow time for sudo or terms prompts.
        return subprocess.run(argv, check=False,
                              env={**os.environ, 'LC_ALL': 'C', 'TZ': 'UTC'})

    def path_exists(self, path):
        try:
            path.lstat()
            return True
        except FileNotFoundError:
            return False

    def remove_tree(self, path):
        if path.is_symlink():
            path.unlink()
        else:
            shutil.rmtree(path)

    def read_text(self, path):
        return path.read_text(encoding='utf-8')

    def atomic_write(self, path, text):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                             dir=path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(text)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def remove_file(self, path):
        path.unlink(missing_ok=True)

    @contextmanager
    def exclusive_lock(self, path):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with path.open('a') as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    @property
    def current_pid(self):
        return os.getpid()

    def process_start_time(self, pid):
        try:
            # comm (field 2) can contain spaces and parentheses. Field 22 is
            # ticks since boot, stable for a process even when a PID is reused.
            fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
            return fields[19] if fields[0] not in ('Z', 'X', 'x') else None
        except (OSError, IndexError, ValueError):
            return None
