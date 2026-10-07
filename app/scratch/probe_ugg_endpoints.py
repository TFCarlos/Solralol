"""Sonda: busca endpoints de U.GG con 2 páginas de runas (popular + winrate)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.champion_scraper_service import ChampionScraperService  # noqa: E402

svc = ChampionScraperService(rank="emerald_plus")
cid = svc.champion_ids.get("aatrox")
patch = "16_17"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Referer": "https://u.gg/",
}

candidates = [
    f"https://stats2.u.gg/lol/1.5/overview/{patch}/ranked_solo_5x5/{cid}/1.5.0.json",
    f"https://stats2.u.gg/lol/1.5/runes/{patch}/ranked_solo_5x5/{cid}/1.5.0.json",
    f"https://stats2.u.gg/lol/1.5/rune/{patch}/ranked_solo_5x5/{cid}/1.5.0.json",
    f"https://stats2.u.gg/lol/1.5/builds/{patch}/ranked_solo_5x5/{cid}/1.5.0.json",
    f"https://stats2.u.gg/lol/1.5/champion/{patch}/ranked_solo_5x5/{cid}/1.5.0.json",
    f"https://stats2.u.gg/lol/1.5/overview/{patch}/ranked_solo_5x5/{cid}/1.6.0.json",
    f"https://stats2.u.gg/lol/1.5/overview/{patch}/ranked_solo_5x5/{cid}/1.5.1.json",
]

for url in candidates:
    try:
        resp = svc.session.get(url, headers=headers, timeout=12)
        body = resp.text[:160].replace("\n", " ")
        keys = ""
        if resp.status_code == 200:
            try:
                data = resp.json()
                keys = str(list(data.keys())[:8]) if isinstance(data, dict) else f"list[{len(data)}]"
            except ValueError:
                keys = "no-json"
        print(f"{resp.status_code} {url.split('/lol/1.5/')[-1]} :: {keys or body}")
    except Exception as exc:  # noqa: BLE001
        print(f"ERR {url} :: {exc}")
    time.sleep(0.5)
