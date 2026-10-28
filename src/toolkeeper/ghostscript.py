"""Ghostscript の入っている版と最新（docs/design.md §3.3）

本家（Artifex）は winget に出していないので、GitHub の releases を見る。トークンは使わない（1 時間に 60 回まで）。
"""
import json
import re
from pathlib import Path

from . import store

RELEASES = "https://api.github.com/repos/ArtifexSoftware/ghostpdl-downloads/releases/latest"


def tag_version(tag: str) -> str | None:
    """"gs10080" → "10.08.0"、"gs10051" → "10.05.1"（末尾 3 桁が 2 桁のマイナーと 1 桁のパッチ）"""
    m = re.fullmatch(r"gs(\d+)(\d\d)(\d)", tag or "")
    return f"{int(m.group(1))}.{m.group(2)}.{m.group(3)}" if m else None


def vkey(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v))


def parse_release(obj: dict) -> dict | None:
    """releases/latest の JSON → {version, published, asset, url, sha256}。64 ビット版が無ければ None"""
    version = tag_version(obj.get("tag_name", ""))
    if not version:
        return None
    for a in obj.get("assets") or []:
        name = a.get("name", "")
        if re.fullmatch(r"gs\d+w64\.exe", name):
            digest = a.get("digest") or ""
            return {"version": version, "published": obj.get("published_at"), "asset": name,
                    "url": a.get("browser_download_url"),
                    "sha256": digest[7:] if digest.startswith("sha256:") else None}
    return None


def latest(cache: Path, max_age_hours: float) -> dict:
    body = store.fetch(RELEASES, cache / "ghostscript-latest.json", max_age_hours)
    rel = parse_release(json.loads(body.decode("utf-8")))
    if not rel:
        raise RuntimeError("Ghostscript の最新の 64 ビット版が見つかりません")
    return rel


def installed() -> list[str]:
    """HKLM\\SOFTWARE\\GPL Ghostscript\\<版> の版を古い順に（入っていなければ空）"""
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\GPL Ghostscript", 0,
                             winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
    except OSError:
        return []
    out = []
    with key:
        i = 0
        while True:
            try:
                out.append(winreg.EnumKey(key, i))
            except OSError:
                break
            i += 1
    return sorted((v for v in out if re.fullmatch(r"\d+(\.\d+)+", v)), key=vkey)
