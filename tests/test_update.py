import io
import json
import tempfile
import unittest
from pathlib import Path

from toolkeeper import check, store, update


def item(key, tier="B", updatable=True, name=None):
    return {"key": key, "tier": tier, "name": name or key, "installed": "1.0", "latest": "1.1",
            "updatable": updatable, "eol": None, "new": False, "notes": []}


RESULT = {"schema": 1, "items": [
    item("winget:Gyan.FFmpeg"), item("winget:7zip.7zip"),
    item("winget:Microsoft.WSL", tier="C"), item("choco:gh", tier="D"), item("winget:OpenJS.NodeJS.20", tier="E"),
    item("winget:Python.Python.3.12", updatable=False),
    item("php", tier="A"), item("cygwin", tier="A"),
]}


class Plan(unittest.TestCase):
    def test_b_is_allowed(self):
        self.assertEqual([it["key"] for it in update.plan(RESULT, ["winget:Gyan.FFmpeg", "winget:7zip.7zip"])],
                         ["winget:Gyan.FFmpeg", "winget:7zip.7zip"])

    def test_refuses_everything_when_one_is_bad(self):
        """1 つでも上げられない物があれば、どれも動かさない"""
        for bad in ("winget:Microsoft.WSL", "choco:gh", "winget:OpenJS.NodeJS.20", "winget:Python.Python.3.12",
                    "winget:Nope", "php"):
            with self.subTest(bad), self.assertRaises(update.Refused):
                update.plan(RESULT, ["winget:Gyan.FFmpeg", bad])

    def test_php_points_to_migration(self):
        with self.assertRaises(update.Refused) as cm:
            update.plan(RESULT, ["php"])
        self.assertIn("§7", str(cm.exception))


class Run(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        store.write_json(self.data / check.CHECK_FILE, RESULT)
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def runner(self, codes):
        def run(args, out):
            self.calls.append(args)
            code = codes[len(self.calls) - 1]
            out.write("installing...\r\n")
            return code, "" if code == 0 else "インストーラーが失敗しました"
        return run

    def test_runs_in_order_and_keeps_going(self):
        out = io.StringIO()
        done = update.run(self.data, ["winget:Gyan.FFmpeg", "winget:7zip.7zip"], out, self.runner([0x8A150011, 0]))
        self.assertEqual([c[3] for c in self.calls], ["Gyan.FFmpeg", "7zip.7zip"])
        self.assertIn("--exact", self.calls[0])
        self.assertNotIn("--include-pinned", self.calls[0])
        self.assertEqual([d["ok"] for d in done], [False, True])
        self.assertEqual(done[0]["code"], "0x8A150011")
        self.assertEqual(done[0]["tail"], "インストーラーが失敗しました")
        with open(self.data / update.HISTORY_FILE, encoding="utf-8") as f:
            hist = [json.loads(x) for x in f]
        self.assertEqual([h["key"] for h in hist], ["winget:Gyan.FFmpeg", "winget:7zip.7zip"])

    def test_not_applicable_is_not_failure(self):
        done = update.run(self.data, ["winget:7zip.7zip"], io.StringIO(), self.runner([0x8A15002B]))
        self.assertTrue(done[0]["ok"])

    def test_no_check_yet(self):
        (self.data / check.CHECK_FILE).unlink()
        with self.assertRaises(update.Refused):
            update.run(self.data, ["winget:7zip.7zip"], io.StringIO(), self.runner([0]))


class Exclusive(unittest.TestCase):
    def test_second_holder_is_busy(self):
        with tempfile.TemporaryDirectory() as d:
            with store.exclusive(Path(d)):
                with self.assertRaises(store.Busy):
                    with store.exclusive(Path(d)):
                        pass
            with store.exclusive(Path(d)):  # 外したら取れる
                pass


if __name__ == "__main__":
    unittest.main()
