import json
def dump(src,dst,limit=None):
    t=open(src,encoding='utf-8').read().splitlines()
    if limit: t=t[:limit]
    open(dst,'w',encoding='utf-8',newline='\n').write('\n'.join(t))
    print(dst,len(t))
dump('app/services/live_recommendation_service.py','scratch/focus_svc.txt')
dump('app/ui/recommendation_panel.py','scratch/focus_pnl.txt')
dump('scratch/test_live_recommendations.py','scratch/focus_tst.txt',160)
try:
    root=json.load(open('data/items.json',encoding='utf-8'))
    data=root.get('data',root)
    lines=[]
    for k in ['2138','2139','2140','3123','3033','3046','3026']:
        it=data.get(k) if isinstance(data,dict) else None
        if isinstance(it,dict):
            g=it.get('gold'); tot=g.get('total') if isinstance(g,dict) else g
            lines.append('%s :: %s :: total=%s :: into=%s :: from=%s' % (k,it.get('name'),tot,it.get('into'),it.get('from')))
    open('scratch/focus_cat.txt','w',encoding='utf-8',newline='\n').write('\n'.join(lines))
    print('focus_cat',len(lines))
except Exception as e:
    print('cat error',e)
