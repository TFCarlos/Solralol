import json, urllib.request, time
base='https://lol-api-champion.op.gg/api/global/champions/ranked/aatrox/top?tier='
valid=[]; invalid=[]
for t in ['IRON','IRON_PLUS','BRONZE','BRONZE_PLUS','SILVER','SILVER_PLUS','GOLD','GOLD_PLUS','PLATINUM','PLATINUM_PLUS','EMERALD','EMERALD_PLUS','DIAMOND','DIAMOND_PLUS','MASTER','MASTER_PLUS','GRANDMASTER','GRANDMASTER_PLUS','CHALLENGER','CHALLENGER_PLUS','EMERALD_PLUS_1','EMERALD_PLUS_2']:
    try:
        req=urllib.request.Request(base+t, headers={'User-Agent':'Mozilla/5.0'})
        j=json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
        p=(j['data']['summary'].get('average_stats') or {}).get('play')
        valid.append((t,p))
    except Exception as e:
        invalid.append((t,str(e)))
    time.sleep(0.12)
print('VALID:', valid)
print('INVALID:', invalid)
