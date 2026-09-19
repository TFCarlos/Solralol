import sys
import os
sys.path.insert(0, os.path.abspath("."))

from app.services.draft_analyzer_service import DraftAnalyzerService
from app.services.lcu_service import LCUService

analyzer = DraftAnalyzerService()

print("--- Testing Draft Analyzer Service ---")
my_team = ["Aatrox", "Sejuani", "Ahri", "Jinx", "Lulu"]
enemy_team = ["Darius", "Lee Sin", "Syndra", "Kaisa", "Nautilus"]

my_dmg = analyzer.calculate_team_damage_breakdown(my_team)
en_dmg = analyzer.calculate_team_damage_breakdown(enemy_team)

print(f"My Team Damage Breakdown: {my_dmg}")
print(f"Enemy Team Damage Breakdown: {en_dmg}")

my_curve = analyzer.calculate_team_power_curve(my_team)
en_curve = analyzer.calculate_team_power_curve(enemy_team)

print(f"My Team Power Curve: {my_curve}")
print(f"Enemy Team Power Curve: {en_curve}")

spike = analyzer.analyze_power_spike_phase(my_curve, en_curve)
print(f"Power Spike Window: {spike}")

bans = analyzer.get_recommended_bans("Aatrox", top_n=3)
print("Top 3 Recommended Bans for Aatrox:")
for b in bans:
    print(f" - {b['champion']} (WR: {b['win_rate']}%)")

build = analyzer.get_champion_build("Aatrox", enemy_team)
print("Build for Aatrox vs enemy team:")
print(f" - Items: {build['items']}")
print(f" - Boots: {build.get('boots')} ({build.get('boots_reason')})")
print(" - Situacionales:")
for group in build.get("situational", []):
    print(f"    {group['label']}: {[item['name'] for item in group['items']]}")

runes_spells = analyzer.get_champion_runes_and_summoners("Aatrox", "Top")
print("Runes & Spells for Aatrox (Top):")
print(f" - Page 1: {runes_spells.get('page_1') and runes_spells['page_1'].get('keystone')}")
print(f" - Spells: {runes_spells.get('spells')}")

jgl = analyzer.get_champion_runes_and_summoners("Aatrox", "Jungle")
print(f" - Spells Jungle: {jgl.get('spells')}")

print("\n--- Testing LCU Service Connection Check ---")
lcu = LCUService()
is_conn = lcu.is_connected()
print(f"LCU Connected: {is_conn}")

