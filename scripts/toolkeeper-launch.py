"""窓を出さずに ToolKeeper を動かすための起動役（scripts/register-task.ps1 が使う）

uv 0.11 の .venv\\Scripts\\pythonw.exe は python.exe と同じコンソール用の起動役で、黒い窓が開く。
そこで本体の Python の pythonw.exe（scripts\\find-pythonw.ps1 が探す）でこのファイルを動かす。
ToolKeeper は標準ライブラリしか使わないので、src を読み込み先に足せば .venv は要らない。

  <home>\\pythonw.exe scripts\\toolkeeper-launch.py --log check
  <home>\\pythonw.exe scripts\\toolkeeper-launch.py gui
"""
import os
import sys
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, SRC)
# 画面が別のプロセスで呼ぶ python -m toolkeeper にも src を見せる
os.environ["PYTHONPATH"] = os.pathsep.join(p for p in (SRC, os.environ.get("PYTHONPATH")) if p)

from toolkeeper.cli import main  # noqa: E402

sys.exit(main())
