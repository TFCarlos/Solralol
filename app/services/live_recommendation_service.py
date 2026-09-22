"""Deterministic, offline LIVE advice. Never assumes vision, cooldowns or shop access."""
from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from _paths import DATA_DIR
from app.services.synergy_recommendation_service import SynergyRecommendationService


def number(value, default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def canonical(value):
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().lower())


def item_ids(values):
    result = []
    for value in values if isinstance(values, list) else []:
        if isinstance(value, dict):
            count = max(1, min(6, int(number(value.get("count", 1), 1))))
            value = value.get("itemID", value.get("id"))
        else:
            count = 1
        ident = int(number(value))
        if ident > 0:
            result.extend([str(ident)] * count)
    return result


@lru_cache(maxsize=1)
def load_knowledge():
    root = DATA_DIR
    def read(name):
        try:
            value = json.loads((root / name).read_text(encoding="utf-8"))
            return value if isinstance(value, list) else []
        except (OSError, ValueError):
            return []
    champions = {canonical(p.get("character")): p for p in read("champions_strict.json") if isinstance(p, dict)}
    items = {str(p.get("id")): p for p in read("legendary_items_strict.json") if isinstance(p, dict)}
    return champions, items


class LiveRecommendationService:
    """Scores independent alternatives, not an automatically executable six-item build."""

    HEALERS = {"aatrox", "briar", "drmundo", "fiddlesticks", "irelia", "kayn", "maokai",
               "nami", "nilah", "samira", "senna", "sona", "soraka", "swain", "sylas",
               "taric", "vladimir", "warwick", "yuumi", "zac"}
    GROUPS = (
        {"3006", "3009", "3020", "3047", "3111", "3117", "3158", "3005", "3008", "3010"},
        {"3053", "3156", "6673", "3040"},
        {"3074", "3748", "6698", "6631"},
        {"3033", "3036", "6694", "3071"},
        {"3078", "3100", "6662"},
        {"3003", "3040", "3004", "3042", "3119", "3121"},
        {"3135", "3137"},
    )
    ANTIHEAL = {"3033", "3075", "3165", "3123", "3076", "3916"}
    RESPONSES = {
        "healing": {"3033", "3075", "3165"},
        "armor": {"3033", "3036", "3071", "6694"},
        "mr": {"3135", "3137"},
        "health": {"3153", "6653"},
        "cc": {"3111", "3139", "3222"},
        "crit": {"3143"},
    }
    LABELS = {"healing": "Curación", "armor": "Armadura acumulada", "mr": "Resistencia mágica",
              "health": "Vida acumulada", "cc": "Control", "crit": "Crítico", "physical": "Daño físico",
              "magic": "Daño mágico"}

    def __init__(self, catalog=None, champions=None, strict_items=None):
        known_champions, known_items = load_knowledge()
        self.champions = champions if champions is not None else known_champions
        self.strict = strict_items if strict_items is not None else known_items
        raw = catalog or {}
        raw = raw.get("items", raw.get("data", raw))
        self.catalog = {str(k): v for k, v in raw.items() if isinstance(v, dict)}
        self.synergy = SynergyRecommendationService()

    def profile(self, name):
        return self.champions.get(canonical(name), {})

    def stat(self, ident, key):
        aliases = {
            "armor": "FlatArmorMod", "magic_resistance": "FlatSpellBlockMod",
            "health": "FlatHPPoolMod", "attack_damage": "FlatPhysicalDamageMod",
            "ability_power": "FlatMagicDamageMod", "mana": "FlatMPPoolMod",
            "critical_strike_chance_percent": "FlatCritChanceMod",
            "life_steal_percent": "PercentLifeStealMod",
        }
        stats = self.catalog.get(ident, {}).get("stats", {})
        value = number(stats.get(aliases.get(key, key)))
        if key in {"critical_strike_chance_percent", "life_steal_percent"} and 0 < value <= 1:
            value *= 100
        return value or number(self.strict.get(ident, {}).get("stats", {}).get(key))

    def name(self, ident):
        return str(self.catalog.get(ident, {}).get("name", f"Objeto {ident}"))

    def cost(self, ident):
        return max(0, int(number(self.catalog.get(ident, {}).get("gold", {}).get("total"))))

    def available(self, ident, map_id="11"):
        item = self.catalog.get(ident, {})
        return (bool(item) and item.get("gold", {}).get("purchasable") is True
                and self.cost(ident) > 0 and item.get("maps", {}).get(str(map_id), True)
                and not item.get("requiredAlly") and not item.get("requiredChampion")
                and not item.get("inStore") is False)

    def compatible(self, ident, owned):
        if ident in owned:
            return False
        return not any(ident in group and any(i in group for i in owned) for group in self.GROUPS)

    def _recipe(self, target, owned):
        """Remaining gold and consumed components, with multiset accounting and cycle guard."""
        pool = Counter(owned)
        consumed = Counter()
        def visit(ident, ancestors):
            if ident in ancestors:
                return 0
            if pool[ident]:
                pool[ident] -= 1
                consumed[ident] += 1
                return self.cost(ident)
            children = item_ids(self.catalog.get(ident, {}).get("from", []))
            credit = sum(visit(c, ancestors | {ident}) for c in children)
            return min(self.cost(ident), credit)
        credit = visit(target, set())
        return max(0, self.cost(target) - credit), consumed

    def purchase(self, target, owned, gold, map_id="11"):
        """A single feasible buy; never claims an unaffordable component is buyable."""
        slots = sum(1 for i in owned if "Trinket" not in self.catalog.get(i, {}).get("tags", []))
        candidates = []
        pool = Counter(owned)

        def walk(ident, ancestors):
            if ident in ancestors:
                return 0, 0
            if pool[ident]:
                pool[ident] -= 1
                return self.cost(ident), 1
            credit, consumed = 0, 0
            for child in item_ids(self.catalog.get(ident, {}).get("from", [])):
                value, count = walk(child, ancestors | {ident})
                credit += value
                consumed += count
            remaining = max(0, self.cost(ident) - credit)
            if self.available(ident, map_id) and remaining > 0:
                fits = slots - consumed + 1 <= 6 or ident in {"2138", "2139", "2140"}
                candidates.append((ident, remaining, fits))
            return min(self.cost(ident), credit), consumed

        walk(target, set())
        remaining, _ = self._recipe(target, owned)
        possible = [c for c in candidates if c[2] and gold is not None and c[1] <= gold]
        if possible:
            chosen = next((c for c in possible if c[0] == target), max(possible, key=lambda c: (c[1], c[0])))
            return {"status": "buy", "id": chosen[0], "cost": chosen[1], "target": target,
                    "remaining": remaining, "text": "Asequible al volver a la tienda; no implica que estés en base."}
        fits = [c for c in candidates if c[2]]
        if not fits:
            return {"status": "full", "target": target, "remaining": remaining,
                    "text": "Inventario lleno: no compres ni vendas automáticamente. Revisa un hueco o completa un objeto."}
        cheapest = min(fits, key=lambda c: (c[1], c[0]))
        return {"status": "unknown" if gold is None else "save", "target": target,
                "id": cheapest[0], "cost": cheapest[1], "remaining": remaining,
                "missing": None if gold is None else max(0, cheapest[1] - gold),
                "text": "Oro actual no disponible: no se puede confirmar la compra." if gold is None
                else f"Ahorra {max(0, cheapest[1] - gold):,} de oro para {self.name(cheapest[0])}."}

    @staticmethod
    def latest(session):
        players = {k: dict(p) for k, p in session.get("players", {}).items() if isinstance(p, dict)}
        times = {}
        for snap in session.get("snapshots", []):
            if not isinstance(snap, dict):
                continue
            t = number(snap.get("time"))
            for key, point in snap.get("players", {}).items():
                if isinstance(point, dict) and t >= times.get(key, -1):
                    players.setdefault(key, {}).update(point)
                    times[key] = t
        return players, times

    def inventory_summary(self, player):
        """Compact observed-item facts, independent of estimated kit threats."""
        known = isinstance(player.get("items"), list)
        ids = item_ids(player.get("items"))
        missing = [i for i in ids if i not in self.catalog or
                   number(self.catalog[i].get("gold", {}).get("total"), None) is None]
        value = sum(self.cost(i) for i in ids)
        badges = []
        for kind, label, stat, threshold in (
            ("armor", "Armadura", "armor", 1),
            ("mr", "Res. mágica", "magic_resistance", 1),
            ("crit", "Crítico", "critical_strike_chance_percent", 1),
            ("lifesteal", "Robo de vida", "life_steal_percent", 1),
            ("health", "Vida alta", "health", 1000),
        ):
            amount = sum(self.stat(i, stat) for i in ids)
            if amount >= threshold:
                unit = "%" if kind in {"crit", "lifesteal"} else ""
                badges.append({"kind": kind, "label": label,
                               "detail": f"{amount:g}{unit} en objetos observados; no incluye estadísticas base ni runas."})
        antiheal = sorted(set(ids) & self.ANTIHEAL)
        if antiheal:
            badges.insert(0, {"kind": "antiheal", "label": "Cortacura",
                             "detail": "Heridas graves: " + ", ".join(self.name(i) for i in antiheal) +
                             ". Su aplicación depende del objeto; no indica que el efecto esté activo."})
        return {"known": known, "value": value if known else None,
                "partial": bool(missing), "badges": badges}

    @staticmethod
    def _mark_strength(rows):
        """Compare rivals with complete observations; ties remain explicit."""
        for row in rows:
            row["strength_label"] = ""
        measurable = [r for r in rows if r["strength"] is not None]
        if len(measurable) < 2:
            return
        highest = max(r["strength"] for r in measurable)
        lowest = min(r["strength"] for r in measurable)
        if highest == lowest:
            for row in measurable:
                row["strength_label"] = "FUERZA SIMILAR"
            return
        for score, label in ((highest, "MÁS FUERTE"), (lowest, "MÁS DÉBIL")):
            tied = sum(r["strength"] == score for r in measurable) > 1
            for row in measurable:
                if row["strength"] == score:
                    row["strength_label"] = label + (" · EMPATE" if tied else "")


    def _threats(self, enemies, now, times):
        rows = []
        for key, player in enemies.items():
            champ = str(player.get("champion_name", "?"))
            profile = self.profile(champ)
            ids = item_ids(player.get("items", []))
            signals = []
            # Inventory stats are observable; kit information is explicitly a profile estimate.
            for kind, stat, threshold in (("armor", "armor", 90), ("mr", "magic_resistance", 70),
                                           ("health", "health", 1000), ("crit", "critical_strike_chance_percent", 40)):
                amount = sum(self.stat(i, stat) for i in ids)
                if amount >= threshold:
                    signals.append({"kind": kind, "evidence": f"{amount:g} de {self.LABELS[kind].lower()} en objetos", "observed": True})
            healing_items = [i for i in ids if self.stat(i, "life_steal_percent") >= 7]
            if canonical(champ) in self.HEALERS or healing_items:
                signals.append({"kind": "healing", "evidence": "Robo de vida en inventario" if healing_items else "Sustain del kit (perfil, no curación medida)", "observed": bool(healing_items)})
            cc = number(profile.get("map_and_control", {}).get("crowd_control"))
            if cc >= 7:
                signals.append({"kind": "cc", "evidence": f"Control del perfil: {cc:g}/10; no indica habilidades disponibles", "observed": False})
            damage = profile.get("damage_breakdown", {})
            physical = number(damage.get("physical_damage_percent"))
            magic = number(damage.get("magic_damage_percent"))
            if not physical and not magic:
                damage_type = profile.get("basic_info", {}).get("damage_type", "")
                physical, magic = (80, 20) if damage_type == "AD" else (20, 80) if damage_type == "AP" else (50, 50)
            # AP/AD investments can alter a profile's expected damage orientation.
            ad = sum(self.stat(i, "attack_damage") for i in ids)
            ap = sum(self.stat(i, "ability_power") for i in ids)
            if ap >= 200 and ad < 60:
                physical, magic = 20, 80
            elif ad >= 160 and ap < 60:
                physical, magic = 80, 20
            weight = 1 + min(1.5, max(0, number(player.get("kills")) - number(player.get("deaths"))) * .15)
            inventory = self.inventory_summary(player)
            stale = key not in times or now - times[key] > 30
            level = number(player.get("level"), None)
            kda = [number(player.get(k), None) for k in ("kills", "deaths", "assists")]
            reliable = (inventory["known"] and not inventory["partial"]
                        and level is not None and level >= 1
                        and all(v is not None and v >= 0 for v in kda))
            # Item investment and levels dominate; KDA is only a bounded adjustment.
            strength = (round(inventory["value"] / 1000 + level * .6
                              + max(-2, min(2, (kda[0] + kda[2] * .3 - kda[1]) * .15)), 2)
                        if reliable else None)
            rows.append({"key": key, "champion": champ, "items": ids, "signals": signals,
                         "inventory": inventory, "level": int(level or 0), "strength": strength,
                         "physical": physical, "magic": magic, "weight": weight,
                         "kda": f"{int(number(player.get('kills')))}/{int(number(player.get('deaths')))}/{int(number(player.get('assists')))}",
                         "stale": stale})
        self._mark_strength(rows)
        return sorted(rows, key=lambda r: (r["strength"] is None, -(r["strength"] or 0), r["champion"], r["key"]))

    def analyze(self, session: dict[str, Any]):
        session = session or {}
        players, times = self.latest(session)
        local_key = session.get("local_player_key")
        local = players.get(local_key, {})
        champ = str(local.get("champion_name") or session.get("champion_name") or "Campeón")
        profile = self.profile(champ)
        team = local.get("team") or session.get("local_team")
        enemies, allies = {}, {}
        for key, p in players.items():
            if key == local_key:
                continue
            side = p.get("side")
            if side == "enemy" or (side != "ally" and team and p.get("team") and p["team"] != team):
                enemies[key] = p
            elif side == "ally" or (team and p.get("team") == team):
                allies[key] = p
        now = max(number(session.get("duration")), max(times.values(), default=0))
        ended = bool(session.get("ended_at") or session.get("final_sync", {}).get("status") == "synced")
        gold = next((number(local[k], None) for k in ("current_gold", "currentGold", "goldCurrent")
                     if local.get(k) is not None and number(local[k], None) is not None), None)
        gold = max(0, int(gold)) if gold is not None else None
        owned = item_ids(local.get("items", []))
        threats = self._threats(enemies, now, times)
        phase = "Inicio" if now < 900 else "Medio juego" if now < 1800 else "Juego tardío"
        warnings = ["Orientación heurística, no probabilidad de victoria. Sin visión, posiciones ni enfriamientos fiables."]
        if not profile:
            warnings.append("Campeón sin perfil específico: no se inventa una build genérica.")
        if not local:
            warnings.append("Jugador local no identificado: compras desactivadas.")
        if gold is None:
            warnings.append("Oro disponible desconocido; el oro estimado acumulado no se usa para comprar.")
        if not enemies:
            warnings.append("Sin rivales identificados: faltan datos para contramedidas.")
        if any(t["stale"] for t in threats):
            warnings.append("Hay inventarios sin snapshot reciente (>30 s); confirma las amenazas antes de adaptar.")
        if session.get("game_version") and isinstance(session.get("game_version"), str):
            warnings.append(f"Partida: {session['game_version']}. El catálogo configurado puede pertenecer a otro parche.")
        map_id = "12" if session.get("game_mode") == "ARAM" else "11"
        threat_kinds = {s["kind"] for t in threats for s in t["signals"]}
        physical = sum(t["physical"] * t["weight"] for t in threats)
        magic = sum(t["magic"] * t["weight"] for t in threats)
        total = max(physical + magic, 1)
        physical_share = physical / total
        recommendations = self._rank(profile, champ, owned, threats, physical_share, map_id) if profile and local else []
        purchases = self._purchases(owned, map_id, profile, champ, threats, physical_share)
        for rec in recommendations + purchases:
            rec["next_buy"] = self._next_buy(rec["id"], owned, gold, map_id)
        purchase = self.purchase(recommendations[0]["id"], owned, gold, map_id) if recommendations else {"status": "none", "text": "Sin compras compatibles verificables con el catálogo y el perfil disponibles."}
        if ended:
            purchase = {"status": "postgame", "text": "Partida finalizada: revisión del último estado, no una orden de compra en directo."}
        elif local_key not in times or now - times.get(local_key, 0) > 30:
            purchase = {"status": "stale", "text": "Esperando un snapshot reciente del jugador local para confirmar compras."}
        actions = self._actions(champ, profile, local, allies, threats, threat_kinds, phase, session, now, owned)
        return {"champion": champ, "profile": profile, "time": now, "phase": phase, "ended": ended,
                "gold": gold, "owned": owned, "threats": threats, "recommendations": recommendations,
                "purchases": purchases, "purchase": purchase, "actions": actions, "warnings": warnings, "physical_share": physical_share,
                "level": int(number(local.get("level"))), "role": local.get("role", "UNKNOWN")}

    def _missing_parts(self, ident, owned):
        """Components still missing to finish this item (owned components are not re-bought)."""
        pool = Counter(owned)

        def visit(node, ancestors):
            if node in ancestors:
                return []
            if pool[node]:
                pool[node] -= 1
                return []
            return [node]

        return [part for child in item_ids(self.catalog.get(ident, {}).get("from", []))
                for part in visit(child, {ident})]

    def _next_buy(self, ident, owned, gold, map_id="11"):
        """Use the same recipe, budget and slot checks as the priority purchase."""
        if gold is None:
            return None
        buy = self.purchase(ident, owned, gold, map_id)
        if buy["status"] == "buy":
            if buy["id"] == ident:
                return f"Comprable ya ({buy['cost']:,} oro)"
            return f"Ya puedes comprar {self.name(buy['id'])} ({buy['cost']:,} oro)"
        if buy["status"] == "save":
            return f"Faltan {buy['missing']:,} oro para {self.name(buy['id'])}"
        return buy["text"]

    def _purchases(self, owned, map_id, profile=None, champ="", threats=(), physical_share=0.5, limit=3):
        """Completed items whose recipe already uses components you own, with their affinity."""
        if not owned:
            return []
        rows = []
        for ident, item in self.catalog.items():
            if ident not in self.strict:
                continue
            if ident in owned or not self.available(ident, map_id) or not self.compatible(ident, owned):
                continue
            if "Boots" in item.get("tags", []):
                continue
            sources = item_ids(item.get("from", []))
            if not sources:
                continue
            remaining, consumed = self._recipe(ident, owned)
            if not consumed or remaining <= 0:
                continue
            row = {"id": ident, "name": self.name(ident),
                   "reason": "Completas: " + ", ".join(self.name(c) for c in sorted(consumed)),
                   "missing": [self.name(c) for c in self._missing_parts(ident, owned)],
                   "cost": remaining, "score": None}
            if profile:
                scored = self._score_candidate(
                    ident, {**item, **self.strict.get(ident, {}), "name": item.get("name", ident),
                            "tier": "Legendary"},
                    profile, champ, owned, threats, physical_share)
                if scored:
                    row["score"] = scored["score"]
            rows.append(row)
        rows.sort(key=lambda r: (len(r["missing"]), r["cost"], r["id"]))
        return rows[:limit]

    def _rank(self, profile, champ, owned, threats, physical_share, map_id):
        if sum(1 for i in owned if "Trinket" not in self.catalog.get(i, {}).get("tags", [])) >= 6:
            # Los elixires se consumen al comprarlos con el inventario lleno.
            rows = []
            for ident in ("2138", "2139", "2140"):
                if not self.available(ident, map_id) or ident in owned:
                    continue
                rows.append({"id": ident, "name": self.name(ident), "score": 15.0,
                             "reasons": ["Inventario completo (6 objetos): elixir consumido al comprarlo en tienda"],
                             "responses": [], "cost": self.cost(ident), "invested": 0})
            return rows[:3]
        basic = profile.get("basic_info", {})
        damage = basic.get("damage_type", "")
        style = basic.get("play_style", "")
        preferred = set()
        for key in ("most_played_build", "full_build", "items"):
            preferred.update(self.synergy._normalise_item_name(n) for n in profile.get(key, []))
        preferred.update(self.synergy._normalise_item_name(n) for n in profile.get("power_curve_and_scaling", {}).get("power_spike_items", []))
        for names in profile.get("situational_items", {}).values():
            if isinstance(names, list):
                preferred.update(self.synergy._normalise_item_name(n) for n in names)
        pool = {}
        for ident, item in self.catalog.items():
            if not self.available(ident, map_id) or not self.compatible(ident, owned):
                continue
            strict = self.strict.get(ident, {})
            boots = "Boots" in item.get("tags", []) and ident != "1001"
            if not strict and not boots:
                continue
            if boots and (canonical(champ) == "cassiopeia" or any("Boots" in self.catalog.get(i, {}).get("tags", []) and i != "1001" for i in owned)):
                continue
            known = self.synergy._normalise_item_name(item.get("name", "")) in preferred
            ap, ad = self.stat(ident, "ability_power"), self.stat(ident, "attack_damage")
            if not known and ((damage == "AD" and ap > 0) or (damage == "AP" and ad > 0)):
                continue
            if basic.get("resource_type") not in ("Mana", "mana") and self.stat(ident, "mana") > 0:
                continue
            classes = set(strict.get("classifications", {}).get("intended_classes", []))
            matching = classes & ({style} | self.synergy.STYLE_CLASSES.get(style, set()))
            defensive = self.stat(ident, "armor") + self.stat(ident, "magic_resistance") > 0
            if not (known or matching or boots or defensive):
                continue
            # Pure utility requires an appropriate support identity or recorded champion usage.
            if not known and classes <= {"Enchanter", "Support"} and style not in {"Enchanter", "Warden"} and not boots:
                continue
            pool[ident] = {**item, **strict, "name": item.get("name", ident), "tier": "Legendary"}
        rows = []
        for ident, item in pool.items():
            row = self._score_candidate(ident, item, profile, champ, owned, threats, physical_share)
            if row:
                rows.append(row)
        return sorted(rows, key=lambda r: (-r["score"], -r["invested"], r["id"]))[:8]

    def _score_candidate(self, ident, item, profile, champ, owned, threats, physical_share):
        """Afinidad de un único candidato, en la misma escala que las recomendaciones ordenadas."""
        basic = profile.get("basic_info", {})
        damage = basic.get("damage_type", "")
        style = basic.get("play_style", "")
        base = self.synergy.rank_items(profile, style, {ident: item}, [], limit=1)
        if not base:
            return None
        rec = base[0]
        score = rec.score
        reasons = list(rec.reasons)
        responses = []
        for threat in threats:
            for signal in threat["signals"]:
                kind = signal["kind"]
                if ident in self.RESPONSES.get(kind, set()):
                    if kind == "healing" and self.ANTIHEAL.intersection(owned):
                        continue
                    # Don't buy physical penetration for AP or magic penetration for AD.
                    if kind == "armor" and damage == "AP" or kind == "mr" and damage == "AD":
                        continue
                    score += 7 * threat["weight"]
                    responses.append(f"{self.LABELS[kind]} de {threat['champion']}")
        armor, mr = self.stat(ident, "armor"), self.stat(ident, "magic_resistance")
        if threats and armor > 0 and physical_share >= .6:
            score += 12
            responses.append("Predominio físico estimado")
        if threats and mr > 0 and physical_share <= .4:
            score += 12
            responses.append("Predominio mágico estimado")
        if ident == "3065" and canonical(champ) in self.HEALERS:
            score += 8
            reasons.insert(0, f"Refuerza el sustain propio de {champ}")
        if ident == "3071" and damage == "AD":
            reasons.insert(0, "La reducción de armadura también beneficia al daño físico aliado")
        if ident == "3075" and responses:
            reasons.append("Heridas graves requiere que te ataquen; no garantiza aplicación al sanador")
        if ident == "3111":
            reasons.append("La tenacidad no reduce derribos ni supresiones")
        remaining, used = self._recipe(ident, owned)
        if used:
            score += 10
            reasons.insert(0, "Aprovecha componentes de tu inventario; evita desviar el oro invertido")
        if "Boots" in self.catalog.get(ident, {}).get("tags", []):
            score += 5
        return {"id": ident, "name": rec.name, "score": round(score, 1),
                "reasons": reasons, "responses": list(dict.fromkeys(responses)),
                "cost": remaining, "invested": self.cost(ident) - remaining}

    def _actions(self, champ, profile, local, allies, threats, kinds, phase, session, now, owned):
        actions = []
        if canonical(champ) == "briar":
            actions.append(("Tu condición de pelea", "Entra después del control aliado; conserva E para cortar el frenesí y salir. No uses R a ciegas hacia una zona sin visión."))
        else:
            style = profile.get("basic_info", {}).get("play_style", "")
            plan = {
                "Marksman": "Golpea al objetivo seguro más cercano detrás de tu frontline; conserva movilidad para el engage enemigo.",
                "Enchanter": "Mantén alcance de protección sobre tu carry; reserva escudo o curación para la respuesta rival.",
                "Assassin": "Busca un flanco con visión y espera a que se gasten las herramientas de protección antes de entrar.",
                "Mage": "Controla accesos con habilidades y juega alrededor de tus ventanas de alcance; evita entrar primero.",
                "Vanguard": "Inicia solo cuando tu equipo pueda seguirte; no consumas todo el control lejos de tus carries.",
                "Warden": "Prioriza interceptar el dive y proteger al aliado que aporta el daño.",
            }.get(style, "Coordina el foco con tus aliados y no comprometas tu salida antes de confirmar que pueden seguirte.")
            actions.append((f"Plan de {champ}", plan))
        if threats:
            top = threats[0]
            actions.append(("Rival a vigilar", f"{top['champion']} ({top['kda']}): prioridad estimada por bajas y muertes, no daño medido. Respeta su rango y confirma sus objetos."))
        controls = [p.get("champion_name", "?") for p in allies.values()
                    if number(self.profile(p.get("champion_name")).get("map_and_control", {}).get("crowd_control")) >= 7]
        if controls:
            actions.append(("Sinergia aliada · control", f"Coordina el foco con {', '.join(controls)}: encadena tu entrada tras su control, sin solaparlo innecesariamente."))
        protectors = [p.get("champion_name", "?") for p in allies.values()
                      if self.profile(p.get("champion_name")).get("basic_info", {}).get("play_style") in {"Enchanter", "Warden"}]
        if protectors:
            actions.append(("Sinergia aliada · protección", f"Juega al alcance de {', '.join(protectors)}; no rompas la distancia de sus herramientas de protección."))
        if "healing" in kinds:
            covered = bool(self.ANTIHEAL.intersection(owned))
            actions.append(("Curación rival", "Ya llevas heridas graves: aplica el efecto al objetivo correcto, no dupliques la compra." if covered else
                            "Coordina quién aplicará heridas graves. Si el sanador queda fuera de tu alcance, comprar anti-curación por sí solo no resuelve la pelea."))
        if "cc" in kinds:
            actions.append(("Ventana de entrada", "Espera al control decisivo antes del all-in. La tenacidad no resuelve supresiones ni derribos; no se conocen sus enfriamientos."))
        role = local.get("role", "")
        phase_plan = ("Prioriza experiencia, farmeo y recalls sin perder oleadas." if role != "JUNGLE"
                      else "Ordena el siguiente ciclo de campamentos hacia el lado con prioridad aliada; evita invadir sin apoyo.")
        if phase == "Medio juego":
            phase_plan = "Empuja una oleada segura y prepara visión con aliados antes de disputar un objetivo; sincroniza el recall para gastar oro."
        elif phase == "Juego tardío":
            phase_plan = "No facecheckees: avanza con visión y equipo. Conserva recursos para una pelea decisiva y evita morir lejos del siguiente objetivo."
        actions.append((phase, phase_plan))
        matchup = session.get("lane_matchups", {}).get(role, {})
        enemy_key = matchup.get("enemy_key")
        current, _ = self.latest(session)
        enemy = current.get(enemy_key, {})
        # Inventory investment is not total gold earned and is deliberately labelled as such.
        my_value = sum(self.cost(i) for i in owned)
        enemy_value = sum(self.cost(i) for i in item_ids(enemy.get("items", [])))
        if enemy and my_value and enemy_value:
            delta = my_value - enemy_value
            actions.append(("Tempo del enfrentamiento", f"Diferencia de inversión en objetos: {delta:+,} oro (no oro ganado). " +
                            ("Con ventaja de objetos, transforma presión en visión y objetivos sin perseguir bajas." if delta >= 1000 else
                             "Con desventaja de objetos, recoge recursos seguros y evita duelos sin superioridad numérica." if delta <= -1000 else
                             "Inversión similar: decide por apoyo, nivel y recursos, no solo por KDA.")))
        recent = [e for e in session.get("events", []) if isinstance(e, dict) and e.get("type") == "objective"
                  and 0 <= now - number(e.get("time")) <= 120]
        if recent:
            event = max(recent, key=lambda e: number(e.get("time")))
            actions.append(("Último objetivo registrado", f"{event.get('label', event.get('objective', 'Objetivo'))}. Reorganiza presión y visión; no se infiere el siguiente respawn."))
        live = local.get("live_stats", {})
        hp, maximum = number(live.get("currentHealth")), number(live.get("maxHealth"))
        if maximum > 0 and hp > 0 and hp / maximum < .3:
            actions.insert(0, ("Vida baja", "Menos del 30 % de vida en la última muestra: prioriza una retirada segura antes de disputar."))
        return actions