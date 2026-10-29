"""通信の許可（design.md §3.9）。netsh の出力は tests/fixtures に小さく作って読ませる"""
import os
import subprocess
import unittest
from unittest import mock

from toolkeeper import firewall
from tests.helpers import fixture

JAVA_NEW = r"C:\Program Files\Microsoft\jdk-21.0.13.21-hotspot\bin\java.exe"
NODE = r"C:\Users\taro\AppData\Roaming\nvm\v24.22.1\node.exe"
PY314 = r"C:\Python314\python.exe"
GIT = r"C:\Program Files\Git\cmd\git.exe"
USED = {"java": JAVA_NEW, "node": NODE, "python": PY314, "git": GIT}
PRESENT = {os.path.normcase(p) for p in (JAVA_NEW, NODE, PY314, GIT, r"C:\python312\python.exe",
                                          r"C:\Windows\system32\svchost.exe")}


def exists(p):
    return os.path.normcase(os.path.normpath(p)) in PRESENT


def inspect(name="netsh_firewall_ja.txt", used=None):
    return firewall.inspect(firewall.parse_rules(fixture(name)), USED if used is None else used,
                            process_env={"SystemRoot": r"C:\Windows"}, exists=exists)


class Parse(unittest.TestCase):
    def test_japanese(self):
        rules = firewall.parse_rules(fixture("netsh_firewall_ja.txt"))
        self.assertEqual(len(rules), 6)
        self.assertEqual(rules[2], {"name": "node.exe", "enabled": True, "direction": "in", "profiles": "プライベート,パブリック",
                                    "protocol": "UDP", "program": r"C:\users\taro\appdata\roaming\nvm\v24.22.1\node.exe",
                                    "action": "block"})
        self.assertIsNone(rules[3]["program"])  # 任意
        self.assertEqual(rules[3]["direction"], "out")
        self.assertFalse(rules[4]["enabled"])
        self.assertEqual(rules[4]["name"], "リモート デスクトップ - ユーザー モード (TCP 受信)")
        # 本物の出力は CRLF（fixture はリポジトリの決まりで LF にしてある）
        self.assertEqual(firewall.parse_rules(fixture("netsh_firewall_ja.txt").replace("\n", "\r\n")), rules)

    def test_english(self):
        rules = firewall.parse_rules(fixture("netsh_firewall_en.txt"))
        self.assertEqual([(r["name"], r["action"], r["direction"], r["enabled"]) for r in rules],
                         [("OpenJDK Platform binary", "allow", "in", True), ("node.exe", "block", "in", True),
                          ("Core Networking - DNS (UDP-Out)", "allow", "out", True)])
        self.assertIsNone(rules[2]["program"])

    @mock.patch.object(firewall, "OEM", "cp932")  # GitHub のランナーは英語の Windows で OEM が cp437
    def test_decode_utf8_and_oem(self):
        """UTF-8 で読めなければ OEM のコード ページで読む（日本語の Windows の古い netsh は cp932 で書く）"""
        text = fixture("netsh_firewall_ja.txt")
        self.assertEqual(firewall.decode(text.encode("utf-8")), text)
        self.assertEqual(firewall.decode(text.encode("cp932")), text)

    @mock.patch.object(firewall, "OEM", "cp932")
    def test_netsh_failure(self):
        def run(args, **kw):
            self.assertEqual(args, firewall.NETSH)
            return subprocess.CompletedProcess(args, 1, "サービスが動いていません".encode("cp932"), b"")
        with self.assertRaises(RuntimeError) as e:
            firewall.read_rules(run)
        self.assertIn("サービスが動いていません", str(e.exception))

    def test_read_rules(self):
        raw = fixture("netsh_firewall_en.txt").encode("utf-8")
        rules = firewall.read_rules(lambda args, **kw: subprocess.CompletedProcess(args, 0, raw, b""))
        self.assertEqual(len(rules), 3)


class Inspect(unittest.TestCase):
    def test_states_and_order(self):
        rows = inspect()
        self.assertEqual([(r["state"], r["tool"], r["name"]) for r in rows], [
            ("block", "node", "node.exe"),
            ("none", "java", "-"),        # 上げて場所が変わり、新しい場所に規則が無い
            ("none", "python", "-"),      # python312 には規則があるが、使っている 3.14 には無い
            ("gone", "java（ほかの場所）", "OpenJDK Platform binary"),
            ("allow", "python（ほかの場所）", "Python"),
            ("off", "", "リモート デスクトップ - ユーザー モード (TCP 受信)"),
        ])
        self.assertEqual(rows[1]["program"], JAVA_NEW)
        self.assertEqual(len({r["id"] for r in rows}), len(rows))

    def test_tcp_and_udp_are_one_row(self):
        gone = next(r for r in inspect() if r["state"] == "gone")
        self.assertEqual(gone["protocol"], "UDP, TCP")

    def test_program_is_expanded(self):
        off = next(r for r in inspect() if r["state"] == "off")
        self.assertEqual(off["program"], r"C:\Windows\system32\svchost.exe")

    def test_no_rule_only_when_another_place_has_one(self):
        """git のように規則がどこにも無い物は「規則が無い」にしない（外から接続を受けない）"""
        self.assertNotIn("git", [r["tool"] for r in inspect()])
        rows = inspect(used={})
        self.assertNotIn("none", [r["state"] for r in rows])
        self.assertEqual({r["tool"] for r in rows}, {""})

    def test_counts(self):
        self.assertEqual(firewall.counts(inspect()), {"block": 1, "none": 2, "gone": 1, "allow": 1, "off": 1})


class Commands(unittest.TestCase):
    def test_links_are_followed_and_store_aliases_skipped(self):
        local = r"C:\Users\taro\AppData\Local"
        reg = {"machine": {"Path": r"C:\nvm\nodejs;%LOCALAPPDATA%\Microsoft\WindowsApps"}, "user": {}}
        files = {os.path.normcase(p) for p in (r"C:\nvm\nodejs\node.exe", local + r"\Microsoft\WindowsApps\python.exe")}
        used = firewall.commands(reg, ["node", "python", "git"], process_env={"LOCALAPPDATA": local, "PATHEXT": ".EXE"},
                                 isfile=lambda p: os.path.normcase(p) in files,
                                 realpath=lambda p: p.replace("nodejs", "v24.22.1"))
        self.assertEqual(used, {"node": r"C:\nvm\v24.22.1\node.exe"})


if __name__ == "__main__":
    unittest.main()
