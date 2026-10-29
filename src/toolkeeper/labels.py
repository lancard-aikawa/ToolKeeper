"""check.json の値を人に見せる言葉（CLI の表と画面で同じものを使う）"""

TIER_LABEL = {"A": "A 専用", "B": "B winget", "C": "C winget", "D": "D choco", "E": "E 乗り換え"}
EOL_LABEL = {"ended": "サポート終了", "soon": "もうすぐ終了"}
# 環境変数と PATH（§3.7）
ENV_STATE = {"bad": "切れている", "warn": "注意", "info": "整理できる", "ok": "正しい"}
ENV_KIND = {"var": "変数", "path-missing": "PATH の切れ", "path-dup": "PATH の重複", "path-versioned": "PATH の版",
            "shadow": "2 つある"}
SCOPE_LABEL = {"machine": "マシン", "user": "ユーザー", "": "-"}
# 通信の許可（§3.9）
FW_STATE = {"block": "ブロック", "none": "規則が無い", "gone": "プログラムが無い", "allow": "許可", "off": "無効"}
FW_DIRECTION = {"in": "受信", "out": "送信", "": "-"}


def can_update(it: dict) -> bool:
    """更新のボタンを付けてよいか（区分 A・B で新しい版がある。手で入れた PHP は §7 の乗り換えが先）"""
    return it["tier"] in ("A", "B") and bool(it.get("updatable")) and "manual" not in (it.get("notes") or [])


def note_text(it: dict) -> str:
    parts = []
    if it.get("eol") and it["eol"]["state"] in EOL_LABEL:
        e = it["eol"]
        parts.append(f"{EOL_LABEL[e['state']]} {e['date'] or ''}".strip())
    for n in it.get("notes") or []:
        kind, _, val = n.partition(":")
        parts.append({"manual": "手で入れた物（winget へ乗り換え）", "twin": f"winget でも見えている ({val.split(':', 1)[-1]})",
                      "old": f"古い版 {val} も入っている", "running": f"動いている: {val}",
                      "same": "winget は更新ありと出すが、版の書き方が違うだけで最新",
                      "pinned": f"pin {val} 件" if val else "pin"}.get(kind, n))
    if it.get("packages"):
        parts.append(f"古いパッケージ {it['packages']['outdated']}/{it['packages']['installed']}")
    if it.get("new"):
        parts.insert(0, "新しい")
    return "、".join(parts)
