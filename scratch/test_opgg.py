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

champions = [("aatrox", "top"), ("briar", "jungle"), ("ahri", "mid"), ("ezreal", "adc"), ("thresh", "support"), ("ksante", "top")]
items_dict = json.load(open("data/items.json", encoding="utf-8"))["items"]

for champ, role in champions:
    url = f"https://lol-api-champion.op.gg/api/global/champions/ranked/{champ}/{role}"
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        opdata = r.json().get("data", {})
        cores = opdata.get("core_items", [])
        boots = opdata.get("boots", [])
        lasts = opdata.get("last_items", [])

        core_ids = cores[0].get("ids", []) if cores else []
        boot_id = boots[0].get("ids", [None])[0] if boots else None
        
        full_build_ids = []
        # 1. Add core items (usually 3 items)
        for item_id in core_ids:
            if item_id not in full_build_ids:
                full_build_ids.append(item_id)
        # 2. Add boots
        if boot_id and boot_id not in full_build_ids:
            full_build_ids.append(boot_id)
        # 3. Add last items until we have 6 items
        for entry in lasts:
            for item_id in entry.get("ids", []):
                if item_id not in full_build_ids and str(item_id) in items_dict:
                    # Ignore consumable items or starter items if any
                    tags = items_dict.get(str(item_id), {}).get("tags", [])
                    if "Consumable" not in tags and "Trinket" not in tags:
                        full_build_ids.append(item_id)
                if len(full_build_ids) >= 6:
                    break
            if len(full_build_ids) >= 6:
                break
        
        full_build_names = [items_dict[str(i)]["name"] for i in full_build_ids if str(i) in items_dict]
        print(f"\n{champ.capitalize()} ({role}):")
        print("  Core items:", [items_dict[str(i)]["name"] for i in core_ids if str(i) in items_dict])
        print("  Full build (6 items):", full_build_names)
    else:
        print(f"\n{champ.capitalize()} error:", r.status_code)

