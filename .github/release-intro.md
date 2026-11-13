<!-- release.yml が Release の本文の後ろに付ける「入れ方・更新の仕方」 -->
## 入れ方・更新の仕方

**[RepoTether](https://github.com/lancard-aikawa/RepoTether) を使っているなら、RepoTether から入れるのがいちばん楽です**
（道具タブの ToolKeeper の欄の「入れる」。Python は要りません。更新も同じ欄から）。

自分で入れるなら、どちらかで（Windows 10 / 11、64 bit）。調べる道具に合わせて winget や choco が要ります。

- **`ToolKeeper-<版>-win-x64.zip`** — 展開するだけで動きます（Python は要りません）。`toolkeeper.exe status` がコマンド、`toolkeeperw.exe gui` が画面。
  設定とデータは exe の隣にできます。更新は、新しい zip の中身で上書きします（設定 `toolkeeper.json` と `data` フォルダは zip に入っていないので残ります）
- **ソースコード** — Python 3.11 以上で動かします。`git clone https://github.com/lancard-aikawa/ToolKeeper.git` して、更新は `git pull`

署名していないので、初回は SmartScreen が出ることがあります。詳しくは [README](https://github.com/lancard-aikawa/ToolKeeper#readme)。
