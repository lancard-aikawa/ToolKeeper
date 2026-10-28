import copy
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from toolkeeper import check, cygwin, eol, ghostscript, winget
from toolkeeper.config import DEFAULTS
from tests.helpers import fixture


class FakeLookup:
    def __init__(self, fail=()):
        self.fail = set(fail)

    def get(self, product, cycle):
        if product in self.fail:
            raise OSError("つながらない")
        try:
            cycles = json.loads(fixture(f"eol_{product}.json"))
        except OSError:
            return None
        return eol.state(cycles, product, cycle, date(2026, 10, 28))


class Fake(check.Sources):
    """本物の winget・choco・ネットを使わない"""

    def __init__(self, **over):
        self.over = over
        self.cyg_root_seen = None

    def winget_upgrades(self):
        if "winget" in self.over:
            raise self.over["winget"]
        return winget.parse(fixture("winget_upgrade.txt"))

    def winget_installed(self):
        return winget.parse(fixture("winget_list.txt"))

    def choco_available(self):
        return True

    def choco_outdated(self):
        from toolkeeper import choco
        return choco.parse(fixture("choco_outdated.txt"))

    def gs_installed(self):
        return self.over.get("gs_installed", ["9.56.1", "10.05.1"])

    def gs_latest(self, cache, hours):
        if "gs" in self.over:
            raise self.over["gs"]
        return ghostscript.parse_release(json.loads(fixture("gs_release.json")))

    def cyg_installed(self, root):
        return cygwin.parse_installed(fixture("installed.db"))

    def cyg_setup_rc(self, root):
        return cygwin.parse_setup_rc(fixture("setup.rc"))

    def cyg_latest(self, mirror, cache, hours):
        self.mirror_seen = mirror
        return cygwin.parse_setup_ini(fixture("setup.ini"))

    def cyg_running(self, root):
        return ["mintty.exe"]

    def php(self):
        return self.over.get("php", ("8.3.7", r"C:\work\php-8.3.7-nts-Win32-vs16-x64\php.exe"))

    def eol(self, cache, hours, today):
        return FakeLookup(self.over.get("eol_fail", ()))


class Run(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name) / "data"
        root = Path(self.tmp.name) / "cygwin64"
        (root / "etc" / "setup").mkdir(parents=True)
        (root / "etc" / "setup" / "installed.db").write_text("INSTALLED.DB 3\n", encoding="utf-8")
        self.cfg = copy.deepcopy(DEFAULTS)
        self.cfg["cygwin_root"] = str(root)

    def tearDown(self):
        self.tmp.cleanup()

    def run_check(self, **over):
        return check.run(self.cfg, self.data, Fake(**over))

    def by_key(self, result):
        return {it["key"]: it for it in result["items"]}

    def test_tiers(self):
        items = self.by_key(self.run_check())
        self.assertEqual(items["winget:Gyan.FFmpeg"]["tier"], "B")
        self.assertEqual(items["winget:Microsoft.WSL"]["tier"], "C")
        self.assertEqual(items["choco:gh"]["tier"], "D")
        self.assertEqual(items["php"]["tier"], "A")
        self.assertEqual(items["ghostscript"]["tier"], "A")
        self.assertEqual(items["cygwin"]["tier"], "A")

    def test_eol_moves_to_e(self):
        node = self.by_key(self.run_check())["winget:OpenJS.NodeJS.20"]
        self.assertEqual(node["tier"], "E")
        self.assertEqual(node["eol"], {"product": "nodejs", "cycle": "20", "date": "2026-04-30", "state": "ended"})

    def test_eol_only_items_without_updates_are_not_listed_when_ok(self):
        items = self.by_key(self.run_check())
        self.assertNotIn("winget:Python.Python.3.12", items)  # 更新も無く、サポート中
        self.assertIsNone(items["winget:Microsoft.WSL"]["eol"])

    def test_php_manual_install(self):
        php = self.by_key(self.run_check())["php"]
        self.assertEqual((php["installed"], php["latest"], php["updatable"]), ("8.3.7", "8.3.36", True))
        self.assertEqual(php["notes"], ["manual"])

    def test_php_from_winget_is_left_to_winget_row(self):
        exe = r"C:\Users\x\AppData\Local\Microsoft\WinGet\Links\php.exe"
        self.assertNotIn("php", self.by_key(self.run_check(php=("8.3.36", exe))))

    def test_ghostscript(self):
        gs = self.by_key(self.run_check())["ghostscript"]
        self.assertEqual((gs["installed"], gs["latest"], gs["updatable"]), ("10.05.1", "10.08.0", True))
        self.assertEqual(gs["notes"], ["old:9.56.1"])
        up = self.by_key(self.run_check(gs_installed=["10.08.0"]))["ghostscript"]
        self.assertFalse(up["updatable"])

    def test_cygwin(self):
        cyg = self.by_key(self.run_check())["cygwin"]
        self.assertEqual((cyg["installed"], cyg["latest"]), ("3.6.0-1", "3.6.12-1"))
        self.assertEqual(cyg["packages"], {"installed": 5, "outdated": 2, "names": ["bash", "cygwin"]})
        self.assertEqual(cyg["notes"], ["running:mintty.exe"])

    def test_cygwin_missing_is_skipped(self):
        self.cfg["cygwin_root"] = str(Path(self.tmp.name) / "nowhere")
        self.assertNotIn("cygwin", self.by_key(self.run_check()))

    def test_choco_twins_and_pins(self):
        items = self.by_key(self.run_check())
        self.assertEqual(items["choco:gh"]["notes"], ["twin:winget:GitHub.cli"])
        self.assertEqual(items["choco:jq"]["notes"], ["pinned"])

    def test_pinned_count(self):
        self.assertEqual(self.by_key(self.run_check())["winget:(pinned)"]["notes"], ["pinned:1"])

    def test_summary(self):
        r = self.run_check()
        # A: php・ghostscript・cygwin、B: 7zip・FFmpeg・gh・OpenJDK 17・Python Launcher
        # サポート終了: Node.js 20（終了）と OpenJDK 17（材料では 2027-01-15 で、90 日以内）
        self.assertEqual(r["summary"], {"updatable": 8, "eol": 2, "new": 0, "failed": 0})
        jdk = self.by_key(r)["winget:Microsoft.OpenJDK.17"]
        self.assertEqual((jdk["tier"], jdk["eol"]["state"]), ("B", "soon"))
        self.assertEqual(r["schema"], check.SCHEMA)

    def test_order(self):
        tiers = [it["tier"] for it in self.run_check()["items"]]
        self.assertEqual(tiers, sorted(tiers, key=check.TIER_ORDER.get))
        self.assertEqual(tiers[0], "E")

    def test_one_source_failing_keeps_others(self):
        r = self.run_check(winget=RuntimeError("winget upgrade が失敗しました"), gs=OSError("GitHub に接続できない"))
        self.assertEqual([f["source"] for f in r["failed"]], ["winget", "ghostscript"])
        items = self.by_key(r)
        self.assertIn("cygwin", items)
        self.assertIsNone(items["ghostscript"]["latest"])
        self.assertFalse(any(k.startswith("winget:") for k in items))

    def test_eol_failure_is_reported(self):
        r = self.run_check(eol_fail=["nodejs"])
        self.assertIn("endoflife.date (nodejs)", [f["source"] for f in r["failed"]])

    def test_new_compares_with_previous(self):
        self.run_check()
        prev = json.loads((self.data / check.CHECK_FILE).read_text(encoding="utf-8"))
        for it in prev["items"]:
            if it["key"] == "winget:Gyan.FFmpeg":
                it["latest"] = "9.0.1"
        prev["items"] = [it for it in prev["items"] if it["key"] != "ghostscript"]
        (self.data / check.CHECK_FILE).write_text(json.dumps(prev), encoding="utf-8")
        r = self.run_check()
        self.assertEqual(sorted(it["key"] for it in r["items"] if it["new"]), ["ghostscript", "winget:Gyan.FFmpeg"])
        self.assertEqual(r["summary"]["new"], 2)

    def test_no_local_paths_in_check_json(self):
        """RepoTether が画面の画像を撮ることがあるので、手元のパスを入れない（§9.1）"""
        self.run_check()
        text = (self.data / check.CHECK_FILE).read_text(encoding="utf-8")
        self.assertNotIn(":\\\\", text)
        self.assertNotIn(self.tmp.name.replace("\\", "\\\\"), text)


if __name__ == "__main__":
    unittest.main()
