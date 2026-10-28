import json
import tempfile
import unittest
from pathlib import Path

from toolkeeper import config
from toolkeeper.paths import APP_DIR


class Sample(unittest.TestCase):
    def test_sample_matches_defaults(self):
        """キーを足したら toolkeeper.sample.json も直す（design.md §6）"""
        with open(APP_DIR / "toolkeeper.sample.json", encoding="utf-8") as f:
            self.assertEqual(json.load(f), config.DEFAULTS)

    def test_design_lists_all_keys(self):
        with open(APP_DIR / "docs" / "design.md", encoding="utf-8") as f:
            text = f.read()
        section = text[text.index("## 6. 設定"):text.index("## 7.")]
        for k in config.DEFAULTS:
            self.assertIn(f"`{k}`", section, k)


class Load(unittest.TestCase):
    def test_missing_file_gives_defaults(self):
        self.assertEqual(config.load(Path("does-not-exist.json")), config.DEFAULTS)

    def test_override_replaces_whole_list(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "toolkeeper.json"
            p.write_text('{"winget_update": ["Foo.Bar"], "x_unknown": 1}', encoding="utf-8")
            cfg = config.load(p)
        self.assertEqual(cfg["winget_update"], ["Foo.Bar"])
        self.assertEqual(cfg["x_unknown"], 1)
        self.assertEqual(cfg["cache_hours"], config.DEFAULTS["cache_hours"])


if __name__ == "__main__":
    unittest.main()
