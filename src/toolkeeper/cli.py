"""コマンドライン（docs/design.md §5）"""
import argparse
import contextlib
import json
import sys
import traceback
from pathlib import Path

from . import __version__, check, store, winget
from . import config as cfgmod
from . import status as statusmod
from . import update as updatemod
from .paths import data_dir, default_config_path

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_BUSY = 3
EXIT_PARTIAL = 4  # 調べられなかった取得元がある
EXIT_FAILED = 5   # 上げられなかった物がある

TIER_LABEL = {"A": "A 専用", "B": "B winget", "C": "C winget", "D": "D choco", "E": "E 乗り換え"}
EOL_LABEL = {"ended": "サポート終了", "soon": "もうすぐ終了"}


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="toolkeeper", description="PC に入れた道具が古くなっていないかを調べる")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--config", help="設定ファイル（既定: プログラムの置き場所の toolkeeper.json）")
    p.add_argument("--data", help="データの場所（設定より優先）")
    p.add_argument("--log", action="store_true", help="今回の出力を <data>/last-run.log に書く（定期実行の pythonw 用）")
    sub =p.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="全部を調べ、<data>/check.json に書く。前回から増えた更新を出す")
    ls = sub.add_parser("list", help="check.json を表で出す")
    ls.add_argument("--all", action="store_true", help="C・D も出す（既定は A・B・E と、サポート終了の物）")
    up = sub.add_parser("update", help="選んだ物を上げる（区分 A・B だけ）。終わったら調べ直す")
    up.add_argument("keys", nargs="+", metavar="キー", help="check.json の key（winget:<ID> など）")
    up.add_argument("--no-check", action="store_true", help="終わったあとに調べ直さない")
    st = sub.add_parser("status", help="使える状態か")
    st.add_argument("--json", action="store_true", help="JSON で出す")
    return p


def _note(it: dict) -> str:
    parts = []
    if it.get("eol") and it["eol"]["state"] in EOL_LABEL:
        e = it["eol"]
        parts.append(f"{EOL_LABEL[e['state']]} {e['date'] or ''}".strip())
    for n in it.get("notes") or []:
        kind, _, val = n.partition(":")
        parts.append({"manual": "手で入れた物（winget へ乗り換え）", "twin": f"winget でも見えている ({val.split(':', 1)[-1]})",
                      "old": f"古い版 {val} も入っている", "running": f"動いている: {val}",
                      "pinned": f"pin {val} 件" if val else "pin"}.get(kind, n))
    if it.get("packages"):
        parts.append(f"古いパッケージ {it['packages']['outdated']}/{it['packages']['installed']}")
    if it.get("new"):
        parts.insert(0, "新しい")
    return "、".join(parts)


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
          f"新しい {s['new']}  失敗 {s['failed']}")
    rows = [it for it in result["items"]
            if show_all or it["tier"] in ("A", "B", "E") or (it.get("eol") and it["eol"]["state"] != "ok")]
    for it in rows:
        mark = "*" if it["updatable"] and it["tier"] in ("A", "B") else " "
        print(f"{mark} {_fit(TIER_LABEL[it['tier']], 11)} {_fit(it['name'], 36)} {_fit(it['installed'] or '-', 16, True)} -> "
              f"{_fit(it['latest'] or '-', 16)} {_note(it)}")
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
        print(f"\n済み {len(done) - len(failed)} 件、失敗 {len(failed)} 件" + (f": {', '.join(failed)}" if failed else ""))
        return EXIT_FAILED if failed else EXIT_OK
    if args.command == "list":
        result = store.read_json(data / check.CHECK_FILE)
        if not result:
            print("まだ調べていません（toolkeeper check）", file=sys.stderr)
            return EXIT_USAGE
        _print_table(result, show_all=args.all)
        return EXIT_OK
    if args.command == "status":
        st = statusmod.run(cfg, data)
        if args.json:
            print(json.dumps(st, ensure_ascii=False, indent=2))
        else:
            for k, v in st.items():
                print(f"{k}: {v}")
        return EXIT_OK
    return EXIT_USAGE
