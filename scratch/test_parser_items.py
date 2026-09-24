import json
import re

desc_es = "<mainText><stats><attention>35</attention> de daño de ataque<br><attention>35%</attention> de penetración de armadura<br><attention>25%</attention> de probabilidad de impacto crítico</stats><br><br><li><passive>Verdugo de gigantes:</passive> Infliges hasta un 15% de daño físico adicional a campeones con más vida máxima que tú (máximo con 1500 más de vida).</li></mainText>"
desc_en = "<mainText><stats><attention>35</attention> Attack Damage<br><attention>35%</attention> Armor Penetration<br><attention>25%</attention> Critical Strike Chance</stats><br><br><li><passive>Giant Slayer:</passive> Deal up to 15% bonus physical damage against champions with greater max Health than you (maxed at 1500 max Health difference).</li></mainText>"

def extract_header_stats(desc_es: str, desc_en: str) -> dict[str, int | float]:
    stats = {}
    stats_blocks = []
    for d in (desc_es, desc_en):
        m = re.search(r"<stats>(.*?)</stats>", d, re.DOTALL | re.IGNORECASE)
        if m:
            clean_text = re.sub(r"<[^>]+>", " ", m.group(1))
            stats_blocks.append(clean_text)
    
    combined_stats_text = " ".join(stats_blocks)

    patterns = {
        "attack_damage": r"(\d+)\s*(?:Attack Damage|de da[ñn]o de ataque)",
        "ability_power": r"(\d+)\s*(?:Ability Power|de poder de habilidad)",
        "health": r"(\d+)\s*(?:Health|de vida)",
        "armor": r"(\d+)\s*(?:Armor|de armadura)",
        "magic_resistance": r"(\d+)\s*(?:Magic Resist(?:ance)?|resistencia m[áa]gica)",
        "ability_haste": r"(\d+)\s*(?:Ability Haste|velocidad de habilidades|aceleraci[óo]n de habilidad)",
        "lethality": r"(\d+)\s*(?:Lethality|letalidad)",
        "armor_penetration_percent": r"(\d+)%\s*(?:Armor Penetration|penetraci[óo]n de armadura)",
        "magic_penetration_percent": r"(\d+)%\s*(?:Magic Penetration|penetraci[óo]n m[áa]gica)",
        "magic_penetration_flat": r"(\d+)\s*(?:Magic Penetration|penetraci[óo]n m[áa]gica)",
        "critical_strike_chance_percent": r"(\d+)%\s*(?:Critical Strike Chance|probabilidad de impacto cr[íi]tico)",
        "attack_speed_percent": r"(\d+)%\s*(?:Attack Speed|velocidad de ataque)",
        "life_steal_percent": r"(\d+)%\s*(?:Life Steal|robo de vida)",
        "omnivamp_percent": r"(\d+)%\s*(?:Omnivamp|omnivampirismo)",
        "heal_and_shield_power_percent": r"(\d+)%\s*(?:Heal and Shield Power|curaci[óo]n y escudos)",
        "movement_speed_percent": r"(\d+)%\s*(?:Movement Speed|velocidad de movimiento)",
        "base_health_regeneration_percent": r"(\d+)%\s*(?:Base Health Regen|regeneraci[óo]n de vida b[áa]sica)",
        "base_mana_regeneration_percent": r"(\d+)%\s*(?:Base Mana Regen|regeneraci[óo]n de man[áa] b[áa]sica)",
        "tenacity": r"(\d+)%\s*(?:Tenacity|tenacidad)",
    }

    for stat_key, pat in patterns.items():
        m = re.search(pat, combined_stats_text, re.IGNORECASE)
        if m:
            stats[stat_key] = int(m.group(1))

    return stats

res = extract_header_stats(desc_es, desc_en)
print("Clean Lord Dominik stats:", res)

