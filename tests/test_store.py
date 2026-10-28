import os
import tempfile
import time
import unittest
from pathlib import Path

from toolkeeper import store


class Fetch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "cache" / "x.json"
        self.calls = 0

    def tearDown(self):
        self.tmp.cleanup()

    def download(self, url):
        self.calls += 1
        return b"new"

    def fail(self, url):
        self.calls += 1
        raise OSError("つながらない")

    def test_fresh_cache_is_used(self):
        self.assertEqual(store.fetch("https://e/x", self.path, 24, self.download), b"new")
        self.assertEqual(store.fetch("https://e/x", self.path, 24, self.fail), b"new")
        self.assertEqual(self.calls, 1)

    def test_old_cache_is_refreshed(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b"old")
        old = time.time() - 25 * 3600
        os.utime(self.path, (old, old))
        self.assertEqual(store.fetch("https://e/x", self.path, 24, self.download), b"new")

    def test_failure_falls_back_to_old_cache(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b"old")
        old = time.time() - 25 * 3600
        os.utime(self.path, (old, old))
        self.assertEqual(store.fetch("https://e/x", self.path, 24, self.fail), b"old")

    def test_failure_without_cache_raises(self):
        with self.assertRaises(OSError):
            store.fetch("https://e/x", self.path, 24, self.fail)


if __name__ == "__main__":
    unittest.main()
