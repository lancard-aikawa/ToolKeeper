"""toolkeeper gui: 道具の一覧と更新・履歴の画面（docs/design.md §8）

tkinter で作る（実行時の依存を足さない）。グローバルの CLAUDE.md にある tkinter の落とし穴の対策:
  - タブは選ばれたものがはっきり分かるスタイル（ensure_notebook_style）
  - 下のボタン行は本体より先に side=BOTTOM で置く
  - 絵文字は使わない（起動が約 1 秒遅れ、白黒になる）
調べる・上げるは別のプロセス（python -m toolkeeper ...）で動かす。排他は CLI のものがそのまま効く。
押せる行（A・B の更新できる物）は、[ ] の札・乗せたときの色・指のカーソルで分かるようにし、押せない行は灰色にする。
"""
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, ttk

from . import __version__, check, cygwin, env, store, update
from . import config as cfgmod
from . import status as statusmod
from .ghostscript import _ps51_env
from .labels import ENV_KIND, ENV_STATE, SCOPE_LABEL, TIER_LABEL, can_update, note_text
from .paths import APP_DIR, data_dir

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PICK_OFF, PICK_ON = "[ ]", "[x]"
HOVER_BG = "#dbeafe"
PRIMARY_BG, PRIMARY_HOVER, PRIMARY_ACTIVE, PRIMARY_OFF = "#2563eb", "#1e40af", "#1e3a8a", "#9ca3af"
PLAIN_FG = "#777777"


def ensure_notebook_style(name: str = "ToolKeeper.TNotebook") -> str:
    """選ばれたタブがはっきり分かるスタイル（Windows の vista テーマでは見分けにくいため）。何度呼んでもよい"""
    style = ttk.Style()
    try:
        style.configure(f"{name}.Tab", padding=[14, 6])
        style.map(
            f"{name}.Tab",
            background=[("selected", "#ffffff"), ("!selected", "#e8e8e8")],
            foreground=[("selected", "#000000"), ("!selected", "#757575")],
            font=[("selected", ("", 10, "bold")), ("!selected", ("", 9))],
        )
    except tk.TclError:
        pass
    return name


def table_rows(result: dict | None, show_all: bool, picked: set[str]) -> list[tuple[str, tuple, bool]]:
    """表の行: (key, 表示する値, 押せるか)。並びは check.json のまま（E → A → B → C → D）。
    既定では C・D を隠す（サポート終了の物は出す）"""
    rows = []
    for it in (result or {}).get("items") or []:
        eol_bad = bool(it.get("eol") and it["eol"]["state"] != "ok")
        if not show_all and it["tier"] in ("C", "D") and not eol_bad:
            continue
        pick = can_update(it)
        mark = (PICK_ON if it["key"] in picked else PICK_OFF) if pick else ""
        rows.append((it["key"], (mark, TIER_LABEL[it["tier"]], it["name"], it["installed"] or "-", it["latest"] or "-",
                                 note_text(it)), pick))
    return rows


def summary_text(result: dict | None) -> str:
    if not result:
        return "まだ調べていません。「調べ直す」で調べます"
    s = result["summary"]
    text = (f"調べた時刻 {result['checked_at'].replace('T', ' ')[:16]}　更新できる {s['updatable']}　"
            f"サポート終了 {s['eol']}　新しい {s['new']}")
    if s.get("env"):
        text += f"　環境の注意 {s['env']}（環境のタブ）"
    if result.get("failed"):
        text += "　調べられなかった: " + "、".join(f["source"] for f in result["failed"])
    return text


def env_rows(found: list[dict], picked: set[str], fixable: bool = True) -> list[tuple[str, tuple, str, bool]]:
    """環境のタブの行: (ID, 選ぶ・状態・種類・範囲・名前・値・説明・直し方, 色の札, 押せるか)。
    並びは env.inspect のまま（切れている物が先）。押せるのは、設定 env_fix が true で、直し方が決まっている行だけ"""
    rows = []
    for f in found:
        pick = fixable and bool(f.get("fix"))
        mark = (PICK_ON if f["id"] in picked else PICK_OFF) if pick else ""
        rows.append((f["id"], (mark, ENV_STATE[f["state"]], ENV_KIND[f["kind"]], SCOPE_LABEL[f["scope"]], f["name"],
                               f["value"], f["detail"], env.fix_text(f)), f["state"], pick))
    return rows


def history_rows(path: Path, limit: int = 500) -> list[tuple]:
    """history.jsonl を新しい順に: (時刻, キー, 前, 後, 結果, 終了コード)"""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    rows = []
    for line in reversed(lines[-limit:]):
        try:
            h = json.loads(line)
        except ValueError:
            continue
        rows.append((h.get("at", "").replace("T", " ")[:19], h.get("key", ""), h.get("from") or "-", h.get("to") or "-",
                     "済み" if h.get("ok") else "失敗", h.get("code", "")))
    return rows


class LineBuffer:
    """流れてくる出力を行に分ける。winget の進み具合は \\r で上書きされるので、行は最後の \\r より後だけを残し、
    書きかけの行（進み具合）は別に返す"""

    def __init__(self):
        self.partial = ""

    def feed(self, text: str) -> tuple[list[str], str]:
        buf = (self.partial + text).replace("\r\n", "\n")
        *done, self.partial = buf.split("\n")
        lines = [x.rsplit("\r", 1)[-1] for x in done]
        return lines, self.partial.rsplit("\r", 1)[-1]


class App:
    def __init__(self, root: tk.Tk, config_path: Path, data_override: str | None):
        self.root = root
        self.config_path = config_path
        self.data_override = data_override
        self.cfg = cfgmod.load(config_path)
        self.jobs: queue.Queue = queue.Queue()
        self.running = False
        self.result: dict | None = None
        self.picked: set[str] = set()
        self.hover: str | None = None
        self.env_found: dict[str, dict] = {}
        self.env_picked: set[str] = set()
        self.env_hover: str | None = None

        root.title(f"ToolKeeper {__version__}")
        root.geometry("1180x680")
        root.minsize(760, 460)

        # 下のステータス行を、本体より先に置く（落とし穴: 本体が場所を食ってフッターが消える）
        bar = ttk.Frame(root)
        bar.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=6)
        ttk.Button(bar, text="閉じる", command=self.close, cursor="hand2").pack(side=tk.RIGHT)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.message = ttk.Label(bar, text="")
        self.message.pack(side=tk.LEFT, fill=tk.X, expand=True)

        nb = ttk.Notebook(root, style=ensure_notebook_style())
        nb.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=(8, 0))
        self.notebook = nb
        self._build_tools(nb)
        self._build_env(nb)
        self._build_history(nb)

        self._after = self.root.after(100, self._poll)
        self.reload()

    def close(self) -> None:
        """予約した処理を取り消し、溜まっている描画を済ませてから閉じる（閉じたあとに走ると Tcl のエラーが出る）"""
        self.root.after_cancel(self._after)
        self.root.update_idletasks()
        self.root.destroy()

    @property
    def data(self) -> Path:
        return data_dir(self.cfg, self.data_override)

    def _global_args(self) -> list[str]:
        args = ["--config", str(self.config_path)]
        if self.data_override:
            args += ["--data", self.data_override]
        return args

    def toolkeeper(self, *args: str) -> list[str]:
        return [sys.executable, "-m", "toolkeeper", *self._global_args(), *args]

    # ---- 裏の仕事（別スレッド → キュー → 画面のスレッドで受け取る）

    def _run_in_background(self, work, done) -> None:
        """work() を別スレッドで動かし、終わったら画面のスレッドで done(結果, 例外) を呼ぶ"""
        def body():
            try:
                self.jobs.put((done, work(), None))
            except Exception as e:  # noqa: BLE001 (画面に理由を出す)
                self.jobs.put((done, None, e))
        threading.Thread(target=body, daemon=True).start()

    def _poll(self) -> None:
        try:
            while True:
                done, result, error = self.jobs.get_nowait()
                done(result, error)
        except queue.Empty:
            pass
        self._after = self.root.after(100, self._poll)

    def run_command(self, label: str, argv: list[str], env: dict | None = None, out: tk.Text | None = None) -> None:
        """コマンドを別のプロセスで動かし、出力を下の欄（既定は道具のタブの欄）に流す。終わったら読み直す"""
        out = out or self.output
        if self.running:
            self.message.config(text="ほかの仕事が終わるまで待ってください")
            return
        self.running = True
        self._set_buttons(False)
        out.delete("1.0", tk.END)
        out.insert(tk.END, f"> {label}\n")
        self.message.config(text=f"{label}…")
        lines = LineBuffer()

        def show(chunk, _error):
            done, partial = lines.feed(chunk)
            for line in done:
                if line.strip():
                    out.insert(tk.END, line + "\n")
            out.see(tk.END)
            if partial.strip():
                self.message.config(text=partial.strip()[:120])

        def work():
            p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=_NO_WINDOW,
                                 cwd=str(APP_DIR), env=env)
            import codecs
            dec = codecs.getincrementaldecoder("utf-8")(errors="replace")
            while True:
                chunk = p.stdout.read1(4096)
                if not chunk:
                    break
                self.jobs.put((show, dec.decode(chunk), None))
            return p.wait()

        def done(code, error):
            self.running = False
            self._set_buttons(True)
            if error:
                out.insert(tk.END, f"起動できません: {error}\n")
                self.message.config(text=f"{label}: 起動できません")
                return
            show("\n", None)
            out.insert(tk.END, f"(終了コード {code})\n")
            out.see(tk.END)
            note = {0: "終わりました", 3: "ほかの ToolKeeper が実行中です", 4: "調べられなかった取得元があります",
                    5: "上げられなかった物があります"}.get(code, "失敗しました")
            self.message.config(text=f"{label}: {note}")
            self.reload()

        self._run_in_background(work, done)

    # ---- 道具のタブ

    @staticmethod
    def _primary_button(parent, text: str, command) -> tk.Button:
        """主役のボタン。塗りで脇役と分ける（ttk の vista テーマは塗れないので tk.Button。乗せる・押すで色を変える）"""
        b = tk.Button(parent, text=text, command=command, cursor="hand2", bg=PRIMARY_BG, fg="#ffffff",
                      activebackground=PRIMARY_ACTIVE, activeforeground="#ffffff", disabledforeground="#c7d2fe",
                      relief=tk.RAISED, bd=1, padx=10, pady=1, font=("", 9, "bold"))
        b.bind("<Enter>", lambda _e: b.cget("state") != tk.DISABLED and b.config(bg=PRIMARY_HOVER))
        b.bind("<Leave>", lambda _e: b.config(bg=PRIMARY_OFF if b.cget("state") == tk.DISABLED else PRIMARY_BG))
        return b

    def _build_tools(self, nb: ttk.Notebook) -> None:
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text="道具")

        buttons = ttk.Frame(tab)
        buttons.pack(side=tk.TOP, fill=tk.X)
        self.update_button = self._primary_button(buttons, "選んだものを更新", self.update_picked)
        self.buttons = [
            self.update_button,
            ttk.Button(buttons, text="調べ直す", command=lambda: self.run_command("調べ直す", self.toolkeeper("check")),
                       cursor="hand2"),
            ttk.Button(buttons, text="定期実行を登録", command=lambda: self.register_task(False), cursor="hand2"),
            ttk.Button(buttons, text="定期実行を解除", command=lambda: self.register_task(True), cursor="hand2"),
            ttk.Button(buttons, text="前回のログを開く", command=self.open_log, cursor="hand2"),
        ]
        for b in self.buttons:
            b.pack(side=tk.LEFT, padx=(0, 6))
        self.show_all = tk.BooleanVar(value=False)
        ttk.Checkbutton(buttons, text="C・D も出す", variable=self.show_all, command=self.show_table,
                        cursor="hand2").pack(side=tk.RIGHT)

        self.summary = ttk.Label(tab, text="")
        self.summary.pack(side=tk.TOP, anchor=tk.W, pady=(8, 0))
        self.status = ttk.Label(tab, text="", foreground="#555555")
        self.status.pack(side=tk.TOP, anchor=tk.W)

        # 出力の欄を、表より先に下に置く
        out = ttk.Frame(tab)
        out.pack(side=tk.BOTTOM, fill=tk.X, pady=(6, 0))
        scroll = ttk.Scrollbar(out, orient=tk.VERTICAL)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.output = tk.Text(out, height=9, wrap=tk.WORD, yscrollcommand=scroll.set, font=("Consolas", 9))
        self.output.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.config(command=self.output.yview)
        ttk.Label(tab, text="動かした仕事の出力").pack(side=tk.BOTTOM, anchor=tk.W, pady=(6, 0))

        ttk.Label(tab, text="A・B の行を押すと選べます（[x] にした物を「選んだものを更新」で上げます）。"
                            "灰色の行（C・D・E と最新の物）は見るだけです").pack(side=tk.TOP, anchor=tk.W, pady=(8, 2))
        table = ttk.Frame(tab)
        table.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        cols = [("pick", "選ぶ", 44), ("tier", "区分", 80), ("name", "名前", 300), ("installed", "入っている版", 120),
                ("latest", "最新", 120), ("note", "注意", 300)]
        self.tree = ttk.Treeview(table, columns=[c[0] for c in cols], show="headings", selectmode="none")
        for key, label, width in cols:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, stretch=key in ("name", "note"), anchor=tk.CENTER if key == "pick" else tk.W)
        self.tree.tag_configure("plain", foreground=PLAIN_FG)
        self.tree.tag_configure("hover", background=HOVER_BG)
        scroll = ttk.Scrollbar(table, orient=tk.VERTICAL, command=self.tree.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.bind("<Button-1>", self._click)
        self.tree.bind("<Motion>", self._motion)
        self.tree.bind("<Leave>", lambda _e: self._set_hover(None))

    def _pickable(self, key: str | None) -> bool:
        return bool(key) and "pick" in self.tree.item(key, "tags")

    def _set_hover(self, key: str | None) -> None:
        if key == self.hover:
            return
        if self.hover and self.tree.exists(self.hover):
            self.tree.item(self.hover, tags=[t for t in self.tree.item(self.hover, "tags") if t != "hover"])
        self.hover = key if self._pickable(key) else None
        if self.hover:
            self.tree.item(self.hover, tags=[*self.tree.item(self.hover, "tags"), "hover"])
        self.tree.configure(cursor="hand2" if self.hover else "")

    def _motion(self, event) -> None:
        self._set_hover(self.tree.identify_row(event.y) or None)

    def _click(self, event) -> str | None:
        key = self.tree.identify_row(event.y)
        if self.tree.identify_region(event.x, event.y) == "heading" or not self._pickable(key):
            return None
        self.toggle(key)
        return "break"

    def toggle(self, key: str) -> None:
        if self.running:
            return
        self.picked.symmetric_difference_update({key})
        values = list(self.tree.item(key, "values"))
        values[0] = PICK_ON if key in self.picked else PICK_OFF
        self.tree.item(key, values=values)
        self._update_button_text()

    def _update_button_text(self) -> None:
        """押せない状態にはしない（vista テーマの押せないボタンは枠が消え、ただの文字に見える。2026-10-28 に画面で確かめた）。
        何も選ばずに押したら、選び方を出す"""
        n = len(self.picked)
        self.update_button.config(text=f"選んだものを更新 ({n})" if n else "選んだものを更新")

    @staticmethod
    def _enable(button, on: bool) -> None:
        """押せないボタンは指のカーソルにしない（ttk.Button と tk.Button の両方）"""
        if isinstance(button, ttk.Button):
            button.state(["!disabled"] if on else ["disabled"])
        else:  # 塗った主役のボタン。押せない間は灰色にする（青のままだと押せそうに見える）
            button.config(state=tk.NORMAL if on else tk.DISABLED, bg=PRIMARY_BG if on else PRIMARY_OFF)
        button.config(cursor="hand2" if on else "")

    @staticmethod
    def enabled(button) -> bool:
        if isinstance(button, ttk.Button):
            return button.instate(["!disabled"])
        return str(button.cget("state")) != tk.DISABLED

    def show_table(self) -> None:
        self.hover = None
        self.tree.delete(*self.tree.get_children())
        rows = table_rows(self.result, self.show_all.get(), self.picked)
        for key, values, pick in rows:
            self.tree.insert("", tk.END, iid=key, values=values, tags=["pick"] if pick else ["plain"])
        self.summary.config(text=summary_text(self.result))
        self._update_button_text()

    def _set_buttons(self, enabled: bool) -> None:
        for b in self.buttons:
            self._enable(b, enabled)
        if enabled:
            self._update_button_text()

    def update_picked(self) -> None:
        keys = [k for k, _v, pick in table_rows(self.result, True, self.picked) if pick and k in self.picked]
        if not keys:
            self.message.config(text="A・B の行を押して、上げる物を選んでください")
            return
        if "cygwin" in keys:
            names = cygwin.running(Path(self.cfg["cygwin_root"]))
            if names:
                messagebox.showwarning("ToolKeeper", "Cygwin のプログラムが動いています。閉じてからやり直してください。\n\n"
                                       + "\n".join(names), parent=self.root)
                return
        names = [self.tree.item(k, "values")[2] for k in keys if self.tree.exists(k)]
        if not messagebox.askokcancel("ToolKeeper", f"{len(keys)} 件を上げます。UAC の確認が出たら「はい」を押してください。\n\n"
                                      + "\n".join(names), parent=self.root):
            return
        self.picked.clear()
        self.run_command(f"{len(keys)} 件を更新", self.toolkeeper("update", *keys))

    def register_task(self, unregister: bool) -> None:
        script = APP_DIR / "scripts" / "register-task.ps1"
        argv = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)]
        if unregister:
            argv.append("-Unregister")
        elif self.data_override:
            argv += ["-Data", self.data_override]
        # PowerShell 7 から呼ばれたときの PSModulePath を外す（5.1 の ScheduledTasks を読めなくなる）
        self.run_command("定期実行を解除" if unregister else "定期実行を登録", argv, env=_ps51_env())

    def open_log(self) -> None:
        log = self.data / "last-run.log"
        if not log.is_file():
            self.message.config(text=f"ログがありません: {log}")
            return
        os.startfile(log)  # noqa: S606  既定のアプリで開く（Windows）

    # ---- 環境のタブ（§3.7）

    def _build_env(self, nb: ttk.Notebook) -> None:
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text="環境")
        # 書き換えは、設定 env_fix を true にした人にだけ出す（PATH を壊すと関係の無いアプリまで動かなくなり、
        # 素人には原因が分からない。既定は見るだけ。§3.7）
        self.env_can_fix = bool(self.cfg.get("env_fix"))
        top = ttk.Frame(tab)
        top.pack(side=tk.TOP, fill=tk.X)
        self.fix_button = self._primary_button(top, "選んだものを直す", self.fix_picked) if self.env_can_fix else None
        self.env_buttons = [
            *([self.fix_button, ttk.Button(top, text="最後の変更を戻す", command=self.undo_env, cursor="hand2")]
              if self.env_can_fix else []),
            ttk.Button(top, text="読み直す", command=self.reload_env, cursor="hand2"),
        ]
        for b in self.env_buttons:
            b.pack(side=tk.LEFT, padx=(0, 6))
        self.buttons += self.env_buttons
        self.env_count = ttk.Label(top, text="")
        self.env_count.pack(side=tk.LEFT, padx=(10, 0))
        if self.env_can_fix:
            intro = ("PATH と道具の環境変数を、レジストリから読んで見ています。[ ] の付いた行（直し方が決まっている物）を押すと選べます。"
                     "マシンの変数を直すときは UAC が出ます。変更は新しく開いたプログラムにだけ届くので、"
                     "開いたままのターミナルや VS Code は開き直してください")
        else:
            intro = ("PATH と道具の環境変数を、レジストリから読んで見ています（ここでは書き換えません）。「直し方」は参考です。"
                     "PATH を書き換えると、関係の無いアプリまで起動しなくなることがあります。分からないときは触らずに、詳しい人に見てもらってください")
        ttk.Label(tab, text=intro, wraplength=1120, justify=tk.LEFT).pack(side=tk.TOP, anchor=tk.W, pady=(8, 4))

        # 出力の欄と全文の行を、表より先に下に置く（出力の欄は書き換えるときだけ）
        self.env_output = None
        if self.env_can_fix:
            out = ttk.Frame(tab)
            out.pack(side=tk.BOTTOM, fill=tk.X, pady=(6, 0))
            scroll = ttk.Scrollbar(out, orient=tk.VERTICAL)
            scroll.pack(side=tk.RIGHT, fill=tk.Y)
            self.env_output = tk.Text(out, height=4, wrap=tk.WORD, yscrollcommand=scroll.set, font=("Consolas", 9))
            self.env_output.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scroll.config(command=self.env_output.yview)
        # 値と説明は長いので、乗せた行の全文を表の下に出す
        self.env_full = ttk.Label(tab, text="", foreground="#555555", wraplength=980, justify=tk.LEFT)
        self.env_full.pack(side=tk.BOTTOM, anchor=tk.W, fill=tk.X, pady=(6, 0))

        table = ttk.Frame(tab)
        table.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        # 説明は表に出す（重複の相手の行など、乗せなくても読めるように。2026-10-29 に「重複していない行が重複と出る」と見えた）
        cols = [("pick", "選ぶ", 44), ("state", "状態", 70), ("kind", "種類", 84), ("scope", "範囲", 56), ("name", "名前", 84),
                ("value", "値", 280), ("detail", "説明", 330), ("fix", "直し方", 170)]
        self.env_tree = ttk.Treeview(table, columns=[c[0] for c in cols], show="headings", selectmode="none")
        for key, label, width in cols:
            self.env_tree.heading(key, text=label)
            self.env_tree.column(key, width=width, stretch=key in ("value", "detail"), anchor=tk.CENTER if key == "pick" else tk.W)
        if not self.env_can_fix:  # 見るだけのときは「選ぶ」の列を出さない
            self.env_tree.configure(displaycolumns=[c[0] for c in cols if c[0] != "pick"])
            self.env_tree.heading("fix", text="直し方（参考）")
        self.env_tree.tag_configure("bad", foreground="#b00020")
        self.env_tree.tag_configure("warn", foreground="#8a5a00")
        self.env_tree.tag_configure("ok", foreground=PLAIN_FG)
        self.env_tree.tag_configure("hover", background=HOVER_BG)
        scroll = ttk.Scrollbar(table, orient=tk.VERTICAL, command=self.env_tree.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.env_tree.configure(yscrollcommand=scroll.set)
        self.env_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.env_tree.bind("<Button-1>", self._env_click)
        self.env_tree.bind("<Motion>", self._env_motion)
        self.env_tree.bind("<Leave>", lambda _e: self._env_hover(None))

    def _env_pickable(self, row: str | None) -> bool:
        return bool(row) and "pick" in self.env_tree.item(row, "tags")

    def _env_hover(self, row: str | None) -> None:
        """押せる行だけ色と指のカーソルを変える。全文の行は、どの行でも出す"""
        if self.env_hover and self.env_tree.exists(self.env_hover):
            self.env_tree.item(self.env_hover, tags=[t for t in self.env_tree.item(self.env_hover, "tags") if t != "hover"])
        self.env_hover = row if self._env_pickable(row) else None
        if self.env_hover:
            self.env_tree.item(self.env_hover, tags=[*self.env_tree.item(self.env_hover, "tags"), "hover"])
        self.env_tree.configure(cursor="hand2" if self.env_hover else "")
        f = self.env_found.get(row) if row else None
        self.env_full.config(text=f"{f['name']}: {f['value']}" + (f"\n{f['detail']}" if f["detail"] else "") if f else "")

    def _env_motion(self, event) -> None:
        self._env_hover(self.env_tree.identify_row(event.y) or None)

    def _env_click(self, event) -> str | None:
        row = self.env_tree.identify_row(event.y)
        if self.env_tree.identify_region(event.x, event.y) == "heading" or not self._env_pickable(row):
            return None
        self.toggle_env(row)
        return "break"

    def _show_fix_count(self) -> None:
        if self.fix_button is not None:
            n = len(self.env_picked)
            self.fix_button.config(text=f"選んだものを直す ({n})" if n else "選んだものを直す")

    def toggle_env(self, row: str) -> None:
        if self.running or not self.env_can_fix:
            return
        self.env_picked.symmetric_difference_update({row})
        values = list(self.env_tree.item(row, "values"))
        values[0] = PICK_ON if row in self.env_picked else PICK_OFF
        self.env_tree.item(row, values=values)
        self._show_fix_count()

    def show_env(self, found: list[dict] | None, error: Exception | None) -> None:
        self.env_hover = None
        self.env_tree.delete(*self.env_tree.get_children())
        if error:
            self.env_count.config(text=f"読めません: {error}")
            return
        self.env_found = {f["id"]: f for f in found}
        self.env_picked &= {f["id"] for f in found if f.get("fix")}
        for row, values, state, pick in env_rows(found, self.env_picked, self.env_can_fix):
            self.env_tree.insert("", tk.END, iid=row, values=values, tags=[state, "pick"] if pick else [state])
        self.env_count.config(text=f"切れている・注意 {env.problems(found)} 件（行にマウスを乗せると、下に全文が出ます）")
        self._show_fix_count()

    def reload_env(self) -> None:
        """レジストリを読んでファイルの有無を見るだけなので CLI を挟まない（速い）。それでも画面は止めない"""
        vars_, cmds = list(self.cfg["env_vars"]), list(self.cfg["env_commands"])
        self._run_in_background(lambda: env.inspect(env.read_registry(), vars_, cmds), self.show_env)

    def fix_picked(self) -> None:
        if not self.env_can_fix:
            return
        ids = [i for i in self.env_found if i in self.env_picked]
        if not ids:
            self.message.config(text="[ ] の付いた行を押して、直す物を選んでください")
            return
        try:
            writes = env.plan(env.read_registry(), list(self.env_found.values()), ids)
        except env.Refused as e:
            messagebox.showwarning("ToolKeeper", f"{e}\n\n「読み直す」を押してから選び直してください。", parent=self.root)
            return
        lines = [c for w in writes for c in w["changes"]]
        uac = "マシンの変数を書くので、UAC の確認が出たら「はい」を押してください。\n" if any(w["scope"] == "machine" for w in writes) else ""
        if not messagebox.askokcancel("ToolKeeper", f"次のとおり書き換えます。{uac}「最後の変更を戻す」で 1 つずつ戻せます。\n\n"
                                      + "\n".join(lines), parent=self.root):
            return
        self.env_picked.clear()
        self.run_command("環境を直す", self.toolkeeper("env", "--fix", *ids), out=self.env_output)

    def undo_env(self) -> None:
        if not self.env_can_fix:
            return
        try:
            w = env.undo_plan(self.data)
        except env.Refused as e:
            self.message.config(text=str(e))
            return
        uac = "\nUAC の確認が出たら「はい」を押してください。" if w["scope"] == "machine" else ""
        if not messagebox.askokcancel("ToolKeeper", w["changes"][0] + "。" + uac + f"\n\n今: {w['old']}\n戻す先: {w['new']}",
                                      parent=self.root):
            return
        self.run_command("最後の変更を戻す", self.toolkeeper("env", "--undo"), out=self.env_output)

    # ---- 履歴のタブ

    def _build_history(self, nb: ttk.Notebook) -> None:
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text="履歴")
        self.history_count = ttk.Label(tab, text="")
        self.history_count.pack(side=tk.BOTTOM, anchor=tk.W, pady=(6, 0))
        table = ttk.Frame(tab)
        table.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        cols = [("at", "時刻", 150), ("key", "キー", 300), ("from", "前", 120), ("to", "後", 120), ("ok", "結果", 60),
                ("code", "終了コード", 110)]
        self.history = ttk.Treeview(table, columns=[c[0] for c in cols], show="headings", selectmode="browse")
        for key, label, width in cols:
            self.history.heading(key, text=label)
            self.history.column(key, width=width, stretch=key == "key")
        self.history.tag_configure("failed", foreground="#b00020")
        scroll = ttk.Scrollbar(table, orient=tk.VERTICAL, command=self.history.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.history.configure(yscrollcommand=scroll.set)
        self.history.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def show_history(self) -> None:
        self.history.delete(*self.history.get_children())
        rows = history_rows(self.data / update.HISTORY_FILE)
        for r in rows:
            self.history.insert("", tk.END, values=r, tags=["failed"] if r[4] == "失敗" else [])
        self.history_count.config(text=f"{len(rows)} 件（新しい順）" if rows else "まだ何も上げていません")

    # ---- 読み直す

    def _show_status(self, s: dict | None, error: Exception | None) -> None:
        if error:
            self.status.config(text=f"状態を読めません: {error}")
            return
        src = s["sources"]
        parts = [f"定期実行 {'登録済み' if s['task']['registered'] else '未登録'}",
                 f"winget {src['winget'] or 'なし'}", f"choco {src['choco'] or 'なし'}",
                 f"Cygwin {'あり' if src['cygwin'] else 'なし'}", f"Ghostscript {'あり' if src['ghostscript'] else 'なし'}",
                 f"データ {s['data_dir']}"]
        self.status.config(text="　".join(parts))

    def reload(self) -> None:
        """結果と履歴を読み直す。状態は winget --version などで 1 秒ほどかかるので裏で"""
        self.result = store.read_json(self.data / check.CHECK_FILE)
        live = {k for k, _v, pick in table_rows(self.result, True, set()) if pick}
        self.picked &= live
        self.show_table()
        self.show_history()
        self.reload_env()
        cfg, data = dict(self.cfg), self.data
        self._run_in_background(lambda: statusmod.run(cfg, data), self._show_status)


def run(config_path: Path, data_override: str | None = None) -> int:
    root = tk.Tk()
    App(root, config_path, data_override)
    root.mainloop()
    return 0
