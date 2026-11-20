"""Sound events use one serial worker; fixtures do not exercise audio hardware."""
from __future__ import annotations

import threading

from app.services.overlay_sound_service import OverlaySoundService


def test_consecutive_alerts_of_same_kind_are_each_played_once():
    played = []
    second_finished = threading.Event()

    def player(data):
        played.append(data)
        if len(played) == 2:
            second_finished.set()

    service = OverlaySoundService(player=player)
    try:
        assert service.play_enemy_buy()
        assert service.play_enemy_buy()
        assert second_finished.wait(2)
        assert len(played) == 2
    finally:
        service.close()
    assert service._worker is not None and not service._worker.is_alive()


def test_close_discards_queued_audio_and_joins_worker():
    started = threading.Event()
    release = threading.Event()
    played = []

    def player(data):
        played.append(data)
        started.set()
        release.wait(2)

    service = OverlaySoundService(player=player)
    assert service.play_dragon_spawn()
    assert started.wait(2)
    assert service.play_enemy_buy()
    timer = threading.Timer(0.05, release.set)
    timer.start()
    service.close()
    timer.join()
    assert not service.play_enemy_buy()
    assert not service._worker.is_alive()
    assert len(played) == 1
