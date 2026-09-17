import json
root = json.load(open('data/items.json', encoding='utf-8'))
data = root.get('data', root)
for iid in ['2138','2139','2140','2137','3123','3033','6694','3006']:
    it = data.get(iid)
    if it:
        print(iid, '|', it.get('name'), '| gold:', it.get('gold',{}).get('total'), '| into:', it.get('into'), '| from:', it.get('from'), '| tags:', it.get('tags'))
    else:
        print(iid, 'NO ESTA')
