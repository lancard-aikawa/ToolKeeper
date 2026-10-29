"""コマンドライン（docs/design.md §5）"""
import argparse
import contextlib
import json
import sys
import traceback
from pathlib import Path

from . import __version__, check, store, winget
from .labels import ENV_KIND, ENV_STATE, SCOPE_LABEL, TIER_LABEL, note_text
from . import config as cfgmod
from . import env as envmod
from . import status as statusmod
from . import update as updatemod
from .paths import data_dir, default_config_path

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_BUSY = 3
EXIT_PARTIAL = 4  # 調べられなかった取得元がある
EXIT_FAILED = 5   # 上げられなかった物がある

class _Unbroken:
    """書く先が無くなっても（読む側が閉じた）例外を出さず、黙って捨てる出力"""

    def __init__(self, stream):
        self._stream, self._broken = stream, stream is None

    def write(self, s: str) -> int:
        if not self._broken:
            try:
                self._stream.write(s)
            except (OSError, ValueError):
                self._broken = True
        return len(s)

    def flush(self) -> None:
        if not self._broken:
            try:
                self._stream.flush()
            except (OSError, ValueError):
                self._broken = True

    def __getattr__(self, name):
        return getattr(self._stream, name)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="toolkeeper", description="PC に入れた道具が古くなっていないかを調べる")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--config", help="設定ファイル（既定: プログラムの置き場所の toolkeeper.json）")
    p.add_argument("--data", help="データの場所（設定より優先）")
    p.add_argument("--log", action="store_true", help="今回の出力を <data>/last-run.log に書く（定期実行の pythonw 用）")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="全部を調べ、<data>/check.json に書く。前回から増えた更新を出す")
    ls = sub.add_parser("list", help="check.json を表で出す")
    ls.add_argument("--all", action="store_true", help="C・D も出す（既定は A・B・E と、サポート終了の物）")
    up = sub.add_parser("update", help="選んだ物を上げる（区分 A・B だけ）。終わったら調べ直す")
    up.add_argument("keys", nargs="+", metavar="キー", help="check.json の key（winget:<ID> など）")
    up.add_argument("--no-check", action="store_true", help="終わったあとに調べ直さない")
    ev = sub.add_parser("env", help="道具にかかわる環境変数と PATH をレジストリから読んで出す（--fix・--undo のときだけ書き換える）")
    ev.add_argument("--fix", nargs="+", metavar="ID", help="出した行の ID を直す（直し方のある行だけ。マシンの分は UAC が出る）")
    ev.add_argument("--undo", action="store_true", help="最後の変更を 1 つ戻す")
    st = sub.add_parser("status", help="使える状態か")
    st.add_argument("--json", action="store_true", help="JSON で出す")
    sub.add_parser("gui", help="画面を開く（pythonw で scripts/toolkeeper-launch.py gui なら黒い窓が出ない）")
    return p


def _fit(s: str, n: int, right: bool = False) -> str:
    """全角を 2 桁と数えて n 桁に詰める（長ければ切る）"""
    out = ""
    for c in s:
        if winget.width(out + c) > n:
            break
        out += c
    pad = " " * (n - winget.width(out))
    return pad + out if right else out + pad


def _print_table(result: dict, show_all: bool) -> None:
    s = result["summary"]
    print(f"調べた時刻 {result['checked_at']}  更新できる {s['updatable']}  サポート終了 {s['eol']}  "
          f"新しい {s['new']}  失敗 {s['failed']}  環境 {s.get('env', 0)}（toolkeeper env）")
    rows = [it for it in result["items"]
            if show_all or it["tier"] in ("A", "B", "E") or (it.get("eol") and it["eol"]["state"] != "ok")]
    for it in rows:
        mark = "*" if it["updatable"] and it["tier"] in ("A", "B") else " "
        print(f"{mark} {_fit(TIER_LABEL[it['tier']], 11)} {_fit(it['name'], 36)} {_fit(it['installed'] or '-', 16, True)} -> "
              f"{_fit(it['latest'] or '-', 16)} {_fit(it.get('latest_date') or '-', 10)} {note_text(it)}")
    hidden = len(result["items"]) - len(rows)
    if hidden:
        print(f"  (C・D の {hidden} 件は --all で出す)")
    for f in result["failed"]:
        print(f"! {f['source']}: {f['reason']}")


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # pythonw では None
            pass
    args = _build_parser().parse_args(argv)
    try:
        cfg = cfgmod.load(Path(args.config) if args.config else default_config_path())
    except (OSError, ValueError) as e:
        print(f"設定を読めません: {e}", file=sys.stderr)
        return EXIT_USAGE
    data = data_dir(cfg, args.data)
    if not args.log:
        return _dispatch(args, cfg, data)
    # pythonw では標準出力が捨てられるので、今回の出力をファイルに残す（design.md §5）
    data.mkdir(parents=True, exist_ok=True)
    with open(data / "last-run.log", "w", encoding="utf-8", newline="\n") as log, \
            contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        print(f"{store.iso(store.now())} toolkeeper {' '.join(argv if argv is not None else sys.argv[1:])}")
        try:
            code = _dispatch(args, cfg, data)
        except Exception:
            traceback.print_exc()
            code = 1
        print(f"{store.iso(store.now())} 終了コード {code}")
    return code


def _env(args, cfg: dict, data: Path, reg: envmod.Registry | None = None) -> int:
    """環境変数と PATH（§3.7）。--fix・--undo のときだけ書き換える"""
    try:
        if args.undo:
            writes = [envmod.undo_plan(data)]
        elif args.fix:
            found = envmod.inspect(envmod.read_registry(), cfg["env_vars"], cfg["env_commands"])
            writes = envmod.plan(envmod.read_registry(), found, args.fix)
        else:
            writes = None
        if writes is not None:
            for w in writes:
                for c in w["changes"]:
                    print(c)
            data.mkdir(parents=True, exist_ok=True)
            envmod.apply(writes, data, reg)
            print("書き換えました。新しく開いたプログラムにだけ届きます（開いたままのターミナルや VS Code は開き直す）")
            return EXIT_OK
    except envmod.Refused as e:
        print(e, file=sys.stderr)
        return EXIT_USAGE
    except (OSError, RuntimeError) as e:
        print(e, file=sys.stderr)
        return EXIT_FAILED
    found = envmod.inspect(envmod.read_registry(), cfg["env_vars"], cfg["env_commands"])
    for f in found:
        print(f"{_fit(ENV_STATE[f['state']], 10)} {_fit(ENV_KIND[f['kind']], 12)} {_fit(SCOPE_LABEL[f['scope']], 8)} "
              f"{_fit(f['name'], 10)} {f['value']}")
        if f["detail"]:
            print(f"{' ' * 42}{f['detail']}")
        if f.get("fix"):
            print(f"{' ' * 42}直し方: {envmod.fix_text(f)}（--fix {f['id']}）")
    print(f"切れている・注意 {envmod.problems(found)} 件（変更は新しく開いたプログラムにだけ届く）")
    return EXIT_OK


def _dispatch(args, cfg: dict, data: Path) -> int:
    if args.command == "check":
        try:
            with store.exclusive(data):
                result = check.run(cfg, data)
        except store.Busy as e:
            print(e, file=sys.stderr)
            return EXIT_BUSY
        _print_table(result, show_all=False)
        return EXIT_PARTIAL if result["failed"] else EXIT_OK
    if args.command == "update":
        # 画面から呼ばれたとき、途中で画面を閉じると出力の先が無くなる。そこで止まると、入れかけのまま履歴も残らない
        # （2026-10-29、OpenJDK 11 が OSError: [Errno 22] で落ちた）。書けなくても最後まで続ける
        sys.stdout, sys.stderr = _Unbroken(sys.stdout), _Unbroken(sys.stderr)
        try:
            with store.exclusive(data):
                done = updatemod.run(cfg, data, args.keys)
                if not args.no_check:
                    print("\n調べ直しています…", flush=True)
                    check.run(cfg, data)
        except store.Busy as e:
            print(e, file=sys.stderr)
            return EXIT_BUSY
        except updatemod.Refused as e:
            print(e, file=sys.stderr)
            return EXIT_USAGE
        failed = [d["key"] for d in done if not d["ok"]]
        skipped = len(args.keys) - len(done)
        print(f"\n済み {len(done) - len(failed)} 件、失敗 {len(failed)} 件" + (f": {', '.join(failed)}" if failed else "")
              + (f"、止めたので動かしていない物 {skipped} 件" if skipped else ""))
        for d in done:
            if d.get("reason"):
                print(f"{d['key']} の理由:\n" + "".join(f"  {x}\n" for x in d["reason"].splitlines()), end="")
            if d.get("env"):
                print(f"{d['key']} で環境変数が変わりました（toolkeeper env で確かめる）:\n"
                      + "".join(f"  {envmod.change_text(c)}\n" for c in d["env"]), end="")
        return EXIT_FAILED if failed else EXIT_OK
    if args.command == "list":
        result = store.read_json(data / check.CHECK_FILE)
        if not result:
            print("まだ調べていません（toolkeeper check）", file=sys.stderr)
            return EXIT_USAGE
        _print_table(result, show_all=args.all)
        return EXIT_OK
    if args.command == "env":
        return _env(args, cfg, data)
    if args.command == "status":
        st = statusmod.run(cfg, data)
        if args.json:
            print(json.dumps(st, ensure_ascii=False, indent=2))
        else:
            for k, v in st.items():
                print(f"{k}: {v}")
        return EXIT_OK
    if args.command == "gui":
        from .gui import run  # tkinter は画面を開くときだけ読む
        return run(Path(args.config) if args.config else default_config_path(), args.data)
    return EXIT_USAGE
