"""Pruebas para la identidad visible de los participantes."""

from app.services.identidad_jugador import nombre_riot_visible
from app.services.servicio_puntuacion_rendimiento import puntuar_sesion


def test_prioriza_game_name_y_tag_con_su_capitalizacion() -> None:
    """Compone la cuenta desde campos de Riot y conserva sus mayúsculas."""
    assert (
        nombre_riot_visible(
            {
                "riot_id": "chaos:marqq#black",
                "riotIdGameName": "Marqq",
                "riotIdTagline": "BLACK",
            }
        )
        == "Marqq#BLACK"
    )


def test_rechaza_clave_interna_y_utiliza_alias_del_participante() -> None:
    """Evita mostrar prefijos de equipo y cae al nombre visible verificado."""
    assert (
        nombre_riot_visible({"riot_id": "chaos:marqq#black", "summoner_name": "Marqq"})
        == "Marqq"
    )
    assert nombre_riot_visible({"riotIdGameName": "Marqq"}) == "Marqq"
    assert nombre_riot_visible({"riot_id": "order:participant_72"}) == ""


def test_clasificacion_adjunta_id_visible_sin_cambiar_la_clave_interna() -> None:
    """Mantiene el identificador interno para la búsqueda y expone Riot ID aparte."""
    resultado = puntuar_sesion(
        {
            "players": {
                "chaos:participant_72": {
                    "champion_name": "Jinx",
                    "riot_id": "chaos:marqq#black",
                    "team": "chaos",
                    "role": "BOTTOM",
                    "final": {
                        "riot_id_game_name": "Marqq",
                        "riot_id_tagline": "BLACK",
                    },
                }
            },
            "snapshots": [
                {
                    "players": {
                        "chaos:participant_72": {
                            "kills": 3,
                            "deaths": 2,
                            "assists": 6,
                        }
                    }
                }
            ],
            "duration": 1800,
        }
    )
    participante = resultado["by_id"]["chaos:participant_72"]
    assert participante["participant_id"] == "chaos:participant_72"
    assert participante["champion"] == "Jinx"
    assert participante["riot_id"] == "Marqq#BLACK"
