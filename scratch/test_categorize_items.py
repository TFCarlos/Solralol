import requests
import json

items_data = json.load(open("data/items.json", encoding="utf-8")).get("items", {})

ANTIHEAL_IDS = {"3033", "3075", "3123", "3165", "3076", "3907"}  # Mortal Reminder, Thornmail, Executioner's, Morellonomicon, Bramble, Chempunk

def categorize_item(item_id: str) -> str:
    item = items_data.get(str(item_id), {})
    name = item.get("name", "")
    description = item.get("description", "").lower()
    plaintext = item.get("plaintext", "").lower()
    tags = item.get("tags", [])
    stats = item.get("stats", {})
    
    # 1. Antiheal (corta curas)
    if str(item_id) in ANTIHEAL_IDS or "heridas graves" in description or "grievous wounds" in description:
        return "corta_curas"
    
    # 2. Tanque (Armor / Magic Resist / HP heavy)
    if "Armor" in tags or "SpellBlock" in tags or stats.get("FlatArmorMod", 0) > 0 or stats.get("FlatSpellBlockMod", 0) > 0 or stats.get("FlatHPPoolMod", 0) >= 350:
        if stats.get("FlatPhysicalDamageMod", 0) == 0 and stats.get("FlatMagicDamageMod", 0) == 0:
            return "tanque"
        elif "Armor" in tags or "SpellBlock" in tags:
            return "tanque"
            
    # 3. Asesino / Daño Explosivo (Lethality, ArmorPen, MagicPen, AP Burst)
    if "ArmorPenetration" in tags or "MagicPenetration" in tags or "lethality" in description or stats.get("FlatPhysicalDamageMod", 0) >= 55 or stats.get("FlatMagicDamageMod", 0) >= 80:
        return "asesino"
        
    # 4. Utilidad / Defensa
    if "Active" in tags or "NonSpellDamage" in tags or "MagicResist" in tags or "CooldownReduction" in tags or stats.get("FlatSpellBlockMod", 0) > 0:
        return "utilidad_y_defensa"
        
    return "daño_y_situacional"

# Test categorization on last_items of Aatrox, Briar, Ahri, Jinx
champions = ["aatrox", "briar", "ahri", "jinx"]
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128.0.0.0"}

for champ in champions:
    url = f"https://lol-api-champion.op.gg/api/global/champions/ranked/{champ}/top" if champ == "aatrox" else f"https://lol-api-champion.op.gg/api/global/champions/ranked/{champ}/jungle" if champ == "briar" else f"https://lol-api-champion.op.gg/api/global/champions/ranked/{champ}/mid" if champ == "ahri" else f"https://lol-api-champion.op.gg/api/global/champions/ranked/{champ}/adc"
    r = requests.get(url, headers=headers).json()
    opdata = r.get("data", {})
    lasts = opdata.get("last_items", [])
    
    cats = {"corta_curas": [], "tanque": [], "asesino": [], "utilidad_y_defensa": [], "daño_y_situacional": []}
    for entry in lasts:
        for i in entry.get("ids", []):
            sid = str(i)
            if sid in items_data:
                name = items_data[sid]["name"]
                cat = categorize_item(sid)
                if name not in cats[cat]:
                    cats[cat].append(name)
                    
    print(f"\n{champ.upper()} Situational Categories:")
    for c, items in cats.items():
        if items:
            print(f"  {c}: {items[:4]}")

