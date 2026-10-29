"""環境変数と PATH（design.md §3.7）。レジストリもファイルも作り物で、本物の PC は見ない"""
import unittest

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
]}
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


def inspect(commands=("java", "cmake", "python", "php", "gh", "curl")):
    return env.inspect(REG, ["JAVA_HOME", "JDK_HOME", "PHPRC", "GS_LIB"], list(commands), PROC, exists, isfile)


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
        self.assertEqual([f["value"] for f in pick(inspect(), "path-missing")], ["C:\\Python313\\Scripts\\\\"])

    def test_duplicates_are_info_and_point_at_the_later_one(self):
        dups = pick(inspect(), "path-dup")
        self.assertEqual([(f["scope"], f["value"]) for f in dups],
                         [("machine", r"%SystemRoot%\system32"), ("user", r"C:\Program Files\Microsoft\jdk-21.0.9.10-hotspot\bin")])
        self.assertTrue(all(f["state"] == "info" for f in dups))

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


if __name__ == "__main__":
    unittest.main()
