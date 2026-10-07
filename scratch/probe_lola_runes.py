"""Sonda: esquema JSON de Lolalytics ep=rune por tier (para mapear a páginas de runas)."""
import json
import urllib.request
from pathlib import Path

CHAMP = "aatrox"
LANE = "top"
OUT = Path(__file__).parent


def fetch(tier: str) -> dict:
    url = (f"https://a1.lolalytics.com/mega/?v=1&c={CHAMP}&queue=ranked&region=all"
           f"&lane={LANE}&patch=16.19&tier={tier}&ep=rune")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def shape(obj, depth=0, max_depth=4):
    pad = "  " * depth
    if depth >= max_depth:
        return pad + "..."
    if isinstance(obj, dict):
        lines = [pad + "{"]
        for k, v in list(obj.items())[:25]:
            lines.append(f"{pad}  {k!r}: " + shape(v, depth + 1, max_depth).lstrip())
        lines.append(pad + "}")
        return "\n".join(lines)
    if isinstance(obj, list):
        if not obj:
            return pad + "[]"
        return (f"{pad}[len={len(obj)}] first: " +
                shape(obj[0], depth + 1, max_depth).lstrip())
    return pad + repr(obj)


for tier in ("emerald_plus", "bronze_plus"):
    try:
        data = fetch(tier)
    except Exception as exc:  # noqa: BLE001
        print(tier, "ERROR", exc)
        continue
    (OUT / f"lola_rune_{tier}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=" * 30, tier, "=" * 30)
    print("top keys:", list(data.keys()))
    print(shape(data))
    print()
