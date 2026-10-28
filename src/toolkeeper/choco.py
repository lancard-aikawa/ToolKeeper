"""choco の古い物を読む（docs/design.md §3.5）。知らせるだけで、更新はしない"""
import shutil
import subprocess

TIMEOUT = 600


def parse(text: str) -> list[dict]:
    """`choco outdated --limit-output` の `名前|今の版|最新|pin` の行 → [{name, version, available, pinned}]"""
    out = []
    for line in text.splitlines():
        parts = line.strip().split("|")
        if len(parts) != 4 or not parts[0]:
            continue
        out.append({"name": parts[0], "version": parts[1], "available": parts[2], "pinned": parts[3].lower() == "true"})
    return out


def available() -> bool:
    return shutil.which("choco") is not None


def outdated() -> list[dict]:
    r = subprocess.run(["choco", "outdated", "--limit-output"], capture_output=True, timeout=TIMEOUT,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    text = r.stdout.decode("utf-8", errors="replace")
    if r.returncode not in (0, 2):  # 2 は「古い物がある」
        raise RuntimeError(f"choco outdated が失敗しました（終了コード {r.returncode}）")
    return parse(text)


def version() -> str | None:
    if not available():
        return None
    try:
        r = subprocess.run(["choco", "--version"], capture_output=True, text=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() or None
