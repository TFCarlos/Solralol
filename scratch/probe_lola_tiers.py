import json, urllib.request
CHAMP='aatrox'; LANE='top'
tiers=['e_plus','p_plus','bronze_plus','silver_plus','gold_plus','platinum_plus','diamond_plus','diamond_2_plus','all','iron','unranked','master_plus']
for t in tiers:
    url=f'https://a1.lolalytics.com/mega/?v=1&c={CHAMP}&queue=ranked&region=all&lane={LANE}&patch=16.19&tier={t}&ep=rune'
    try:
        req=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=20) as r:
            d=json.loads(r.read().decode())
        if 'summary' in d:
            s=d['summary']['runes']['pick']['set']
            print(t, 'OK', 'n=', d.get('header',{}).get('n'), 'pri=', s['pri'], 'sec=', s['sec'])
        else:
            print(t, 'BAD', d)
    except Exception as e:
        print(t, 'ERR', e)
