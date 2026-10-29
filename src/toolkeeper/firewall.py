"""Windows ファイアウォールの規則のうち、プログラムを指す物を見る（docs/design.md §3.9）

見るだけで、規則は書き換えない。check からは呼ばず、check.json にも入れない（パスを含むため）。
"""
import os
import re
import subprocess

from . import env

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NETSH = ["netsh", "advfirewall", "firewall", "show", "rule", "name=all", "verbose"]
# 見出しは言語で変わるので、使う物だけ日本語と英語の両方を持つ
FIELDS = {
    "規則名": "name", "Rule Name": "name",
    "有効": "enabled", "Enabled": "enabled",
    "方向": "direction", "Direction": "direction",
    "プロファイル": "profiles", "Profiles": "profiles",
    "プロトコル": "protocol", "Protocol": "protocol",
    "プログラム": "program", "Program": "program",
    "操作": "action", "Action": "action",
}
VALUES = {"はい": True, "Yes": True, "いいえ": False, "No": False,
          "許可": "allow", "Allow": "allow", "ブロック": "block", "Block": "block",
          "入力": "in", "In": "in", "出力": "out", "Out": "out"}
ANY = {"任意", "Any"}
_LINE = re.compile(r"^([^:]+?):\s*(.*)$")
STATE_ORDER = {"block": 0, "none": 1, "gone": 2, "allow": 3, "off": 4}
DETAIL = {
    "block": "外からの接続を断っている（Windows に許可を聞かれて、許可しなかったときにできる）",
    "none": "この場所には規則が無い。外から接続を受ける初回に、Windows がまた許可を聞いてくる（ほかの場所の同じ名前の物には規則がある）",
    "gone": "プログラムが無い（上げたか消した物の残り）。害は無い",
    "allow": "外からの接続を許している",
    "off": "無効（使われていない）",
}


def decode(raw: bytes) -> str:
    """UTF-8 として読み、読めなければ OEM のコード ページ（日本語の Windows では cp932）で読む。
    手元の Windows 11 はコンソールの有無に関係なく UTF-8 だったが、古い netsh は OEM で書くことがある"""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return raw.decode("oem", errors="replace")
        except LookupError:  # Windows 以外（テスト）
            return raw.decode("cp932", errors="replace")


def parse_rules(text: str) -> list[dict]:
    """netsh の出力 → [{name, enabled, direction, profiles, protocol, program, action}]。program は無ければ None"""
    rules: list[dict] = []
    for line in text.splitlines():
        m = _LINE.match(line)
        if not m or m.group(1).strip() not in FIELDS:
            continue
        key, value = FIELDS[m.group(1).strip()], m.group(2).strip()
        if key == "name":
            rules.append({"name": value, "enabled": False, "direction": "", "profiles": "", "protocol": "",
                          "program": None, "action": ""})
        elif rules:
            if key == "program":
                rules[-1]["program"] = None if not value or value in ANY else value
            else:
                rules[-1][key] = VALUES.get(value, value)
    return rules


def read_rules(run=subprocess.run) -> list[dict]:
    r = run(NETSH, capture_output=True, creationflags=_NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError(f"netsh が終了コード {r.returncode} で終わりました: {decode(r.stdout or b'').strip()[:200]}")
    return parse_rules(decode(r.stdout))


def commands(reg: dict, names: list[str], process_env=None, isfile=os.path.isfile,
             realpath=os.path.realpath) -> dict[str, str]:
    """コマンド → レジストリの PATH で最初に見つかる場所（ストアのアプリの呼び出し口は除く）。
    リンクは先をたどる。規則には本当の場所が入る（nvm の nodejs\\node.exe → v24.22.1\\node.exe、winget の Links\\ffmpeg.exe）"""
    e = env.base_env(reg, process_env)
    entries, pathext = env.path_entries(reg, e), env._pathext(e)
    out = {}
    for name in names:
        hits = env.find_all(name, entries, pathext, isfile)
        if hits and not env._is_store_alias(hits[0], e):
            out[name] = realpath(hits[0])
    return out


def inspect(rules: list[dict], used: dict[str, str], process_env=None, exists=os.path.exists) -> list[dict]:
    """§3.9 の表の行: {id, state, tool, name, direction, profiles, protocol, program, detail}。
    used はコマンド → 使っている場所（commands の結果）。tool は「java」「java（ほかの場所）」か ""。"""
    environ = {k.upper(): v for k, v in (os.environ if process_env is None else process_env).items()}
    by_path = {env.norm(p): c for c, p in used.items()}
    by_file = {os.path.basename(env.norm(p)): c for c, p in used.items()}
    groups: dict[tuple, dict] = {}
    for r in rules:
        if not r["program"]:
            continue
        program = env.expand(r["program"], environ)
        key = (r["name"], env.norm(program), r["action"], r["direction"], r["enabled"], r["profiles"])
        g = groups.get(key)
        if g:
            if r["protocol"] and r["protocol"] not in g["protocols"]:
                g["protocols"].append(r["protocol"])
            continue
        groups[key] = {**r, "program": program, "protocols": [r["protocol"]] if r["protocol"] else []}

    rows, ruled = [], set()
    for g in groups.values():
        p = env.norm(g["program"])
        ruled.add(p)
        if not exists(g["program"]):
            state = "gone"
        elif not g["enabled"]:
            state = "off"
        elif g["action"] == "block":
            state = "block"
        else:
            state = "allow"
        if p in by_path:
            tool = by_path[p]
        elif os.path.basename(p) in by_file:
            tool = f"{by_file[os.path.basename(p)]}（ほかの場所）"
        else:
            tool = ""
        rows.append({"state": state, "tool": tool, "name": g["name"], "direction": g["direction"],
                     "profiles": g["profiles"], "protocol": ", ".join(g["protocols"]), "program": g["program"],
                     "detail": DETAIL.get(state, "")})
    ruled_files = {os.path.basename(p) for p in ruled}
    for cmd, path in used.items():
        p = env.norm(path)
        if p not in ruled and os.path.basename(p) in ruled_files:
            rows.append({"state": "none", "tool": cmd, "name": "-", "direction": "", "profiles": "", "protocol": "",
                         "program": path, "detail": DETAIL["none"]})
    rows.sort(key=lambda r: (STATE_ORDER[r["state"]], not r["tool"], r["tool"], r["name"].lower(), r["program"].lower()))
    for i, r in enumerate(rows):
        r["id"] = f"fw{i}"
    return rows


def counts(rows: list[dict]) -> dict[str, int]:
    out = {s: 0 for s in STATE_ORDER}
    for r in rows:
        out[r["state"]] += 1
    return out
