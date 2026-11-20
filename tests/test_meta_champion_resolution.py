from __future__ import annotations

from app.services.meta_service import ServicioMeta


def _grid(names: list[str], role: str = "support", region: str = "euw") -> str:
    cards = []
    for position, name in enumerate(names, 1):
        cards.append(f"""
        <div class="h-[151px] min-w-[150px]"><a href="/es/lol/{name.lower()}/build/">
          <img alt="{name}"/><div class="rounded-full">{position}</div>
          <div class="m-auto w-[48px]"><div>{'S'}</div><div>52.1</div><div>2.3</div><div>1.0</div></div>
        </a></div>""")
    return f"""<html><head><title>LoL Tier List for Patch 16.20</title></head>
    <body><script>tb_tl_region_{role}_ranked_grid_emerald_plus_16.20_{region}__</script>
    {''.join(cards)}</body></html>"""


def _service() -> ServicioMeta:
    service = ServicioMeta.__new__(ServicioMeta)
    service._campeones = ServicioMeta._cargar_catalogo_campeones()
    return service


def test_resolves_localized_and_variant_champion_names_to_data_dragon_ids():
    service = _service()
    cases = {
        "Bardo": "Bard",
        "bArD": "Bard",
        "Maestro Yi": "MasterYi",
        "Master Yi": "MasterYi",
        "Wukong": "MonkeyKing",
        "Nunu & Willump": "Nunu",
        "Dr. Mundo": "DrMundo",
        "Kai'Sa": "Kaisa",
        "Kha'Zix": "Khazix",
        "Cho'Gath": "Chogath",
        "Renata Glasc": "Renata",
    }
    assert {name: service._resolver_campeon(name) for name in cases} == cases


def test_support_grid_resolves_bard_and_preserves_real_source_position():
    service = _service()
    filters = ServicioMeta._normalizar_filtros_tier({"role": "support", "region": "euw"})
    diagnostics: list[dict] = []
    rows, patch = service._extraer_campeones_cuadricula(
        _grid(["Bardo", "Braum"]), filters, diagnostics
    )
    assert patch == "16.20"
    assert [(row["position"], row["champion_id"], row["name"]) for row in rows] == [
        (1, "Bard", "Bard"), (2, "Braum", "Braum")
    ]
    assert diagnostics == []


def test_unknown_first_champion_is_reported_without_promoting_second_place():
    service = _service()
    filters = ServicioMeta._normalizar_filtros_tier({"role": "support", "region": "all"})
    diagnostics: list[dict] = []
    rows, _ = service._extraer_campeones_cuadricula(
        _grid(["UnknownChampion", "Bard"], region="all"), filters, diagnostics
    )
    assert [row["position"] for row in rows] == [2]
    assert diagnostics == [{"source_name": "UnknownChampion", "position": 1}]
    ServicioMeta._validar_ranking(
        rows, filters, "16.20", 2, completo=False, no_resueltos=diagnostics
    )
    assert not any(row["position"] == 1 for row in rows)


def test_partial_ranking_with_unexplained_gap_is_rejected():
    filters = ServicioMeta._normalizar_filtros_tier({"role": "support", "region": "all"})
    rows = [{
        "champion_id": "Bard", "name": "Bard", "role": "support", "region": "all",
        "rank": "emerald_plus", "queue": "ranked_solo_duo", "patch": "16.20",
        "position": 2, "tier": "A", "win_rate": 50.0, "pick_rate": 1.0, "ban_rate": 1.0,
    }]
    try:
        ServicioMeta._validar_ranking(rows, filters, "16.20", 2, completo=False, no_resueltos=[])
    except RuntimeError:
        pass
    else:
        raise AssertionError("El puesto ausente debe requerir un diagnóstico de identidad")
