"""選んだ物を上げる（docs/design.md §3・§4・§5）

人が画面で押したときか、`toolkeeper update` を手で打ったときだけ動く。定期の実行からは呼ばない。
上げてよいのは check.json で区分が A・B の物だけ。1 つずつ順に動かす（winget は並べて動かせない）。
結果は <data>/history.jsonl に足す。
"""
import codecs
import subprocess
import sys
from pathlib import Path

from . import check, store, winget

HISTORY_FILE = "history.jsonl"
TAIL_LINES = 20
# winget の終了コード（符号なし）。APPINSTALLER_CLI_ERROR_UPDATE_NOT_APPLICABLE（-1978335189）は
# 「上げる物が無い」（ほかで先に上げた）なので失敗にしない
NOT_APPLICABLE = {0x8A15002B}


class Refused(ValueError):
    """上げられない物を選んだ"""


def plan(result: dict, keys: list[str]) -> list[dict]:
    """check.json の結果から、選んだキーの行を順に返す。上げられない物があれば Refused（どれも動かさない）"""
    by_key = {it["key"]: it for it in result.get("items") or []}
    out, bad = [], []
    for k in keys:
        it = by_key.get(k)
        if it is None:
            bad.append(f"{k}: check.json にありません（toolkeeper check で調べ直してください）")
        elif it["tier"] not in ("A", "B"):
            bad.append(f"{k}: 区分 {it['tier']} は更新しません（A・B だけ。design.md §2）")
        elif not it["updatable"]:
            bad.append(f"{k}: 新しい版がありません")
        elif k == "php":
            bad.append("php: 手で入れた PHP は、先に winget へ乗り換えてください（design.md §7）")
        elif not k.startswith("winget:"):
            bad.append(f"{k}: まだ作っていません")
        else:
            out.append(it)
    if bad:
        raise Refused("\n".join(bad))
    return out


def winget_args(winget_id: str) -> list[str]:
    return ["winget", "upgrade", "--id", winget_id, "--exact", "--silent",
            "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"]


def _stream(args: list[str], out) -> tuple[int, str]:
    """出力をそのまま流しながら、最後の TAIL_LINES 行を覚える（winget の進み具合は \\r で上書きされる）"""
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    dec = codecs.getincrementaldecoder("utf-8")(errors="replace")
    text = ""
    while True:
        chunk = p.stdout.read1(4096) if hasattr(p.stdout, "read1") else p.stdout.read(4096)
        if not chunk:
            break
        s = dec.decode(chunk)
        text += s
        out.write(s)
        out.flush()
    code = p.wait()
    lines = [winget._clean(x) for x in text.replace("\r\n", "\n").split("\n")]
    tail = "\n".join([x for x in lines if x.strip()][-TAIL_LINES:])
    return code & 0xFFFFFFFF, tail


def run(data: Path, keys: list[str], out=None, runner=_stream) -> list[dict]:
    """選んだ物を順に上げ、1 件ずつの結果を返す。1 つが失敗しても残りは続ける"""
    out = out or sys.stdout
    result = store.read_json(data / check.CHECK_FILE)
    if not result:
        raise Refused("まだ調べていません（toolkeeper check）")
    done = []
    for it in plan(result, keys):
        winget_id = it["key"].split(":", 1)[1]
        out.write(f"\n== {it['name']} ({winget_id}) {it['installed']} -> {it['latest']}\n")
        out.flush()
        code, tail = runner(winget_args(winget_id), out)
        ok = code == 0 or code in NOT_APPLICABLE
        rec = {"at": store.iso(store.now()), "key": it["key"], "from": it["installed"], "to": it["latest"],
               "ok": ok, "code": f"0x{code:08X}", "tail": None if code == 0 else tail}
        store.append_jsonl(data / HISTORY_FILE, rec)
        done.append(rec)
        out.write(f"-- {'済み' if ok else '失敗'}（終了コード {rec['code']}）\n")
        out.flush()
    return done
