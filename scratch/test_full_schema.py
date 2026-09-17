import sys
sys.path.insert(0, ".")
import requests
import json
from app.services.champion_scraper_service import ChampionScraperService

scraper = ChampionScraperService()
items_data = scraper.items_data

SUMMONER_SPELLS = {
    1: "Purificar",
    3: "Extenuación",
    4: "Destello",
    6: "Fantasmal",
    7: "Curación",
    11: "Aplastar",
    12: "Teleportación",
    14: "Ignición",
    21: "Barrera",
}

ANTIHEAL_IDS = {"3033", "3075", "3123", "3165", "3076", "3907", "3074"}

def categorize_item(item_id: str) -> str:
    item = items_data.get(str(item_id), {})
    description = item.get("description", "").lower()
    tags = item.get("tags", [])
    stats = item.get("stats", {})
    
    if str(item_id) in ANTIHEAL_IDS or "heridas graves" in description or "grievous wounds" in description:
        return "corta_curas"
    if "Armor" in tags or "SpellBlock" in tags or stats.get("FlatArmorMod", 0) > 0 or stats.get("FlatSpellBlockMod", 0) > 0 or stats.get("FlatHPPoolMod", 0) >= 350:
        return "tanque"
    if "ArmorPenetration" in tags or "MagicPenetration" in tags or "lethality" in description or stats.get("FlatPhysicalDamageMod", 0) >= 50 or stats.get("FlatMagicDamageMod", 0) >= 70:
        return "asesino"
    return "utilidad_y_defensa"

champions = json.load(open("data/champions_strict.json", encoding="utf-8"))
sample_champs = ["Briar", "Aatrox", "Ahri", "Jinx", "Thresh"]

for champ in champions:
    if champ.get("character") in sample_champs:
        name = champ.get("character")
        role = scraper._role(champ)
        slug = scraper._slug(name)
        
        # Test fetching OP.GG extra data
        url = f"https://lol-api-champion.op.gg/api/global/champions/ranked/{slug}/{role}"
        r = requests.get(url, headers=scraper.session.headers).json()
        opdata = r.get("data", {})
        
        # Starters
        starters = opdata.get("starter_items", [])
        starter_names = []
        if starters and isinstance(starters, list):
            s_ids = starters[0].get("ids", [])
            starter_names = [items_data.get(str(i), {}).get("name", str(i)) for i in s_ids if str(i) in items_data]
        if not starter_names:
            starter_names = ["Espada de Doran", "Poción de vida"] if role != "support" else ["Escudo de la reliquia", "Poción de vida"]

        # Summoner spells
        spells = opdata.get("summoner_spells", [])
        spell_names = []
        if spells and isinstance(spells, list):
            sp_ids = spells[0].get("ids", [])
            spell_names = [SUMMONER_SPELLS.get(i, f"Hechizo {i}") for i in sp_ids if i in SUMMONER_SPELLS]
        if not spell_names:
            spell_names = ["Destello", "Aplastar"] if role == "jungle" else ["Destello", "Teleportación"]

        # Situational items
        lasts = opdata.get("last_items", [])
        situational = {"corta_curas": [], "tanque": [], "asesino": [], "utilidad_y_defensa": []}
        for entry in (lasts if isinstance(lasts, list) else []):
            if isinstance(entry, dict):
                for i in entry.get("ids", []):
                    sid = str(i)
                    if scraper._is_finished_item(sid) and sid in items_data:
                        item_name = items_data[sid]["name"]
                        cat = categorize_item(sid)
                        if item_name not in situational[cat] and len(situational[cat]) < 4:
                            situational[cat].append(item_name)
                            
        champ["starter_items"] = starter_names
        champ["summoner_spells"] = spell_names
        champ["situational_items"] = situational
        
        print(f"\n{name} ({role}):")
        print("  Starter items:", champ["starter_items"])
        print("  Summoner spells:", champ["summoner_spells"])
        print("  Situational items:", champ["situational_items"])

