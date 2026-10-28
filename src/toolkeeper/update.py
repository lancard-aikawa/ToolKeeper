"""選んだ物を上げる（docs/design.md §3・§4・§5）

人が画面で押したときか、`toolkeeper update` を手で打ったときだけ動く。定期の実行からは呼ばない。
上げてよいのは check.json で区分が A・B の物だけ。1 つずつ順に動かす（winget は並べて動かせない）。
結果は <data>/history.jsonl に足す。
"""
import codecs
import shutil
import subprocess
import sys
from pathlib import Path

from . import check, ghostscript, store, winget

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
        elif _kind(k) not in RUNNERS:
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


def _kind(key: str) -> str:
    return key.split(":", 1)[0]


def _winget(it: dict, cfg: dict, data: Path, out, stream=_stream) -> tuple[int, str]:
    return stream(winget_args(it["key"].split(":", 1)[1]), out)


def _ghostscript(it: dict, cfg: dict, data: Path, out) -> tuple[int, str]:
    """取る → SHA-256 と署名 → gs-install.ps1 を管理者として（入れる・PATH を書き換える）→ レジストリで確かめる（§3.3）"""
    rel = ghostscript.latest(data / "cache", cfg["cache_hours"])
    have = ghostscript.installed()
    folder = data / "downloads" / "ghostscript"
    try:
        exe = ghostscript.download(rel, folder, out)
    except Exception as e:  # noqa: BLE001 (理由を履歴に残す)
        out.write(f"{e}\n")
        return 1, str(e)
    log = data / "downloads" / "ghostscript-install.log"
    out.write("インストーラを動かします（UAC の確認が出ます）\n")
    out.flush()
    code = ghostscript.run_elevated(exe, rel["version"], have[-1] if have else None, log)
    try:
        text = log.read_text(encoding="ascii", errors="replace")
    except OSError:
        text = "（記録がありません。UAC を断ったか、スクリプトが動きませんでした）\n"
    out.write(text)
    if code == 0 and rel["version"] not in ghostscript.installed():
        code, text = 11, text + "入れたあとに新しい版がレジストリに見つかりません\n"
    if code == 0:
        shutil.rmtree(folder, ignore_errors=True)
    elif code in ghostscript.SCRIPT_EXIT:
        out.write(ghostscript.SCRIPT_EXIT[code] + "\n")
    tail = "\n".join(text.strip().splitlines()[-TAIL_LINES:])
    return code, tail


# 取得元ごとの上げ方。it, cfg, data, out → (終了コード, 出力の最後)
RUNNERS = {"winget": _winget, "ghostscript": _ghostscript}


def run(cfg: dict, data: Path, keys: list[str], out=None, runners: dict | None = None) -> list[dict]:
    """選んだ物を順に上げ、1 件ずつの結果を返す。1 つが失敗しても残りは続ける"""
    out = out or sys.stdout
    runners = runners or RUNNERS
    result = store.read_json(data / check.CHECK_FILE)
    if not result:
        raise Refused("まだ調べていません（toolkeeper check）")
    done = []
    for it in plan(result, keys):
        out.write(f"\n== {it['name']} ({it['key']}) {it['installed']} -> {it['latest']}\n")
        out.flush()
        try:
            code, tail = runners[_kind(it["key"])](it, cfg, data, out)
        except Exception as e:  # noqa: BLE001 (1 つが失敗しても残りは続ける)
            code, tail = 1, f"{type(e).__name__}: {e}"
            out.write(tail + "\n")
        ok = code == 0 or (_kind(it["key"]) == "winget" and code in NOT_APPLICABLE)
        rec = {"at": store.iso(store.now()), "key": it["key"], "from": it["installed"], "to": it["latest"],
               "ok": ok, "code": f"0x{code:08X}", "tail": None if code == 0 else tail}
        store.append_jsonl(data / HISTORY_FILE, rec)
        done.append(rec)
        out.write(f"-- {'済み' if ok else '失敗'}（終了コード {rec['code']}）\n")
        out.flush()
    return done
