import json, time, urllib.request

def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

# champion id -> expected primary lane
checks = [(266, 'top', 'Aatrox'), (64, 'jungle', 'LeeSin'), (222, 'adc', 'Jinx'), (267, 'support', 'Nami'), (103, 'mid', 'Ahri')]
d = get('https://stats2.u.gg/lol/1.5/overview/16_19/ranked_solo_5x5/266/1.5.0.json')
b = d['12']['17']  # emerald+
print('aatrox games per position:', {p: (b[p][0][0] if b.get(p) and b[p] else 0) for p in ['1','2','3','4','5']})
time.sleep(0.4)
for cid, lane, name in [(64,'jungle','LeeSin'), (222,'adc','Jinx'), (267,'support','Nami'), (103,'mid','Ahri')]:
    dd = get(f'https://stats2.u.gg/lol/1.5/overview/16_19/ranked_solo_5x5/{cid}/1.5.0.json')
    bb = dd['12']['17']
    games = {p: (bb[p][0][0] if bb.get(p) and bb[p] else 0) for p in ['1','2','3','4','5']}
    print(name, games, '-> max pos', max(games, key=games.get))
    time.sleep(0.4)
