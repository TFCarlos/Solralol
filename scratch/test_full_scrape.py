import sys
sys.path.insert(0, ".")
import json
from pathlib import Path
from app.services.champion_scraper_service import ChampionScraperService

scraper = ChampionScraperService()
champions = json.loads(Path("data/champions_strict.json").read_text(encoding="utf-8"))

# Test on 5 champions: Briar, Aatrox, Ahri, Jinx, Thresh
test_names = ["Briar", "Aatrox", "Ahri", "Jinx", "Thresh"]

for champ in champions:
    if champ.get("character") in test_names:
        updated = scraper.update_champion(champ)
        print(f"\nChampion: {champ.get('character')} (updated={updated})")
        print("  Power Spike Items (Core 3):", champ.get("power_curve_and_scaling", {}).get("power_spike_items"))
        print("  Most Played Build (Full 6):", champ.get("most_played_build"))
        print("  Common Runes count:", len(champ.get("common_runes", [])))
        print("  Matchups counters count:", len(champ.get("matchups", {}).get("counters", [])))

