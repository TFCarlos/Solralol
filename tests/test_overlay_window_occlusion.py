from app.services.game_window_geometry import _occlusion_for_rects


def test_other_monitor_focus_does_not_count_as_occlusion():
    result = _occlusion_for_rects((0, 0, 1920, 1080), [(2000, 0, 3000, 1080)], {'gold': (30, 30, 300, 200)})
    assert result['gameOccluded'] is False
    assert result['coveredPanels'] == []


def test_overlapping_window_hides_affected_overlay_and_full_game_when_substantial():
    result = _occlusion_for_rects((0, 0, 1920, 1080), [(0, 0, 960, 1080)], {'gold': (20, 30, 300, 200), 'items': (1500, 30, 300, 200)})
    assert result['gameOccluded'] is True
    assert result['coveredPanels'] == ['gold']


def test_partial_overlap_only_hides_intersected_panel():
    result = _occlusion_for_rects((0, 0, 1920, 1080), [(100, 100, 350, 220)], {'gold': (20, 30, 300, 200), 'items': (700, 30, 300, 200)})
    assert result['gameOccluded'] is False
    assert result['coveredPanels'] == ['gold']
