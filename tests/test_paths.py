"""exe で動くときの置き場所（design.md §9.3）"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from toolkeeper import paths


class FrozenTest(unittest.TestCase):
    def test_self_command_from_source_is_python_m(self):
        self.assertEqual(paths.self_command(), [sys.executable, "-m", "toolkeeper"])

    def test_self_command_when_frozen_is_the_console_exe(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "executable", str(Path(d) / "toolkeeperw.exe")):
            self.assertEqual(paths._app_dir(), Path(d).resolve())
            self.assertEqual(paths.self_command(), [str(Path(d).resolve() / "toolkeeper.exe")])

    def test_app_dir_from_source_is_the_repository(self):
        self.assertTrue((paths.APP_DIR / "pyproject.toml").is_file())


if __name__ == "__main__":
    unittest.main()
