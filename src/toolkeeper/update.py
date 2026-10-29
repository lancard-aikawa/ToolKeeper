"""選んだ物を上げる（docs/design.md §3・§4・§5）

人が画面で押したときか、`toolkeeper update` を手で打ったときだけ動く。定期の実行からは呼ばない。
上げてよいのは check.json で区分が A・B の物だけ。1 つずつ順に動かす（winget は並べて動かせない）。
1 つが失敗したらそこで止め、残りは動かさない（同じ理由で続けて失敗し、UAC の確認だけが続くのを避ける）。
結果は <data>/history.jsonl に足す。
"""
import codecs
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import check, cygwin, env, ghostscript, store, winget

HISTORY_FILE = "history.jsonl"
TAIL_LINES = 20
TICK_SECONDS = 2.0
# winget の終了コード（符号なし）。APPINSTALLER_CLI_ERROR_UPDATE_NOT_APPLICABLE（-1978335189）は
# 「上げる物が無い」（ほかで先に上げた）なので失敗にしない
NOT_APPLICABLE = {0x8A15002B}
# 出力の最後の行の「…終了コードで失敗しました: 1603」の 1603（インストーラ自身の終了コード。文は言語で変わるので数だけ見る）
_INNER_CODE = re.compile(r"[:：]\s*(\d{3,10})\s*$")


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
    """--silent は付けない。MSI が /quiet になり、PC 全体に入れた古い版を消すときに UAC の確認を出せず 1603 で失敗する
    （2026-10-29 OpenJDK 17・21。付けなければ /passive になり、確認が出て通った）"""
    return ["winget", "upgrade", "--id", winget_id, "--exact",
            "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"]


def tick_text(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"\r  {m}:{s:02} 経過（winget は取り込みとインストールの間、進み具合を出しません）"


def _stream(args: list[str], out, tick: float = TICK_SECONDS, clock=time.monotonic) -> tuple[int, str]:
    """出力をそのまま流しながら、最後の TAIL_LINES 行を覚える（winget の進み具合は \\r で上書きされる）。

    winget は出力の先がパイプだと取り込みの進み具合を出さず、FFmpeg（約 200 MB）では「ダウンロード中 <URL>」のあと
    3 分なにも出なかった（2026-10-29。止まって見えた）。インストーラが動いている間も出ない（Rustup は隠れたコンソールで
    古い部品 5,895 個を 15 分以上かけて消していた）。そこで、出力が行の終わりで止まっている間は tick 秒ごとに
    \\r で経過を書く。次に winget が書くときは前に \\r を付けて、経過の行を上書きさせる。経過は tail に入れない"""
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    chunks: queue.Queue = queue.Queue()

    def read():
        while True:
            chunk = p.stdout.read1(4096) if hasattr(p.stdout, "read1") else p.stdout.read(4096)
            chunks.put(chunk)
            if not chunk:
                return

    threading.Thread(target=read, daemon=True).start()
    dec = codecs.getincrementaldecoder("utf-8")(errors="replace")
    text, ticking, start = "", False, clock()
    while True:
        try:
            chunk = chunks.get(timeout=tick)
        except queue.Empty:
            if not text or text.endswith("\n"):
                out.write(tick_text(clock() - start))
                out.flush()
                ticking = True
            continue
        if not chunk:
            break
        s = dec.decode(chunk)
        text += s
        out.write(("\r" if ticking else "") + s)
        out.flush()
        ticking = False
    if ticking:
        out.write("\r\n")
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


def _cygwin(it: dict, cfg: dict, data: Path, out, stream=_stream) -> tuple[int, str]:
    """動いている物があれば止める → Cygwin Setup を winget で用意 → 入っている物を全部上げる → 古い物が残っていないか見る（§3.4）"""
    root = Path(cfg["cygwin_root"])
    names = cygwin.running(root)
    if names:
        msg = f"Cygwin のプログラムが動いています。閉じてからやり直してください: {', '.join(names)}"
        out.write(msg + "\n")
        return 1, msg
    exe = cygwin.setup_exe()
    if exe is None:
        out.write("Cygwin Setup を winget で入れます\n")
        code, tail = stream(["winget", "install", "--id", cygwin.SETUP_ID, *winget_args(cygwin.SETUP_ID)[4:]], out)
        exe = cygwin.setup_exe()
        if exe is None:
            return code or 1, tail or "Cygwin Setup を入れられませんでした"
    rc = cygwin.read_setup_rc(root)
    mirror = cygwin.mirror(rc)
    package_dir = (rc.get("last-cache") or [str(data / "cache" / "cygwin-packages")])[0]
    out.write(f"Cygwin Setup を動かします（UAC の確認が出ます。ミラー {mirror}）\n")
    out.flush()
    r = subprocess.run(cygwin.setup_args(exe, root, mirror, package_dir), capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    code = r.returncode & 0xFFFFFFFF
    tail = cygwin.log_tail(root, TAIL_LINES)
    out.write(tail + "\n")
    left = cygwin.outdated(cygwin.read_installed(root), cygwin.latest(mirror, data / "cache", cfg["cache_hours"]))
    if left:
        msg = f"上げたあとも古い物が {len(left)} 個あります: {', '.join(left[:20])}"
        out.write(msg + "\n")
        tail += "\n" + msg
        if code == 0:
            code = 1
    return code, tail


def explain(code: int) -> str | None:
    """終了コードの意味を `winget error` に聞く（Windows の言語の文）。分からなければ None"""
    try:
        r = subprocess.run(["winget", "error", f"0x{code:08X}"], capture_output=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = [x.strip() for x in r.stdout.decode("utf-8", errors="replace").splitlines() if x.strip()]
    return lines[-1] if r.returncode == 0 and len(lines) >= 2 else None  # 1 行目はコードと名前


def _reason(it: dict, code: int, tail: str, explain) -> str | None:
    """失敗の理由。winget は出力が進み具合と「失敗しました」だけで、なぜかが分からない（2026-10-29 OpenJDK 17）ので、
    winget の終了コードの意味と、出力の最後の行にインストーラの終了コードがあればその意味を引く。ほかは出力の最後の行"""
    last = (tail or "").strip().splitlines()[-1:]
    if _kind(it["key"]) != "winget":
        return last[0] if last else None
    parts = [f"winget: {explain(code) or '（意味を引けませんでした）'}"]
    m = _INNER_CODE.search(last[0]) if last else None
    if m:
        inner = int(m.group(1))
        parts.append(f"インストーラの終了コード {inner}: {explain(inner) or '（意味を引けませんでした）'}")
    return "\n".join(parts)


# 取得元ごとの上げ方。it, cfg, data, out → (終了コード, 出力の最後)
RUNNERS = {"winget": _winget, "ghostscript": _ghostscript, "cygwin": _cygwin}


def _read_env(read):
    try:
        return read()
    except Exception:  # noqa: BLE001 (読めなくても上げるのは止めない。比べないだけ)
        return None


def run(cfg: dict, data: Path, keys: list[str], out=None, runners: dict | None = None, explain=explain,
        read_env=env.read_registry) -> list[dict]:
    """選んだ物を順に上げ、動かした物の結果を 1 件ずつ返す。1 つが失敗したら、そこで止める。
    1 件ごとに前と後でレジストリの環境変数と PATH を比べ、変わっていれば env に入れる"""
    out = out or sys.stdout
    runners = runners or RUNNERS
    result = store.read_json(data / check.CHECK_FILE)
    if not result:
        raise Refused("まだ調べていません（toolkeeper check）")
    done = []
    todo = plan(result, keys)
    for n, it in enumerate(todo):
        out.write(f"\n== {it['name']} ({it['key']}) {it['installed']} -> {it['latest']}\n")
        out.flush()
        before = _read_env(read_env)
        try:
            code, tail = runners[_kind(it["key"])](it, cfg, data, out)
        except Exception as e:  # noqa: BLE001 (理由を履歴に残して止める)
            code, tail = 1, f"{type(e).__name__}: {e}"
            out.write(tail + "\n")
        after = _read_env(read_env) if before is not None else None
        changed = env.changes(before, after, cfg["env_vars"]) if after is not None else []
        ok = code == 0 or (_kind(it["key"]) == "winget" and code in NOT_APPLICABLE)
        reason = None if ok else _reason(it, code, tail, explain)
        rec = {"at": store.iso(store.now()), "key": it["key"], "from": it["installed"], "to": it["latest"],
               "ok": ok, "code": f"0x{code:08X}", "reason": reason, "env": changed, "tail": None if code == 0 else tail}
        store.append_jsonl(data / HISTORY_FILE, rec)
        done.append(rec)
        out.write(f"-- {'済み' if ok else '失敗'}（終了コード {rec['code']}）\n")
        if reason:
            out.write("".join(f"   {x}\n" for x in reason.splitlines()))
        if changed:
            out.write("-- 環境変数が変わりました:\n" + "".join(f"   {env.change_text(c)}\n" for c in changed))
        rest = todo[n + 1:]
        if not ok and rest:
            out.write(f"-- 失敗したので止めました。残りの {len(rest)} 件は動かしていません: {', '.join(r['name'] for r in rest)}\n")
            out.flush()
            break
        out.flush()
    return done
