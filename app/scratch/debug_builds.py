"""Depura por qué _builds no devuelve datos."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.champion_scraper_service import ChampionScraperService  # noqa: E402

svc = ChampionScraperService(rank="emerald_plus")
cid = svc.champion_ids.get("aatrox")
print("patches:", svc._patches())
import json  # noqa: E402

local = json.loads((svc.champions_path.parent / "champion_catalog.json").read_text(encoding="utf-8")).get("version", "")
print("local_version:", local)
builds = svc._builds(cid)
print("_builds ->", None if builds is None else f"dict[{len(builds)}]")
if builds is not None:
    pages = svc._ugg_rune_pages(builds, "top", [5008, 5008, 5001])
    print("páginas:", json.dumps(pages, ensure_ascii=False)[:600])
