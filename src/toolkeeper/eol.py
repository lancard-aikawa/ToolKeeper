"""系列のサポート終了（docs/design.md §3.6）。endoflife.date の製品ごとの JSON を 1 日置いておく"""
import json
import re
from datetime import date, timedelta
from pathlib import Path

from . import store

API = "https://endoflife.date/api/{}.json"
SOON_DAYS = 90


def match(rules: list[dict], winget_id: str) -> tuple[str, str] | None:
    """winget の ID → (製品, 系列)。当てはまる規則が無ければ None"""
    for r in rules:
        m = re.fullmatch(r["id"], winget_id)
        if m:
            return r["product"], m.group(1)
    return None


def state(cycles: list[dict], product: str, cycle: str, today: date) -> dict | None:
    """{product, cycle, date, state, latest, latest_date}。state は ended・soon・ok。系列が載っていなければ None"""
    for c in cycles:
        if str(c.get("cycle")) != cycle:
            continue
        end = c.get("eol")
        when = None
        if isinstance(end, str):
            when = date.fromisoformat(end)
            st = "ended" if when <= today else "soon" if when <= today + timedelta(days=SOON_DAYS) else "ok"
        else:
            st = "ended" if end is True else "ok"
        return {"product": product, "cycle": cycle, "date": when.isoformat() if when else None,
                "state": st, "latest": c.get("latest"), "latest_date": c.get("latestReleaseDate")}
    return None


class Lookup:
    """製品ごとに 1 度だけ取る"""

    def __init__(self, cache: Path, max_age_hours: float, today: date):
        self.cache, self.max_age, self.today = cache, max_age_hours, today
        self._cycles: dict[str, list] = {}

    def get(self, product: str, cycle: str) -> dict | None:
        if product not in self._cycles:
            body = store.fetch(API.format(product), self.cache / f"eol-{product}.json", self.max_age)
            self._cycles[product] = json.loads(body.decode("utf-8"))
        return state(self._cycles[product], product, cycle, self.today)
