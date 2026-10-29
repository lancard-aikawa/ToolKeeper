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


class Firewall(unittest.TestCase):
    def test_prints_rows_and_counts(self):
        from toolkeeper import firewall
        from tests.helpers import fixture
        rules = firewall.parse_rules(fixture("netsh_firewall_en.txt"))
        with contextlib.redirect_stdout(io.StringIO()) as out, mock.patch.object(cli.firewall, "commands", return_value={}):
            code = cli._firewall({"env_commands": []}, read_rules=lambda: rules, read_registry=dict)
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("node.exe", out.getvalue())
        self.assertIn("wf.msc", out.getvalue())

    def test_netsh_failure(self):
        def broken():
            raise RuntimeError("netsh が終了コード 1 で終わりました")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            code = cli._firewall({"env_commands": []}, read_rules=broken, read_registry=dict)
        self.assertEqual(code, cli.EXIT_FAILED)
        self.assertIn("規則を読めません", err.getvalue())


if __name__ == "__main__":
    unittest.main()


class Unbroken(unittest.TestCase):
    """画面を閉じて出力の先が無くなっても、update は最後まで続ける（2026-10-29、OpenJDK 11 が OSError: [Errno 22] で落ちた）"""

    class Closed:
        def __init__(self):
            self.calls = 0

        def write(self, s):
            self.calls += 1
            raise OSError(22, "Invalid argument")

        def flush(self):
            raise OSError(22, "Invalid argument")

    def test_write_after_close(self):
        inner = self.Closed()
        out = cli._Unbroken(inner)
        self.assertEqual(out.write("abc"), 3)
        out.flush()
        out.write("def")
        self.assertEqual(inner.calls, 1)  # 一度壊れたら、もう書きに行かない

    def test_passes_through(self):
        inner = io.StringIO()
        out = cli._Unbroken(inner)
        out.write("x")
        self.assertEqual(inner.getvalue(), "x")
        self.assertEqual(cli._Unbroken(None).write("y"), 1)  # pythonw では sys.stdout が None
