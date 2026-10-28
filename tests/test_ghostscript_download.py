import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from toolkeeper import ghostscript

BODY = b"MZ fake installer"
REL = {"version": "10.08.0", "asset": "gs10080w64.exe", "url": "https://github.com/x/gs10080w64.exe",
       "sha256": hashlib.sha256(BODY).hexdigest()}
ARTIFEX = 'CN="Artifex Software, Inc.", O="Artifex Software, Inc.", S=California, C=US'


class Download(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name) / "downloads" / "ghostscript"

    def tearDown(self):
        self.tmp.cleanup()

    def test_ok(self):
        with mock.patch.object(ghostscript, "signer", return_value=("Valid", ARTIFEX)):
            exe = ghostscript.download(REL, self.folder, io.StringIO(), fetch=lambda url: BODY)
        self.assertEqual(exe.read_bytes(), BODY)

    def test_starts_from_empty_folder(self):
        self.folder.mkdir(parents=True)
        (self.folder / "planted.dll").write_bytes(b"x")
        with mock.patch.object(ghostscript, "signer", return_value=("Valid", ARTIFEX)):
            ghostscript.download(REL, self.folder, io.StringIO(), fetch=lambda url: BODY)
        self.assertEqual([p.name for p in self.folder.iterdir()], ["gs10080w64.exe"])

    def test_reuses_verified_download(self):
        with mock.patch.object(ghostscript, "signer", return_value=("Valid", ARTIFEX)):
            ghostscript.download(REL, self.folder, io.StringIO(), fetch=lambda url: BODY)
            (self.folder / "planted.dll").write_bytes(b"x")

            def no_fetch(url):
                raise AssertionError("取り直した")
            ghostscript.download(REL, self.folder, io.StringIO(), fetch=no_fetch)
        self.assertEqual([p.name for p in self.folder.iterdir()], ["gs10080w64.exe"])

    def test_tampered_download_is_fetched_again(self):
        self.folder.mkdir(parents=True)
        (self.folder / "gs10080w64.exe").write_bytes(b"tampered")
        with mock.patch.object(ghostscript, "signer", return_value=("Valid", ARTIFEX)):
            exe = ghostscript.download(REL, self.folder, io.StringIO(), fetch=lambda url: BODY)
        self.assertEqual(exe.read_bytes(), BODY)

    def test_signature_check_failure_stops(self):
        with mock.patch.object(ghostscript, "signer", side_effect=RuntimeError("署名を確かめられません")):
            with self.assertRaisesRegex(RuntimeError, "署名"):
                ghostscript.download(REL, self.folder, io.StringIO(), fetch=lambda url: BODY)
        self.assertFalse(self.folder.exists())

    def test_ps51_env_drops_psmodulepath_any_case(self):
        with mock.patch.dict(ghostscript.os.environ, {"PSMODULEPATH": r"C:\pwsh\Modules"}):
            self.assertFalse(any(k.lower() == "psmodulepath" for k in ghostscript._ps51_env()))

    def test_sha_mismatch(self):
        with self.assertRaisesRegex(RuntimeError, "SHA-256"):
            ghostscript.download(REL, self.folder, io.StringIO(), fetch=lambda url: b"other")
        self.assertFalse((self.folder / "gs10080w64.exe").exists())

    def test_no_sha_from_github(self):
        with self.assertRaisesRegex(RuntimeError, "SHA-256"):
            ghostscript.download({**REL, "sha256": None}, self.folder, io.StringIO(), fetch=lambda url: BODY)

    def test_bad_signature(self):
        for st in (("NotSigned", ""), ("Valid", 'CN="Someone Else", O="Someone Else"'), ("HashMismatch", ARTIFEX)):
            with self.subTest(st), mock.patch.object(ghostscript, "signer", return_value=st):
                with self.assertRaisesRegex(RuntimeError, "署名"):
                    ghostscript.download(REL, self.folder, io.StringIO(), fetch=lambda url: BODY)
                self.assertFalse(self.folder.exists())


if __name__ == "__main__":
    unittest.main()
