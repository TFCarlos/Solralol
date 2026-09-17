import json
d = json.load(open('data/items.json', encoding='utf-8'))
print('ROOT keys:', list(d.keys())[:10])
items = d.get('items', d.get('data', {}))
print('total items:', len(items))
for iid in ('2138','2139','2140','3123','3033'):
    it = items.get(str(iid)) or {}
    print(iid, '|', it.get('name'), '| gold:', (it.get('gold') or {}).get('total'), '| into:', it.get('into'), '| from:', it.get('from'), '| tags:', it.get('tags'))
