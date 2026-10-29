import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from toolkeeper import check, store, update
from toolkeeper.config import DEFAULTS


def item(key, tier="B", updatable=True, name=None):
    return {"key": key, "tier": tier, "name": name or key, "installed": "1.0", "latest": "1.1",
            "updatable": updatable, "eol": None, "new": False, "notes": []}


RESULT = {"schema": 1, "items": [
    item("winget:Gyan.FFmpeg"), item("winget:7zip.7zip"),
    item("winget:Microsoft.WSL", tier="C"), item("choco:gh", tier="D"), item("winget:OpenJS.NodeJS.20", tier="E"),
    item("winget:Python.Python.3.12", updatable=False),
    item("php", tier="A"), item("ghostscript", tier="A"),
]}
CFG = copy.deepcopy(DEFAULTS)
# winget error の代わり（2026-10-29 に winget error で引いた文）
EXPLAIN = {0x8A150030: "アンインストール コマンドの実行に失敗しました", 1603: "Fatal error during installation."}


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

    def test_ghostscript_is_allowed(self):
        self.assertEqual([it["key"] for it in update.plan(RESULT, ["ghostscript"])], ["ghostscript"])

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

    def runners(self, codes):
        def stream(args, out):
            self.calls.append(args)
            code = codes[len(self.calls) - 1]
            out.write("installing...\r\n")
            # 2026-10-29 に OpenJDK 17 で出た、最後の 2 行
            return code, "" if code == 0 else "パッケージのアンインストールを開始しています...\nアンインストールは次の終了コードで失敗しました: 1603"

        def gs(it, cfg, data, out):
            raise RuntimeError("SHA-256 が合いません")
        return {"winget": lambda it, cfg, data, out: update._winget(it, cfg, data, out, stream), "ghostscript": gs}

    def run_update(self, keys, codes, out=None, regs=None, explain=EXPLAIN.get):
        """regs はレジストリを読むたびに返す値の並び（無ければ毎回同じ値）"""
        regs = list(regs or [])
        same = {"machine": {"Path": r"C:\Windows"}, "user": {}}
        return update.run(CFG, self.data, keys, out or io.StringIO(), self.runners(codes), explain=explain,
                          read_env=lambda: regs.pop(0) if regs else same)

    def test_runs_in_order(self):
        done = self.run_update(["winget:Gyan.FFmpeg", "winget:7zip.7zip"], [0, 0])
        self.assertEqual([c[3] for c in self.calls], ["Gyan.FFmpeg", "7zip.7zip"])
        self.assertIn("--exact", self.calls[0])
        self.assertNotIn("--include-pinned", self.calls[0])
        self.assertEqual([d["ok"] for d in done], [True, True])
        self.assertIsNone(done[0]["reason"])
        self.assertEqual(done[0]["env"], [])

    def test_no_silent(self):
        """--silent だと MSI が /quiet になり、古い版を消すときに UAC の確認を出せず 1603 で失敗する（2026-10-29）"""
        self.assertNotIn("--silent", update.winget_args("Microsoft.OpenJDK.21"))

    def test_env_changes_are_recorded(self):
        before = {"machine": {"JAVA_HOME": "C:\\jdk-21\\", "Path": "C:\\jdk-21\\bin"}, "user": {}}
        after = {"machine": {"JAVA_HOME": "C:\\jdk-17\\", "Path": "C:\\jdk-17\\bin;C:\\jdk-21\\bin"}, "user": {}}
        out = io.StringIO()
        done = self.run_update(["winget:Gyan.FFmpeg"], [0], out, regs=[before, after])
        self.assertEqual([(c["name"], c.get("new")) for c in done[0]["env"]], [("JAVA_HOME", "C:\\jdk-17\\"), ("PATH", None)])
        self.assertIn("-- 環境変数が変わりました:\n   マシンの JAVA_HOME: C:\\jdk-21\\ → C:\\jdk-17\\\n", out.getvalue())

    def test_unreadable_registry_does_not_stop(self):
        def broken():
            raise OSError("読めない")
        done = update.run(CFG, self.data, ["winget:Gyan.FFmpeg"], io.StringIO(), self.runners([0]),
                          explain=EXPLAIN.get, read_env=broken)
        self.assertEqual((done[0]["ok"], done[0]["env"]), (True, []))

    def test_stops_at_first_failure(self):
        """同じ理由で続けて失敗し、UAC の確認だけが続くのを避ける（2026-10-29 OpenJDK 17 → 21）"""
        out = io.StringIO()
        done = self.run_update(["winget:Gyan.FFmpeg", "winget:7zip.7zip"], [0x8A150030, 0], out)
        self.assertEqual([c[3] for c in self.calls], ["Gyan.FFmpeg"])
        self.assertEqual([d["ok"] for d in done], [False])
        self.assertEqual(done[0]["code"], "0x8A150030")
        self.assertIn("残りの 1 件は動かしていません: winget:7zip.7zip", out.getvalue())
        with open(self.data / update.HISTORY_FILE, encoding="utf-8") as f:
            hist = [json.loads(x) for x in f]
        self.assertEqual([h["key"] for h in hist], ["winget:Gyan.FFmpeg"])

    def test_winget_reason_has_both_codes(self):
        out = io.StringIO()
        done = self.run_update(["winget:Gyan.FFmpeg"], [0x8A150030], out)
        self.assertEqual(done[0]["reason"], "winget: アンインストール コマンドの実行に失敗しました\n"
                                            "インストーラの終了コード 1603: Fatal error during installation.")
        self.assertIn("   winget: アンインストール コマンドの実行に失敗しました\n", out.getvalue())

    def test_reason_when_winget_cannot_explain(self):
        done = self.run_update(["winget:Gyan.FFmpeg"], [0x8A150030], explain=lambda _c: None)
        self.assertIn("（意味を引けませんでした）", done[0]["reason"])

    def test_not_applicable_is_not_failure(self):
        done = self.run_update(["winget:7zip.7zip", "winget:Gyan.FFmpeg"], [0x8A15002B, 0])
        self.assertEqual([d["ok"] for d in done], [True, True])

    def test_no_check_yet(self):
        (self.data / check.CHECK_FILE).unlink()
        with self.assertRaises(update.Refused):
            self.run_update(["winget:7zip.7zip"], [0])

    def test_exception_stops_too(self):
        done = self.run_update(["ghostscript", "winget:7zip.7zip"], [0])
        self.assertEqual([d["ok"] for d in done], [False])
        self.assertIn("SHA-256", done[0]["tail"])
        self.assertEqual(done[0]["reason"], "RuntimeError: SHA-256 が合いません")
        self.assertEqual(self.calls, [])


class CygwinRunner(unittest.TestCase):
    def test_running_programs_stop_before_setup(self):
        """動いている物は終了させず、名前を出して止める"""
        out = io.StringIO()
        with mock.patch.object(update.cygwin, "running", return_value=["mintty.exe", "bash.exe"]), \
             mock.patch.object(update.subprocess, "run") as run:
            code, tail = update._cygwin(item("cygwin", tier="A"), CFG, Path("."), out)
        self.assertEqual(code, 1)
        self.assertIn("mintty.exe", tail)
        run.assert_not_called()

    def test_setup_args(self):
        args = update.cygwin.setup_args(Path(r"C:\x\cygwinsetup.exe"), Path(r"C:\cygwin64"),
                                        "https://ftp.jaist.ac.jp/pub/cygwin/", r"C:\dl")
        for a in ("--quiet-mode", "--wait", "--upgrade-also", "--only-site", "--no-desktop"):
            self.assertIn(a, args)
        self.assertEqual(args[args.index("--root") + 1], r"C:\cygwin64")
        self.assertEqual(args[args.index("--local-package-dir") + 1], r"C:\dl")


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
