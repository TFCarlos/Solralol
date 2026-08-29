import json

from riot_live import LiveClient


def is_active_player(player: dict, active_player: dict) -> bool:
    active_riot_id = active_player.get("riotId", "")
    active_summoner_name = active_player.get("summonerName", "")

    return (
        bool(active_riot_id and player.get("riotId") == active_riot_id)
        or bool(
            active_summoner_name
            and player.get("summonerName") == active_summoner_name
        )
    )


client = LiveClient()

if not client.is_in_game():
    print("No hay partida activa. Entra en una partida y prueba otra vez.")
else:
    all_game_data = client.get_all_game_data()
    active_player = client.get_active_player()

    local_player = next(
        (
            player
            for player in all_game_data.get("allPlayers", [])
            if is_active_player(player, active_player)
        ),
        None,
    )

    if local_player is None:
        print("No se pudo identificar tu jugador.")
    else:
        enemy_team = (
            "CHAOS"
            if local_player.get("team") == "ORDER"
            else "ORDER"
        )

        for player in all_game_data.get("allPlayers", []):
            if player.get("team") != enemy_team:
                continue

            print("=" * 60)
            print(f"CAMPEÓN: {player.get('championName', 'Desconocido')}")
            print("RUNAS RECIBIDAS POR LA API:")
            print(
                json.dumps(
                    player.get("runes", {}),
                    indent=2,
                    ensure_ascii=False,
                )
            )