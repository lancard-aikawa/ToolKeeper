import unittest

from toolkeeper import winget
from tests.helpers import fixture


class ParseUpgrade(unittest.TestCase):
    def setUp(self):
        self.r = winget.parse(fixture("winget_upgrade.txt"))
        self.by_id = {x["id"]: x for x in self.r["items"]}

    def test_all_rows(self):
        self.assertEqual(sorted(self.by_id), sorted([
            "7zip.7zip", "Microsoft.WSL", "Nvidia.PhysX", "Python.Launcher", "Zoom.Zoom.EXE",
            "OpenJS.NodeJS.20", "Gyan.FFmpeg", "GitHub.cli", "Microsoft.OpenJDK.17"]))
        self.assertTrue(all(x["source"] == "winget" for x in self.r["items"]))

    def test_japanese_name_keeps_columns(self):
        """全角を 2 桁と数えないと、日本語の名前の行だけ ID と版がずれる"""
        wsl = self.by_id["Microsoft.WSL"]
        self.assertEqual(wsl["name"], "Linux 用 Windows サブシステム")
        self.assertEqual((wsl["version"], wsl["available"]), ("2.3.26.0", "2.7.14"))
        self.assertEqual(self.by_id["Nvidia.PhysX"]["available"], "9.26.0703")

    def test_versions_with_spaces(self):
        self.assertEqual(self.by_id["Zoom.Zoom.EXE"]["version"], "7.1.9 (48550)")
        self.assertEqual(self.by_id["Zoom.Zoom.EXE"]["available"], "7.2.1 (48556)")
        self.assertEqual(self.by_id["Python.Launcher"]["version"], "< 3.14.7")

    def test_counts_after_table(self):
        self.assertEqual((self.r["unknown"], self.r["pinned"]), (1, 1))


class ParseList(unittest.TestCase):
    def test_list_has_no_source_column(self):
        r = winget.parse(fixture("winget_list.txt"))
        by_id = {x["id"]: x for x in r["items"]}
        self.assertIn("Microsoft.AppInstaller", by_id)
        self.assertEqual(by_id["Python.Python.3.12"]["available"], "")
        self.assertEqual(by_id["OpenJS.NodeJS.20"]["available"], "20.20.2")
        self.assertEqual(by_id["Microsoft.WSL"]["version"], "2.3.26.0")


class ParseOtherLanguage(unittest.TestCase):
    def test_english_header_and_second_table(self):
        text = (
            "Name        Id            Version  Available Source\r\n"
            "---------------------------------------------------\r\n"
            "Foo Tool    Foo.Tool      1.0      1.1       winget\r\n"
            "2 upgrades available.\r\n"
            "\r\n"
            "The following packages have an upgrade available, but require explicit targeting for upgrade:\r\n"
            "Name        Id            Version  Available Source\r\n"
            "---------------------------------------------------\r\n"
            "Bar         Bar.Bar       2.0      3.0       winget\r\n"
            "3 package(s) have pins that prevent upgrade. Use the 'winget pin' command ... '--include-pinned' ...\r\n"
        )
        r = winget.parse(text)
        self.assertEqual([x["id"] for x in r["items"]], ["Foo.Tool", "Bar.Bar"])
        self.assertEqual(r["pinned"], 3)

    def test_nothing(self):
        self.assertEqual(winget.parse("No installed package found matching input criteria.\r\n")["items"], [])


if __name__ == "__main__":
    unittest.main()
