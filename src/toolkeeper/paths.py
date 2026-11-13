"""置き場所。設定はプログラムの置き場所（exe ならそのフォルダ、リポジトリから動かすならリポジトリの根）、
データは設定の data_dir か <app>/data（design.md §6・§9.3）"""
import sys
from pathlib import Path


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


APP_DIR = _app_dir()


def self_command() -> list[str]:
    """ToolKeeper のコマンドを別のプロセスで呼ぶときの頭（design.md §9.3）。
    exe なら隣のコンソール用の toolkeeper.exe（窓を出さない toolkeeperw.exe から呼んでも出力を読める）"""
    if getattr(sys, "frozen", False):
        return [str(_app_dir() / "toolkeeper.exe")]
    return [sys.executable, "-m", "toolkeeper"]


def default_config_path() -> Path:
    return APP_DIR / "toolkeeper.json"


def data_dir(cfg: dict, override: str | None = None) -> Path:
    if override:
        return Path(override)
    if cfg.get("data_dir"):
        return Path(cfg["data_dir"])
    return APP_DIR / "data"
