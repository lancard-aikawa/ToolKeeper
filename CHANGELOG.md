# 変更履歴

<!-- 見出しは `## <版番号>` の形にする。まだ出していない変更は「## 未公開」に書き、リリースのときに版番号へ書き換える -->

## 0.2.0

上げるときに気を付けること:

- `check.json` の形（`schema`）は 1 のまま。項目を足しただけなので、RepoTether 0.15.0 の道具タブもそのまま読める
  （`latest_date`・`summary.env` は無いものとして扱われる）
- 画面の環境のタブは既定では見るだけ。PATH や環境変数を画面から直すには、設定 `env_fix` を `true` にする

変更:

- 環境変数と PATH を調べる（design.md §3.7。`toolkeeper env` と画面の「環境」のタブ）。設定 `env_vars` の変数が無い場所を指していないか、
  PATH の切れ・重複・版の入ったフォルダ、同じコマンドが PATH に 2 つあるか（`env_commands`）。PATH はレジストリから読む。
  `check.json` の `summary.env` に、切れている物と注意の数を出す。PHP の場所もレジストリの PATH で探す
- 直し方が 1 つに決まる物を直す（`toolkeeper env --fix <ID>`・`--undo`。画面では設定 `env_fix` が `true` のときだけ）。マシンの変数は UAC が 1 回出る
- 最新版の公開日（`latest_date`。design.md §3.8）。endoflife.date か `winget show` から取り、画面と `list` に「公開日」の列
- winget が「更新あり」と出し続ける Microsoft の OpenJDK（`21.0.13.21` と `21.0.13.1021`）を、同じ版として扱う（注意に「版の書き方が違うだけで最新」）
- 更新を安全にした:
  - winget を `--silent` で呼ばない。PC 全体に入れた MSI の古い版を消すときに UAC を出せず、1603 で失敗していた（OpenJDK 17）
  - 1 つ失敗したらそこで止め、残りは動かさない
  - 画面を閉じても、裏の更新は最後まで続ける（閉じたら OpenJDK 11 が途中で落ちた）。仕事が動いている間に閉じるときは確かめる
- 失敗の理由を出す: `winget error` で引いた終了コードの意味と、Windows のイベントログにある MSI のエラー（Strawberry Perl の Error 1730）。
  履歴に `reason`、画面に失敗の窓と履歴の「理由」の列
- 管理者でないと上げられない MSI（Error 1730・1925）は、失敗の窓のあとで、管理者のターミナルで `winget upgrade` を動かすかを聞く
- インストーラが環境変数を書き換えたら知らせる（OpenJDK 17 を上げたら `JAVA_HOME` が 17 になった）。履歴に `env`
- winget が黙っている間（取り込みとインストール）、2 秒ごとに経過時間を出す
- 画面: 選んだ行を黄色で塗って太字にし、選んでいる物を表の上に並べる
- 通信の許可（design.md §3.9。`toolkeeper firewall` と画面の「通信の許可」のタブ）。Windows ファイアウォールの規則のうち、プログラムを指す物を見るだけ。
  ブロック、上げて場所が変わり規則が無い物、無いプログラムを指す物を先に並べる

## 0.1.0

- `toolkeeper check`: winget・choco・PHP・Ghostscript・Cygwin の道具が古くなっていないかを調べ、`<data>/check.json` に書く（RepoTether が読む）
- `toolkeeper update`: 区分 A・B の物を上げる。Ghostscript は SHA-256 と Artifex の署名を確かめてから入れる。Cygwin は動いているプログラムがあれば止める
- 週に 1 回 `check` を動かすタスク（`scripts/register-task.ps1`）
- 画面（`toolkeeper gui`）: 道具の一覧・更新・調べ直す・履歴
