"""置き場所。設定はプログラムの置き場所（リポジトリの根）、データは設定の data_dir か <app>/data"""
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[2]


def default_config_path() -> Path:
    return APP_DIR / "toolkeeper.json"


def data_dir(cfg: dict, override: str | None = None) -> Path:
    if override:
        return Path(override)
    if cfg.get("data_dir"):
        return Path(cfg["data_dir"])
    return APP_DIR / "data"
