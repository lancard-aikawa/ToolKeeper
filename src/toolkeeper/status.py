"""使える状態か（docs/design.md §9.2）。ネットに出ない。winget と choco は版を聞くだけ"""
import subprocess
from pathlib import Path

from . import __version__, check, choco, ghostscript, store, winget

TASK_NAME = "ToolKeeper"


def task_registered() -> bool:
    try:
        r = subprocess.run(["schtasks", "/query", "/tn", TASK_NAME], capture_output=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


def run(cfg: dict, data: Path) -> dict:
    last = store.read_json(data / check.CHECK_FILE) or {}
    root = Path(cfg["cygwin_root"]) if cfg.get("cygwin_root") else None
    return {
        "toolkeeper": __version__,
        "schema": check.SCHEMA,
        "data_dir": str(data),
        "last_check": last.get("checked_at"),
        "task": {"registered": task_registered()},
        "sources": {
            "winget": winget.version(),
            "choco": choco.version() if cfg["choco"] else None,
            "cygwin": str(root) if root and (root / "etc" / "setup" / "installed.db").is_file() else None,
            "ghostscript": bool(cfg["ghostscript"] and ghostscript.installed()),
        },
    }
