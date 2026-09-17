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

# 1. U.GG overview
url_ugg = "https://stats2.u.gg/lol/1.5/overview/16_18/ranked_solo_5x5/233/1.5.0.json"
r_ugg = requests.get(url_ugg, headers=headers)
if r_ugg.status_code == 200:
    data = r_ugg.json()
    print("U.GG overview fetched successfully!")
    # pd for jungle (position 1)
    pd = data.get("12", {}).get("10", {}).get("1", [None])[0]
    print("U.GG pd length:", len(pd) if isinstance(pd, list) else None)
    if isinstance(pd, list):
        print("pd[0] (perks):", pd[0][:2] if len(pd) > 0 else None)
        print("pd[1] (summoners):", pd[1] if len(pd) > 1 else None)
        print("pd[2] (starting items):", pd[2] if len(pd) > 2 else None)
        print("pd[3] (core items / item builds):", pd[3] if len(pd) > 3 else None)
        print("pd[4]:", pd[4] if len(pd) > 4 else None)
        print("pd[5]:", pd[5] if len(pd) > 5 else None)
        print("pd[6]:", pd[6] if len(pd) > 6 else None)

# 2. OP.GG champion API
url_opgg = "https://lol-api-champion.op.gg/api/global/champions/ranked/briar/jungle"
r_opgg = requests.get(url_opgg, headers=headers)
if r_opgg.status_code == 200:
    opdata = r_opgg.json().get("data", {})
    print("\nOP.GG data:")
    print("core_items:", opdata.get("core_items")[:2] if opdata.get("core_items") else None)
    print("boots:", opdata.get("boots")[:2] if opdata.get("boots") else None)
    print("last_items:", opdata.get("last_items")[:5] if opdata.get("last_items") else None)

