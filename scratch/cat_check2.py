import json
root = json.load(open('data/items.json', encoding='utf-8'))
items = root['items'] if isinstance(root, dict) and 'items' in root else root
print('TOTAL', len(items))
for k in ('2138','2139','2140','3123','3033','3036'):
    it = items.get(k) if isinstance(items, dict) else None
    if isinstance(it, dict):
        print(k, '|', it.get('name'), '| gold:', (it.get('gold') or {}).get('total') if isinstance(it.get('gold'), dict) else it.get('gold'), '| into:', it.get('into'), '| from:', it.get('from'), '| tags:', it.get('tags'))
    else:
        print(k, 'NOT FOUND', type(it).__name__)
