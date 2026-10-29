"""toolkeeper gui（design.md §8）。表の中身と、窓を作っての通し（画面には出さない）"""
import json
import tempfile
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


class EnvRows(unittest.TestCase):
    def test_labels_and_tags(self):
        rows = gui.env_rows([
            {"state": "bad", "kind": "path-missing", "scope": "machine", "name": "PATH", "value": r"C:\Python313\Scripts", "detail": "フォルダが無い"},
            {"state": "ok", "kind": "var", "scope": "user", "name": "PHPRC", "value": r"C:\work\php-conf", "detail": ""},
        ])
        self.assertEqual(rows[0], (("切れている", "PATH の切れ", "マシン", "PATH", r"C:\Python313\Scripts", "フォルダが無い"), "bad"))
        self.assertEqual(rows[1][0][:3], ("正しい", "変数", "ユーザー"))

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


class Window(unittest.TestCase):
    """窓を作って、選ぶ・押せない行は押せない・閉じる、までを通す（画面には出さない）"""

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
        self.env_patch = mock.patch.object(gui.env, "inspect", return_value=[
            {"state": "warn", "kind": "shadow", "scope": "", "name": "cmake", "value": r"C:\Strawberry\c\bin\cmake.exe", "detail": "x"}])
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        with mock.patch.object(gui.statusmod, "run", return_value={
                "toolkeeper": "0.1.0", "schema": 1, "data_dir": str(self.data), "last_check": None,
                "task": {"registered": False}, "sources": {"winget": "1.29.380", "choco": None, "cygwin": None, "ghostscript": False}}):
            self.app = gui.App(self.root, self.data / "none.json", str(self.data))
            self.root.update()

    def tearDown(self):
        try:
            self.app.close()
        except Exception:  # noqa: BLE001
            pass
        self.tmp.cleanup()

    def test_pick_and_button(self):
        """更新のボタンは押せない状態にしない（vista テーマでは枠が消えて文字に見える）"""
        app = self.app
        self.assertTrue(app.enabled(app.update_button))
        app.toggle("winget:Gyan.FFmpeg")
        self.assertEqual(app.tree.item("winget:Gyan.FFmpeg", "values")[0], gui.PICK_ON)
        self.assertIn("(1)", app.update_button.cget("text"))
        app.toggle("winget:Gyan.FFmpeg")
        self.assertNotIn("(", app.update_button.cget("text"))
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

    def test_env_tab_shows_rows(self):
        app = self.app
        for _ in range(50):  # 裏のスレッドの結果は _poll（100 ms ごと）で受け取る
            self.root.update()
            if app.env_tree.get_children():
                break
            self.root.after(20)
        rows = app.env_tree.get_children()
        self.assertEqual(len(rows), 1)
        self.assertEqual(app.env_tree.item(rows[0], "tags"), ("warn",))
        self.assertIn("1 件", app.env_count.cget("text"))

    def test_footer_stays_inside_small_window(self):
        """下のボタン行が、窓を小さくしても外に押し出されない"""
        self.root.deiconify()
        self.root.geometry("760x460")
        self.root.update()
        bar = self.app.message.master
        self.assertLessEqual(bar.winfo_y() + bar.winfo_height(), self.root.winfo_height())
        self.root.withdraw()


if __name__ == "__main__":
    unittest.main()
