# ToolKeeper

設計は `docs/design.md` が正。仕様を変えたら先にそちらを直す。LockWatch（`../LockWatch`）と同じ作法で作る。

- 実行時の依存は足さない（標準ライブラリだけ）。テストも `unittest`
- ファイルは必ず `encoding="utf-8"` で開く。JSON を書くときは `newline="\n"`、一時ファイルに書いてから `os.replace`
- **定期の実行は調べるだけ。何かを入れる処理は `update` からしか呼ばない**（design.md §4）
- **プロセスを勝手に終了しない。**Cygwin の更新の前に動いている物があれば、名前を出して止める
- 自分で取ったインストーラは SHA-256 と署名を確かめてから実行する。トークンは扱わない
- winget の表は言語で見出しが変わる。見出しの文字で探さず、`-----` の行と全角 2 桁の数え方で列を切る（design.md §3.1）
- テストで本物の winget・choco・ネットを使わない。出力は `tests/fixtures/` に小さく作って読ませる（日本語の名前の行を必ず入れる）
- `check.json` と `status --json` は RepoTether が読む（design.md §9）。名前や意味を変えたら `schema` を上げ、design.md §9 と RepoTether の両方を直す。
  ToolKeeper から RepoTether を呼ばない
- 設定のキーを足したら `config.py` の `DEFAULTS`、`toolkeeper.sample.json`、design.md §6 を一緒に直す
- 画面（`gui.py`）は tkinter。絵文字を使わない、下のボタン行は本体より先に `side=BOTTOM` で置く、タブは `ensure_notebook_style` を使う。
  更新などの重い仕事は画面のスレッドで動かさない（別のプロセスで CLI を呼ぶ）
- `scripts/*.cmd` と `scripts/*.ps1` は ASCII だけ・CRLF（コメントもメッセージも英語）。使い方は `powershell -NoProfile -ExecutionPolicy Bypass -File ...` で書き、
  Windows PowerShell 5.1 で動くものにする。`tests/test_scripts.py` で検査する
- 窓を出さずに動かすときは `.venv\Scripts\pythonw.exe` を使わない（コンソール用で黒い窓が開く）。`scripts/find-pythonw.ps1` が探す本体の `pythonw.exe` で
  `scripts/toolkeeper-launch.py` を動かす。`.venv` があることを前提にしない
