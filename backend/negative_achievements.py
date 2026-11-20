"""Conservative, telemetry-backed improvement findings for match analysis."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

ROLES = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")
SEVERITIES = ("mild", "moderate", "severe", "critical")
LABELS = {"mild": "Leve", "moderate": "Moderado", "severe": "Grave", "critical": "Crítico"}

# `lower` means lower values are worse; `higher` means higher values are worse.
# The unsupported findings remain in settings/registry, disabled, until Riot
# supplies participant-level evidence for opportunities and archetypes.
DEFINITIONS: tuple[dict[str, Any], ...] = (
    {"id":"dark_map","name":"Mapa a oscuras","category":"vision","metric":"wards_per_10","unit":"centinelas/10 min","direction":"lower","roles":list(ROLES),"min_duration":10,"thresholds":[4.5,3.5,2.5,1.5],"source":"Match-V5 · wardsPlaced"},
    {"id":"no_river_control","name":"Sin control del río","category":"vision","metric":"control_wards","unit":"centinelas de control","direction":"lower","roles":list(ROLES),"min_duration":15,"thresholds":[3,2,1,0],"source":"Match-V5 · detectorWardsPlaced o WARD_PLACED de control"},
    {"id":"vision_abandoned","name":"Visión abandonada","category":"vision","metric":"wards_killed_per_10","unit":"centinelas/10 min","direction":"lower","roles":["JUNGLE","MIDDLE","BOTTOM","UTILITY"],"min_duration":12,"thresholds":[2.5,1.7,1.0,0.4],"source":"Match-V5 · wardsKilled"},
    {"id":"absent_fights","name":"Ausente en las peleas","category":"combat","metric":"kill_participation_pct","unit":"% de participación","direction":"lower","roles":list(ROLES),"min_duration":10,"thresholds":[55,42,30,20],"source":"Match-V5 · kills + assists / bajas del equipo"},
    {"id":"no_finisher","name":"Sin rematar","category":"combat","metric":"kills_per_10","unit":"asesinatos/10 min","direction":"lower","roles":["TOP","JUNGLE","MIDDLE","BOTTOM"],"min_duration":15,"thresholds":[1.8,1.2,0.7,0.3],"source":"Match-V5 · kills y duración"},
    {"id":"low_assists","name":"Poca presencia","category":"combat","metric":"assists_per_10","unit":"asistencias/10 min","direction":"lower","roles":["TOP","JUNGLE","MIDDLE","BOTTOM","UTILITY"],"min_duration":15,"thresholds":[2.5,1.7,1.0,0.5],"source":"Match-V5 · assists; no se activa si el jugador acumula muchas bajas"},
    {"id":"forgotten_dragons","name":"Dragones olvidados","category":"objectives","metric":"dragon_control_gap","unit":"dragones de desventaja","direction":"higher","roles":["JUNGLE"],"min_duration":15,"thresholds":[1,2,3,4],"source":"Riot Match-V5 Timeline · ELITE_MONSTER_KILL con killerId verificado"},
    {"id":"unattended_objectives","name":"Objetivos desatendidos","category":"objectives","metric":"major_objective_participation","unit":"participaciones verificadas","direction":"lower","roles":list(ROLES),"min_duration":15,"thresholds":[2,1,0,0],"source":"Riot no expone participación individual fiable en todos los objetivos","supported":False,"enabled":False},
    {"id":"wasted_farm","name":"Farm desperdiciado","category":"economy","metric":"cs_per_min","unit":"CS/min","direction":"lower","roles":["TOP","JUNGLE","MIDDLE","BOTTOM"],"min_duration":15,"thresholds":[6.0,5.0,4.0,3.0],"source":"Match-V5 · totalMinionsKilled + neutralMinionsKilled"},
    {"id":"stalled_economy","name":"Economía estancada","category":"economy","metric":"gold_per_min","unit":"oro/min","direction":"lower","roles":list(ROLES),"min_duration":15,"thresholds":[390,340,290,240],"source":"Match-V5 · goldEarned y duración"},
    {"id":"too_many_deaths","name":"Demasiadas visitas a base","category":"survival","metric":"deaths_per_10","unit":"muertes/10 min","direction":"higher","roles":list(ROLES),"min_duration":10,"thresholds":[2.0,3.0,4.0,5.5],"source":"Match-V5 · deaths y duración"},
    {"id":"rough_start","name":"Inicio accidentado","category":"survival","metric":"early_deaths","unit":"muertes antes del minuto 10","direction":"higher","roles":list(ROLES),"min_duration":10,"thresholds":[1,2,3,4],"source":"Match-V5 Timeline · CHAMPION_KILL con victimId y timestamp","integer":True},
    {"id":"no_pressure","name":"Sin presión","category":"map_pressure","metric":"structure_damage_per_min","unit":"daño a estructuras/min","direction":"lower","roles":["TOP","JUNGLE","MIDDLE","BOTTOM"],"min_duration":18,"thresholds":[160,100,50,15],"source":"Match-V5 · damageDealtToTurrets (preferido) o damageDealtToBuildings"},
    {"id":"low_champion_damage","name":"Golpes insuficientes","category":"combat","metric":"champion_damage_per_min","unit":"daño a campeones/min","direction":"lower","roles":["TOP","JUNGLE","MIDDLE","BOTTOM"],"min_duration":15,"thresholds":[650,480,320,180],"source":"Match-V5 · totalDamageDealtToChampions"},
    {"id":"blind","name":"A ciegas","category":"vision","metric":"vision_per_min","unit":"visión/min","direction":"lower","roles":list(ROLES),"min_duration":15,"thresholds":[0.75,0.55,0.35,0.2],"source":"Match-V5 · visionScore; se suprime si ya aplica Mapa a oscuras"},
    {"id":"xp_behind","name":"Por detrás en experiencia","category":"economy","metric":"xp_deficit_10","unit":"XP de desventaja al min 10","direction":"higher","roles":list(ROLES),"min_duration":10,"thresholds":[500,900,1400,2000],"source":"Match-V5 Timeline · xp frente a rival de misma posición"},
    {"id":"lane_behind","name":"Línea cuesta arriba","category":"economy","metric":"gold_deficit_10","unit":"oro de desventaja al min 10","direction":"higher","roles":["TOP","MIDDLE","BOTTOM","UTILITY"],"min_duration":10,"thresholds":[700,1200,1800,2500],"source":"Match-V5 Timeline · totalGold frente a rival de misma posición"},
    {"id":"dead_too_long","name":"Demasiado tiempo fuera","category":"survival","metric":"dead_time_pct","unit":"% de la partida muerto","direction":"higher","roles":list(ROLES),"min_duration":10,"thresholds":[8,13,19,27],"source":"Match-V5 · totalTimeSpentDead"},
    {"id":"low_protection","name":"Poco apoyo","category":"team_utility","metric":"allied_protection","unit":"curación y escudo a aliados","direction":"lower","roles":["UTILITY"],"min_duration":15,"thresholds":[10000,5000,1500,0],"source":"Match-V5 · totalHealsOnTeammates + totalDamageShieldedOnTeammates","supported":False,"enabled":False},
    {"id":"low_teamfight_presence","name":"Escasa presencia decisiva","category":"combat","metric":"teamfight_participation","unit":"participaciones verificadas","direction":"lower","roles":list(ROLES),"min_duration":15,"thresholds":[2,1,0,0],"source":"No existe un campo de asistencia individual fiable a teamfights","supported":False,"enabled":False},
    {"id":"unspent_gold","name":"Oro sin invertir","category":"economy","metric":"prolonged_unspent_gold","unit":"ventanas observadas","direction":"higher","roles":list(ROLES),"min_duration":15,"thresholds":[1,2,3,4],"source":"Current gold no permite inferir oportunidad segura de compra","supported":False,"enabled":False},
)

_BY_ID = {item["id"]: item for item in DEFINITIONS}
DESCRIPTIONS = {
    "dark_map":"Tu colocación de centinelas fue baja para el tiempo y la posición.",
    "no_river_control":"Se observaron pocos centinelas de control colocados.",
    "vision_abandoned":"Destruiste pocos centinelas enemigos para el tiempo de partida.",
    "absent_fights":"Participaste en una proporción baja de las bajas de tu equipo.",
    "no_finisher":"Tu ritmo de eliminaciones fue bajo para una posición de daño.",
    "low_assists":"Tu participación y asistencias fueron reducidas en esta partida.",
    "forgotten_dragons":"La cronología actual no permite atribuir participación individual fiable.",
    "unattended_objectives":"La cronología actual no permite atribuir presencia individual fiable.",
    "wasted_farm":"Tu ritmo de súbditos y monstruos fue bajo para la posición.",
    "stalled_economy":"El oro por minuto observado quedó por debajo de la referencia configurable.",
    "too_many_deaths":"La frecuencia de muertes fue elevada para la duración de la partida.",
    "rough_start":"Las muertes tempranas pueden haber limitado tu progresión inicial.",
    "no_pressure":"El daño a estructuras registrado fue reducido.",
    "low_champion_damage":"El daño a campeones por minuto fue bajo para la posición.",
    "blind":"La puntuación de visión por minuto fue reducida.",
    "xp_behind":"Tu experiencia estuvo por detrás del rival de la misma posición.",
    "lane_behind":"Tu oro estuvo por detrás del rival de la misma posición al minuto 10.",
    "dead_too_long":"El tiempo muerto ocupó una parte elevada de la partida.",
    "low_protection":"No hay una expectativa fiable de curación o escudo para este campeón.",
    "low_teamfight_presence":"No existe telemetría fiable para atribuir asistencia individual a teamfights.",
    "unspent_gold":"La telemetría no permite inferir compras seguras no realizadas.",
}

RECOMMENDATIONS = {
    "dark_map": "Coloca centinelas en entradas de río y jungla antes de que aparezcan los objetivos. Retírate con el equipo y no cruces zonas oscuras sin información reciente.",
    "no_river_control": "Compra centinelas de control en tus recalles y colócalos cerca del objetivo que se disputará. Coordina quién limpia la visión rival para no dejar el control solo al support.",
    "vision_abandoned": "Limpia la visión rival antes de dragón, Heraldo o Nashor. Aprovecha el barrido del support, la lente de detección y los cambios de lente; no entres solo a zonas sin cobertura aliada.",
    "absent_fights": "Revisa el minimapa cuando se agrupen los equipos y busca una ruta segura para apoyar. Si tu campeón debe dividir, presiona y coordina el movimiento en vez de llegar tarde a una pelea ya perdida.",
    "no_finisher": "Convierte ventajas de línea en rotaciones y objetivos, pero evita perseguir bajas bajo torre o sin visión. Enfócate en el daño y la presión que tu campeón puede aportar con seguridad.",
    "low_assists": "Acompaña las jugadas cercanas y comunica cuándo puedes moverte. Si tu rol debe jugar aislado, prioriza una ventaja medible de línea y presión en mapa para que el bajo número de asistencias tenga contexto.",
    "forgotten_dragons": "Controla el temporizador y prepara visión con antelación. Si tu botlane pierde línea, no fuerces una pelea: observa cuándo la botlane rival necesita recallear, aprovecha esa ventana para iniciar el dragón con prioridad de medio o apoyo del equipo y, si no es seguro, intercambia por un objetivo en la parte superior del mapa.",
    "unattended_objectives": "Consulta los temporizadores, prepara visión y decide con el equipo qué objetivo se puede disputar. No inicies sin prioridad de línea ni información suficiente; si el rival ya tiene ventaja numérica, intercambia por recursos en otra zona.",
    "wasted_farm": "Planifica rutas entre oleadas y campamentos, recoge las oleadas seguras y evita quedarte esperando una jugada sin información. No sacrifiques objetivos o peleas decisivas por CS marginal.",
    "stalled_economy": "Reduce tiempos muertos entre oleadas y recallear tras empujar una línea cuando sea seguro. Prioriza campamentos u oleadas disponibles y evita recorridos largos sin objetivo.",
    "too_many_deaths": "Antes de avanzar, comprueba visión, posiciones rivales y temporizadores. Después de una muerte, espera a que el equipo recupere visión y evita volver solo a la misma zona.",
    "rough_start": "En los primeros minutos, respeta las ventanas de nivel y las rutas de jungla conocidas. Si pierdes vida o no tienes visión, cede una oleada antes que arriesgar otra muerte.",
    "no_pressure": "Busca ventanas para golpear la torre después de empujar la oleada o cuando los rivales estén lejos. Coordina la presión con el equipo y no te quedes bajo una estructura sin visión.",
    "low_champion_damage": "Busca intercambios cuando tengas ventaja de nivel, objetos o enfriamientos, y apunta a objetivos prioritarios. No persigas daño de relleno si puedes convertir la presión en una baja, torre u objetivo.",
    "blind": "Combina centinelas, barridos y control de zonas antes de objetivos. La puntuación de visión también depende de duración y rol, así que revisa el mapa y la colocación, no solo el total final.",
    "xp_behind": "Recoge experiencia de las oleadas y campamentos seguros y evita abandonar varias oleadas por una rotación sin resultado. Coordina la ayuda del equipo si el rival te expulsa de la zona.",
    "lane_behind": "Compara el estado de la oleada antes de intercambiar y evita perder súbditos por un intento de baja de baja probabilidad. Usa un recalleo después de empujar para volver con recursos y mantener experiencia.",
    "dead_too_long": "Cada muerte te deja fuera del mapa: pierdes tiempo para ganar experiencia y oro, defender líneas y ayudar en objetivos. En el juego tardío la reaparición suele ser más larga y una muerte puede decidir la partida. Evita avanzar sin visión o separado del equipo, guarda recursos defensivos para la amenaza principal y espera a que tus aliados puedan acompañarte.",
    "low_protection": "Prioriza proteger al aliado que pueda sostener la pelea y usa curación o escudo cuando el rival comprometa recursos, no al final del combate. Si tu campeón no ofrece esa utilidad, este indicador no debe interpretarse como una carencia.",
    "low_teamfight_presence": "La telemetría disponible no permite recomendar una acción concreta para esta métrica.",
    "unspent_gold": "La telemetría disponible no confirma si era seguro recallear o comprar; no interpretes este dato como una oportunidad perdida.",
}


def default_settings() -> dict[str, Any]:
    factors = {
        "dark_map": {"UTILITY": 1.5, "JUNGLE": 1.15},
        "no_river_control": {"UTILITY": 1.5, "JUNGLE": 1.2},
        "vision_abandoned": {"UTILITY": 1.5, "JUNGLE": 1.2},
        "absent_fights": {"UTILITY": 1.2, "JUNGLE": 1.15, "TOP": 0.9},
        "no_finisher": {"TOP": 0.9, "JUNGLE": 1.0, "MIDDLE": 1.1, "BOTTOM": 1.15},
        "low_assists": {"UTILITY": 1.5, "JUNGLE": 1.2},
        "wasted_farm": {"TOP": 1.0, "JUNGLE": 0.72, "MIDDLE": 1.0, "BOTTOM": 1.08},
        "stalled_economy": {"UTILITY": 0.62, "JUNGLE": 0.9},
        "too_many_deaths": {"UTILITY": 1.2, "JUNGLE": 0.92, "TOP": 1.12},
        "no_pressure": {"TOP": 1.25, "BOTTOM": 1.25, "UTILITY": 0.45, "JUNGLE": 0.8},
        "low_champion_damage": {"BOTTOM": 1.25, "MIDDLE": 1.15, "UTILITY": 0.55},
        "blind": {"UTILITY": 1.5, "JUNGLE": 1.15},
        "dead_too_long": {"UTILITY": 1.2, "TOP": 1.1},
    }
    return {
        "enabled": True,
        "show_mild": False,
        "role_aware": True,
        "early_game_window_minutes": 10,
        "opponent_checkpoint_minutes": 10,
        "rules": {item["id"]: {
            "enabled": item.get("enabled", item.get("supported", True)),
            "roles": list(item["roles"]),
            "min_duration_minutes": item["min_duration"],
            "thresholds": dict(zip(SEVERITIES, item["thresholds"])),
            "role_factors": {role: factors.get(item["id"], {}).get(role, 1.0) for role in ROLES},
        } for item in DEFINITIONS},
    }


def public_registry(settings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    rules = (settings or default_settings()).get("rules", {})
    return [{**{key: value for key, value in item.items() if key not in {"thresholds", "roles", "min_duration"}},
             "description": DESCRIPTIONS[item["id"]],
             "roles": list(rules.get(item["id"], {}).get("roles", item["roles"])),
             "minDurationMinutes": rules.get(item["id"], {}).get("min_duration_minutes", item["min_duration"]),
             "supported": item.get("supported", True),
             "thresholds": deepcopy(rules.get(item["id"], {}).get("thresholds", dict(zip(SEVERITIES, item["thresholds"])))),
             "roleFactors": deepcopy(rules.get(item["id"], {}).get("role_factors", {role: 1.0 for role in ROLES}))}
            for item in DEFINITIONS]


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if value == value and abs(value) != float("inf") else None


def _role(player: dict[str, Any]) -> str:
    value = str(player.get("role") or "").upper()
    return {"MID":"MIDDLE", "MIDLANE":"MIDDLE", "ADC":"BOTTOM", "BOT":"BOTTOM", "SUPPORT":"UTILITY", "SUPP":"UTILITY"}.get(value, value)


def _dragon_context(local: dict[str, Any], participants: list[dict[str, Any]],
                    events: list[dict[str, Any]], timeline_available: bool) -> dict[str, Any] | None:
    """Compare verified dragon secures by both junglers and the player's team."""
    if not timeline_available or _role(local) != "JUNGLE" or local.get("side") not in {"allied", "enemy"}:
        return None
    opposing_junglers = [row for row in participants
                         if row.get("side") not in {None, "unknown", local.get("side")} and _role(row) == "JUNGLE"]
    if len(opposing_junglers) != 1:
        return None
    enemy_jungle = opposing_junglers[0]
    by_id = {str(row.get("participantId")): row for row in participants if row.get("participantId") is not None}
    seen: set[str] = set()
    dragon_events: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict) or event.get("type") != "ELITE_MONSTER_KILL":
            continue
        if str(event.get("monsterType") or "").upper() != "DRAGON":
            continue
        killer_id = event.get("killerId")
        killer = by_id.get(str(killer_id))
        if killer is None:
            continue
        key = str(event.get("id") or (event.get("timestamp"), event.get("monsterType"), event.get("monsterSubType"), killer_id))
        if key in seen:
            continue
        seen.add(key)
        dragon_events.append({**event, "_killer": killer})
    if not dragon_events:
        return None
    local_team = [event for event in dragon_events if event["_killer"].get("side") == local.get("side")]
    enemy_jungle_events = [event for event in dragon_events
                           if str(event.get("killerId")) == str(enemy_jungle.get("participantId"))]
    local_jungle_events = [event for event in dragon_events
                           if str(event.get("killerId")) == str(local.get("participantId"))]
    # Attribute this finding to the local jungler's verified secure count.
    # Team totals remain in context, so the card does not imply that the
    # opposing jungler alone secured every dragon his team obtained.
    gap = max(0, len(enemy_jungle_events) - len(local_jungle_events))
    if gap <= 0:
        return None
    return {
        "gap": float(gap),
        "local_jungle_dragons": len(local_jungle_events),
        "allied_team_dragons": len(local_team),
        "enemy_jungle_dragons": len(enemy_jungle_events),
        "evidence": [event for event in enemy_jungle_events + local_jungle_events],
    }


def _number_label(value: float, decimals: int = 1) -> str:
    if float(value).is_integer():
        return f"{int(value):,}".replace(",", ".")
    return f"{value:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _frame_at(frames: list[dict[str, Any]], pid: Any, key: str, target_ms: int) -> float | None:
    rows = [(abs(int(frame["timestamp"]) - target_ms), _num(frame.get(key))) for frame in frames
            if isinstance(frame, dict) and frame.get("participantId") == pid
            and isinstance(frame.get("timestamp"), (int, float)) and abs(int(frame["timestamp"]) - target_ms) <= 60_000]
    rows = [row for row in rows if row[1] is not None]
    return min(rows, key=lambda row: row[0])[1] if rows else None


def _metrics(player: dict[str, Any], participants: list[dict[str, Any]], events: list[dict[str, Any]],
             frames: list[dict[str, Any]], duration_seconds: float, timeline_available: bool,
             settings: dict[str, Any]) -> dict[str, float | None]:
    role = _role(player)
    minutes = duration_seconds / 60 if duration_seconds > 0 else 0
    pid = player.get("participantId")
    availability = player.get("achievementAvailability") if isinstance(player.get("achievementAvailability"), dict) else {}
    def stat(key: str, availability_key: str) -> float | None:
        if availability.get(availability_key) is False:
            return None
        return _num(player.get(key))
    team = [row for row in participants if row.get("side") == player.get("side")]
    opponents = [row for row in participants if row.get("side") != player.get("side") and row.get("side") in {"allied", "enemy"}]
    team_kills = (sum(_num(row.get("kills")) or 0 for row in team)
                  if len(team) == 5 and all(_num(row.get("kills")) is not None
                    and not (isinstance(row.get("achievementAvailability"), dict) and row["achievementAvailability"].get("kills") is False)
                    for row in team) else None)
    kills = None if availability.get("kills") is False else _num(player.get("kills"))
    assists = None if availability.get("assists") is False else _num(player.get("assists"))
    kp = ((kills + assists) * 100 / team_kills) if team_kills and team_kills > 0 and kills is not None and assists is not None else None
    cs = stat("cs", "cs")
    gold = stat("gold", "gold")
    wards = stat("wardsPlaced", "wards_placed")
    wards_killed = stat("wardsKilled", "wards_killed")
    control = _num(player.get("detectorWardsPlaced"))
    if control is None and timeline_available:
        seen = [event for event in events if isinstance(event, dict) and event.get("type") == "WARD_PLACED" and event.get("actorId") == pid
                and "CONTROL" in str(event.get("wardType") or "").upper()]
        control = float(len({str(event.get("id") or (event.get("timestamp"), event.get("wardType"))) for event in seen}))
    early_deaths = None
    if timeline_available:
        early_window_ms = float(settings.get("early_game_window_minutes", 10)) * 60_000
        deaths = [event for event in events if isinstance(event, dict) and event.get("type") == "CHAMPION_KILL" and event.get("victimId") == pid
                  and isinstance(event.get("timestamp"), (int, float)) and 0 <= event["timestamp"] <= early_window_ms]
        early_deaths = float(len({str(event.get("id") or (event.get("timestamp"), pid)) for event in deaths}))
    total_deaths = None if availability.get("deaths") is False else _num(player.get("deaths"))
    damage = stat("championDamageDealt", "champion_damage")
    structure = _num(player.get("damageToTurrets"))
    if structure is None:
        structure = _num(player.get("damageToBuildings"))
    vision = stat("vision", "vision")
    rival = next((row for row in opponents if _role(row) == role), None)
    gold_deficit = xp_deficit = None
    if rival and timeline_available:
        checkpoint_ms = float(settings.get("opponent_checkpoint_minutes", 10)) * 60_000
        local_gold, rival_gold = _frame_at(frames, pid, "gold", int(checkpoint_ms)), _frame_at(frames, rival.get("participantId"), "gold", int(checkpoint_ms))
        local_xp, rival_xp = _frame_at(frames, pid, "xp", int(checkpoint_ms)), _frame_at(frames, rival.get("participantId"), "xp", int(checkpoint_ms))
        if local_gold is not None and rival_gold is not None:
            gold_deficit = max(0.0, rival_gold - local_gold)
        if local_xp is not None and rival_xp is not None:
            xp_deficit = max(0.0, rival_xp - local_xp)
    dead_seconds = _num(player.get("totalTimeSpentDead"))
    return {
        "wards_per_10": wards * 10 / minutes if wards is not None and minutes else None,
        "control_wards": control,
        "wards_killed_per_10": wards_killed * 10 / minutes if wards_killed is not None and minutes else None,
        "kill_participation_pct": kp,
        "kills_per_10": kills * 10 / minutes if kills is not None and minutes else None,
        "assists_per_10": assists * 10 / minutes if assists is not None and minutes else None,
        "dragon_control_gap": None,
        "major_objective_participation": None,
        "cs_per_min": cs / minutes if cs is not None and minutes else None,
        "gold_per_min": gold / minutes if gold is not None and minutes else None,
        "deaths_per_10": total_deaths * 10 / minutes if total_deaths is not None and minutes else None,
        "early_deaths": early_deaths,
        "structure_damage_per_min": structure / minutes if structure is not None and minutes else None,
        "champion_damage_per_min": damage / minutes if damage is not None and minutes else None,
        "vision_per_min": vision / minutes if vision is not None and minutes else None,
        "xp_deficit_10": xp_deficit,
        "gold_deficit_10": gold_deficit,
        "dead_time_pct": dead_seconds * 100 / duration_seconds if dead_seconds is not None and duration_seconds > 0 else None,
        "allied_protection": None,
        "teamfight_participation": None,
        "prolonged_unspent_gold": None,
    }


def evaluate(participants: list[dict[str, Any]], events: list[dict[str, Any]], frames: list[dict[str, Any]],
             duration_seconds: float, timeline_available: bool, settings: dict[str, Any] | None) -> dict[str, Any]:
    settings = settings or default_settings()
    local = next((player for player in participants if player.get("local")), None)
    if not local:
        return {"enabled": bool(settings.get("enabled", True)), "showMild": bool(settings.get("show_mild", False)), "items": [], "unsupported": []}
    role = _role(local)
    values = _metrics(local, participants, events, frames, duration_seconds, timeline_available, settings)
    dragon = _dragon_context(local, participants, events, timeline_available)
    if dragon:
        values["dragon_control_gap"] = dragon["gap"]
    rules = settings.get("rules", {})
    findings: list[dict[str, Any]] = []
    active: dict[str, dict[str, Any]] = {}
    unsupported: list[str] = []
    for definition in DEFINITIONS:
        rule = rules.get(definition["id"], {})
        if not definition.get("supported", True):
            unsupported.append(definition["id"])
            continue
        if not settings.get("enabled", True) or not rule.get("enabled", True) or role not in rule.get("roles", definition["roles"]):
            continue
        if duration_seconds < float(rule.get("min_duration_minutes", definition["min_duration"])) * 60:
            continue
        value = values.get(definition["metric"])
        if value is None:
            continue
        # A low assist rate is only actionable when overall participation is
        # also low; this avoids calling a solo-kill-heavy game a weakness.
        if definition["id"] == "low_assists":
            kp = values.get("kill_participation_pct")
            if kp is None or kp >= 55 or (_num(local.get("kills")) or 0) >= 8:
                continue
        thresholds = rule.get("thresholds", {})
        factor = (_num((rule.get("role_factors") or {}).get(role)) or 1.0) if settings.get("role_aware", True) else 1.0
        severity = None
        effective_threshold = None
        for level in reversed(SEVERITIES):
            threshold = _num(thresholds.get(level))
            if threshold is None:
                continue
            effective_threshold = threshold * factor
            if (value >= effective_threshold if definition["direction"] == "higher" else value <= effective_threshold):
                severity = level
                break
        if severity is None:
            continue
        observed = _number_label(float(value))
        required = _number_label(float(effective_threshold)) if effective_threshold is not None else "—"
        severity_reason = (f"El nivel {LABELS[severity].lower()} se activa desde {required} {definition['unit']}; "
                           f"el valor observado fue {observed} {definition['unit']}." if definition["direction"] == "higher"
                           else f"El nivel {LABELS[severity].lower()} se activa con {required} {definition['unit']} o menos; "
                           f"el valor observado fue {observed} {definition['unit']}.")
        evidence: list[dict[str, Any]] = []
        if definition["id"] == "rough_start":
            early_window_ms = float(settings.get("early_game_window_minutes", 10)) * 60_000
            seen_events: set[str] = set()
            for event in events:
                if not (isinstance(event, dict) and event.get("type") == "CHAMPION_KILL"
                        and event.get("victimId") == local.get("participantId")
                        and isinstance(event.get("timestamp"), (int, float))
                        and 0 <= event["timestamp"] <= early_window_ms):
                    continue
                event_key = str(event.get("id") or (event.get("timestamp"), local.get("participantId")))
                if event_key in seen_events:
                    continue
                seen_events.add(event_key)
                evidence.append({"event_id": event.get("id"), "timestamp_ms": event.get("timestamp"), "participant_id": local.get("participantId")})
        if definition["id"] == "forgotten_dragons" and dragon:
            evidence = [{"event_id": event.get("id"), "timestamp_ms": event.get("timestamp"),
                         "participant_id": event.get("killerId")}
                        for event in dragon["evidence"]]
        description = DESCRIPTIONS[definition["id"]]
        recommendation = RECOMMENDATIONS[definition["id"]]
        context: dict[str, Any] = {}
        if definition["id"] == "dead_too_long":
            death_count = _num(local.get("deaths"))
            dead_seconds = _num(local.get("totalTimeSpentDead"))
            if death_count is not None and dead_seconds is not None:
                dead_minutes = dead_seconds / 60
                description = (f"Has muerto {int(death_count)} veces y acumulaste "
                               f"{_number_label(dead_minutes)} min con la pantalla en gris "
                               f"({_number_label(float(value))}% de la partida). Ese tiempo te dejó fuera del mapa, "
                               "sin poder ganar recursos, defender ni ayudar al equipo.")
                recommendation = ("Para reducirlo, comprueba dónde están los rivales antes de avanzar, evita entrar solo "
                                  "en zonas sin visión y espera a que tus aliados puedan acompañarte. Sobre todo en el juego "
                                  "tardío, evita muertes innecesarias: las reapariciones son más largas y una sola puede "
                                  "dejar al equipo sin defensa u objetivo.")
                context = {"deaths": int(death_count), "dead_minutes": dead_minutes,
                           "dead_time_percent": float(value)}
        elif definition["id"] == "forgotten_dragons" and dragon:
            local_dragons = int(dragon["local_jungle_dragons"])
            team_dragons = int(dragon["allied_team_dragons"])
            rival_dragons = int(dragon["enemy_jungle_dragons"])
            description = (f"Aseguraste {local_dragons} dragones; tu equipo aseguró {team_dragons} y "
                           f"el jungla rival aseguró {rival_dragons}. La diferencia individual verificada es de "
                           f"{int(value)} dragones.")
            recommendation = (f"El jungla rival aseguró {rival_dragons} dragones frente a tus {local_dragons}. "
                              + RECOMMENDATIONS["forgotten_dragons"])
            context = {"local_jungle_dragons": local_dragons, "allied_team_dragons": team_dragons,
                       "enemy_jungle_dragons": rival_dragons}
        finding = {
            "achievement_id": definition["id"], "name": definition["name"], "category": definition["category"],
            "description": description, "recommendation": recommendation, "context": context,
            "severity_reason": severity_reason,
            "severity": severity, "severity_label": LABELS[severity],
            "measured_value": value, "unit": definition["unit"], "threshold": effective_threshold,
            "role": role,
            "data_quality": "verified_timeline" if definition["metric"] in {"early_deaths", "xp_deficit_10", "gold_deficit_10", "dragon_control_gap"} else "verified_match_statistic",
            "confidence": "configurable_fallback_thresholds",
            "source": definition["source"], "evidence": evidence,
            "observation_window": {"start_minute": 0, "end_minute": float(settings.get("early_game_window_minutes", 10)) if definition["id"] == "rough_start" else duration_seconds / 60},
        }
        active[definition["id"]] = finding
        findings.append(finding)
    # Avoid repeating the same vision diagnosis. Keep control wards distinct.
    if "dark_map" in active and "blind" in active:
        findings = [finding for finding in findings if finding["achievement_id"] != "blind"]
    if not settings.get("show_mild", False):
        findings = [finding for finding in findings if finding["severity"] != "mild"]
    severity_order = {key: index for index, key in enumerate(SEVERITIES)}
    findings.sort(key=lambda row: (-severity_order[row["severity"]], row["category"], row["achievement_id"]))
    return {"enabled": bool(settings.get("enabled", True)), "showMild": bool(settings.get("show_mild", False)),
            "items": findings, "unsupported": unsupported}
