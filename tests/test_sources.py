"""choco・Cygwin・Ghostscript・endoflife.date の読み方"""
import json
import unittest
from datetime import date

from toolkeeper import choco, cygwin, eol, ghostscript
from toolkeeper.config import DEFAULTS
from tests.helpers import fixture


class Choco(unittest.TestCase):
    def test_parse(self):
        rows = choco.parse(fixture("choco_outdated.txt") + "Chocolatey v2.5.1\nnot|a|row\n")
        self.assertEqual([r["name"] for r in rows], ["chocolatey", "gh", "python", "jq"])
        self.assertEqual(rows[2]["available"], "3.15.2")
        self.assertTrue(rows[3]["pinned"])


class Cygwin(unittest.TestCase):
    def test_installed(self):
        got = cygwin.parse_installed(fixture("installed.db"))
        self.assertEqual(got["alternatives"], "1.31-1")
        self.assertEqual(got["_autorebase"], "001091-1")
        self.assertEqual(got["cygwin"], "3.6.0-1")

    def test_setup_ini_uses_first_version(self):
        """[prev] と [test] の後の version: は使わない"""
        got = cygwin.parse_setup_ini(fixture("setup.ini"))
        self.assertEqual(got, {"_autorebase": "001091-1", "alternatives": "1.31-1", "bash": "5.2.37-1",
                               "cygwin": "3.6.12-1"})

    def test_mirror(self):
        rc = cygwin.parse_setup_rc(fixture("setup.rc"))
        self.assertEqual(cygwin.mirror(rc), "https://ftp.jaist.ac.jp/pub/cygwin/")
        self.assertEqual(cygwin.mirror({}), cygwin.DEFAULT_MIRROR)

    def test_outdated_ignores_packages_missing_from_mirror(self):
        have = cygwin.parse_installed(fixture("installed.db"))
        cur = cygwin.parse_setup_ini(fixture("setup.ini"))
        self.assertEqual(cygwin.outdated(have, cur), ["bash", "cygwin"])


class Ghostscript(unittest.TestCase):
    def test_tag_version(self):
        self.assertEqual(ghostscript.tag_version("gs10080"), "10.08.0")
        self.assertEqual(ghostscript.tag_version("gs10051"), "10.05.1")
        self.assertEqual(ghostscript.tag_version("gs9561"), "9.56.1")
        self.assertIsNone(ghostscript.tag_version("v1.0"))

    def test_release_picks_w64(self):
        rel = ghostscript.parse_release(json.loads(fixture("gs_release.json")))
        self.assertEqual(rel["version"], "10.08.0")
        self.assertEqual(rel["asset"], "gs10080w64.exe")
        self.assertEqual(rel["sha256"], "52a91b8bf09298788d7a57b9206127026c23eacd75405f0a131e26dc381dce50")

    def test_vkey(self):
        self.assertGreater(ghostscript.vkey("10.08.0"), ghostscript.vkey("10.05.1"))
        self.assertGreater(ghostscript.vkey("10.10.0"), ghostscript.vkey("10.9.0"))


class Eol(unittest.TestCase):
    def test_match_default_rules(self):
        rules = DEFAULTS["eol"]
        self.assertEqual(eol.match(rules, "OpenJS.NodeJS.20"), ("nodejs", "20"))
        self.assertEqual(eol.match(rules, "Python.Python.3.14"), ("python", "3.14"))
        self.assertEqual(eol.match(rules, "PHP.PHP.NTS.8.3"), ("php", "8.3"))
        self.assertEqual(eol.match(rules, "PHP.PHP.8.4"), ("php", "8.4"))
        self.assertEqual(eol.match(rules, "Microsoft.OpenJDK.17"), ("microsoft-build-of-openjdk", "17"))
        self.assertEqual(eol.match(rules, "EclipseAdoptium.Temurin.8.JRE"), ("eclipse-temurin", "8"))
        self.assertIsNone(eol.match(rules, "Python.Launcher"))
        self.assertIsNone(eol.match(rules, "OpenJS.NodeJS.LTS"))

    def test_state(self):
        cycles = json.loads(fixture("eol_nodejs.json"))
        today = date(2026, 10, 28)
        self.assertEqual(eol.state(cycles, "nodejs", "20", today)["state"], "ended")
        self.assertEqual(eol.state(cycles, "nodejs", "22", today)["state"], "ok")
        self.assertEqual(eol.state(cycles, "nodejs", "22", date(2027, 3, 1))["state"], "soon")
        self.assertIsNone(eol.state(cycles, "nodejs", "18", today))
        py = eol.state(json.loads(fixture("eol_python.json")), "python", "2.7", today)
        self.assertEqual((py["state"], py["date"]), ("ended", None))


if __name__ == "__main__":
    unittest.main()
