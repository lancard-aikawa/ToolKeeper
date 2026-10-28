# ToolKeeper 設計

2026-10-28 時点の案。実装しながら直す。
数字は作者の PC（Windows 11、winget 1.29.380、choco 2.5.1）で 2026-10-28 に測ったもの。

## 1. 何をするか

PC に入れた道具（PHP・Ghostscript・Cygwin と、winget / choco で入れたもの）が古くなっていないかを週に 1 回調べ、
画面で選んだものを最新に上げる。

LockWatch とは見る物が違う。LockWatch はリポジトリの lock ファイルに書かれた依存を照合する。
ToolKeeper は**この PC に入っている道具そのもの**の版を見る。両方は互いに呼び合わない。

2026-10-28 の手元の状態（作るきっかけ）:

| 道具 | 入っている版 | 最新 | 入れ方 |
|---|---|---|---|
| PHP | 8.3.7（2024-05） | 8.3.36 | `C:\work\php-8.3.7-nts-Win32-vs16-x64` に zip を手で展開 |
| Ghostscript | 10.05.1 | 10.08.0（2026-09-08） | `C:\Program Files\gs\gs10.05.1`、インストーラを手で実行 |
| Cygwin | 3.6.0（最後の更新 2025-04-01） | 3.6.12-1 | `C:\cygwin64`、パッケージ 77 個 |
| winget | 44 件が更新できる | | Godot と osv-scanner は pin で版を固定している |
| choco | 20 件が古い | | 管理者権限が要る |

## 2. 区分

道具を 5 つに分け、区分ごとに扱いを変える。区分は設定（§6）の ID の一覧で決める。一覧に無い winget の物は C とみなす。

| 区分 | 対象（2026-10-28 の例） | 調べる | 更新のボタン |
|---|---|---|---|
| **A. 専用の処理** | PHP（winget へ乗り換える、§7）、Ghostscript、Cygwin | する | 付ける |
| **B. winget の開発の道具** | `7zip.7zip`、`GitHub.cli`、`Kitware.CMake`、`Gyan.FFmpeg`、`Python.Python.3.14`、`Python.Launcher`、`Rustlang.Rustup`、`StrawberryPerl.StrawberryPerl`、`TeraTermProject.teraterm5`、`Microsoft.OpenJDK.11/17/21`、`EclipseAdoptium.Temurin.11.JDK`、`EclipseAdoptium.Temurin.8.JRE`、`PHP.PHP.NTS.8.3`、`Cygwin.CygwinSetup` | する | 付ける |
| **C. winget の残り** | 自分で更新するアプリ（Claude・Slack・Zoom・Docker・Notion）、大きく変わるもの（VS 2022 の 17.7 → 17.14、VS Build Tools、WSL、VirtualBox 7.1 → 7.2）、VCRedist、NVIDIA など | する | 付けない（一覧に出すだけ） |
| **D. choco** | 20 件 | する | 付けない（知らせるだけ） |
| **E. 大きい版の乗り換え** | Node.js 20（2026-04 にサポート終了）、JDK 8・11、Python・PHP の系列 | サポート終了だけ | 付けない（警告だけ） |

- **止めたい物は winget の pin に任せる。**ToolKeeper は `--include-pinned` を付けないので、pin した物は一覧に出ない。版を固定する手段を ToolKeeper 側に作らない
- D を更新しない理由: 管理者権限が要る。winget と二重に管理している物がある（gh・MarkText・OpenJDK 17 / 21 は両方の一覧に出る）。
  choco の `python` は 3.14.0 から 3.15.2 に系列ごと上げようとする。二重の物は choco から外して winget に寄せる（§10）
- E は winget の ID が系列ごとに分かれている（`OpenJS.NodeJS.20`、`Python.Python.3.14`）ので、`winget upgrade` では系列の中の更新しか出ない。
  系列の乗り換えは、使っている側（リポジトリ、PATH、venv）の都合があるので人が決める
- uv の Python、rustup のツールチェーン、npm の global、fvm は対象外。それぞれの道具に任せる

## 3. 調べ方と上げ方

### 3.1 winget（B・C、A の PHP と Cygwin Setup）

調べる: `winget upgrade --accept-source-agreements --disable-interactivity`

- JSON で出す手段が無いので、表を読む。PowerShell の `Microsoft.WinGet.Client` は入っておらず、足すと依存が増えるので使わない
- 出力は **UTF-8**（コンソールのコード ページが 932 でも、パイプに出すときは UTF-8 だった）
- 列は空白で揃えてあり、**全角を 2 桁として数える**（`unicodedata.east_asian_width` が W / F の文字）。
  見出しの文字は言語で変わる（日本語では「名前 / ID / バージョン / 利用可能 / ソース」）ので、文字では探さない。
  `-----` だけの行の 1 つ上を見出しとし、見出しの語の始まりの桁で列を切る
- 名前は長いと `…` で切られる。ID で照合するので困らない
- 表の後ろの「44 アップグレードを利用できます。」などの行は、列の数が合わないので捨てる。
  「pin があります」「版を判別できません」の行は件数だけを拾って画面に出す（言語に依らないよう、数字だけを見る）
- 先頭に進み具合の記号（`\r`、`-\|/`）が混じることがあるので、`\r` より前を捨てる

上げる: `winget upgrade --id <ID> --exact --silent --accept-package-agreements --accept-source-agreements --disable-interactivity`

- machine 範囲で入れた物は、インストーラが自分で UAC を出す。ToolKeeper は管理者として動かない
- 終了コードが 0 以外なら、出力の最後の 20 行を結果に残す

### 3.2 PHP

winget の `PHP.PHP.NTS.8.3`（portable の zip、8.3.36）に乗り換え、以後は §3.1 の B として扱う。乗り換えの手順は §7。

- zip は `%LOCALAPPDATA%\Microsoft\WinGet\Packages\PHP.PHP.NTS.8.3_Microsoft.Winget.Source_8wekyb3d8bbwe\` に展開される。フォルダ名に版が入らないので、更新でパスは変わらない
- 目録に `ArchiveBinariesDependOnPath: true` があるので、winget は Links に置かず、**展開したフォルダそのものをユーザーの PATH の末尾に足す**（DLL を一緒に読むため。2026-10-28 に確かめた）。
  前に入れた PHP が PATH にあると、そちらが先に使われる
- **`php.ini` は展開先に置かない。**更新で消える心配がある（未確認）。`C:\work\php-conf\php.ini` に置き、ユーザーの環境変数 `PHPRC` で指す
- `extension_dir` は展開先の `ext` を絶対パスで書く（相対で書くと、PHP は実行したときの作業フォルダから探す）
- `check` は、PATH の php が winget のフォルダの下にあれば winget の行に任せ、A の `php` の行を出さない

### 3.3 Ghostscript

本家（Artifex）は winget に出していない（2026-10-28 に `winget search ghostscript` で確かめた）。

調べる:

- 入っている版: レジストリ `HKLM\SOFTWARE\GPL Ghostscript\<版>`（版ごとにキーができる。複数あれば全部出す）
- 最新: `https://api.github.com/repos/ArtifexSoftware/ghostpdl-downloads/releases/latest`。トークンは使わない（1 時間に 60 回まで。週 1 回なら足りる）。
  タグ `gs10080` は 10.08.0、64 ビット版は `gs10080w64.exe`。API が資産ごとに `digest`（`sha256:...`）を返す

上げる:

1. `gs<N>w64.exe` を、ほかに何も無い `<data>/downloads/ghostscript/` に取る。`digest` の SHA-256 と合わなければ止める
   （GitHub が `digest` を返さなければ入れない）。前に取った物の SHA-256 が合えば取り直さない（65 MB。手元では 3〜7 分かかった）
2. Authenticode の状態が `Valid` で、署名者に `O="Artifex Software, Inc."` が無ければ止める。
   `Get-AuthenticodeSignature` を `powershell.exe`（5.1）で呼ぶときは `PSModulePath` を外す（PowerShell 7 から起動すると引き継がれ、全部失敗する。ProcCheck の件）。
   **Windows の Python の `os.environ` は名前を大文字（`PSMODULEPATH`）で持つ**ので、大文字小文字を区別せずに外す（2026-10-28、`pop("PSModulePath")` では消えずに失敗した）
3. `scripts/gs-install.ps1` を `Start-Process -Verb RunAs` で動かす（UAC が 1 回）。スクリプトの出力は見えないので、`<data>/downloads/ghostscript-install.log` に書かせて読む
   1. 入れる**前に**、古い版の bin の場所をレジストリ（`GS_DLL`）から読んでおく
   2. `gs<N>w64.exe /S` で入れる
   3. マシンとユーザーの PATH の古い bin を新しい bin に書き換える。インストーラが既に直していれば触らない。新しい行が既にあって古い行も残っていれば、古い行を消す。
      PATH はレジストリから展開せずに読み、`REG_EXPAND_SZ` のまま書く（`[Environment]::GetEnvironmentVariable` は `%SystemRoot%` を展開して返すので使わない）
4. 新しい版がレジストリに載ったことを確かめ、取ったインストーラを消す

10.05.1 → 10.08.0 で確かめたこと（2026-10-28）:

- `/S` で画面を出さずに入る。終了コードは 0
- **インストーラが古い版を自分で消す**（フォルダ・レジストリ・アンインストールの登録）。そのため「古い版を消す」は作らない（`old:` の印は、手で入れた古い版が残っているときだけ出る）
- **インストーラがマシンの PATH を自分で直す**（古い行を消し、新しい行を末尾に足す）。ほかの 36 行と `%...%` の 7 行は変わらなかった。
  ToolKeeper の書き換えは、インストーラがそうしない版に当たったときのための備え（HKCU の試験用のキーで、置き換え・重ならない・既に直っている・無い、の 4 つを確かめた）

### 3.4 Cygwin

調べる:

- 入っている物: `C:\cygwin64\etc\setup\installed.db`。1 行目は `INSTALLED.DB 3`、以後は `<名前> <ファイル名> 0`。
  版はファイル名から `<名前>-` と `.tar.*` を外して取る（`alternatives-1.31-1.tar.bz2` は 1.31-1）
- ミラー: `C:\cygwin64\etc\setup\setup.rc` の `last-mirror` の次の行（手元は `https://ftp.jaist.ac.jp/pub/cygwin/`）
- 最新: `<ミラー>/x86_64/setup.xz`（3.6 MB、展開すると 22 MB、jaist から 28 秒）を `lzma` で読む。
  `@ <名前>` の後の**最初の** `version:` が今の版。`[prev]` と `[test]` の後の `version:` は使わない
- `setup.xz` は 1 日に 1 回だけ取り直す

上げる:

1. Cygwin の中のプログラムが動いていれば止める（実行ファイルのパスが `C:\cygwin64\` で始まるプロセス。`EnumProcesses` と `QueryFullProcessImageNameW` を ctypes で呼ぶ）。
   **プロセスを勝手に終了しない**。名前を出して、閉じてもらう
2. Cygwin Setup は winget の `Cygwin.CygwinSetup`（portable、2.937）を使う。winget が SHA-256 を照合するので、自分では取らない。
   `%LOCALAPPDATA%\Microsoft\WinGet\Links\cygwinsetup.exe`（シンボリックリンク）に置かれる。無ければ `winget install` で入れる。
   Setup そのものの更新は B の `Cygwin.CygwinSetup` として winget の行で出る
3. `cygwinsetup.exe --quiet-mode --wait --upgrade-also --root C:\cygwin64 --site <ミラー> --only-site --local-package-dir <setup.rc の last-cache> --no-desktop --no-shortcuts --no-startmenu`
   - Setup は `asInvoker` で作られていて、管理者が要ると自分で UAC を出して上がる。`--wait` で、上がった子のプロセスが終わるまで待つ（PowerShell のスクリプトは挟まない）
   - `--only-site` はミラーの一覧を取らない
   - Setup の出力は見えないので、`<root>/var/log/setup.log` の最後の 20 行を読む（このファイルは前の回の分も残っている）
4. `installed.db` と `setup.xz` で古い物が残っていないか見る。残っていれば失敗にする

3.6.0-1 → 3.6.12-1（古いパッケージ 38 個）で確かめたこと（2026-10-28）: UAC は 1 回、124 秒、終了コード 0。新しく要るようになったパッケージが 3 個入り、77 個 → 80 個、古い物 0 個。

### 3.5 choco（D）

`choco outdated --limit-output` は `名前|今の版|最新|pin` の行を返す（管理者でなくても動く）。一覧に出すだけ。
winget の一覧にも同じ物があれば（名前の対応は設定 §6 の `choco_twins`）、「winget でも見えている」と印を付ける。

### 3.6 サポート終了（E）

endoflife.date の `https://endoflife.date/api/<製品>.json` で系列ごとのサポート終了日を見る。
winget の ID と系列の対応は設定 §6 の `eol` に正規表現で書く（最初の `()` が系列。例: `OpenJS\.NodeJS\.(\d+)` → `nodejs`、
`Python\.Python\.(\d+\.\d+)` → `python`、`PHP\.PHP\.(?:NTS\.)?(\d+\.\d+)` → `php`）。終わっていれば「サポート終了」、90 日以内なら「もうすぐ終了」。取ったものは 1 日置いておく。

- 更新の無い物も見るため、`winget list --source winget` の行を規則に当てる（`winget upgrade` には更新のある物しか出ない）。
  `winget list` は pin で止めた物の「利用可能」も出すので、更新の一覧には使わない
- サポート終了の物は区分を E にする。サポート中で更新も無い物は出さない
- 手で入れた PHP（§3.2 の乗り換え前）は、endoflife.date の系列の `latest` を最新とみなす

## 4. 守ること

- **定期の実行（タスク）は調べるだけで、何も入れない。**入れるのは、人が画面で押したときか、`toolkeeper update` を手で打ったときだけ
- 外に出すのは道具の名前だけ（GitHub・endoflife.date・Cygwin のミラー。winget と choco は自分の取得元に問い合わせる）
- トークンを扱わない
- 自分で取ったファイルは、SHA-256 と署名を確かめてから実行する（§3.3）
- プロセスを勝手に終了しない（§3.4）
- 管理者として常駐しない。権限が要る所はその場で UAC を出す

## 5. 実行

```
toolkeeper check            # 全部を調べ、<data>/check.json に書く。前回から増えた更新を出す
toolkeeper list             # check.json を表で出す
toolkeeper update <キー>... # 選んだものを上げる（キーは winget:<ID>、php、ghostscript、cygwin）
toolkeeper status --json    # 使える状態か（RepoTether の「確かめる」が呼ぶ、§9）
toolkeeper gui              # 画面
```

- `check` は道具ごとに独立して動かす。1 つが失敗しても（ネットが無い、Cygwin が無いなど）残りは出し、失敗した物は理由を付けて出す
- `update` は 1 つずつ順に動かす（winget は並べて動かせない）。結果を `<data>/history.jsonl` に足す
  （`{at, key, from, to, ok, code, tail}`。`code` は `0x8A15002B` の形、`tail` は失敗したときの出力の最後の 20 行）
  - 上げてよいのは `check.json` で区分が A・B、`updatable` の物だけ。1 つでも外れた物を選んだら、どれも動かさずに理由を出して止める
  - 手で入れた PHP（`php`）は選べない。§7 の乗り換えを案内する
  - winget の `0x8A15002B`（上げる物が無い。ほかで先に上げた）は失敗にしない
  - 1 つが失敗しても残りは続ける。終わったら `check` をもう一度流して `check.json` を今の状態にする（`--no-check` で流さない）
- `check` と `update` は `<data>/lock` で排他する。取れなければ終了コード 3
- 終了コード: 0 成功、2 使い方の誤り・上げられない物を選んだ、3 実行中、4 調べられなかった取得元がある（`check`）、5 上げられなかった物がある（`update`）
- タスクスケジューラ: 週 1 回 `check`。窓を出さないよう、LockWatch と同じく本体の `pythonw.exe` で `scripts/toolkeeper-launch.py` を動かす（`scripts/find-pythonw.ps1`）

`check.json` の形は §9.1。

## 6. 設定（`<app>/toolkeeper.json`）

| キー | 既定 | 意味 |
|---|---|---|
| `data_dir` | `<app>/data` | 結果とキャッシュの置き場 |
| `winget_update` | §2 の B の ID | 更新のボタンを付ける winget の ID。無い物は C |
| `cygwin_root` | `C:\cygwin64` | 無ければ Cygwin は調べない |
| `ghostscript` | `true` | Ghostscript を調べるか |
| `choco` | `true` | choco を調べるか（入っていなければ調べない） |
| `eol` | §3.6 の 5 つ（Node.js・Python・PHP・Microsoft の OpenJDK・Temurin） | `{"id": 正規表現, "product": endoflife.date の製品}` の並び |
| `choco_twins` | gh・marktext・microsoft-openjdk17・microsoft-openjdk-21・python314・Temurin11・visualstudio2019buildtools | choco の名前 → winget の ID（版が一致した物を 2026-10-28 に確かめた） |
| `cache_hours` | `24` | `setup.xz`・endoflife.date・GitHub を取り直す間隔 |

ファイルに書いたキーだけ既定値を置き換える。並びや表は丸ごと置き換える（足し合わせない）。全部の既定値は `toolkeeper.sample.json`。

## 7. PHP の乗り換え（1 回だけ、手で）

1. 今の拡張と設定を控える: `php -m`、`php --ini`、`php.ini`（`php.ini-development` と比べて、変えてある行を見る）
2. `winget install --id PHP.PHP.NTS.8.3 --exact`
3. `php.ini` を `C:\work\php-conf\php.ini` に写し、`extension_dir` を新しい展開先の `ext` に直す。ユーザーの環境変数 `PHPRC=C:\work\php-conf`
4. ユーザーの PATH から古いフォルダを外す（レジストリから展開せずに読み、`REG_EXPAND_SZ` のまま書く）
5. 新しいターミナルで、`where php` が winget のフォルダの 1 つだけ、`php -v` が新しい版、`php --ini` が `C:\work\php-conf\php.ini`、`php -m` が 1 と同じことを確かめる
6. 古いフォルダを直に指している物（IDE の設定、`.bat`、Web サーバの設定、タスク）を探して直す
7. 古いフォルダは、しばらく残してから消す

2026-10-28 に 8.3.7 → 8.3.36 で通した。変えてあったのは `memory_limit = 1024M`、`extension_dir`、拡張 16 個だけ。拡張の一覧は前と同じになった。
古いフォルダを指していたのは VS Code のユーザー設定の `php.validate.executablePath` だけ（`C:\Repos` と `C:\work` の設定ファイル、タスク、環境変数、JetBrains の設定を探した）。
古い `C:\work\php-8.3.7-nts-Win32-vs16-x64` はまだ残してある。

## 8. 画面（`toolkeeper gui`）

tkinter。LockWatch と同じ決まり（絵文字を使わない、下のボタン行を先に `side=BOTTOM`、タブは `ensure_notebook_style`、重い仕事は別のプロセスで CLI を呼ぶ）。

- 1 つの表に全部を並べる: 区分・名前・入っている版・最新・注意（サポート終了、choco と二重、pin の件数）
- A と B の行だけにチェックの枠を付け、「選んだものを更新」で `toolkeeper update` を別のプロセスで呼ぶ。C・D・E の行は押せない平らな行にし、区分の札で分ける
- 更新の途中の出力は下の欄に流す。Cygwin のプロセスが動いているときは、更新を始める前に名前を出して止める

## 9. RepoTether との受け渡し

RepoTether（`../RepoTether`）の「脆弱性」タブの隣に「道具」タブを置き、ToolKeeper の結果を出す。LockWatch の組み込み方と同じ形にする。

- **RepoTether は見るだけ。**`check.json` を読み、`toolkeeper status --json` を呼ぶだけで、`update` は呼ばない。
  更新は「ToolKeeper を開く」で ToolKeeper の画面（`toolkeeper gui`）を出し、そこでする（UAC、数分かかる Cygwin、プロセスを閉じてもらう場面があるため）
- 脆弱性タブの中には混ぜない。脆弱性タブはプロジェクトごとの行の表で、ToolKeeper の結果は PC 全体で 1 つ
- ToolKeeper は RepoTether を呼ばない。RepoTether が無くても ToolKeeper は単独で動く
- RepoTether 側を作るのは、ToolKeeper の `check` が動いてから

「道具」タブの中身（RepoTether 側の案）:

| 部分 | 中身 |
|---|---|
| タブの数 | `summary.updatable`（A・B の更新できる件数）＋ `summary.eol`（サポート終了の件数） |
| 表 | 区分・名前・入っている版・最新・注意。重いもの（サポート終了 → A → B → C・D）の順 |
| ボタン | 「ToolKeeper を開く」「結果を読み直す」 |
| 下の欄 | ToolKeeper の場所、「確かめる」（`status --json` の中身を出す） |

### 9.1 `check.json`（ToolKeeper → RepoTether）

`<data>/check.json`。`check` のたびに丸ごと書き直す（一時ファイルに書いてから `os.replace`）。

```json
{
  "schema": 1,
  "toolkeeper": "0.1.0",
  "checked_at": "2026-10-28T10:00:00+09:00",
  "summary": {"updatable": 17, "eol": 2, "new": 3, "failed": 1},
  "items": [
    {"key": "winget:Gyan.FFmpeg", "tier": "B", "name": "FFmpeg", "installed": "8.1", "latest": "9.0.2",
     "updatable": true, "eol": null, "new": true, "notes": []},
    {"key": "winget:OpenJS.NodeJS.20", "tier": "E", "name": "Node.js", "installed": "20.9.0", "latest": "20.20.2",
     "updatable": true, "eol": {"product": "nodejs", "cycle": "20", "date": "2026-04-30", "state": "ended"}, "new": false, "notes": []},
    {"key": "cygwin", "tier": "A", "name": "Cygwin", "installed": "3.6.0-1", "latest": "3.6.12-1",
     "updatable": true, "eol": null, "new": false, "notes": ["running:mintty.exe"],
     "packages": {"installed": 77, "outdated": 38, "names": ["bash", "cygwin"]}},
    {"key": "choco:gh", "tier": "D", "name": "gh", "installed": "2.87.2", "latest": "2.103.3",
     "updatable": true, "eol": null, "new": false, "notes": ["twin:winget:GitHub.cli"]}
  ],
  "failed": [
    {"source": "ghostscript", "reason": "GitHub に接続できない"}
  ]
}
```

- `schema` は形の版。項目を足すだけなら上げない。名前や意味を変えたら上げ、RepoTether は知らない `schema` なら読まずに「ToolKeeper を更新してください」と出す
- `checked_at` が古ければ（8 日より前）、RepoTether は「定期実行が止まっている」と出す
- `tier` は `A`〜`E`。更新のボタンを付けてよいのは `A` と `B` だけ（RepoTether は付けないが、ToolKeeper の画面と同じ判断に使う）
- `updatable` は新しい版があるか。`summary.updatable` は `tier` が A・B で `updatable` の物の数。
  Cygwin は本体の版が同じでもパッケージが古ければ `true`（`packages` に数と、古い物の名前を 50 個まで）
- `installed`・`latest` は winget などが出したままの文字（`< 3.14.7`、`7.1.9 (48550)` もある）。大小は比べない
- `eol.state` は `ended`（終了）・`soon`（90 日以内）・`ok`。分からなければ `eol` が `null`
- `new` は前回の `check` に無かった更新（同じ `key` で `latest` が変わったものも含む）。初めての `check` では全部 `false`
- `notes` は短い印の並び: `twin:<key>`（choco と winget で二重）、`pinned`（choco の pin）、`pinned:<件数>`（winget の pin。`key` が `winget:(pinned)` の行）、
  `running:<名前>`（Cygwin のプロセスが動いている）、`manual`（手で入れた PHP。§7 の乗り換え）、`old:<版>`（Ghostscript の古い版も入っている）
- `failed` は調べられなかった取得元と理由。1 つが失敗しても `items` は残りの分を出す
- 手元のパスは入れない（RepoTether が画面の画像を撮ることがあるため。場所は `status` で返す）

### 9.2 `toolkeeper status --json`

RepoTether の「確かめる」と、ToolKeeper の画面の上の欄が使う。速く返す（ネットに出ない、winget も呼ばない）。

```json
{
  "toolkeeper": "0.1.0",
  "schema": 1,
  "data_dir": "C:\\Repos\\mywork\\ToolKeeper\\data",
  "last_check": "2026-10-28T10:00:00+09:00",
  "task": {"registered": true},
  "sources": {"winget": "1.29.380", "choco": "2.5.1", "cygwin": "C:\\cygwin64", "ghostscript": true}
}
```

- `task` はタスクスケジューラの登録を `schtasks /query /tn ToolKeeper` の終了コードで見る（登録は `scripts/register-task.ps1`）。
  次の実行時刻は出さない（`schtasks` の一覧の見出しが言語で変わるため）
- 道具が無ければ `sources` のその値を `null` にする（Cygwin を入れていない PC など）
- `winget --version` と `choco --version` だけは呼ぶ（どちらも 1 秒以内）

## 10. 決めていないこと

- 新しい更新を知らせる手段（Windows の通知、Slack、画面を開いたときだけ、RepoTether の「道具」タブの数（§9））
- choco と二重の物の外し方（`choco uninstall <名前> -n` で choco の記録だけ消せるかを確かめる）。外し終われば `choco_twins` は要らなくなる
- FFmpeg のように大きい版が上がる物を B に置いたままにするか（2026-10-28 は B に置くと決めた）
