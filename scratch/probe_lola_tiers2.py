import json, urllib.request, time
CHAMP='aatrox'; LANE='top'
tiers=['e_plus','p_plus','emerald_plus','bronze_plus','silver_plus','bronze','silver','iron_plus','emerald','platinum','diamond','master','grandmaster','challenger','challenger_plus','master_plus','grandmaster_plus','gold','d_plus','e_','gold_']
for t in tiers:
    url=f'https://a1.lolalytics.com/mega/?v=1&c={CHAMP}&queue=ranked&region=all&lane={LANE}&patch=16.19&tier={t}&ep=rune'
    try:
        req=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=20) as r:
            d=json.loads(r.read().decode())
        if 'summary' in d:
            print(t, 'OK n=', d.get('header',{}).get('n'))
        else:
            print(t, 'BAD', d)
    except Exception as e:
        print(t, 'ERR', e)
    time.sleep(0.3)
