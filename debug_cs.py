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
    print("No hay una partida activa.")
    print("Entra en la herramienta de práctica o una partida y vuelve a ejecutarlo.")
else:
    active_player = client.get_active_player()
    all_game_data = client.get_all_game_data()

    for player in all_game_data.get("allPlayers", []):
        if is_active_player(player, active_player):
            print("=== CAMPOS DEL JUGADOR LOCAL ===")
            print()
            print(json.dumps(player, indent=2, ensure_ascii=False))
            print()
            print("=== SCORES ===")
            print(json.dumps(player.get("scores", {}), indent=2, ensure_ascii=False))
            break
    else:
        print("No se pudo encontrar tu jugador dentro de allPlayers.")