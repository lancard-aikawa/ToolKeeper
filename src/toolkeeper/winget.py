"""winget の表を読む（docs/design.md §3.1）

winget は JSON を出せないので表を読む。パイプに出すと UTF-8。列は空白で揃えてあり、全角は 2 桁と数える。
見出しの文字は言語で変わるので、`-----` だけの行の 1 つ上を見出しとし、見出しの語の始まりの桁で列を切る。
版の欄には空白を含むもの（"7.1.9 (48550)"、"< 3.14.7"）があるので、空白で割らない。
"""
import re
import subprocess
import unicodedata

COMMON = ["--accept-source-agreements", "--disable-interactivity"]
TIMEOUT = 300
COLUMNS = ("name", "id", "version", "available", "source")
_DASHES = re.compile(r"^-{10,}$")
_DATE = re.compile(r"^\s+[^:]+:\s*(\d{4}-\d{2}-\d{2})$")


def width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _clean(line: str) -> str:
    """進み具合の記号（"\\r-\\r\\|"）が前に付いた行は、最後の \\r より後だけを使う"""
    return line.rsplit("\r", 1)[-1].rstrip()


def _starts(header: str) -> list[int]:
    starts, pos, gap = [], 0, True
    for c in header:
        if c != " " and gap:
            starts.append(pos)
        gap = c == " "
        pos += width(c)
    return starts


def _cut(line: str, starts: list[int]) -> list[str]:
    cells = [""] * len(starts)
    pos, col = 0, 0
    for c in line:
        while col + 1 < len(starts) and pos >= starts[col + 1]:
            col += 1
        cells[col] += c
        pos += width(c)
    return [x.strip() for x in cells]


def parse(text: str) -> dict:
    """winget upgrade / list の出力 → {"items": [{name, id, version, available, source}], "unknown": n, "pinned": n}

    表は 1 つとは限らない（「明示的な対象設定が必要」の表が続くことがある）。表の後ろの件数の行は捨て、
    版を判別できない物と pin で止めた物の件数だけを拾う（文の言語に依らないよう、行に出てくるオプションの名前で見分ける）"""
    lines = [_clean(x) for x in text.replace("\r\n", "\n").split("\n")]
    items, unknown, pinned = [], 0, 0
    starts = None
    for i, line in enumerate(lines):
        if _DASHES.match(line):
            starts = _starts(lines[i - 1]) if i > 0 else None
            continue
        m = re.match(r"\s*(\d+)\D", line)
        if m and "--include-unknown" in line:
            unknown += int(m.group(1))
            continue
        if m and "--include-pinned" in line:
            pinned += int(m.group(1))
            continue
        if not starts or not line.strip():
            continue
        if i + 1 < len(lines) and _DASHES.match(lines[i + 1]):  # 次の表の見出し
            continue
        cells = _cut(line, starts)
        if len(cells) < 3 or not cells[1] or " " in cells[1] or not cells[2]:
            starts = None if not cells[1] else starts  # 表の後ろの文の行
            continue
        row = dict(zip(COLUMNS, cells + [""] * (len(COLUMNS) - len(cells))))
        items.append(row)
    return {"items": items, "unknown": unknown, "pinned": pinned}


def parse_release_date(text: str) -> str | None:
    """winget show の出力 → その版の公開日（"2026-09-20"）。載っていなければ None（任意の項目で、書いていない道具がある）

    見出しの語（「リリース日」「Release Date」）は言語で変わるので使わない。字下げの無い行で塊に分け、
    SHA256 の行がある塊（インストーラー）の中から、値が日付だけの行を拾う（リリースノートの中の日付を拾わないため）"""
    blocks: list[list[str]] = [[]]
    for line in (_clean(x) for x in text.replace("\r\n", "\n").split("\n")):
        if line and not line[0].isspace():
            blocks.append([])
        blocks[-1].append(line)
    for block in blocks:
        if any("SHA256" in line for line in block):
            for line in block:
                m = _DATE.match(line)
                if m:
                    return m.group(1)
    return None


def _run(args: list[str]) -> str:
    r = subprocess.run(["winget", *args], capture_output=True, timeout=TIMEOUT,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    text = r.stdout.decode("utf-8", errors="replace")
    if r.returncode != 0 and "-----" not in text:
        tail = "\n".join(text.strip().splitlines()[-3:])
        raise RuntimeError(f"winget {args[0]} が失敗しました（終了コード {r.returncode}）: {tail}")
    return text


def upgrades() -> dict:
    """更新できる物。pin で止めた物は出ない（--include-pinned を付けない）"""
    return parse(_run(["upgrade", *COMMON]))


def installed() -> dict:
    """winget の取得元で見つかる、入っている物全部（サポート終了を見るのに使う。pin で止めた物も「利用可能」が出る）"""
    return parse(_run(["list", "--source", "winget", *COMMON]))


def release_date(winget_id: str, version: str) -> str | None:
    """その版の公開日。1 件に 1〜6 秒かかる"""
    r = subprocess.run(["winget", "show", "--id", winget_id, "--exact", "--version", version, *COMMON],
                       capture_output=True, timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        raise RuntimeError(f"winget show {winget_id} が失敗しました（終了コード {r.returncode}）")
    return parse_release_date(r.stdout.decode("utf-8", errors="replace"))


def version() -> str | None:
    try:
        r = subprocess.run(["winget", "--version"], capture_output=True, text=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip().lstrip("v") or None
