from app.services.live_player_metrics_service import build_inventory_report, build_inventory_value

ROLES = ('TOP', 'JUNGLE', 'MIDDLE', 'BOTTOM', 'UTILITY')
CATALOG = {'1001': {'gold': {'total': 300}, 'tags': ['Boots']},
           '1028': {'gold': {'total': 400}, 'tags': []},
           '3001': {'gold': {'total': 1000}, 'tags': [], 'from': ['1028']},
           '3340': {'gold': {'total': 0}, 'tags': ['Trinket']},
           '2003': {'gold': {'total': 50}, 'tags': ['Consumable']}}


def player(team, role, items):
    return {'team': team, 'position': role, 'championName': role,
            'items': [{'itemID': item, 'count': 1} for item in items]}


def test_inventory_report_uses_current_owned_full_prices_and_complete_pairs():
    allies = [player('ORDER', role, ['1001', '3001', '3340']) for role in ROLES]
    enemies = [player('CHAOS', role, ['1001', '1028', '2003']) for role in reversed(ROLES)]
    snapshot = {'local_team': 'ORDER', 'all_players': enemies + allies}
    report = build_inventory_report(snapshot, CATALOG)
    assert [row['role'] for row in report['lanes']] == list(ROLES)
    assert [row['delta'] for row in report['lanes']] == [600] * 5
    assert report['team']['delta'] == 3000
    allies[0]['items'] = [{'itemID': '1028', 'count': 1}]
    updated = build_inventory_report(snapshot, CATALOG)
    assert updated['lanes'][0]['delta'] == -300
    assert updated['team']['delta'] == 2100


def test_unknown_or_duplicate_role_does_not_fabricate_pair_or_total():
    allies = [player('ORDER', role, []) for role in ROLES]
    enemies = [player('CHAOS', role, []) for role in ROLES]
    enemies[-1]['position'] = 'TOP'
    report = build_inventory_report({'local_team': 'ORDER', 'all_players': allies + enemies}, CATALOG)
    assert report['lanes'][0]['delta'] is None
    assert report['lanes'][-1]['delta'] is None
    assert report['team']['delta'] is None
    assert report['lanes'][1]['delta'] == 0


def test_missing_price_is_unavailable_not_zero():
    assert build_inventory_value(player('ORDER', 'TOP', ['9999']), CATALOG) is None
    assert build_inventory_value(player('ORDER', 'TOP', []), CATALOG) == 0
