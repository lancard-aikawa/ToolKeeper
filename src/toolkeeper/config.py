"""設定ファイル (toolkeeper.json) を読む。形は docs/design.md §6（LockWatch の config.py と同じ作り）"""
import copy
import json
from pathlib import Path

DEFAULTS: dict = {
    "data_dir": None,
    # 区分 B: 更新のボタンを付ける winget の ID。ここに無い winget の物は C（§2）
    "winget_update": [
        "7zip.7zip",
        "GitHub.cli",
        "Kitware.CMake",
        "Gyan.FFmpeg",
        "Python.Python.3.14",
        "Python.Launcher",
        "Rustlang.Rustup",
        "StrawberryPerl.StrawberryPerl",
        "TeraTermProject.teraterm5",
        "Microsoft.OpenJDK.11",
        "Microsoft.OpenJDK.17",
        "Microsoft.OpenJDK.21",
        "EclipseAdoptium.Temurin.11.JDK",
        "EclipseAdoptium.Temurin.8.JRE",
        "PHP.PHP.NTS.8.3",
        "Cygwin.CygwinSetup",
    ],
    "cygwin_root": "C:\\cygwin64",
    "ghostscript": True,
    "choco": True,
    # winget の ID（正規表現。最初の () が系列）→ endoflife.date の製品（§3.6）
    "eol": [
        {"id": r"OpenJS\.NodeJS\.(\d+)", "product": "nodejs"},
        {"id": r"Python\.Python\.(\d+\.\d+)", "product": "python"},
        {"id": r"PHP\.PHP\.(?:NTS\.)?(\d+\.\d+)", "product": "php"},
        {"id": r"Microsoft\.OpenJDK\.(\d+)", "product": "microsoft-build-of-openjdk"},
        {"id": r"EclipseAdoptium\.Temurin\.(\d+)\.J(?:DK|RE)", "product": "eclipse-temurin"},
    ],
    "choco_twins": {
        "gh": "GitHub.cli",
        "marktext": "MarkText.MarkText",
        "microsoft-openjdk17": "Microsoft.OpenJDK.17",
        "microsoft-openjdk-21": "Microsoft.OpenJDK.21",
        "python314": "Python.Python.3.14",
        "Temurin11": "EclipseAdoptium.Temurin.11.JDK",
        "visualstudio2019buildtools": "Microsoft.VisualStudio.2019.BuildTools",
    },
    "cache_hours": 24,
}


def load(path: Path) -> dict:
    """設定を読む。ファイルが無ければ既定値。書いてあるキーだけ既定値を置き換える（並びや表は丸ごと置き換える）"""
    cfg = copy.deepcopy(DEFAULTS)
    if not path.is_file():
        return cfg
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: JSON のオブジェクトではありません")
    cfg.update(data)
    return cfg
