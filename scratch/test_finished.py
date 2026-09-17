import json

items_data = json.load(open("data/items.json", encoding="utf-8")).get("items", {})

def is_finished_item(item_id: str) -> bool:
    item = items_data.get(str(item_id))
    if not item:
        return False
    tags = item.get("tags", [])
    if "Consumable" in tags or "Trinket" in tags or "Lane" in tags:
        return False
    # Upgraded boots check
    if "Boots" in tags:
        return item.get("gold", {}).get("total", 0) >= 900
    # Finished items do not build into anything (into is empty)
    into = item.get("into", [])
    if into:
        return False
    return item.get("gold", {}).get("total", 0) >= 1500 or "Depth3" in item.get("tags", []) or "Legendary" in item.get("tags", [])

test_items = ["3071", "3031", "1038", "1036", "3076", "3047", "1001", "3036", "6676"]
for i in test_items:
    item = items_data.get(i, {})
    print(f"Item {i} ({item.get('name')}): finished={is_finished_item(i)}, into={item.get('into')}")

