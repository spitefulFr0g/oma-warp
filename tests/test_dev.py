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

    def test_scrub_accepts_only_the_audited_packaging_homepage(self):
        address = '.'.join(('1', '1', '1', '1'))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'recipe'
            for text, expected in ((f'url="https://{address}"', 0), (address, 1),
                                   (f'url="https://{address}" {address}', 1)):
                path.write_text(text)
                result = subprocess.run(['/usr/bin/python3', '-B', str(ROOT / 'dev/scrub'), str(path)], capture_output=True)
                self.assertEqual(result.returncode, expected, result.stderr)


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
                                        env={**os.environ, 'PATH': str(bindir), 'OMA_WARP_QT_BIN': str(bindir),
                                             'GATE_LOG': str(log), 'FAIL_STEP': failure},
                                        capture_output=True)
                with self.subTest(failure=failure):
                    self.assertEqual(result.returncode, int(bool(failure)), result.stderr)
                    self.assertEqual(log.read_text().splitlines(), ['python3', 'qmllint', 'qmltestrunner', 'omarchy', 'scrub'])

    def test_qml_steps_use_strict_qt6_tools_against_the_omarchy_shell(self):
        import json
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'dev').mkdir()
            (root / 'tests/qml').mkdir(parents=True)
            (root / 'Panel.qml').write_text('// test input\n')
            (root / 'tests/qml/tst_logic.qml').write_text('// test input\n')
            shutil.copyfile(ROOT / 'dev/check', root / 'dev/check')
            shell = root / 'omarchy/shell'
            (shell / 'Ui').mkdir(parents=True)
            (shell / 'Ui/qmldir').write_text('module qs.Ui\n')
            qt, other = root / 'qt6', root / 'bin'
            qt.mkdir()
            other.mkdir()
            recorder = (
                '#!/usr/bin/python3\nimport json, os, sys\n'
                'args = sys.argv[1:]\n'
                'imports = [args[i + 1] for i, a in enumerate(args) if a == "-I"]\n'
                'record = {"args": args, "platform": os.environ.get("QT_QPA_PLATFORM"),\n'
                '          "shell": [os.path.isfile(os.path.join(d, "qs/Ui/qmldir")) for d in imports]}\n'
                'with open(os.environ["GATE_LOG"], "a") as log:\n'
                '    log.write(json.dumps([os.path.basename(sys.argv[0]), record]) + "\\n")\n'
            )
            for directory, names in ((qt, ('qmllint', 'qmltestrunner')),
                                     (other, ('python3', 'omarchy', 'qmllint', 'qmltestrunner'))):
                for name in names:
                    path = directory / name
                    path.write_text(recorder if directory == qt else '#!/bin/sh\n[ "${0##*/}" != qmllint ] && [ "${0##*/}" != qmltestrunner ]\n')
                    path.chmod(0o755)
            (root / 'dev/scrub').write_text('#!/bin/sh\n')
            (root / 'dev/scrub').chmod(0o755)
            log = root / 'calls'
            result = subprocess.run(['/usr/bin/python3', '-B', str(root / 'dev/check')],
                                    env={**os.environ, 'PATH': str(other), 'OMA_WARP_QT_BIN': str(qt),
                                         'OMARCHY_PATH': str(root / 'omarchy'), 'GATE_LOG': str(log)},
                                    capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            calls = dict(json.loads(line) for line in log.read_text().splitlines())
            lint = calls['qmllint']
            self.assertEqual(lint['args'][lint['args'].index('--max-warnings') + 1], '0')
            self.assertEqual(lint['shell'], [True])
            self.assertIn('Panel.qml', lint['args'])
            self.assertIn('tests/qml/tst_logic.qml', lint['args'])
            runner = calls['qmltestrunner']
            self.assertEqual(runner['args'][:2], ['-input', 'tests'])
            self.assertEqual(runner['platform'], 'offscreen')
