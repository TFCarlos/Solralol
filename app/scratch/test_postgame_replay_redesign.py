from app.ui.postgame_replay_window import marker_filter_group


def test_marker_filter_group_classifies_supported_aliases() -> None:
    """Comprueba que tipos canónicos y alias llegan a su filtro correcto.

    Returns:
        None.
    """
    assert marker_filter_group("kill") == "kill"
    assert marker_filter_group("death") == "death"
    assert marker_filter_group("assist") == "assist"
    assert marker_filter_group("dragon") == "dragon"
    assert marker_filter_group("rift herald") == "herald"
    assert marker_filter_group("baron") == "baron"
    assert marker_filter_group("tower") == "tower"
    assert marker_filter_group("inhibitor") == "inhibitor"
    assert marker_filter_group("teamfight") == "other"
    assert marker_filter_group("unmapped-kind") == "other"
