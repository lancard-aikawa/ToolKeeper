from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    """改行を変換せずに読む（winget の行の頭の進み具合の記号 \\r を残すため）"""
    with open(FIXTURES / name, encoding="utf-8", newline="") as f:
        return f.read()
