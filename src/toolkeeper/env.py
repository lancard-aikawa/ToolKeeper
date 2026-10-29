"""道具にかかわる環境変数と PATH を調べる（docs/design.md §3.7）

PATH と環境変数はレジストリから読む。プロセスの環境は、起動した側が開いたときの古い値のことがある。
ここでは何も書き換えない。
"""
import os
import re

MACHINE_KEY = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
USER_KEY = "Environment"
SCOPES = ("machine", "user")
ENV_FILE = "env.json"
VERSIONED = re.compile(r"\d+\.\d+\.\d+")
# 版の入ったフォルダでも、ToolKeeper の更新が PATH を書き換える物は「更新で切れうる」にしない（§3.3 の gs-install.ps1）
SELF_MANAGED = re.compile(r"\\gs\\gs\d+\.\d+\.\d+\\bin\\?$", re.IGNORECASE)
VERSIONED_NOTE = "版の入ったフォルダ。更新で名前が変わると切れる"
STATE_ORDER = {"bad": 0, "warn": 1, "info": 2, "ok": 3}


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
    """PATH の行をマシン → ユーザーの順に: {"scope", "raw", "dir"}"""
    rows = []
    for scope in SCOPES:
        for raw in (_get(reg.get(scope, {}), "Path") or "").split(";"):
            if raw.strip():
                rows.append({"scope": scope, "raw": raw, "dir": expand(raw.strip(), env)})
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


def _finding(state, kind, scope, name, value, detail) -> dict:
    return {"state": state, "kind": kind, "scope": scope, "name": name, "value": value, "detail": detail}


def inspect(reg: dict, var_names: list[str], commands: list[str], process_env=None,
            exists=os.path.exists, isfile=os.path.isfile) -> list[dict]:
    """§3.7 の表の行。state は bad（切れている）・warn（注意・更新で切れうる）・info（整理できる）・ok"""
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
                found.append(_finding("bad", "var", scope, name, raw, "無い場所: " + "; ".join(missing)))
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
            where = "マシン" if first["scope"] == "machine" else "ユーザー"
            found.append(_finding("info", "path-dup", e["scope"], "PATH", e["raw"], f"{where}の PATH にもある。こちらは使われない"))
            continue
        seen[d] = e
        if not exists(e["dir"].strip().strip('"')):
            found.append(_finding("bad", "path-missing", e["scope"], "PATH", e["raw"], "フォルダが無い"))
        elif VERSIONED.search(e["dir"]) and not SELF_MANAGED.search(e["dir"]):
            found.append(_finding("warn", "path-versioned", e["scope"], "PATH", e["raw"], VERSIONED_NOTE))

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
