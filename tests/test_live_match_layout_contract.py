from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_player_comparison_keeps_metrics_and_combat_icons_in_separate_rows():
    page = (ROOT / "frontend/src/pages/LiveMatchPage.tsx").read_text(encoding="utf-8")
    assert page.count("players.slice(0,5).map") == 1
    main_start = page.index('className="live-row-main"')
    bottom_start = page.index('className="live-row-bottom"', main_start)
    bottom_end = page.index("</div></div></div>)}</div>)}</div>", bottom_start)
    upper = page[main_start:bottom_start]
    lower = page[bottom_start:bottom_end]

    assert "live-row-items" not in upper
    assert "live-row-spells" not in upper
    assert "creepScore" in upper and "kills" in upper and "deaths" in upper
    assert lower.index("live-row-spells") < lower.index("<RuneIcons")
    assert lower.index("<RuneIcons") < lower.index("live-row-items")
    assert "slice(0,6)" in lower


def test_player_comparison_has_responsive_group_sizing_for_both_teams():
    styles = (ROOT / "frontend/src/styles.css").read_text(encoding="utf-8")
    assert ".live-row-bottom{display:flex" in styles
    assert ".live-row-utility{display:flex" in styles
    assert "@media(max-width:620px){.live-row-bottom" in styles
    assert ".live-row-item-icon{width:12px;height:12px" in styles
    assert "@media(max-width:980px){.live-content-grid" in styles
    assert "@media(max-width:620px){.live-team-grid" in styles


def test_live_assets_survive_two_second_snapshot_effect_cleanup():
    page = (ROOT / "frontend/src/pages/LiveMatchPage.tsx").read_text(encoding="utf-8")
    rune_effect = page[page.index("// activeplayerrunes is attached"):page.index("const local=snap?.localPlayer")]
    assert "Keep an in-flight response" in rune_effect
    assert ".then(result=>setAssets(old=>({...old,...result})))" in rune_effect
    assert "if(current)setAssets" not in rune_effect
    assert "if(activeRequest)" not in page

