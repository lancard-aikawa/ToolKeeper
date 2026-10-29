# ToolKeeper

PC に入れた道具（PHP・Ghostscript・Cygwin と、winget / choco で入れたもの）が古くなっていないかを週に 1 回調べ、
選んだものを最新に上げる。Windows 用。実行時の依存は Python 3.11 以上の標準ライブラリだけ。

設計は [docs/design.md](docs/design.md)。

## 使い方

リポジトリのフォルダで:

```
set PYTHONPATH=src
python -m toolkeeper check                 # 全部を調べ、data\check.json に書く
python -m toolkeeper list --all            # 前回の結果を表で出す（--all で C・D も）
python -m toolkeeper update winget:Gyan.FFmpeg ghostscript cygwin   # 選んだ物を上げる（区分 A・B だけ）
python -m toolkeeper env                   # 道具の環境変数と PATH の切れ・重複・2 つある物を出す（書き換えない）
python -m toolkeeper env --fix <ID>        # 直し方のある行を直す（マシンの分は UAC）。--undo で最後の変更を戻す
python -m toolkeeper status --json         # 使える状態か
```

画面の「環境」タブは既定では見るだけ。画面から直す・戻すを出すには、`toolkeeper.json` に `"env_fix": true` を書く
（PATH を壊すと関係の無いアプリまで起動しなくなるので、分かる人だけ）。

`uv` があるなら `uv run toolkeeper check` でもよい。

## 週 1 回の登録

```
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register-task.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register-task.ps1 -Day Friday -At 13:30
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register-task.ps1 -Unregister
```

タスクは調べるだけで、何も入れない。結果は `data\last-run.log` とタスクの「前回の実行結果」
（0 成功、1 ToolKeeper の不具合、2 使い方、3 実行中、4 調べられなかった取得元がある）で見る。
