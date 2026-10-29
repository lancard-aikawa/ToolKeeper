import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from toolkeeper import check, cli, store


class Log(unittest.TestCase):
    def test_log_writes_last_run(self):
        """pythonw では標準出力が捨てられるので、--log で <data>/last-run.log に残す"""
        with tempfile.TemporaryDirectory() as d:
            data = Path(d)
            store.write_json(data / check.CHECK_FILE, {"schema": 1, "checked_at": "2026-10-28T09:00:00+09:00",
                                                       "summary": {"updatable": 0, "eol": 0, "new": 0, "failed": 0},
                                                       "items": [], "failed": []})
            code = cli.main(["--config", str(data / "none.json"), "--data", d, "--log", "list"])
            text = (data / "last-run.log").read_text(encoding="utf-8")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("toolkeeper --config", text)
        self.assertIn("更新できる 0", text)
        self.assertIn("終了コード 0", text)

    def test_log_keeps_exit_code_of_failure(self):
        with tempfile.TemporaryDirectory() as d:
            code = cli.main(["--config", str(Path(d) / "none.json"), "--data", d, "--log", "list"])
            text = (Path(d) / "last-run.log").read_text(encoding="utf-8")
        self.assertEqual(code, cli.EXIT_USAGE)
        self.assertIn("まだ調べていません", text)


class Env(unittest.TestCase):
    def test_undo_without_history_is_refused(self):
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stderr(io.StringIO()) as err:
            code = cli.main(["--data", d, "env", "--undo"])
        self.assertEqual(code, cli.EXIT_USAGE)
        self.assertIn("戻せる変更がありません", err.getvalue())

    def test_unknown_id_is_refused_before_writing(self):
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stderr(io.StringIO()) as err, \
                mock.patch.object(cli.envmod, "read_registry", return_value={"machine": {}, "user": {}}):
            code = cli.main(["--data", d, "env", "--fix", "path-dup:machine:1:00000000"])
            self.assertFalse((Path(d) / "env-history.jsonl").exists())
        self.assertEqual(code, cli.EXIT_USAGE)
        self.assertIn("見つかりません", err.getvalue())


if __name__ == "__main__":
    unittest.main()
