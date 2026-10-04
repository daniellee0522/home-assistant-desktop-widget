import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import app_version


class RunningVersion(unittest.TestCase):
    def test_source_version_matches_project(self):
        with patch.object(app_version.sys, 'frozen', False, create=True):
            self.assertEqual(app_version.running_version(), Path('VERSION').read_text().strip())

    def test_frozen_version_comes_from_running_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory, 'build-info.json')
            with patch.object(app_version.sys, 'frozen', True, create=True), \
                 patch.object(app_version.sys, 'executable', str(Path(directory, 'HA Widgets.exe'))):
                for content, expected in [(' {"version":"1.11.3"}', '1.11.3'),
                                          ('{"version":"invalid"}', 'dev'),
                                          ('{"version":null}', 'dev'), ('broken', 'dev')]:
                    manifest.write_text(content)
                    self.assertEqual(app_version.running_version(), expected)
                manifest.unlink()
                self.assertEqual(app_version.running_version(), 'dev')
