"""データフォルダの読み書きと、取ってきたものの置き場（docs/design.md §5・§9）

  check.json, history.jsonl, lock, cache/<名前>
"""
import json
import os
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from . import __version__

TIMEOUT = 60
USER_AGENT = f"ToolKeeper/{__version__} (+https://github.com/lancard-aikawa/ToolKeeper)"


def now() -> datetime:
    return datetime.now().astimezone()


def iso(t: datetime) -> str:
    return t.isoformat(timespec="seconds")


def parse_time(s) -> datetime | None:
    try:
        return datetime.fromisoformat(s) if isinstance(s, str) else None
    except ValueError:
        return None


def write_json(path: Path, obj, indent: int | None = 2) -> None:
    """一時ファイルに書いてから入れ替える（読む側に書きかけを見せない）"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent)
        f.write("\n")
    os.replace(tmp, path)


def read_json(path: Path):
    """読めなければ None（壊れたキャッシュや前回の結果で止まらない）"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def append_jsonl(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


class Busy(RuntimeError):
    """ほかの ToolKeeper が実行中"""


@contextmanager
def exclusive(data: Path):
    """<data>/lock を OS のファイルロックで押さえる。取れなければ Busy（LockWatch と同じ作り）。
    落ちたプロセスのロックは OS が外すので、ファイルが残っても止まらない"""
    import msvcrt
    data.mkdir(parents=True, exist_ok=True)
    f = open(data / "lock", "a+b")
    try:
        try:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as e:
            raise Busy(f"ほかの ToolKeeper が実行中です（{data / 'lock'}）") from e
        try:
            yield
        finally:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    finally:
        f.close()


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 (https の決まった URL だけ)
        return r.read()


def fetch(url: str, path: Path, max_age_hours: float, download=_download) -> bytes:
    """url を path に置いて返す。path が max_age_hours より新しければ取り直さない。
    取れなければ古い path を使う（無ければ例外をそのまま上げる）"""
    try:
        age = now() - datetime.fromtimestamp(path.stat().st_mtime).astimezone()
        if age < timedelta(hours=max_age_hours):
            return path.read_bytes()
    except OSError:
        pass
    try:
        body = download(url)
    except Exception:
        if path.is_file():
            return path.read_bytes()
        raise
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(body)
    os.replace(tmp, path)
    return body
