"""Cygwin の入っている物と最新を比べる（docs/design.md §3.4）

  入っている物 … <root>/etc/setup/installed.db（"<名前> <ファイル名> 0"）
  ミラー       … <root>/etc/setup/setup.rc の last-mirror の次の行
  最新         … <ミラー>/x86_64/setup.xz を lzma で読む。"@ <名前>" の後の最初の version: が今の版（[prev]・[test] の後は使わない）
"""
import ctypes
import lzma
import re
from ctypes import wintypes
from pathlib import Path

from . import store

DEFAULT_MIRROR = "https://ftp.jaist.ac.jp/pub/cygwin/"
_ARCHIVE = re.compile(r"\.tar\.(?:bz2|xz|gz|zst)$")


def parse_installed(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        name, fname = parts[0], parts[1]
        if fname.startswith(name + "-"):
            out[name] = _ARCHIVE.sub("", fname[len(name) + 1:])
    return out


def parse_setup_rc(text: str) -> dict[str, list[str]]:
    """キーは行頭、値はタブで始まる次の行"""
    out, key = {}, None
    for line in text.splitlines():
        if line.startswith(("\t", " ")):
            if key:
                out[key].append(line.strip())
        elif line.strip():
            key = line.strip()
            out[key] = []
    return out


def parse_setup_ini(text: str) -> dict[str, str]:
    out, name, done = {}, None, True
    for line in text.splitlines():
        if line.startswith("@ "):
            name, done = line[2:].strip(), False
        elif name and not done:
            if line.startswith("["):
                done = True
            elif line.startswith("version:"):
                out[name] = line.split(":", 1)[1].strip()
                done = True
    return out


def read_installed(root: Path) -> dict[str, str]:
    with open(root / "etc" / "setup" / "installed.db", encoding="utf-8") as f:
        return parse_installed(f.read())


def read_setup_rc(root: Path) -> dict[str, list[str]]:
    try:
        with open(root / "etc" / "setup" / "setup.rc", encoding="utf-8") as f:
            return parse_setup_rc(f.read())
    except OSError:
        return {}


def mirror(rc: dict[str, list[str]]) -> str:
    m = (rc.get("last-mirror") or [DEFAULT_MIRROR])[0]
    return m if m.endswith("/") else m + "/"


def latest(mirror_url: str, cache: Path, max_age_hours: float) -> dict[str, str]:
    body = store.fetch(mirror_url + "x86_64/setup.xz", cache / "cygwin-setup.xz", max_age_hours)
    return parse_setup_ini(lzma.decompress(body).decode("utf-8", errors="replace"))


def outdated(installed: dict[str, str], current: dict[str, str]) -> list[str]:
    """入っている版と今の版が違う物（ミラーに無い物は数えない）"""
    return sorted(n for n, v in installed.items() if n in current and current[n] != v)


# ---- 上げる（§3.4）

SETUP_ID = "Cygwin.CygwinSetup"


def setup_exe() -> Path | None:
    """winget の Cygwin.CygwinSetup（portable）が置く cygwinsetup.exe。無ければ None"""
    import os
    p = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / "cygwinsetup.exe"
    return p if p.exists() else None


def setup_args(exe: Path, root: Path, mirror_url: str, package_dir: str) -> list[str]:
    """画面の入力なしで、入っている物を全部上げる。--wait は、管理者に上がった子のプロセスを待つ
    （Setup は asInvoker で作られていて、自分で UAC を出して上がる）。--only-site はミラーの一覧を取らない"""
    return [str(exe), "--quiet-mode", "--wait", "--upgrade-also", "--root", str(root),
            "--site", mirror_url, "--only-site", "--local-package-dir", package_dir,
            "--no-desktop", "--no-shortcuts", "--no-startmenu"]


def log_tail(root: Path, lines: int) -> str:
    try:
        with open(root / "var" / "log" / "setup.log", encoding="utf-8", errors="replace") as f:
            return "\n".join(f.read().strip().splitlines()[-lines:])
    except OSError:
        return ""


# ---- 動いているプロセス（更新の前に閉じてもらう。終了はしない）

def running(root: Path) -> list[str]:
    """実行ファイルが root の下にあるプロセスの名前（重ねない）"""
    prefix = str(root).rstrip("\\").lower() + "\\"
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    ids = (wintypes.DWORD * 4096)()
    got = wintypes.DWORD()
    if not psapi.EnumProcesses(ids, ctypes.sizeof(ids), ctypes.byref(got)):
        return []
    names = set()
    for pid in ids[: got.value // ctypes.sizeof(wintypes.DWORD)]:
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            continue
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buf))
            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)) and buf.value.lower().startswith(prefix):
                names.add(Path(buf.value).name)
        finally:
            k32.CloseHandle(h)
    return sorted(names)
