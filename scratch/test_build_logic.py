import requests
import json
from pathlib import Path

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

# Helper to check if an item is a finished/valid item (not consumable, not basic component < 800 gold unless boots)
def is_valid_build_item(item_id: str) -> bool:
    item = items_data.get(str(item_id))
    if not item:
        return False
    tags = item.get("tags", [])
    if "Consumable" in tags or "Trinket" in tags or "Lane" in tags:
        return False
    gold = item.get("gold", {}).get("total", 0)
    # Exclude basic component items costing less than 800 gold unless it's upgraded boots or special
    if gold < 800 and "Boots" not in tags:
        return False
    return True

def get_opgg_build(champion_slug: str, role: str):
    url = f"https://lol-api-champion.op.gg/api/global/champions/ranked/{champion_slug}/{role}"
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        return None, None
    opdata = r.json().get("data", {})
    cores = opdata.get("core_items", [])
    boots = opdata.get("boots", [])
    lasts = opdata.get("last_items", [])

    core_ids = [str(i) for i in (cores[0].get("ids", []) if cores else []) if is_valid_build_item(str(i))]
    boot_ids = [str(i) for i in (boots[0].get("ids", []) if boots else []) if is_valid_build_item(str(i))]

    full_ids = []
    # 1. Add core items (up to 3)
    for i in core_ids:
        if i not in full_ids:
            full_ids.append(i)

    # 2. Add boots
    if boot_ids and boot_ids[0] not in full_ids:
        full_ids.append(boot_ids[0])

    # 3. Add late items until 6
    for entry in lasts:
        for i in [str(x) for x in entry.get("ids", [])]:
            if i not in full_ids and is_valid_build_item(i):
                full_ids.append(i)
            if len(full_ids) >= 6:
                break
        if len(full_ids) >= 6:
            break

    core_names = [items_data[i]["name"] for i in core_ids[:3] if i in items_data]
    full_names = [items_data[i]["name"] for i in full_ids[:6] if i in items_data]
    return core_names, full_names

def get_ugg_build(champion_id: int, role: str):
    url = f"https://stats2.u.gg/lol/1.5/overview/16_18/ranked_solo_5x5/{champion_id}/1.5.0.json"
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        return None, None
    data = r.json()
    pos_map = {"jungle": 1, "support": 2, "adc": 3, "top": 4, "mid": 5}
    pos_idx = pos_map.get(role, 5)
    bucket = data.get("12", {}).get("10", {})
    pd = bucket.get(str(pos_idx), [None])[0] or bucket.get(pos_idx, [None])[0]
    if not isinstance(pd, list):
        return None, None

    # Core items: pd[3][2]
    core = pd[3] if len(pd) > 3 else []
    core_ids = [str(i) for i in (core[2] if isinstance(core, list) and len(core) > 2 else []) if is_valid_build_item(str(i))]
    
    full_ids = list(core_ids)
    
    # Check pd[5] choices for late items
    if len(pd) > 5 and isinstance(pd[5], list):
        for slot in pd[5]:
            if isinstance(slot, list):
                for choice in slot:
                    if isinstance(choice, list) and choice:
                        item_id = str(choice[0][0] if isinstance(choice[0], list) else choice[0])
                        if item_id not in full_ids and is_valid_build_item(item_id):
                            full_ids.append(item_id)

    core_names = [items_data[i]["name"] for i in core_ids[:3] if i in items_data]
    full_names = [items_data[i]["name"] for i in full_ids[:6] if i in items_data]
    return core_names, full_names

# Test champions
champs = [
    ("aatrox", 266, "top"),
    ("briar", 233, "jungle"),
    ("ahri", 103, "mid"),
    ("jinx", 222, "adc"),
    ("thresh", 412, "support"),
    ("ksante", 897, "top"),
    ("zed", 238, "mid"),
    ("lux", 99, "support"),
]

for slug, cid, role in champs:
    c_op, f_op = get_opgg_build(slug, role)
    c_ug, f_ug = get_ugg_build(cid, role)
    print(f"\n{slug.upper()} ({role}):")
    print("  OP.GG Core:", c_op)
    print("  OP.GG Full (6):", f_op)
    print("  U.GG  Core:", c_ug)
    print("  U.GG  Full (6):", f_ug)

