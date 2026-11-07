import getpass
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ScrubTests(unittest.TestCase):
    def test_scrub_rejects_personal_values_and_accepts_placeholders(self):
        values = [getpass.getuser(), '/' + 'home/' + 'person/file', os.uname().nodename,
                  os.uname().release, 'colo=' + 'ABC', 'loc=' + 'AB',
                  '.'.join(('8', '8', '4', '4')), '2606' + ':4700::1111']
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'content.txt'
            for value in values:
                path.write_text(value)
                result = subprocess.run(['/usr/bin/python3', '-B', str(ROOT / 'dev/scrub'), str(path)], capture_output=True)
                with self.subTest(kind=values.index(value)):
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(b'content.txt', result.stderr)
            path.write_text('203.0.113.7 198.51.100.2 2001:db8::7 colo=XXX loc=XX ~')
            result = subprocess.run(['/usr/bin/python3', '-B', str(ROOT / 'dev/scrub'), str(path)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)


class GateTests(unittest.TestCase):
    def test_gate_runs_all_steps_and_propagates_each_failure(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'dev').mkdir()
            (root / 'tests/qml').mkdir(parents=True)
            (root / 'Panel.qml').write_text('// test input\n')
            (root / 'tests/qml/tst_contract.qml').write_text('// test input\n')
            shutil.copyfile(ROOT / 'dev/check', root / 'dev/check')
            bindir = root / 'bin'
            bindir.mkdir()
            script = '#!/bin/sh\nname=${0##*/}\necho "$name" >> "$GATE_LOG"\n[ "$name" != "$FAIL_STEP" ]\n'
            for name in ('python3', 'qmllint', 'qmltestrunner', 'omarchy'):
                path = bindir / name
                path.write_text(script)
                path.chmod(0o755)
            (root / 'dev/scrub').write_text(script)
            (root / 'dev/scrub').chmod(0o755)
            log = root / 'calls'
            for failure in ('', 'python3', 'qmllint', 'qmltestrunner', 'omarchy', 'scrub'):
                log.unlink(missing_ok=True)
                result = subprocess.run(['/usr/bin/python3', '-B', str(root / 'dev/check')],
                                        env={**os.environ, 'PATH': str(bindir), 'GATE_LOG': str(log), 'FAIL_STEP': failure},
                                        capture_output=True)
                with self.subTest(failure=failure):
                    self.assertEqual(result.returncode, int(bool(failure)), result.stderr)
                    self.assertEqual(log.read_text().splitlines(), ['python3', 'qmllint', 'qmltestrunner', 'omarchy', 'scrub'])
