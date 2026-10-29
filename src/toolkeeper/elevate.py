"""scripts/ の PowerShell を管理者として動かす（UAC が 1 回出る）。Ghostscript の入れ替え（§3.3）とマシンの環境変数（§3.7）が使う"""
import subprocess
from pathlib import Path

from .ghostscript import _ps51_env
from .paths import APP_DIR

SCRIPTS = APP_DIR / "scripts"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run_script(script: Path, args: list[str], log: Path) -> int:
    """script を管理者として動かして終了コードを返す。出力は見えないので、スクリプトに log へ書かせる。
    UAC で断られたら Start-Process が例外を出すので 1 が返る"""
    log.unlink(missing_ok=True)
    argv = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args]
    # Start-Process は ArgumentList を空白でつなぐだけなので、空白を含む値は "" で囲む
    joined = " ".join(f'"{a}"' if " " in a else a for a in argv).replace("'", "''")
    ps = (f"$p = Start-Process -FilePath powershell.exe -Verb RunAs -Wait -PassThru -WindowStyle Hidden "
          f"-ArgumentList '{joined}'; exit $p.ExitCode")
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True,
                       text=True, env=_ps51_env(), creationflags=_NO_WINDOW)
    return r.returncode
