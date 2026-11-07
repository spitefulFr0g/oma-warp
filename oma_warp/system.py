"""The injectable boundary for all product effects."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
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

    def monotonic(self):
        return time.monotonic()

    def wait(self, seconds):
        time.sleep(seconds)

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

    def run_bytes(self, argv, *, timeout):
        return subprocess.run(argv, capture_output=True, timeout=timeout, check=False,
                              env={**os.environ, 'LC_ALL': 'C', 'TZ': 'UTC'})

    def temporary_directory(self, **kwargs):
        import tempfile
        return tempfile.TemporaryDirectory(**kwargs)

    def chmod(self, path, mode):
        path.chmod(mode)

    def read_bytes(self, path):
        return path.read_bytes()

    def write_bytes(self, path, data):
        path.write_bytes(data)

    def make_directory(self, path):
        path.mkdir(parents=True, exist_ok=True)

    def replace(self, source, destination):
        os.replace(source, destination)

    def read_json(self, path):
        import json
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            return None

    def write_json(self, path, document):
        import json
        import tempfile
        self.make_directory(path.parent)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, mode='w', delete=False) as output:
                temporary = Path(output.name)
                json.dump(document, output)
            self.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def fetch_file(self, url, destination, *, timeout, limit):
        import hashlib
        if not url.startswith('https://'):
            raise ValueError('HTTPS required')
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                raise ValueError('redirect refused')
        digest, size = hashlib.sha256(), 0
        with urllib.request.build_opener(NoRedirect).open(url, timeout=timeout) as response:
            with destination.open('wb') as output:
                while chunk := response.read(min(1048576, limit + 1 - size)):
                    size += len(chunk)
                    if size > limit:
                        raise ValueError('Downloaded package exceeds signed size')
                    digest.update(chunk)
                    output.write(chunk)
        return digest.hexdigest(), size

    def effective_uid(self):
        return os.geteuid()

    def find_command(self, command):
        return shutil.which(command)

    def resolve_path(self, path):
        return path.resolve()

    def is_file(self, path):
        return path.is_file()

    def is_directory(self, path):
        return path.is_dir()

    def glob(self, path, pattern):
        return list(path.glob(pattern))

    def make_temporary_directory(self, **kwargs):
        return Path(tempfile.mkdtemp(**kwargs))

    def copy_file(self, source, destination):
        shutil.copyfile(source, destination)

    def write_text(self, path, text, *, encoding='utf-8'):
        path.write_text(text, encoding=encoding)

    def digest(self, path):
        import hashlib
        digest, size = hashlib.sha256(), 0
        with path.open('rb') as source:
            for block in iter(lambda: source.read(1048576), b''):
                digest.update(block)
                size += len(block)
        return digest.hexdigest(), size

    def run_build(self, argv, *, cwd):
        return subprocess.run(argv, cwd=cwd, check=False, text=True, capture_output=True,
                              env={**os.environ, 'LC_ALL': 'C', 'TZ': 'UTC'})
