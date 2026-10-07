"""Sonda: estructura del endpoint 'builds' de U.GG (¿2 páginas de runas?)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.champion_scraper_service import ChampionScraperService  # noqa: E402

svc = ChampionScraperService(rank="emerald_plus")
cid = svc.champion_ids.get("aatrox")
url = f"https://stats2.u.gg/lol/1.5/builds/16_17/ranked_solo_5x5/{cid}/1.5.0.json"
resp = svc.session.get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://u.gg/"}, timeout=15)
print("status:", resp.status_code, "bytes:", len(resp.content))
data = resp.json()
print("top keys:", list(data.keys())[:12])
region = data.get("12", {})
bucket_key = next((k for k in ("17", "8", "5") if k in region), None)
bucket = region.get(bucket_key, {})
print("bucket:", bucket_key, "posiciones:", sorted(bucket.keys()))
entry = bucket.get("4")
print("entry tipo:", type(entry).__name__)
if isinstance(entry, list):
    for i, part in enumerate(entry[:6]):
        head = json.dumps(part, ensure_ascii=False)
        print(f"  entry[{i}] {type(part).__name__} :: {head[:300]}")

# Busca recursivamente bloques tipo página de runas (con keystone en [4])
found = []


def walk(node, path="root"):
    if isinstance(node, list):
        if len(node) >= 5 and isinstance(node[2], int) and isinstance(node[3], int) and isinstance(node[4], list):
            found.append((path, node[:5]))
        for i, child in enumerate(node):
            walk(child, f"{path}[{i}]")
    elif isinstance(node, dict):
        for key, child in node.items():
            walk(child, f"{path}.{key}")


walk(bucket, "region")
print("\nbloques tipo página de runas encontrados:", len(found))
for path, page in found[:10]:
    print("  ", path, json.dumps(page, ensure_ascii=False)[:200])
