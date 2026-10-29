"""道具にかかわる環境変数と PATH を調べ、決まった直し方がある物だけを直す（docs/design.md §3.7）

PATH と環境変数はレジストリから読む。プロセスの環境は、起動した側が開いたときの古い値のことがある。
書き換えは fix / undo からだけ（画面か、手で打った toolkeeper env --fix）。定期の実行（check）からは呼ばない。
"""
import json
import os
import re
import zlib
from pathlib import Path

from . import store

MACHINE_KEY = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
USER_KEY = "Environment"
SCOPES = ("machine", "user")
ENV_FILE = "env.json"
HISTORY_FILE = "env-history.jsonl"
VERSIONED = re.compile(r"\d+\.\d+\.\d+")
# 版の入ったフォルダの名前: 前・大きい版・残りの版・後ろ（jdk- / 21 / .0.9.10 / -hotspot）
VERSIONED_NAME = re.compile(r"^(\D*)(\d+)((?:\.\d+)+)(.*)$")
# 版の入ったフォルダでも、ToolKeeper の更新が PATH を書き換える物は「更新で切れうる」にしない（§3.3 の gs-install.ps1）
SELF_MANAGED = re.compile(r"\\gs\\gs\d+\.\d+\.\d+\\bin\\?$", re.IGNORECASE)
VERSIONED_NOTE = "版の入ったフォルダ。更新で名前が変わると切れる"
STATE_ORDER = {"bad": 0, "warn": 1, "info": 2, "ok": 3}
SCOPE_NAME = {"machine": "マシン", "user": "ユーザー"}


class Refused(Exception):
    """直せない物を選んだ、または選んだあとに値が変わった"""


def read_registry() -> dict[str, dict[str, str]]:
    """{"machine": {名前: 展開していない値}, "user": {...}}"""
    import winreg
    out = {}
    for scope, root, sub in (("machine", winreg.HKEY_LOCAL_MACHINE, MACHINE_KEY), ("user", winreg.HKEY_CURRENT_USER, USER_KEY)):
        values = {}
        try:
            with winreg.OpenKey(root, sub) as k:
                i = 0
                while True:
                    try:
                        name, value, _type = winreg.EnumValue(k, i)
                    except OSError:
                        break
                    if isinstance(value, str):
                        values[name] = value
                    i += 1
        except OSError:
            pass
        out[scope] = values
    return out


def _get(values: dict[str, str], name: str) -> str | None:
    """名前は大文字小文字を区別しない（Path と PATH）"""
    low = name.lower()
    return next((v for k, v in values.items() if k.lower() == low), None)


def _real_name(values: dict[str, str], name: str) -> str:
    low = name.lower()
    return next((k for k in values if k.lower() == low), name)


def expand(raw: str, env: dict[str, str]) -> str:
    """%名前% を展開する。分からない物はそのまま残す（Windows と同じ）"""
    upper = {k.upper(): v for k, v in env.items()}
    return re.sub(r"%([^%;]+)%", lambda m: upper.get(m.group(1).upper(), m.group(0)), raw)


def base_env(reg: dict, process_env=None) -> dict[str, str]:
    """展開に使う値: プロセスの環境（USERPROFILE など）に、マシン → ユーザーの変数を重ねる"""
    env = {k.upper(): v for k, v in (os.environ if process_env is None else process_env).items()}
    for scope in SCOPES:
        for k, v in reg.get(scope, {}).items():
            if k.lower() != "path":
                env[k.upper()] = expand(v, env)
    return env


def path_entries(reg: dict, env: dict[str, str]) -> list[dict]:
    """PATH の行をマシン → ユーザーの順に: {"scope", "pos", "raw", "dir"}。pos は ; で切った何番目か（空の行も数える）"""
    rows = []
    for scope in SCOPES:
        for pos, raw in enumerate((_get(reg.get(scope, {}), "Path") or "").split(";")):
            if raw.strip():
                rows.append({"scope": scope, "pos": pos, "raw": raw, "dir": expand(raw.strip(), env)})
    return rows


def norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path.strip().strip('"'))) if path.strip() else ""


def find_all(cmd: str, entries: list[dict], pathext: list[str], isfile=os.path.isfile) -> list[str]:
    """PATH の順にコマンドを探す。同じフォルダは 1 回だけ数える"""
    hits, seen = [], set()
    for e in entries:
        d = norm(e["dir"])
        if not d or d in seen:
            continue
        seen.add(d)
        for ext in pathext:
            f = os.path.join(e["dir"].strip().strip('"'), cmd + ext)
            if isfile(f):
                hits.append(f)
                break
    return hits


def which(cmd: str, reg: dict | None = None, process_env=None, isfile=os.path.isfile) -> str | None:
    """レジストリの PATH で最初に見つかる物"""
    reg = read_registry() if reg is None else reg
    env = base_env(reg, process_env)
    hits = find_all(cmd, path_entries(reg, env), _pathext(env), isfile)
    return hits[0] if hits else None


def _pathext(env: dict[str, str]) -> list[str]:
    return [x.lower() for x in (env.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD").split(";") if x]


def _is_store_alias(path: str, env: dict[str, str]) -> bool:
    apps = env.get("LOCALAPPDATA")
    return bool(apps) and norm(os.path.dirname(path)) == norm(os.path.join(apps, "Microsoft", "WindowsApps"))


def _vkey(rest: str) -> tuple[int, ...]:
    return tuple(int(x) for x in rest.strip(".").split(".") if x)


def successor(raw: str, env: dict[str, str], exists=os.path.exists, listdir=os.listdir) -> str | None:
    """無くなった版のフォルダを指す値の、向け直し先（展開していない形）。
    版の入ったフォルダの隣に、前・大きい版・後ろが同じフォルダがあれば、いちばん新しい物にする
    （jdk-21.0.9.10-hotspot → jdk-21.0.13.11-hotspot。大きい版は越えない）。見つからなければ None"""
    for comp in sorted(set(re.split(r"[\\/]", raw)), key=len, reverse=True):
        m = VERSIONED_NAME.match(comp)
        if not m or raw.count(comp) != 1:
            continue
        head = raw[:raw.index(comp)]
        parent = expand(head, env)
        try:
            names = listdir(parent)
        except OSError:
            continue
        best = None
        for n in names:
            o = VERSIONED_NAME.match(n)
            if (n != comp and o and o.group(1).lower() == m.group(1).lower() and o.group(2) == m.group(2)
                    and o.group(4).lower() == m.group(4).lower()):
                if best is None or _vkey(o.group(3)) > _vkey(VERSIONED_NAME.match(best).group(3)):
                    best = n
        if best:
            new = raw.replace(comp, best, 1)
            if exists(expand(new, env).strip().strip('"')):
                return new
    return None


def _id(kind: str, scope: str, where, value: str) -> str:
    """表の行の名札。値の crc を入れて、選んだあとに PATH が変わったら別の物として扱う"""
    return f"{kind}:{scope}:{where}:{zlib.crc32(value.encode('utf-8')):08x}"


def _finding(state, kind, scope, name, value, detail, where=None, fix=None) -> dict:
    return {"id": _id(kind, scope, name if where is None else where, value), "state": state, "kind": kind,
            "scope": scope, "name": name, "value": value, "detail": detail, "fix": fix}


def inspect(reg: dict, var_names: list[str], commands: list[str], process_env=None,
            exists=os.path.exists, isfile=os.path.isfile, listdir=os.listdir) -> list[dict]:
    """§3.7 の表の行。state は bad（切れている）・warn（注意・更新で切れうる）・info（整理できる）・ok。
    fix は直し方（無ければ None）: {"action": "set" | "replace" | "remove", "to": 新しい値, "pos": PATH の何番目か}"""
    env = base_env(reg, process_env)
    found = []

    for name in var_names:
        for scope in SCOPES:
            raw = _get(reg.get(scope, {}), name)
            if raw is None:
                continue
            value = expand(raw, env)
            # PYTHONPATH などは ; で並べた物。全部の行が在れば正しい
            parts = [p for p in value.split(";") if p.strip()]
            missing = [p for p in parts if not exists(p.strip().strip('"'))]
            if missing:
                to = successor(raw, env, exists, listdir) if len(parts) == 1 else None
                found.append(_finding("bad", "var", scope, name, raw, "無い場所: " + "; ".join(missing),
                                      fix={"action": "set", "to": to, "pos": None} if to else None))
            elif VERSIONED.search(value):
                found.append(_finding("warn", "var", scope, name, raw, VERSIONED_NOTE))
            else:
                found.append(_finding("ok", "var", scope, name, raw, ""))

    entries = path_entries(reg, env)
    seen: dict[str, dict] = {}
    for e in entries:
        d = norm(e["dir"])
        if d in seen:
            first = seen[d]
            # 書き方が違うと同じに見えないので、相手の行と、展開した値を書く（%SystemRoot%\system32 と C:\Windows\system32）
            expanded = "" if e["raw"].strip() == e["dir"] else f"（展開すると {e['dir']}）"
            found.append(_finding("info", "path-dup", e["scope"], "PATH", e["raw"],
                                  f"{SCOPE_NAME[first['scope']]}の PATH の {first['raw']} と同じフォルダ{expanded}。"
                                  "後ろにあるこちらは使われない", e["pos"],
                                  {"action": "remove", "to": None, "pos": e["pos"]}))
            continue
        seen[d] = e
        if not exists(e["dir"].strip().strip('"')):
            to = successor(e["raw"], env, exists, listdir)
            fix = {"action": "replace", "to": to, "pos": e["pos"]} if to else {"action": "remove", "to": None, "pos": e["pos"]}
            found.append(_finding("bad", "path-missing", e["scope"], "PATH", e["raw"], "フォルダが無い", e["pos"], fix))
        elif VERSIONED.search(e["dir"]) and not SELF_MANAGED.search(e["dir"]):
            found.append(_finding("warn", "path-versioned", e["scope"], "PATH", e["raw"], VERSIONED_NOTE, e["pos"]))

    pathext = _pathext(env)
    for cmd in commands:
        hits = find_all(cmd, entries, pathext, isfile)
        if not hits:
            continue
        rest = [h for h in hits[1:] if not _is_store_alias(h, env)]
        if rest:
            found.append(_finding("warn", "shadow", "", cmd, hits[0], "使われるのはこちら。ほかに: " + "; ".join(rest)))

    found.sort(key=lambda f: STATE_ORDER[f["state"]])
    return found


def problems(found: list[dict]) -> int:
    return sum(1 for f in found if f["state"] in ("bad", "warn"))


def fix_text(f: dict) -> str:
    """直し方を人に見せる言葉（表の「直し方」の列と、確かめの窓）"""
    fx = f.get("fix")
    if not fx:
        return ""
    if fx["action"] == "remove":
        return "PATH から消す"
    return f"{fx['to']} にする"


# ---- 書き換え（§3.7）

def plan(reg: dict, found: list[dict], ids: list[str]) -> list[dict]:
    """選んだ行の直し方を、変数ごとの書き込みにまとめる: [{"scope", "name", "old", "new", "changes": [文]}]。
    同じ PATH への複数の直しは 1 回の書き込みにする（マシンなら UAC が 1 回で済む）"""
    by_id = {f["id"]: f for f in found}
    picked = []
    for i in ids:
        f = by_id.get(i)
        if f is None:
            raise Refused(f"見つかりません（調べ直したあとに変わった）: {i}")
        if not f.get("fix"):
            raise Refused(f"直し方が決まっていない物です: {f['name']} {f['value']}")
        picked.append(f)
    writes: dict[tuple[str, str], dict] = {}
    for f in picked:
        values = reg.get(f["scope"], {})
        name = _real_name(values, f["name"])
        old = _get(values, name)
        w = writes.setdefault((f["scope"], name.lower()), {"scope": f["scope"], "name": name, "old": old, "ops": [], "changes": []})
        w["ops"].append(f["fix"])
        where = f"{name}（{SCOPE_NAME[f['scope']]}）"
        if f["fix"]["action"] == "remove":
            w["changes"].append(f"{where} から {f['value']} を消す")
        elif f["fix"]["action"] == "replace":
            w["changes"].append(f"{where} の {f['value']} を {f['fix']['to']} にする")
        else:
            w["changes"].append(f"{where} を {f['value']} から {f['fix']['to']} にする")
    out = []
    for w in writes.values():
        ops = w.pop("ops")
        if ops[0]["action"] == "set":
            w["new"] = ops[0]["to"]
        else:
            parts: list[str | None] = list((w["old"] or "").split(";"))
            for op in ops:
                parts[op["pos"]] = None if op["action"] == "remove" else op["to"]
            w["new"] = ";".join(p for p in parts if p is not None)
        out.append(w)
    return out


class Registry:
    """書き込み先。ユーザーは HKCU を直に書く。マシンは管理者が要るので scripts/env-set.ps1 を UAC で動かす。試験では差し替える"""

    @staticmethod
    def read(scope: str, name: str) -> str | None:
        return _get(read_registry().get(scope, {}), name)

    @staticmethod
    def write_user(name: str, old: str | None, new: str) -> None:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, USER_KEY, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
            cur, kind = winreg.QueryValueEx(k, name)
            if cur != old:
                raise Refused(f"{name}（ユーザー）が選んだあとに変わりました。調べ直してください")
            winreg.SetValueEx(k, name, 0, kind, new)

    @staticmethod
    def write_machine(writes: list[dict], data: Path) -> None:
        from . import elevate
        req = data / "env-request.json"
        log = data / "env-set.log"
        # スクリプトは ASCII だけで書くので、値も \\uXXXX にして渡す
        with open(req, "w", encoding="utf-8", newline="\n") as f:
            json.dump([{"name": w["name"], "old": w["old"], "new": w["new"]} for w in writes], f, ensure_ascii=True)
        try:
            code = elevate.run_script(elevate.SCRIPTS / "env-set.ps1", ["-Request", str(req), "-Log", str(log)], log)
        finally:
            req.unlink(missing_ok=True)
        if code == 11:
            raise Refused("マシンの変数が選んだあとに変わりました。調べ直してください")
        if code != 0:
            tail = log.read_text(encoding="utf-8", errors="replace").strip() if log.is_file() else ""
            raise RuntimeError(f"マシンの変数を書けませんでした（終了コード {code}。UAC で「いいえ」を押すと 1）{tail}")

    @staticmethod
    def broadcast() -> None:
        """開いているエクスプローラーなどに、環境が変わったと知らせる（新しく開くプログラムに届くように）"""
        import ctypes
        result = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0x0002, 5000, ctypes.byref(result))


def apply(writes: list[dict], data: Path, reg: Registry | None = None) -> list[dict]:
    """書いて、env-history.jsonl に足す。マシンの分はまとめて 1 回の UAC。書いた物を返す"""
    reg = reg or Registry()
    for w in writes:  # 書く前に、選んだあとに変わっていないかを全部見る
        if reg.read(w["scope"], w["name"]) != w["old"]:
            raise Refused(f"{w['name']}（{SCOPE_NAME[w['scope']]}）が選んだあとに変わりました。調べ直してください")
    done = []
    machine = [w for w in writes if w["scope"] == "machine"]
    if machine:
        reg.write_machine(machine, data)
        done += machine
    for w in writes:
        if w["scope"] == "user":
            reg.write_user(w["name"], w["old"], w["new"])
            done.append(w)
    reg.broadcast()
    at = store.iso(store.now())
    for w in done:
        store.append_jsonl(data / HISTORY_FILE, {"at": at, "scope": w["scope"], "name": w["name"], "old": w["old"],
                                                 "new": w["new"], "changes": w["changes"], **({"undo_of": w["undo_of"]} if "undo_of" in w else {})})
    return done


def history(data: Path) -> list[dict]:
    try:
        with open(data / HISTORY_FILE, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def last_undoable(data: Path) -> dict | None:
    """まだ戻していない、いちばん新しい書き込み（戻した書き込みそのものは戻さない）"""
    rows = history(data)
    undone = {(h["undo_of"]["at"], h["undo_of"]["scope"], h["undo_of"]["name"]) for h in rows if h.get("undo_of")}
    for h in reversed(rows):
        if not h.get("undo_of") and (h["at"], h["scope"], h["name"]) not in undone:
            return h
    return None


def undo_plan(data: Path) -> dict:
    h = last_undoable(data)
    if h is None:
        raise Refused("戻せる変更がありません")
    return {"scope": h["scope"], "name": h["name"], "old": h["new"], "new": h["old"],
            "changes": [f"{h['name']}（{SCOPE_NAME[h['scope']]}）を {h['at'][:16].replace('T', ' ')} の変更の前に戻す"],
            "undo_of": {"at": h["at"], "scope": h["scope"], "name": h["name"]}}


def changes(before: dict, after: dict, var_names: list[str]) -> list[dict]:
    """レジストリの値の、前と後の違い（更新の前後に比べる。§5）。インストーラが JAVA_HOME と PATH を自分向けに書き換えることがある
    （2026-10-29、OpenJDK 17 を上げたら JAVA_HOME が 21 から 17 になり、PATH の先頭に 17 が入った）。
    変数は {scope, name, old, new}。PATH は {scope, name: "PATH", added, removed, moved, head}（moved は残った行の順番が変わったか、
    head は先頭の行が変わったときの新しい先頭）"""
    out = []
    for scope in SCOPES:
        b, a = before.get(scope, {}), after.get(scope, {})
        for name in var_names:
            old, new = _get(b, name), _get(a, name)
            if old != new:
                out.append({"scope": scope, "name": _real_name(a if new is not None else b, name), "old": old, "new": new})
        old_rows = [x for x in (_get(b, "Path") or "").split(";") if x.strip()]
        new_rows = [x for x in (_get(a, "Path") or "").split(";") if x.strip()]
        if [norm(x) for x in old_rows] == [norm(x) for x in new_rows]:
            continue
        old_set, new_set = {norm(x) for x in old_rows}, {norm(x) for x in new_rows}
        kept_old = [norm(x) for x in old_rows if norm(x) in new_set]
        kept_new = [norm(x) for x in new_rows if norm(x) in old_set]
        head = new_rows[0] if new_rows and (not old_rows or norm(new_rows[0]) != norm(old_rows[0])) else None
        out.append({"scope": scope, "name": "PATH", "added": [x for x in new_rows if norm(x) not in old_set],
                    "removed": [x for x in old_rows if norm(x) not in new_set], "moved": kept_old != kept_new, "head": head})
    return out


def change_text(c: dict) -> str:
    """changes() の 1 件を人に見せる 1 行に"""
    where = f"{SCOPE_NAME[c['scope']]}の {c['name']}"
    if c["name"] != "PATH":
        return f"{where}: {c['old'] or '（無し）'} → {c['new'] or '（消えた）'}"
    parts = []
    if c["head"]:
        parts.append(f"先頭が {c['head']} になった")
    if c["added"]:
        parts.append("足された " + "、".join(c["added"]))
    if c["removed"]:
        parts.append("消えた " + "、".join(c["removed"]))
    if c["moved"] and not c["head"]:
        parts.append("順番が変わった")
    return f"{where}: " + "。".join(parts)
