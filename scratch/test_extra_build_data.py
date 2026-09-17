import requests
import json

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "sec-ch-ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "cross-site",
}

items_data = json.load(open("data/items.json", encoding="utf-8")).get("items", {})

# Summoner Spells map (Summoner spell ID to name in Spanish/English)
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

# Test OP.GG API
url_opgg = "https://lol-api-champion.op.gg/api/global/champions/ranked/aatrox/top"
r = requests.get(url_opgg, headers=headers).json()
opdata = r.get("data", {})

print("OP.GG starter_items:", opdata.get("starter_items"))
print("OP.GG summoner_spells:", opdata.get("summoner_spells"))
print("OP.GG last_items:", opdata.get("last_items"))

# Let's translate starter_items
starters = opdata.get("starter_items", [])
if starters:
    s_ids = starters[0].get("ids", [])
    s_names = [items_data.get(str(i), {}).get("name", str(i)) for i in s_ids]
    print("Translated starters:", s_names)

# Let's translate summoner_spells
spells = opdata.get("summoner_spells", [])
if spells:
    sp_ids = spells[0].get("ids", [])
    sp_names = [SUMMONER_SPELLS.get(i, f"Hechizo {i}") for i in sp_ids]
    print("Translated summoner spells:", sp_names)

# Let's map situational items from last_items
lasts = opdata.get("last_items", [])
situational_ids = []
for entry in lasts:
    for i in entry.get("ids", []):
        sid = str(i)
        if sid in items_data and sid not in situational_ids:
            situational_ids.append(sid)

situational_names = [items_data[sid]["name"] for sid in situational_ids]
print("Situational item candidates:", situational_names[:10])

