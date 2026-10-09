"""Comprueba las restricciones de compra del catálogo SoloQ por parche."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.elegibilidad_objetos import (
    MODO_SOLOQ,
    ValidadorElegibilidadObjetos,
)
from app.services.preparador_datos_campeon import PreparadorDatosCampeon
from app.services.synergy_recommendation_service import SynergyRecommendationService


def cargar_objeto(identificador: str) -> dict[str, Any]:
    """Devuelve los metadatos locales de un objeto canonical por su ID."""
    catalogo = json.loads(Path("data/items.json").read_text(encoding="utf-8"))
    return catalogo["items"][identificador]


def test_elegibilidad_exige_mapa_tienda_id_y_parche() -> None:
    """Excluye objetos alternativos, eliminados y con disponibilidad desconocida."""
    validar = ValidadorElegibilidadObjetos.validar
    objeto_valido = cargar_objeto("3071")
    assert validar("3071", objeto_valido, "Aatrox", MODO_SOLOQ, "16.20.1").elegible
    assert (
        validar(
            "667101", cargar_objeto("667101"), "Aatrox", MODO_SOLOQ, "16.20.1"
        ).motivo
        == "id_de_variante_de_modo"
    )
    assert (
        validar(
            "667112", cargar_objeto("667112"), "Aatrox", MODO_SOLOQ, "16.20.1"
        ).motivo
        == "id_de_variante_de_modo"
    )
    assert (
        validar("6693", cargar_objeto("6693"), "Aatrox", MODO_SOLOQ, "16.20.1").motivo
        == "no_comprable"
    )
    assert (
        validar("6701", cargar_objeto("6701"), "Aatrox", MODO_SOLOQ, "16.20.1").motivo
        == "no_comprable"
    )
    assert (
        validar("2530", cargar_objeto("2530"), "Aatrox", MODO_SOLOQ, "16.20.1").motivo
        == "no_comprable"
    )
    assert validar("3071", objeto_valido, "Aatrox", MODO_SOLOQ, "16.21.1").elegible

    metadatos_desconocidos = {"id": "999", "gold": {"purchasable": True, "total": 2500}}
    assert (
        validar("999", metadatos_desconocidos, "Aatrox", MODO_SOLOQ, "16.20.1").motivo
        == "mapa_desconocido"
    )
    assert (
        validar("3071", objeto_valido, "Aatrox", "ARENA", "16.20.1").motivo
        == "modo_no_admitido"
    )


def test_restricciones_de_campeon_y_modo_usan_contexto_explicito() -> None:
    """Aplica requiredAlly al campeón y no confunde ARAM con SoloQ."""
    objeto = cargar_objeto("3071")
    objeto_restringido = {**objeto, "requiredAlly": "Ornn"}
    assert not ValidadorElegibilidadObjetos.validar(
        "3071", objeto_restringido, "Aatrox", MODO_SOLOQ, "16.20.1"
    ).elegible
    assert ValidadorElegibilidadObjetos.validar(
        "3071", objeto_restringido, "Ornn", MODO_SOLOQ, "16.20.1"
    ).elegible
    assert (
        ValidadorElegibilidadObjetos.validar(
            "1082", cargar_objeto("1082"), "Aatrox", "ARAM", "16.20.1"
        ).motivo
        == "mapa_no_disponible"
    )


def test_diagnostico_cuenta_elegibles_y_motivos_reales() -> None:
    """Expone recuentos del catálogo y razones de rechazo por ID canónico."""
    catalogo = {
        "3071": cargar_objeto("3071"),
        "667101": cargar_objeto("667101"),
        "999": {"id": "999", "gold": {"purchasable": True, "total": 3000}},
    }
    resultado = ValidadorElegibilidadObjetos.diagnosticar_catalogo(
        catalogo, "Aatrox", MODO_SOLOQ, "16.20.1"
    )
    assert resultado["catalog_entries"] == 3
    assert resultado["champion_eligible_entries"] == 1
    assert resultado["rejected_items"]["667101"] == "id_de_variante_de_modo"
    assert resultado["rejected_items"]["999"] == "mapa_desconocido"


def test_rank_candidates_filtra_antes_de_puntuar_y_conserva_el_pool_legal() -> None:
    """No deja que una puntuación alta rescate un objeto fuera de SoloQ."""
    items = {
        "3071": {**cargar_objeto("3071"), "tier": "Legendary"},
        "667101": {**cargar_objeto("667101"), "tier": "Legendary"},
        "999": {
            "id": "999",
            "tier": "Legendary",
            "gold": {"purchasable": True, "total": 3500},
            "stats": {"attack_damage": 1000},
            "tags": ["Damage"],
        },
    }
    motor = SynergyRecommendationService()
    candidatos = motor.rank_candidates(
        {"character": "Aatrox", "combat_attributes": {"attack_damage": 9}},
        "Juggernaut",
        items,
        [],
        game_mode=MODO_SOLOQ,
        catalog_patch="16.20.1",
    )
    ids = {item.item_id for item in candidatos}
    assert "3071" in ids
    assert "667101" not in ids
    assert "999" not in ids
    assert motor.last_item_eligibility_diagnostics["eligible_entries"] == 1
    assert (
        motor.last_item_eligibility_diagnostics["rejected_entries"]["999"]
        == "mapa_desconocido"
    )


def test_aatrox_soloq_no_recibe_objetos_de_evento_y_conserva_alternativas() -> None:
    """Genera una variedad contextual legal, clasificada y explicable para Aatrox."""
    documento = json.loads(
        Path("data/champion_data/aatrox.json").read_text(encoding="utf-8")
    )
    variante = documento["ranks"]["emerald_plus"]["mid"]
    preparado = PreparadorDatosCampeon(Path("data"))
    resultado = preparado.preparar(
        documento["profile"], {"emerald_plus": {"mid": variante}}
    )["ranks"]["emerald_plus"]["mid"]
    ids = {item["item_id"] for item in resultado["situational_item_candidates"]}
    categorias = resultado["situational_items"]

    assert len(resultado["situational_item_candidates"]) >= 30
    assert all(categorias.values())
    assert {"6333", "3156", "3071"}.issubset(ids)
    assert not {"667101", "667112", "6693", "6701", "2530", "322530"} & ids
    assert "3085" not in ids
    assert "6675" not in ids
    assert "3222" in ids
    assert "3036" in ids
    assert "3072" in ids
    assert "3153" in ids
    mikael = next(
        item
        for item in resultado["situational_item_candidates"]
        if item["item_id"] == "3222"
    )
    assert mikael["compatibility_label"] == "Experimental"
    assert "prioriza proteger a un aliado" in " ".join(mikael["compatibility_reasons"])
    assert (
        next(
            item
            for item in resultado["situational_item_candidates"]
            if item["item_id"] == "3072"
        )["compatibility_label"]
        == "Experimental"
    )
    assert (
        next(
            item
            for item in resultado["situational_item_candidates"]
            if item["item_id"] == "3153"
        )["compatibility_label"]
        == "Experimental"
    )
    dominik = next(
        item
        for item in resultado["situational_item_candidates"]
        if item["item_id"] == "3036"
    )
    assert dominik["compatibility_label"] == "Experimental"
    assert "crítico" in " ".join(dominik["compatibility_reasons"]).casefold()
    assert resultado["recommendation_mode"] == MODO_SOLOQ
    assert resultado["recommendation_catalog_version"] == "16.20.1"
    assert (
        resultado["recommendation_diagnostics"]["eligibility"]["catalog_entries"] > 800
    )
