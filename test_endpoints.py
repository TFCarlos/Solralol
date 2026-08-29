import requests

BASE = "http://127.0.0.1:2999"

endpoints = [
    "/help",
    "/liveclientdata/isgameactive",
    "/liveclientdata/activeplayer",
    "/liveclientdata/allgamedata",
    "/liveclientdata/gamestats",
    "/liveclientdata/championstats",
    "/spectator/gameinfo",
]

for ep in endpoints:
    try:
        r = requests.get(f"{BASE}{ep}", timeout=3)
        print(f"{ep:40s} -> {r.status_code}  {len(r.text)} chars")
        if r.status_code == 200:
            print("   Primeras 200 chars:", r.text[:200])
    except Exception as e:
        print(f"{ep:40s} -> ERROR: {e}")