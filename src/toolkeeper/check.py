"""全部を調べて check.json を作る（docs/design.md §2・§5・§9.1）

取得元ごとに独立して動かす。1 つが失敗しても残りは出し、失敗した物は failed に理由を付けて出す。
何かを入れる処理はここから呼ばない（§4）。
"""
import re
import subprocess
from pathlib import Path

from . import __version__, choco, cygwin, env, eol, ghostscript, store, winget

SCHEMA = 1
CHECK_FILE = "check.json"
DATES_FILE = "winget-dates.json"


class Sources:
    """外とのやりとり。試験では差し替える"""
    winget_upgrades = staticmethod(winget.upgrades)
    winget_installed = staticmethod(winget.installed)
    winget_date = staticmethod(winget.release_date)
    choco_available = staticmethod(choco.available)
    choco_outdated = staticmethod(choco.outdated)
    gs_installed = staticmethod(ghostscript.installed)
    gs_latest = staticmethod(ghostscript.latest)
    cyg_installed = staticmethod(cygwin.read_installed)
    cyg_setup_rc = staticmethod(cygwin.read_setup_rc)
    cyg_latest = staticmethod(cygwin.latest)
    cyg_running = staticmethod(cygwin.running)

    env_registry = staticmethod(env.read_registry)

    @staticmethod
    def php() -> tuple[str, str] | None:
        """PATH の php の (版, パス)。無ければ None。
        PATH はレジストリから読む（起動した側の古い PATH だと、乗り換え前の PHP が出る。§3.7）"""
        exe = env.which("php")
        if not exe:
            return None
        r = subprocess.run([exe, "-r", "echo PHP_VERSION;"], capture_output=True, text=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return (r.stdout.strip(), exe) if r.returncode == 0 and r.stdout.strip() else None

    def eol(self, cache: Path, max_age_hours: float, today):
        return eol.Lookup(cache, max_age_hours, today)


def _item(key, tier, name, installed, latest, updatable, eol_=None, notes=None, **extra) -> dict:
    return {"key": key, "tier": tier, "name": name, "installed": installed, "latest": latest,
            "updatable": updatable, "latest_date": None, "eol": eol_, "new": False, "notes": notes or [], **extra}


def _same_release(a: str | None, b: str | None) -> bool:
    """版の先頭 3 つの数が同じか（winget の "21.0.13.1021" と endoflife.date の "21.0.13.0.2" は同じ版）"""
    ka, kb = ghostscript.vkey(a or "")[:3], ghostscript.vkey(b or "")[:3]
    return len(ka) == 3 and ka == kb


def _same_build(installed: str, available: str) -> bool:
    """winget は更新ありと出すが、版の書き方が違うだけで同じ物か。Microsoft.OpenJDK は入れたあとの版が "21.0.13.21"、
    winget の版が "21.0.13.1021" で、上げても更新ありのまま残る（2026-10-29、17 も同じ）。
    4 つの数のうち先頭 3 つが同じで、最後の数が winget の最後の数の末尾と同じときだけ同じとみなす（"< 3.14.7" は版が分からないので違う）"""
    if installed.lstrip().startswith("<"):
        return False
    a, b = re.findall(r"\d+", installed), re.findall(r"\d+", available)
    return len(a) == 4 and len(b) == 4 and a[:3] == b[:3] and a[3] != b[3] and b[3].endswith(a[3])


def _reason(e: Exception) -> str:
    return str(e) or type(e).__name__


def _winget(cfg, src, lookup, items, failed):
    try:
        up = src.winget_upgrades()
    except Exception as e:  # noqa: BLE001 (取得元ごとに止める)
        failed.append({"source": "winget", "reason": _reason(e)})
        return
    update_ids = set(cfg["winget_update"])
    seen = set()
    for row in up["items"]:
        seen.add(row["id"])
        same = _same_build(row["version"], row["available"])
        items.append(_item(f"winget:{row['id']}", "B" if row["id"] in update_ids else "C", row["name"],
                           row["version"], row["available"], not same, notes=["same"] if same else None))
    if up["pinned"]:
        items.append(_item("winget:(pinned)", "C", "pin で止めた物", None, None, False, notes=[f"pinned:{up['pinned']}"]))

    # サポート終了: 更新の無い物も含めて、規則に当たる物を全部見る
    rules = cfg["eol"]
    try:
        inst = src.winget_installed()["items"] if rules else []
    except Exception as e:  # noqa: BLE001
        failed.append({"source": "winget list", "reason": _reason(e)})
        inst = []
    by_key = {it["key"]: it for it in items}
    for row in inst:
        hit = eol.match(rules, row["id"])
        if not hit:
            continue
        try:
            st = lookup.get(*hit)
        except Exception as e:  # noqa: BLE001
            failed.append({"source": f"endoflife.date ({hit[0]})", "reason": _reason(e)})
            continue
        if not st:
            continue
        key = f"winget:{row['id']}"
        it = by_key.get(key)
        if it is None:
            if st["state"] == "ok" or row["id"] in seen:
                continue
            it = _item(key, "C", row["name"], row["version"], None, False)
            items.append(it)
            by_key[key] = it
        it["eol"] = {k: st[k] for k in ("product", "cycle", "date", "state")}
        if it["updatable"] and _same_release(st["latest"], it["latest"]):
            it["latest_date"] = st.get("latest_date")
        if st["state"] == "ended":
            it["tier"] = "E"


def _php(src, lookup, items, failed):
    """winget で入れた PHP なら winget の行に任せる。手で入れた物だけ A の行にする（§7 の乗り換えを促す）"""
    try:
        got = src.php()
    except Exception as e:  # noqa: BLE001
        failed.append({"source": "php", "reason": _reason(e)})
        return
    if not got:
        return
    version, exe = got
    if "\\microsoft\\winget\\" in exe.lower():
        return
    cycle = ".".join(version.split(".")[:2])
    st = None
    try:
        st = lookup.get("php", cycle)
    except Exception as e:  # noqa: BLE001
        failed.append({"source": "endoflife.date (php)", "reason": _reason(e)})
    latest = st["latest"] if st else None
    items.append(_item("php", "A", "PHP", version, latest, bool(latest and latest != version),
                       {k: st[k] for k in ("product", "cycle", "date", "state")} if st else None, ["manual"],
                       latest_date=st.get("latest_date") if st else None))


def _ghostscript(cfg, src, cache, items, failed):
    if not cfg["ghostscript"]:
        return
    try:
        have = src.gs_installed()
    except Exception as e:  # noqa: BLE001
        failed.append({"source": "ghostscript", "reason": _reason(e)})
        return
    if not have:
        return
    notes = [f"old:{v}" for v in have[:-1]]
    try:
        rel = src.gs_latest(cache, cfg["cache_hours"])
    except Exception as e:  # noqa: BLE001
        failed.append({"source": "ghostscript", "reason": _reason(e)})
        rel = None
    latest = rel["version"] if rel else None
    newer = bool(latest and ghostscript.vkey(latest) > ghostscript.vkey(have[-1]))
    items.append(_item("ghostscript", "A", "Ghostscript", have[-1], latest, newer, notes=notes,
                       latest_date=(rel.get("published") or "")[:10] or None if rel else None))


def _cygwin(cfg, src, cache, items, failed):
    root = Path(cfg["cygwin_root"]) if cfg.get("cygwin_root") else None
    if not root or not (root / "etc" / "setup" / "installed.db").is_file():
        return
    try:
        have = src.cyg_installed(root)
        current = src.cyg_latest(cygwin.mirror(src.cyg_setup_rc(root)), cache, cfg["cache_hours"])
    except Exception as e:  # noqa: BLE001
        failed.append({"source": "cygwin", "reason": _reason(e)})
        return
    old = cygwin.outdated(have, current)
    notes = []
    try:
        notes = [f"running:{n}" for n in src.cyg_running(root)]
    except Exception:  # noqa: BLE001 (見えなくても調べるのは止めない)
        pass
    items.append(_item("cygwin", "A", "Cygwin", have.get("cygwin"), current.get("cygwin"), bool(old), notes=notes,
                       packages={"installed": len(have), "outdated": len(old), "names": old[:50]}))


def _choco(cfg, src, items, failed):
    if not cfg["choco"] or not src.choco_available():
        return
    try:
        rows = src.choco_outdated()
    except Exception as e:  # noqa: BLE001
        failed.append({"source": "choco", "reason": _reason(e)})
        return
    twins = cfg["choco_twins"]
    for r in rows:
        notes = [f"twin:winget:{twins[r['name']]}"] if r["name"] in twins else []
        if r["pinned"]:
            notes.append("pinned")
        items.append(_item(f"choco:{r['name']}", "D", r["name"], r["version"], r["available"], True, notes=notes))


def _dates(src, cache, items) -> None:
    """winget の更新版の公開日（§3.8）。winget show は 1 件に 1〜6 秒かかるので、B・E の更新できる物だけを引き、
    ID と版の組ごとに cache に残して、次からは新しい版だけを引く。引けなくても照合は失敗にしない（「-」と出すだけ）"""
    path = cache / DATES_FILE
    known = store.read_json(path) or {}
    kept = {}
    for it in items:
        if (not it["key"].startswith("winget:") or not it["updatable"] or it["tier"] not in ("B", "E")
                or not it["latest"] or it["latest_date"]):
            continue
        k = f"{it['key'][len('winget:'):]}@{it['latest']}"
        if k not in known:
            try:
                known[k] = src.winget_date(it["key"][len("winget:"):], it["latest"])
            except Exception:  # noqa: BLE001 (次の照合でもう一度引く)
                continue
        kept[k] = known[k]
        it["latest_date"] = known[k]
    if kept != (store.read_json(path) or {}):
        store.write_json(path, kept)


def _env(cfg, src, data, t, failed) -> int:
    """環境変数と PATH（§3.7）。パスを含むので check.json には数だけを出し、中身は env.json に書く"""
    try:
        found = env.inspect(src.env_registry(), cfg["env_vars"], cfg["env_commands"])
    except Exception as e:  # noqa: BLE001
        failed.append({"source": "環境変数", "reason": _reason(e)})
        return 0
    store.write_json(data / env.ENV_FILE, {"checked_at": store.iso(t), "items": found})
    return env.problems(found)


TIER_ORDER = {"E": 0, "A": 1, "B": 2, "C": 3, "D": 4}


def run(cfg: dict, data: Path, src: Sources | None = None) -> dict:
    src = src or Sources()
    cache = data / "cache"
    t = store.now()
    lookup = src.eol(cache, cfg["cache_hours"], t.date())
    items, failed = [], []
    _winget(cfg, src, lookup, items, failed)
    _php(src, lookup, items, failed)
    _ghostscript(cfg, src, cache, items, failed)
    _cygwin(cfg, src, cache, items, failed)
    _choco(cfg, src, items, failed)
    _dates(src, cache, items)
    env_count = _env(cfg, src, data, t, failed)

    prev = store.read_json(data / CHECK_FILE) or {}
    before = {it.get("key"): it.get("latest") for it in prev.get("items") or [] if it.get("updatable")}
    for it in items:
        it["new"] = bool(it["updatable"] and before.get(it["key"], object()) != it["latest"]) if prev else False
    items.sort(key=lambda it: (TIER_ORDER[it["tier"]], it["name"].lower()))

    result = {
        "schema": SCHEMA,
        "toolkeeper": __version__,
        "checked_at": store.iso(t),
        "summary": {
            "updatable": sum(1 for it in items if it["updatable"] and it["tier"] in ("A", "B")),
            "eol": sum(1 for it in items if it["eol"] and it["eol"]["state"] in ("ended", "soon")),
            "new": sum(1 for it in items if it["new"]),
            "failed": len(failed),
            "env": env_count,
        },
        "items": items,
        "failed": failed,
    }
    store.write_json(data / CHECK_FILE, result)
    return result
