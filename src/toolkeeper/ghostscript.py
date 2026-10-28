"""Ghostscript の入っている版と最新（docs/design.md §3.3）

本家（Artifex）は winget に出していないので、GitHub の releases を見る。トークンは使わない（1 時間に 60 回まで）。
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from . import store
from .paths import APP_DIR

RELEASES = "https://api.github.com/repos/ArtifexSoftware/ghostpdl-downloads/releases/latest"
SIGNER = 'O="Artifex Software, Inc."'
INSTALL_SCRIPT = APP_DIR / "scripts" / "gs-install.ps1"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# gs-install.ps1 の終了コード
SCRIPT_EXIT = {10: "インストーラが失敗しました", 11: "入れたあとに新しい版がレジストリに見つかりません",
               12: "PATH を書き換えられませんでした"}


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


def _ps51_env() -> dict:
    """PowerShell 7 から powershell.exe（5.1）を起動すると PSModulePath が引き継がれ、5.1 の
    Get-AuthenticodeSignature が全部失敗する（ProcCheck で見つけた件）ので外す。
    Windows の os.environ は名前を大文字で持つ（PSMODULEPATH）ので、大文字小文字を区別せずに外す"""
    return {k: v for k, v in os.environ.items() if k.lower() != "psmodulepath"}


def signer(path: Path) -> tuple[str, str]:
    """Authenticode の (状態, 署名者)。状態は Valid・NotSigned など。確かめられなければ例外"""
    ps = ("$s = Get-AuthenticodeSignature -LiteralPath $env:TK_FILE; "
          "$s.Status.ToString(); if ($s.SignerCertificate) { $s.SignerCertificate.Subject } else { '' }")
    env = _ps51_env()
    env["TK_FILE"] = str(path)
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True,
                       text=True, timeout=120, env=env, creationflags=_NO_WINDOW)
    lines = (r.stdout.splitlines() + ["", ""])[:2]
    if r.returncode != 0 or not lines[0].strip():
        err = " ".join(r.stderr.split())[:300]
        raise RuntimeError(f"署名を確かめられません（powershell.exe の終了コード {r.returncode}）: {err}")
    return lines[0].strip(), lines[1].strip()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(rel: dict, folder: Path, out, fetch=store._download) -> Path:
    """インストーラを、それ以外に何も無いフォルダに取り、SHA-256 と署名を確かめる。合わなければ消して止める。
    前に取った物の SHA-256 が合えば取り直さない（65 MB ある）"""
    if not rel.get("sha256") or not rel.get("url"):
        raise RuntimeError("GitHub が SHA-256 を返さなかったので入れません")
    exe = folder / rel["asset"]
    kept = exe.is_file() and _sha256(exe) == rel["sha256"]
    if kept:
        for p in folder.iterdir():
            if p != exe:
                shutil.rmtree(p) if p.is_dir() else p.unlink()
        out.write("前に取った物の SHA-256 が合ったので、それを使います\n")
    else:
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
        out.write(f"ダウンロード中 {rel['url']}\n")
        out.flush()
        body = fetch(rel["url"])
        got = hashlib.sha256(body).hexdigest()
        if got != rel["sha256"]:
            raise RuntimeError(f"SHA-256 が合いません（GitHub {rel['sha256']}、取った物 {got}）")
        exe.write_bytes(body)
        out.write("SHA-256 が合いました\n")
    try:
        status, subject = signer(exe)
    except RuntimeError:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    if status != "Valid" or SIGNER not in subject:
        shutil.rmtree(folder, ignore_errors=True)
        raise RuntimeError(f"署名が Artifex の有効な物ではありません（{status}、{subject or '署名者なし'}）")
    out.write(f"署名を確かめました（{subject}）\n")
    out.flush()
    return exe


def run_elevated(exe: Path, new: str, old: str | None, log: Path) -> int:
    """gs-install.ps1 を管理者として動かして終了コードを返す（UAC が 1 回出る）。
    断られたら Start-Process が例外を出すので 1 が返る"""
    log.unlink(missing_ok=True)
    args = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(INSTALL_SCRIPT),
            "-Installer", str(exe), "-NewVersion", new, "-Log", str(log)]
    if old:
        args += ["-OldVersion", old]
    # Start-Process は ArgumentList を空白でつなぐだけなので、空白を含む値は "" で囲む
    joined = " ".join(f'"{a}"' if " " in a else a for a in args).replace("'", "''")
    ps = (f"$p = Start-Process -FilePath powershell.exe -Verb RunAs -Wait -PassThru -WindowStyle Hidden "
          f"-ArgumentList '{joined}'; exit $p.ExitCode")
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True,
                       text=True, env=_ps51_env(), creationflags=_NO_WINDOW)
    return r.returncode


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
