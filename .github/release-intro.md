<!-- release.yml が Release の本文の後ろに付ける「入れ方・更新の仕方」 -->
## 入れ方・更新の仕方

ToolKeeper は Python のソースのまま動かす道具なので、配るファイルはソースコードだけです（ビルドしたファイルはありません）。
Windows 10 / 11 と Python 3.11 以上（標準ライブラリだけで動きます）、調べる道具に合わせて winget や choco が要ります。

```cmd
git clone https://github.com/lancard-aikawa/ToolKeeper.git
cd ToolKeeper
set PYTHONPATH=src
python -m toolkeeper status
```

更新は、そのフォルダで `git pull`。ソースコードの zip を展開して使うこともできますが、更新は git の方が楽です。
詳しくは [README](https://github.com/lancard-aikawa/ToolKeeper#readme)。
