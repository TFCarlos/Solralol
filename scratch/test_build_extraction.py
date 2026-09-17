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

# U.GG for Briar
url_ugg = "https://stats2.u.gg/lol/1.5/overview/16_18/ranked_solo_5x5/233/1.5.0.json"
r_ugg = requests.get(url_ugg, headers=headers).json()
pd = r_ugg["12"]["10"]["1"][0]

items_dict = json.load(open("data/items.json", encoding="utf-8"))["items"]

print("pd[0]:", pd[0][:5])
print("pd[1] (summoner spells):", pd[1])
print("pd[2] (starting items):", pd[2])
print("pd[3] (core items):", pd[3])
if len(pd) > 7:
    print("pd[7]:", pd[7])
if len(pd) > 8:
    print("pd[8] (boots / shards?):", pd[8])


