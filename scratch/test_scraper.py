import requests

h1 = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "sec-ch-ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "cross-site",
}

# Test stats2.u.gg with chrome sec headers
r1 = requests.get("https://stats2.u.gg/lol/1.5/overview/16_18/ranked_solo_5x5/233/1.5.0.json", headers=h1)
print("status stats2 with sec headers:", r1.status_code)

# Test OP.GG champion API endpoint
r_opgg = requests.get("https://lol-api-champion.op.gg/api/euw/champions/ranked/briar/jungle", headers=h1)
print("status OP.GG api:", r_opgg.status_code)
if r_opgg.status_code == 200:
    print("OP.GG keys:", list(r_opgg.json().get("data", {}).keys()))

