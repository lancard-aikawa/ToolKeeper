"""環境変数と PATH（design.md §3.7）。レジストリもファイルも作り物で、本物の PC は見ない"""
import json
import tempfile
import unittest
from pathlib import Path

from toolkeeper import env

PROC = {"SystemRoot": r"C:\WINDOWS", "LOCALAPPDATA": r"C:\Users\x\AppData\Local", "USERPROFILE": r"C:\Users\x",
        "PATH": r"C:\work\php-8.3.7-nts-Win32-vs16-x64", "PATHEXT": ".COM;.EXE;.BAT;.CMD"}

REG = {
    "machine": {
        "Path": ";".join([
            r"C:\WINDOWS\system32",
            r"%SystemRoot%\system32",
            r"C:\Program Files\Microsoft\jdk-21.0.9.10-hotspot\bin",
            r"C:\Strawberry\c\bin",
            r"C:\Program Files\CMake\bin",
            r"C:\Program Files\gs\gs10.08.0\bin",
            r"C:\Python313\Scripts\\",
            "",
        ]),
        "JAVA_HOME": r"C:\Program Files\Microsoft\jdk-21.0.9.10-hotspot\\",
        "PHPCONF": r"C:\work\php-conf",
    },
    "user": {
        "PATH": ";".join([
            r"%LOCALAPPDATA%\Microsoft\WindowsApps",
            r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\PHP.PHP.NTS.8.3_Microsoft.Winget.Source_8wekyb3d8bbwe",
            r"C:\Program Files\Microsoft\jdk-21.0.9.10-hotspot\bin",
            r"C:\Qt\6.9.1\mingw_64\bin",
        ]),
        "PHPRC": "%PHPCONF%",
        "JDK_HOME": r"C:\Program Files\Microsoft\jdk-17.0.1-hotspot",
    },
}

DIRS = {env.norm(d) for d in [
    r"C:\WINDOWS\system32", r"C:\Program Files\Microsoft\jdk-21.0.9.10-hotspot", r"C:\Program Files\Microsoft\jdk-21.0.9.10-hotspot\bin",
    r"C:\Strawberry\c\bin", r"C:\Program Files\CMake\bin", r"C:\Program Files\gs\gs10.08.0\bin", r"C:\work\php-conf",
    r"C:\Users\x\AppData\Local\Microsoft\WindowsApps",
    r"C:\Users\x\AppData\Local\Microsoft\WinGet\Packages\PHP.PHP.NTS.8.3_Microsoft.Winget.Source_8wekyb3d8bbwe",
    r"C:\Program Files\Microsoft\jdk-17.0.17.10-hotspot",
    r"C:\Qt\6.10.0\mingw_64\bin", r"C:\Qt\6.8.0\mingw_64\bin", r"C:\Qt\7.0.0\mingw_64\bin",
]}
# フォルダの中身（向け直し先を探すときに見る）
LISTING = {
    env.norm(r"C:\Program Files\Microsoft"): ["jdk-11.0.16.101-hotspot", "jdk-17.0.17.10-hotspot", "jdk-21.0.9.10-hotspot"],
    env.norm(r"C:\Qt"): ["6.8.0", "6.10.0", "7.0.0", "Tools"],
}
FILES = {env.norm(f) for f in [
    r"C:\Program Files\Microsoft\jdk-21.0.9.10-hotspot\bin\java.exe",
    r"C:\Strawberry\c\bin\cmake.exe",
    r"C:\Program Files\CMake\bin\cmake.exe",
    r"C:\Users\x\AppData\Local\Microsoft\WindowsApps\python.exe",
    r"C:\Strawberry\c\bin\python.exe",
    r"C:\Users\x\AppData\Local\Microsoft\WindowsApps\gh.exe",
    r"C:\Users\x\AppData\Local\Microsoft\WinGet\Packages\PHP.PHP.NTS.8.3_Microsoft.Winget.Source_8wekyb3d8bbwe\gh.exe",
    r"C:\Users\x\AppData\Local\Microsoft\WinGet\Packages\PHP.PHP.NTS.8.3_Microsoft.Winget.Source_8wekyb3d8bbwe\php.exe",
    r"C:\WINDOWS\system32\curl.exe",
]}


def exists(p):
    return env.norm(p) in DIRS or env.norm(p) in FILES


def isfile(p):
    return env.norm(p) in FILES


def listdir(p):
    try:
        return LISTING[env.norm(p)]
    except KeyError:
        raise FileNotFoundError(p) from None


def inspect(commands=("java", "cmake", "python", "php", "gh", "curl")):
    return env.inspect(REG, ["JAVA_HOME", "JDK_HOME", "PHPRC", "GS_LIB"], list(commands), PROC, exists, isfile, listdir)


def pick(found, kind, name=None):
    return [f for f in found if f["kind"] == kind and (name is None or f["name"] == name)]


class Expand(unittest.TestCase):
    def test_expand_is_case_insensitive_and_keeps_unknown(self):
        self.assertEqual(env.expand(r"%systemroot%\x;%NOPE%\y", PROC), r"C:\WINDOWS\x;%NOPE%\y")

    def test_user_vars_can_use_machine_vars(self):
        self.assertEqual(env.base_env(REG, PROC)["PHPRC"], r"C:\work\php-conf")

    def test_path_is_machine_then_user(self):
        rows = env.path_entries(REG, env.base_env(REG, PROC))
        self.assertEqual(rows[0]["scope"], "machine")
        self.assertEqual(rows[-1]["scope"], "user")
        self.assertEqual(rows[1]["dir"], r"C:\WINDOWS\system32")


class Which(unittest.TestCase):
    def test_uses_registry_path_not_process_path(self):
        """プロセスの PATH は乗り換え前の PHP を指していても、レジストリの PATH で探す（2026-10-28 の件）"""
        exe = env.which("php", REG, PROC, isfile)
        self.assertIn(r"\WinGet\Packages\PHP.PHP.NTS.8.3", exe)

    def test_not_found(self):
        self.assertIsNone(env.which("nothing", REG, PROC, isfile))


class Inspect(unittest.TestCase):
    def test_vars(self):
        found = {f["name"]: f for f in pick(inspect(), "var")}
        self.assertEqual(found["JAVA_HOME"]["state"], "warn")  # 版の入ったフォルダ
        self.assertEqual(found["JDK_HOME"]["state"], "bad")    # 無いフォルダ
        self.assertEqual((found["PHPRC"]["state"], found["PHPRC"]["value"]), ("ok", "%PHPCONF%"))
        self.assertNotIn("GS_LIB", found)                      # 無い変数は出さない

    def test_missing_path_entry(self):
        self.assertEqual([f["value"] for f in pick(inspect(), "path-missing")],
                         ["C:\\Python313\\Scripts\\\\", r"C:\Qt\6.9.1\mingw_64\bin"])

    def test_duplicates_are_info_and_point_at_the_later_one(self):
        dups = pick(inspect(), "path-dup")
        self.assertEqual([(f["scope"], f["value"]) for f in dups],
                         [("machine", r"%SystemRoot%\system32"), ("user", r"C:\Program Files\Microsoft\jdk-21.0.9.10-hotspot\bin")])
        self.assertTrue(all(f["state"] == "info" for f in dups))
        # 書き方が違う相手でも分かるよう、相手の行と展開した値を書く（2026-10-29 の画面で、重複に見えなかった）
        self.assertIn(r"C:\WINDOWS\system32 と同じフォルダ（展開すると C:\WINDOWS\system32）", dups[0]["detail"])
        self.assertNotIn("展開すると", dups[1]["detail"])  # 書いてあるままの行には付けない

    def test_versioned_path_but_not_ghostscript(self):
        values = [f["value"] for f in pick(inspect(), "path-versioned")]
        self.assertEqual(values, [r"C:\Program Files\Microsoft\jdk-21.0.9.10-hotspot\bin"])

    def test_shadow(self):
        found = inspect()
        cmake = pick(found, "shadow", "cmake")[0]
        self.assertEqual(cmake["value"], r"C:\Strawberry\c\bin\cmake.exe")
        self.assertIn(r"C:\Program Files\CMake\bin\cmake.exe", cmake["detail"])
        self.assertEqual(pick(found, "shadow", "java"), [])  # 同じフォルダの重複は 1 つと数える
        self.assertEqual(pick(found, "shadow", "curl"), [])

    def test_store_alias_counts_only_when_first(self):
        found = inspect()
        self.assertEqual(pick(found, "shadow", "python"), [])  # WindowsApps の物は後ろにあるだけなら数えない
        gh = pick(found, "shadow", "gh")[0]                     # 先頭にあると、そちらが使われるので出す
        self.assertIn(r"\WindowsApps\gh.exe", gh["value"])
        self.assertEqual(pick(found, "shadow", "php"), [])

    def test_order_and_count(self):
        found = inspect()
        states = [f["state"] for f in found]
        self.assertEqual(states, sorted(states, key=env.STATE_ORDER.get))
        self.assertEqual(env.problems(found), sum(1 for s in states if s in ("bad", "warn")))


class Fixes(unittest.TestCase):
    def test_missing_versioned_folder_points_to_newest_same_major(self):
        """jdk-17.0.1 が消えていれば jdk-17.0.17.10 に。6.9.1 なら 6.8.0 ではなく 6.10.0 に（数で比べる。7 は越えない）"""
        found = inspect()
        jdk = pick(found, "var", "JDK_HOME")[0]
        self.assertEqual(jdk["fix"], {"action": "set", "to": r"C:\Program Files\Microsoft\jdk-17.0.17.10-hotspot", "pos": None})
        qt = [f for f in pick(found, "path-missing") if "Qt" in f["value"]][0]
        self.assertEqual(qt["fix"]["action"], "replace")
        self.assertEqual(qt["fix"]["to"], r"C:\Qt\6.10.0\mingw_64\bin")

    def test_missing_without_successor_is_removed(self):
        py = [f for f in pick(inspect(), "path-missing") if "Python313" in f["value"]][0]
        self.assertEqual(py["fix"]["action"], "remove")

    def test_dups_are_removable_and_warnings_have_no_fix(self):
        found = inspect()
        self.assertTrue(all(f["fix"]["action"] == "remove" for f in pick(found, "path-dup")))
        for kind in ("path-versioned", "shadow"):
            self.assertTrue(all(f["fix"] is None for f in pick(found, kind)), kind)
        self.assertIsNone(pick(found, "var", "JAVA_HOME")[0]["fix"])  # 今は在る。切れてから直す

    def test_ids_are_unique(self):
        ids = [f["id"] for f in inspect()]
        self.assertEqual(len(ids), len(set(ids)))


class Plan(unittest.TestCase):
    def test_several_fixes_on_one_path_become_one_write(self):
        found = inspect()
        dup = pick(found, "path-dup")[0]  # マシンの %SystemRoot%\system32
        py = [f for f in pick(found, "path-missing") if "Python313" in f["value"]][0]
        writes = env.plan(REG, found, [dup["id"], py["id"]])
        self.assertEqual(len(writes), 1)
        w = writes[0]
        self.assertEqual((w["scope"], w["name"], w["old"]), ("machine", "Path", REG["machine"]["Path"]))
        self.assertEqual(w["new"].split(";"), [
            r"C:\WINDOWS\system32", r"C:\Program Files\Microsoft\jdk-21.0.9.10-hotspot\bin", r"C:\Strawberry\c\bin",
            r"C:\Program Files\CMake\bin", r"C:\Program Files\gs\gs10.08.0\bin", ""])
        self.assertEqual(len(w["changes"]), 2)

    def test_user_and_machine_are_separate_writes(self):
        found = inspect()
        ids = [pick(found, "var", "JDK_HOME")[0]["id"], [f for f in pick(found, "path-missing") if "Qt" in f["value"]][0]["id"]]
        writes = {(w["scope"], w["name"]): w for w in env.plan(REG, found, ids)}
        self.assertEqual(writes[("user", "JDK_HOME")]["new"], r"C:\Program Files\Microsoft\jdk-17.0.17.10-hotspot")
        self.assertTrue(writes[("user", "PATH")]["new"].endswith(r"C:\Qt\6.10.0\mingw_64\bin"))  # 名前は書いてあるまま

    def test_refuses_unknown_or_unfixable(self):
        found = inspect()
        with self.assertRaises(env.Refused):
            env.plan(REG, found, ["path-dup:machine:1:00000000"])
        with self.assertRaises(env.Refused):
            env.plan(REG, found, [pick(found, "shadow", "cmake")[0]["id"]])


class FakeRegistry:
    def __init__(self, reg):
        self.reg = json.loads(json.dumps(reg))
        self.machine_calls = 0
        self.broadcasts = 0

    def read(self, scope, name):
        return env._get(self.reg[scope], name)

    def write_user(self, name, old, new):
        self.reg["user"][env._real_name(self.reg["user"], name)] = new

    def write_machine(self, writes, data):
        self.machine_calls += 1
        for w in writes:
            self.reg["machine"][env._real_name(self.reg["machine"], w["name"])] = w["new"]

    def broadcast(self):
        self.broadcasts += 1


class Apply(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        self.fake = FakeRegistry(REG)

    def tearDown(self):
        self.tmp.cleanup()

    def fix(self, *pred):
        found = env.inspect(self.fake.reg, ["JAVA_HOME", "JDK_HOME"], [], PROC, exists, isfile, listdir)
        ids = [f["id"] for f in found if f.get("fix") and any(p(f) for p in pred)]
        return env.apply(env.plan(self.fake.reg, found, ids), self.data, self.fake)

    def test_machine_writes_share_one_elevation_and_history_is_kept(self):
        self.fix(lambda f: f["kind"] == "path-dup" and f["scope"] == "machine", lambda f: "Python313" in f["value"],
                 lambda f: f["name"] == "JDK_HOME")
        self.assertEqual(self.fake.machine_calls, 1)
        self.assertEqual(self.fake.broadcasts, 1)
        self.assertNotIn("Python313", self.fake.reg["machine"]["Path"])
        self.assertEqual(self.fake.reg["user"]["JDK_HOME"], r"C:\Program Files\Microsoft\jdk-17.0.17.10-hotspot")
        hist = env.history(self.data)
        self.assertEqual(sorted((h["scope"], h["name"]) for h in hist), [("machine", "Path"), ("user", "JDK_HOME")])

    def test_refuses_when_value_changed_after_choosing(self):
        found = env.inspect(self.fake.reg, [], [], PROC, exists, isfile, listdir)
        writes = env.plan(self.fake.reg, found, [pick(found, "path-dup")[0]["id"]])
        self.fake.reg["machine"]["Path"] += r";C:\new"
        with self.assertRaises(env.Refused):
            env.apply(writes, self.data, self.fake)
        self.assertEqual(self.fake.machine_calls, 0)
        self.assertEqual(env.history(self.data), [])

    def test_undo_one_by_one(self):
        self.fix(lambda f: f["name"] == "JDK_HOME")
        self.fix(lambda f: "Python313" in f["value"])
        env.apply([env.undo_plan(self.data)], self.data, self.fake)  # Python313 の削除を戻す
        self.assertEqual(self.fake.reg["machine"]["Path"], REG["machine"]["Path"])
        self.assertEqual(self.fake.reg["user"]["JDK_HOME"], r"C:\Program Files\Microsoft\jdk-17.0.17.10-hotspot")
        env.apply([env.undo_plan(self.data)], self.data, self.fake)  # JDK_HOME を戻す
        self.assertEqual(self.fake.reg["user"]["JDK_HOME"], REG["user"]["JDK_HOME"])
        with self.assertRaises(env.Refused):
            env.undo_plan(self.data)  # 戻した物は戻さない

    def test_undo_refuses_when_changed_since(self):
        self.fix(lambda f: f["name"] == "JDK_HOME")
        self.fake.reg["user"]["JDK_HOME"] = r"C:\elsewhere"
        with self.assertRaises(env.Refused):
            env.apply([env.undo_plan(self.data)], self.data, self.fake)


if __name__ == "__main__":
    unittest.main()


class Changes(unittest.TestCase):
    """更新の前後の違い（2026-10-29、OpenJDK 17 のインストーラが JAVA_HOME と PATH の先頭を 17 にした）"""
    BEFORE = {"machine": {"JAVA_HOME": r"C:\jdk-21", "Path": r"C:\jdk-21\bin;C:\Windows;C:\Git\cmd"},
              "user": {"Path": r"C:\Users\x\bin"}}

    def test_same(self):
        self.assertEqual(env.changes(self.BEFORE, self.BEFORE, ["JAVA_HOME"]), [])

    def test_installer_takes_over(self):
        after = {"machine": {"JAVA_HOME": r"C:\jdk-17", "Path": r"C:\jdk-17\bin;C:\jdk-21\bin;C:\Windows;C:\Git\cmd"},
                 "user": {"Path": r"C:\Users\x\bin"}}
        got = env.changes(self.BEFORE, after, ["JAVA_HOME"])
        self.assertEqual(got, [
            {"scope": "machine", "name": "JAVA_HOME", "old": r"C:\jdk-21", "new": r"C:\jdk-17"},
            {"scope": "machine", "name": "PATH", "added": [r"C:\jdk-17\bin"], "removed": [], "moved": False,
             "head": r"C:\jdk-17\bin"}])
        self.assertEqual(env.change_text(got[1]), r"マシンの PATH: 先頭が C:\jdk-17\bin になった。足された C:\jdk-17\bin")

    def test_removed_and_case_only(self):
        after = {"machine": {"Path": r"c:\JDK-21\BIN;C:\Windows"}, "user": {"Path": r"C:\Users\x\bin"}}
        got = env.changes(self.BEFORE, after, ["JAVA_HOME"])
        self.assertEqual(got[0], {"scope": "machine", "name": "JAVA_HOME", "old": r"C:\jdk-21", "new": None})
        self.assertEqual(got[1]["removed"], [r"C:\Git\cmd"])
        self.assertEqual((got[1]["added"], got[1]["head"]), ([], None))  # 大文字小文字だけの違いは同じ行
        self.assertEqual(env.change_text(got[0]), r"マシンの JAVA_HOME: C:\jdk-21 → （消えた）")

    def test_order_only(self):
        after = {"machine": {"JAVA_HOME": r"C:\jdk-21", "Path": r"C:\jdk-21\bin;C:\Git\cmd;C:\Windows"},
                 "user": {"Path": r"C:\Users\x\bin"}}
        got = env.changes(self.BEFORE, after, ["JAVA_HOME"])
        self.assertEqual(env.change_text(got[0]), "マシンの PATH: 順番が変わった")
