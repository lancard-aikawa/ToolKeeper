"""toolkeeper gui（design.md §8）。表の中身と、窓を作っての通し（画面には出さない）"""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from toolkeeper import check, gui, store, update


def item(key, tier, name, updatable=True, notes=None, eol=None):
    return {"key": key, "tier": tier, "name": name, "installed": "1.0", "latest": "1.1" if updatable else "1.0",
            "updatable": updatable, "eol": eol, "new": False, "notes": notes or []}


RESULT = {
    "schema": 1, "checked_at": "2026-10-28T19:40:30+09:00",
    "summary": {"updatable": 3, "eol": 1, "new": 0, "failed": 0},
    "items": [
        item("winget:OpenJS.NodeJS.20", "E", "Node.js", eol={"product": "nodejs", "cycle": "20", "date": "2026-04-30", "state": "ended"}),
        item("cygwin", "A", "Cygwin"),
        item("ghostscript", "A", "Ghostscript", updatable=False),
        item("php", "A", "PHP", notes=["manual"]),
        item("winget:Gyan.FFmpeg", "B", "FFmpeg"),
        item("winget:Microsoft.WSL", "C", "Linux 用 Windows サブシステム"),
        item("winget:Microsoft.OpenJDK.17", "C", "OpenJDK 17", eol={"product": "x", "cycle": "17", "date": "2027-01-15", "state": "soon"}),
        item("choco:gh", "D", "gh", notes=["twin:winget:GitHub.cli"]),
    ],
    "failed": [],
}


class Rows(unittest.TestCase):
    def test_only_a_b_updatable_rows_are_pickable(self):
        rows = {k: pick for k, _v, pick in gui.table_rows(RESULT, True, set())}
        self.assertEqual({k for k, p in rows.items() if p}, {"cygwin", "winget:Gyan.FFmpeg"})
        self.assertFalse(rows["php"])          # 手で入れた PHP は乗り換えが先
        self.assertFalse(rows["ghostscript"])  # 最新
        self.assertFalse(rows["winget:OpenJS.NodeJS.20"])

    def test_c_d_hidden_by_default_except_eol(self):
        keys = [k for k, _v, _p in gui.table_rows(RESULT, False, set())]
        self.assertNotIn("winget:Microsoft.WSL", keys)
        self.assertNotIn("choco:gh", keys)
        self.assertIn("winget:Microsoft.OpenJDK.17", keys)  # もうすぐサポート終了
        self.assertEqual(len(gui.table_rows(RESULT, True, set())), len(RESULT["items"]))

    def test_marks(self):
        values = {k: v for k, v, _p in gui.table_rows(RESULT, True, {"cygwin"})}
        self.assertEqual(values["cygwin"][0], gui.PICK_ON)
        self.assertEqual(values["winget:Gyan.FFmpeg"][0], gui.PICK_OFF)
        self.assertEqual(values["choco:gh"][0], "")  # 押せない行には札を付けない
        self.assertIn("winget でも見えている", values["choco:gh"][5])

    def test_no_result(self):
        self.assertEqual(gui.table_rows(None, True, set()), [])
        self.assertIn("まだ調べていません", gui.summary_text(None))


ENV_FOUND = [
    {"id": "path-missing:machine:7:aa", "state": "bad", "kind": "path-missing", "scope": "machine", "name": "PATH",
     "value": r"C:\Python313\Scripts", "detail": "フォルダが無い", "fix": {"action": "remove", "to": None, "pos": 7}},
    {"id": "shadow::cmake:bb", "state": "warn", "kind": "shadow", "scope": "", "name": "cmake",
     "value": r"C:\Strawberry\c\bin\cmake.exe", "detail": "使われるのはこちら", "fix": None},
    {"id": "var:user:PHPRC:cc", "state": "ok", "kind": "var", "scope": "user", "name": "PHPRC", "value": r"C:\work\php-conf",
     "detail": "", "fix": None},
]


class EnvRows(unittest.TestCase):
    def test_labels_marks_and_tags(self):
        rows = gui.env_rows(ENV_FOUND, {"path-missing:machine:7:aa"})
        self.assertEqual(rows[0], ("path-missing:machine:7:aa",
                                   (gui.PICK_ON, "切れている", "PATH の切れ", "マシン", "PATH", r"C:\Python313\Scripts",
                                    "フォルダが無い", "PATH から消す"),
                                   "bad", True))
        self.assertEqual(rows[1][1][0], "")  # 直し方の無い行には札を付けない
        self.assertFalse(rows[1][3])
        self.assertEqual(rows[2][1][1:4], ("正しい", "変数", "ユーザー"))

    def test_summary_mentions_env_only_when_some(self):
        self.assertNotIn("環境", gui.summary_text(RESULT))
        r = dict(RESULT, summary=dict(RESULT["summary"], env=3))
        self.assertIn("環境の注意 3", gui.summary_text(r))


class Lines(unittest.TestCase):
    def test_progress_is_overwritten(self):
        buf = gui.LineBuffer()
        lines, partial = buf.feed("ダウンロード中\r\n  10%\r  50%")
        self.assertEqual((lines, partial), (["ダウンロード中"], "  50%"))
        lines, partial = buf.feed("\r 100%\r\nインストールが完了しました\r\n")
        self.assertEqual((lines, partial), ([" 100%", "インストールが完了しました"], ""))


class History(unittest.TestCase):
    def test_newest_first_and_skips_broken_lines(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / update.HISTORY_FILE
            p.write_text("\n".join([
                json.dumps({"at": "2026-10-28T18:06:04+09:00", "key": "winget:7zip.7zip", "from": "26.02", "to": "26.05", "ok": True, "code": "0x00000000"}),
                "{broken",
                json.dumps({"at": "2026-10-28T18:55:50+09:00", "key": "ghostscript", "from": "10.05.1", "to": "10.08.0", "ok": False, "code": "0x00000001"}),
            ]) + "\n", encoding="utf-8")
            rows = gui.history_rows(p)
        self.assertEqual([r[1] for r in rows], ["ghostscript", "winget:7zip.7zip"])
        self.assertEqual(rows[0][4], "失敗")
        self.assertEqual(rows[1][0], "2026-10-28 18:06:04")


class WindowBase(unittest.TestCase):
    """窓を作る（画面には出さない）。CONFIG に設定を書くと、その設定で開く"""
    CONFIG: dict | None = None

    def setUp(self):
        import tkinter as tk
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        store.write_json(self.data / check.CHECK_FILE, RESULT)
        try:
            self.root = tk.Tk()
        except tk.TclError as e:
            self.skipTest(f"Tk を開けません: {e}")
        self.root.withdraw()
        # 本物のレジストリは見ない（環境のタブは裏のスレッドで読むので、窓を閉じるまで差し替えておく）
        self.env_patch = mock.patch.object(gui.env, "inspect", return_value=ENV_FOUND)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        with mock.patch.object(gui.statusmod, "run", return_value={
                "toolkeeper": "0.1.0", "schema": 1, "data_dir": str(self.data), "last_check": None,
                "task": {"registered": False}, "sources": {"winget": "1.29.380", "choco": None, "cygwin": None, "ghostscript": False}}):
            config = self.data / "toolkeeper.json"
            if self.CONFIG is not None:
                config.write_text(json.dumps(self.CONFIG), encoding="utf-8")
            self.app = gui.App(self.root, config, str(self.data))
            self.root.update()

    def tearDown(self):
        try:
            self.app.close()
        except Exception:  # noqa: BLE001
            pass
        self.tmp.cleanup()


class Window(WindowBase):
    """道具のタブ: 選ぶ・押せない行は押せない・閉じる、までを通す。環境のタブは既定（見るだけ）"""

    def wait_env(self):
        for _ in range(100):  # 裏のスレッドの結果は _poll（100 ms ごと）で受け取る
            self.root.update()
            if self.app.env_tree.get_children():
                return
            time.sleep(0.02)
        self.fail("環境のタブが埋まらない")

    def test_env_is_read_only_by_default(self):
        """素人が PATH を壊さないよう、既定では直す・戻すを出さず、行も押せない（§3.7）"""
        app = self.app
        self.wait_env()
        self.assertIsNone(app.fix_button)
        self.assertEqual([b.cget("text") for b in app.env_buttons], ["読み直す"])
        self.assertNotIn("pick", app.env_tree.cget("displaycolumns"))
        row = "path-missing:machine:7:aa"
        self.assertEqual(app.env_tree.item(row, "tags"), ("bad",))
        self.assertEqual(app.env_tree.set(row, "fix"), "PATH から消す")  # 直し方は参考として出す
        app._env_hover(row)
        self.assertEqual(str(app.env_tree.cget("cursor")), "")
        app.toggle_env(row)
        self.assertEqual(app.env_picked, set())
        with mock.patch.object(app, "run_command") as run:
            app.fix_picked()
            app.undo_env()
        run.assert_not_called()

    def test_pick_and_button(self):
        """更新のボタンは押せない状態にしない（vista テーマでは枠が消えて文字に見える）"""
        app = self.app
        self.assertTrue(app.enabled(app.update_button))
        self.assertIn("なし", app.picked_label.cget("text"))
        app.toggle("winget:Gyan.FFmpeg")
        self.assertEqual(app.tree.item("winget:Gyan.FFmpeg", "values")[0], gui.PICK_ON)
        self.assertIn("(1)", app.update_button.cget("text"))
        # [x] だけでは見分けられなかったので、行を塗り、表の上に名前を出す（2026-10-29）
        self.assertIn("picked", app.tree.item("winget:Gyan.FFmpeg", "tags"))
        self.assertIn("選んでいる物（1）: FFmpeg", app.picked_label.cget("text"))
        app.toggle("winget:Gyan.FFmpeg")
        self.assertNotIn("(", app.update_button.cget("text"))
        self.assertNotIn("picked", app.tree.item("winget:Gyan.FFmpeg", "tags"))
        self.assertIn("なし", app.picked_label.cget("text"))
        self.assertTrue(app.enabled(app.update_button))

    def test_update_without_picks_explains(self):
        app = self.app
        with mock.patch.object(app, "run_command") as run:
            app.update_picked()
        run.assert_not_called()
        self.assertIn("行を押して", app.message.cget("text"))

    def test_buttons_disabled_while_running_and_back(self):
        app = self.app
        app._set_buttons(False)
        self.assertFalse(any(app.enabled(b) for b in app.buttons))
        self.assertEqual(app.update_button.cget("bg"), gui.PRIMARY_OFF)  # 青のままだと押せそうに見える
        app._set_buttons(True)
        self.assertTrue(all(app.enabled(b) for b in app.buttons))
        self.assertEqual(str(app.update_button.cget("cursor")), "hand2")

    def test_primary_button_is_filled(self):
        """主役は塗りで脇役と分ける（グローバルの「押せるものは押せると見せる」）"""
        self.assertEqual(self.app.update_button.cget("bg"), gui.PRIMARY_BG)

    def test_hover_only_on_pickable_rows(self):
        app = self.app
        app._set_hover("cygwin")
        self.assertIn("hover", app.tree.item("cygwin", "tags"))
        self.assertEqual(str(app.tree.cget("cursor")), "hand2")
        app._set_hover("winget:OpenJS.NodeJS.20")
        self.assertNotIn("hover", app.tree.item("cygwin", "tags"))
        self.assertNotIn("hover", app.tree.item("winget:OpenJS.NodeJS.20", "tags"))
        self.assertEqual(str(app.tree.cget("cursor")), "")

    def test_update_runs_cli_with_picked_keys(self):
        app = self.app
        app.toggle("winget:Gyan.FFmpeg")
        with mock.patch.object(gui.messagebox, "askokcancel", return_value=True), \
             mock.patch.object(app, "run_command") as run:
            app.update_picked()
        argv = run.call_args.args[1]
        self.assertEqual(argv[-2:], ["update", "winget:Gyan.FFmpeg"])
        self.assertIn("--data", argv)

    def test_cygwin_running_stops_before_asking(self):
        app = self.app
        app.toggle("cygwin")
        with mock.patch.object(gui.cygwin, "running", return_value=["mintty.exe"]), \
             mock.patch.object(gui.messagebox, "showwarning") as warn, \
             mock.patch.object(gui.messagebox, "askokcancel") as ask, \
             mock.patch.object(app, "run_command") as run:
            app.update_picked()
        warn.assert_called_once()
        ask.assert_not_called()
        run.assert_not_called()

    def test_footer_stays_inside_small_window(self):
        """下のボタン行が、窓を小さくしても外に押し出されない"""
        self.root.deiconify()
        self.root.geometry("760x460")
        self.root.update()
        bar = self.app.message.master
        self.assertLessEqual(bar.winfo_y() + bar.winfo_height(), self.root.winfo_height())
        self.root.withdraw()


class EnvFixWindow(WindowBase):
    """環境のタブの書き換え（設定 env_fix が true のときだけ出る）"""
    CONFIG = {"env_fix": True}

    def wait_env(self):
        for _ in range(100):  # 裏のスレッドの結果は _poll（100 ms ごと）で受け取る
            self.root.update()
            if self.app.env_tree.get_children():
                return
            time.sleep(0.02)
        self.fail("環境のタブが埋まらない")

    def test_env_tab_shows_rows(self):
        app = self.app
        self.wait_env()
        rows = app.env_tree.get_children()
        self.assertEqual(len(rows), 3)
        self.assertEqual(app.env_tree.item(rows[0], "tags"), ("bad", "pick"))
        self.assertEqual(app.env_tree.item(rows[1], "tags"), ("warn",))
        self.assertIn("2 件", app.env_count.cget("text"))
        self.assertEqual(app.fix_button.cget("bg"), gui.PRIMARY_BG)

    def test_env_hover_and_pick_only_on_fixable_rows(self):
        app = self.app
        self.wait_env()
        app._env_hover("shadow::cmake:bb")
        self.assertEqual(str(app.env_tree.cget("cursor")), "")
        self.assertIn("cmake", app.env_full.cget("text"))  # 全文はどの行でも出す
        app._env_hover("path-missing:machine:7:aa")
        self.assertEqual(str(app.env_tree.cget("cursor")), "hand2")
        app.toggle_env("path-missing:machine:7:aa")
        self.assertIn("(1)", app.fix_button.cget("text"))
        self.assertIn("picked", app.env_tree.item("path-missing:machine:7:aa", "tags"))
        self.assertIn(r"選んでいる物（1）: マシンの PATH C:\Python313\Scripts", app.env_picked_label.cget("text"))

    def test_picked_survives_reload(self):
        """読み直しても、選んだ行は塗ったまま"""
        app = self.app
        self.wait_env()
        app.toggle_env("path-missing:machine:7:aa")
        app.show_env(ENV_FOUND, None)
        self.assertIn("picked", app.env_tree.item("path-missing:machine:7:aa", "tags"))

    def test_env_fix_runs_cli_after_confirming(self):
        app = self.app
        self.wait_env()
        app.toggle_env("path-missing:machine:7:aa")
        writes = [{"scope": "machine", "name": "Path", "old": "a", "new": "b", "changes": ["Path（マシン）から x を消す"]}]
        with mock.patch.object(gui.env, "read_registry", return_value={}), \
             mock.patch.object(gui.env, "plan", return_value=writes), \
             mock.patch.object(gui.messagebox, "askokcancel", return_value=True) as ask, \
             mock.patch.object(app, "run_command") as run:
            app.fix_picked()
        self.assertIn("UAC", ask.call_args.args[1])
        argv = run.call_args.args[1]
        self.assertEqual(argv[-3:], ["env", "--fix", "path-missing:machine:7:aa"])
        self.assertIs(run.call_args.kwargs["out"], app.env_output)

    def test_env_fix_without_picks_explains(self):
        app = self.app
        self.wait_env()
        with mock.patch.object(app, "run_command") as run:
            app.fix_picked()
        run.assert_not_called()
        self.assertIn("行を押して", app.message.cget("text"))

    def test_undo_without_history_explains(self):
        with mock.patch.object(self.app, "run_command") as run:
            self.app.undo_env()
        run.assert_not_called()
        self.assertIn("戻せる変更がありません", self.app.message.cget("text"))


if __name__ == "__main__":
    unittest.main()
