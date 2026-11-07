"""The injectable boundary for all product effects."""
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
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
