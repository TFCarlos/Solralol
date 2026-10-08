"""Pruebas sin red de persistencia, migración, actualización y consulta local."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.services.champion_variant_service import ChampionVariantService
from app.services.preparador_datos_campeon import (
    PreparadorDatosCampeon,
    combinar_perfil,
)
from app.services.repositorio_campeones import (
    VERSION_ESQUEMA,
    EstadoDatos,
    RepositorioCampeones,
    identificador_campeon,
)


@pytest.fixture
def perfil_repositorio() -> dict:
    """Devuelve perfil mínimo independiente de APIs."""
    return {
        "character": "Ahri",
        "basic_info": {"play_style": "Mage", "flex_potential": ["Mid"]},
        "power_curve_and_scaling": {},
    }


@pytest.fixture
def documento(perfil_repositorio: dict) -> dict:
    """Devuelve matriz y metadatos válidos para guardar."""
    return RepositorioCampeones.documento(
        perfil_repositorio,
        {
            "emerald_plus": {
                "mid": {
                    "role": "mid",
                    "rank": "emerald_plus",
                    "runes": [],
                    "most_played_build": ["Espada"],
                    "matchups": {},
                    "updated": True,
                },
                "__lane_stats__": {"lanes": {"mid": {"games": 123, "win_rate": 0.5}}},
            }
        },
    )


def test_guardado_lectura_consulta(tmp_path: Path, documento: dict) -> None:
    """Comprueba guardado, identidad y consulta por tres claves."""
    repo = RepositorioCampeones(tmp_path)
    repo.guardar("Ahri", documento)
    assert repo.obtener_campeon("Ahri").datos == documento
    assert repo.consultar("Ahri", "mid", "emerald_plus").datos["most_played_build"] == [
        "Espada"
    ]
    assert (
        repo.consultar("Ahri", "support", "emerald_plus").estado
        == EstadoDatos.SIN_DATOS_FUENTE
    )
    assert (
        repo.consultar("Akali", "mid", "diamond").estado
        == EstadoDatos.SIN_DATOS_LOCALES
    )
    assert repo.consultar("Ahri", "otro", "diamond").estado == EstadoDatos.NO_COMPATIBLE
    assert repo.perfiles() == [documento["profile"]]
    assert identificador_campeon("Cho'Gath") == "chogath"
    with pytest.raises(ValueError):
        identificador_campeon("...")


def test_reemplazo_cache_externa(tmp_path: Path, documento: dict) -> None:
    """Verifica reemplazo completo e invalidación entre instancias."""
    repo = RepositorioCampeones(tmp_path)
    otra = RepositorioCampeones(tmp_path)
    repo.guardar("Ahri", documento)
    assert repo.consultar("Ahri", "mid", "emerald_plus").datos
    documento["ranks"]["emerald_plus"]["mid"]["most_played_build"] = ["Nuevo"]
    otra.guardar("Ahri", documento)
    assert repo.consultar("Ahri", "mid", "emerald_plus").datos["most_played_build"] == [
        "Nuevo"
    ]
    repo.invalidar("Ahri")
    documento["ranks"] = {}
    repo.guardar("Ahri", documento)
    assert (
        repo.consultar("Ahri", "mid", "emerald_plus").estado
        == EstadoDatos.SIN_DATOS_FUENTE
    )


def test_atomicidad(
    tmp_path: Path, documento: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simula fallo del reemplazo y asegura anterior intacto y temporal retirado."""
    repo = RepositorioCampeones(tmp_path)
    repo.guardar("Ahri", documento)
    original = repo.ruta("Ahri").read_bytes()
    monkeypatch.setattr(
        "app.services.repositorio_campeones.os.replace",
        Mock(side_effect=OSError("fallo")),
    )
    documento["updated_at"] = "otra fecha"
    with pytest.raises(OSError):
        repo.guardar("Ahri", documento)
    assert repo.ruta("Ahri").read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize(
    "cambio", ["schema", "identity", "rank", "lane", "null", "core"]
)
def test_validacion_preserva(tmp_path: Path, documento: dict, cambio: str) -> None:
    """Evita sustituir datos válidos por estructuras malformadas."""
    repo = RepositorioCampeones(tmp_path)
    repo.guardar("Ahri", documento)
    original = repo.ruta("Ahri").read_bytes()
    if cambio == "schema":
        documento["schema_version"] = 999
    elif cambio == "identity":
        documento["champion"] = "Akali"
    elif cambio == "rank":
        documento["ranks"]["inventado"] = {}
    elif cambio == "lane":
        documento["ranks"]["emerald_plus"]["otra"] = {"role": "otra"}
    elif cambio == "null":
        documento["ranks"]["emerald_plus"]["mid"] = None
    else:
        documento["ranks"]["emerald_plus"]["mid"]["runes"] = None
    with pytest.raises(ValueError):
        repo.guardar("Ahri", documento)
    assert repo.ruta("Ahri").read_bytes() == original


def test_corruptos_y_esquema(tmp_path: Path, documento: dict) -> None:
    """Distingue archivo roto, versión incompatible y ausencia local."""
    repo = RepositorioCampeones(tmp_path)
    repo.ruta("Ahri").write_text("{", encoding="utf-8")
    assert repo.consultar("Ahri", "mid", "diamond").estado == EstadoDatos.CORRUPTOS
    documento["profile"]["combat_attributes"] = {"attack_damage": float("nan")}
    repo.ruta("Ahri").write_text(json.dumps(documento), encoding="utf-8")
    assert repo.consultar("Ahri", "mid", "diamond").estado == EstadoDatos.CORRUPTOS
    documento["profile"].pop("combat_attributes")
    documento["schema_version"] = VERSION_ESQUEMA + 1
    repo.ruta("Ahri").write_text(json.dumps(documento), encoding="utf-8")
    assert (
        repo.consultar("Ahri", "mid", "diamond").estado
        == EstadoDatos.ESQUEMA_INCOMPATIBLE
    )
    with pytest.raises(ValueError):
        repo.guardar_perfil(documento["profile"])


def test_migracion(tmp_path: Path, documento: dict) -> None:
    """Migra plural y singular con matrices y assets, eliminando origen solo tras validar."""
    for nombre in ("champions_strict.json", "champion_strict.json"):
        raiz = tmp_path / nombre.replace(".json", "")
        repo = RepositorioCampeones(raiz / "champion_data")
        origen = raiz / nombre
        origen.write_text(json.dumps([documento["profile"]]), encoding="utf-8")
        repo.ruta("Ahri").write_text(
            json.dumps({"version": 1, "ranks": documento["ranks"]}), encoding="utf-8"
        )
        (repo.raiz / "Akali.json").write_text(
            json.dumps({"data": {"Akali": {}}}), encoding="utf-8"
        )
        assert repo.migrar(origen) == 1
        assert not origen.exists()
        assert (raiz / "champion_metadata" / "Akali.json").exists()
        assert repo.consultar("Ahri", "mid", "emerald_plus").datos
        assert repo.migrar(origen) == 0


def test_migracion_fallida_conserva_origen(tmp_path: Path) -> None:
    """Comprueba que datos no migrables no causan eliminación del origen."""
    origen = tmp_path / "champions_strict.json"
    origen.write_text(json.dumps([{"character": "Ahri"}]), encoding="utf-8")
    with pytest.raises(ValueError):
        RepositorioCampeones(tmp_path / "champion_data").migrar(origen)
    assert origen.exists()


def test_preparacion_y_adaptador(
    tmp_path: Path, documento: dict, perfil_repositorio: dict
) -> None:
    """Comprueba generación persistida, separación global y contrato de variantes."""
    (tmp_path / "items.json").write_text(json.dumps({"items": {}}), encoding="utf-8")
    (tmp_path / "legendary_items_strict.json").write_text("[]", encoding="utf-8")
    preparado = PreparadorDatosCampeon(tmp_path).preparar(
        perfil_repositorio, documento["ranks"]
    )
    assert "recommendations" in preparado["ranks"]["emerald_plus"]["mid"]
    repo = RepositorioCampeones(tmp_path / "champion_data")
    repo.guardar("Ahri", preparado)
    repo.guardar_perfil(dict(perfil_repositorio, dato="editado"))
    variante = ChampionVariantService(repo.raiz)
    assert variante.get("Ahri", "mid", "emerald_plus")
    assert variante.available_ranks("Ahri") == ["emerald_plus"]
    assert variante.available_lanes("Ahri", "emerald_plus") == ["mid"]
    assert variante.lane_stats("Ahri", "emerald_plus")["mid"]["games"] == 123
    assert variante.key("Ahri", "Mid", "Diamond") == "ahri|mid|diamond"
    assert variante.path_for("Ahri") == repo.ruta("Ahri")
    assert (
        combinar_perfil(dict(perfil_repositorio, runes=["antiguas"]), {}).get("runes")
        is None
    )


def test_cache_acotada(tmp_path: Path, documento: dict) -> None:
    """Verifica que recorrer campeones no precarga todas sus matrices."""
    repo = RepositorioCampeones(tmp_path)
    for indice in range(12):
        nombre = f"Campeon{indice}"
        perfil = dict(documento["profile"], character=nombre)
        repo.guardar(nombre, repo.documento(perfil, documento["ranks"]))
        repo.obtener_campeon(nombre)
    assert len(repo._cache) == 8


@pytest.fixture
def actualizador(
    tmp_path: Path, documento: dict, monkeypatch: pytest.MonkeyPatch
) -> object:
    """Crea proveedor con catálogos locales y descargas simuladas en memoria."""
    from app.services.champion_scraper_service import ChampionScraperService

    (tmp_path / "champion_catalog.json").write_text(
        json.dumps(
            {
                "data": {
                    "Ahri": {"name": "Ahri", "key": "103"},
                    "Akali": {"name": "Akali", "key": "84"},
                }
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "items.json").write_text(json.dumps({"items": {}}), encoding="utf-8")
    (tmp_path / "legendary_items_strict.json").write_text("[]", encoding="utf-8")
    instancia = ChampionScraperService(
        champions_path=tmp_path / "champion_data", request_delay=0
    )
    instancia.repositorio.guardar("Ahri", documento)
    monkeypatch.setattr(PreparadorDatosCampeon, "descargar_recursos", Mock())
    return instancia


def test_actualiza_uno_y_reemplaza(
    actualizador: object, documento: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Actualiza campeón completo una sola vez y reemplaza matriz anterior."""
    nueva = {
        "diamond": {
            "mid": {
                "role": "mid",
                "rank": "diamond",
                "most_played_build": ["Nuevo"],
                "updated": True,
            }
        }
    }
    descarga = Mock(return_value=nueva)
    monkeypatch.setattr(actualizador, "fetch_matrix", descarga)
    progreso = Mock()
    assert actualizador.actualizar_todo("Ahri", progreso) == (1, 1)
    descarga.assert_called_once()
    repo = actualizador.repositorio
    assert repo.consultar("Ahri", "mid", "diamond").datos["most_played_build"] == [
        "Nuevo"
    ]
    assert (
        repo.consultar("Ahri", "mid", "emerald_plus").estado
        == EstadoDatos.SIN_DATOS_FUENTE
    )
    assert progreso.call_args.args[:2] == (100, 100)
    assert "completado" in progreso.call_args.args[2]
    unidades = [llamada.args[1] for llamada in progreso.call_args_list]
    valores = [llamada.args[0] for llamada in progreso.call_args_list]
    assert unidades == [100] * len(unidades)
    assert valores == sorted(valores)
    assert valores[-1] == 100


def test_actualiza_todos_con_fallo_independiente(
    actualizador: object, documento: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mantiene campeón válido cuando falla y conserva éxito de otro campeón."""
    descarga = Mock(side_effect=[RuntimeError("fallo fuente"), documento["ranks"]])
    monkeypatch.setattr(actualizador, "fetch_matrix", descarga)
    progreso = Mock()
    assert actualizador.actualizar_todo(progress_callback=progreso) == (2, 1)
    repo = actualizador.repositorio
    antiguo = repo.obtener_campeon("Ahri").datos
    assert antiguo["ranks"] == documento["ranks"]
    assert antiguo["updated_at"] == documento["updated_at"]
    assert antiguo["update_status"] == EstadoDatos.ACTUALIZACION_FALLIDA.value
    assert (
        repo.consultar("Akali", "mid", "emerald_plus").estado == EstadoDatos.DISPONIBLE
    )
    assert progreso.call_args.args[:2] == (2, 2)


def test_cancelacion_no_persiste(
    actualizador: object, documento: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancela una matriz en generación sin publicar ningún dato parcial."""
    monkeypatch.setattr(
        actualizador, "fetch_matrix", Mock(side_effect=InterruptedError())
    )
    assert actualizador.actualizar_todo("Ahri") == (1, 0)
    assert actualizador.repositorio.obtener_campeon("Ahri").datos == documento


def test_lecturas_rapidas_no_red(
    tmp_path: Path, documento: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Alterna filtros locales bloqueando todas las peticiones y contando deserializaciones."""
    import app.services.repositorio_campeones as modulo
    from app.services.analisis_local_service import AnalisisLocalService
    from app.services.catalogo_analisis_local import CatalogoAnalisisLocal

    repo = RepositorioCampeones(tmp_path)
    repo.guardar("Ahri", documento)
    cargas = Mock(wraps=modulo.json.loads)
    monkeypatch.setattr(modulo.json, "loads", cargas)
    monkeypatch.setattr(
        "requests.sessions.Session.request", Mock(side_effect=AssertionError("Red"))
    )
    servicio = AnalisisLocalService(
        CatalogoAnalisisLocal({}, [], {}), tmp_path, "16.17.1"
    )
    for _ in range(30):
        for linea, rango in [
            ("mid", "emerald_plus"),
            ("support", "diamond"),
            ("mid", "diamond_plus"),
        ]:
            datos = servicio.cargar(
                documento["profile"], linea, rango, {}, lambda: False
            )
            assert datos.get("estado", "AVAILABLE") in ("AVAILABLE", "NO_SOURCE_DATA")
    assert (
        sum('"schema_version"' in llamada.args[0] for llamada in cargas.call_args_list)
        == 1
    )


def test_descarga_recursos_solo_explicita(
    tmp_path: Path, documento: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Valida assets preparados con APIs simuladas y cancelación previa a publicación."""
    import app.services.preparador_datos_campeon as modulo

    (tmp_path / "items.json").write_text(json.dumps({"items": {}}), encoding="utf-8")
    (tmp_path / "legendary_items_strict.json").write_text("[]", encoding="utf-8")
    funciones = {}
    for nombre in (
        "get_champion_data",
        "get_ability_icon_path",
        "get_champion_icon_path",
        "get_rune_icon_path",
        "get_spell_icon_path",
        "get_item_icon_path",
        "get_champion_splash_path",
    ):
        funciones[nombre] = Mock()
        monkeypatch.setattr(modulo.data_dragon, nombre, funciones[nombre])
    preparador = PreparadorDatosCampeon(tmp_path)
    preparador.descargar_recursos(documento, lambda: False)
    funciones["get_ability_icon_path"].assert_called()
    funciones["get_champion_icon_path"].assert_called_once()
    funciones["get_champion_splash_path"].assert_called_once()
    with pytest.raises(InterruptedError):
        preparador.descargar_recursos(documento, lambda: True)


def test_splash_fallido_no_descarta_recursos(
    tmp_path: Path, documento: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un fallo del splash no aborta la preparación del resto de recursos."""
    import app.services.preparador_datos_campeon as modulo

    (tmp_path / "items.json").write_text(json.dumps({"items": {}}), encoding="utf-8")
    (tmp_path / "legendary_items_strict.json").write_text("[]", encoding="utf-8")
    for nombre in (
        "get_champion_data",
        "get_ability_icon_path",
        "get_champion_icon_path",
        "get_rune_icon_path",
        "get_spell_icon_path",
        "get_item_icon_path",
    ):
        monkeypatch.setattr(modulo.data_dragon, nombre, Mock())
    monkeypatch.setattr(
        modulo.data_dragon,
        "get_champion_splash_path",
        Mock(side_effect=RuntimeError("sin red")),
    )
    preparador = PreparadorDatosCampeon(tmp_path)
    preparador.descargar_recursos(documento, lambda: False)


def test_matriz_completa_y_filtros(
    actualizador: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recorre todos los rangos, valida filtros y evita fallback a otra línea/rango."""
    from app.services.rangos_campeones import OPCIONES_RANGO

    perfil = actualizador.repositorio.perfiles()[0]
    monkeypatch.setattr(actualizador, "_overview", Mock(return_value={"12": {}}))
    monkeypatch.setattr(
        actualizador,
        "_lane_stats",
        Mock(return_value={"mid": {"games": 100, "win_rate": 0.5}}),
    )
    monkeypatch.setattr(
        actualizador,
        "fetch_variant",
        lambda perfil, linea: {
            "role": linea,
            "rank": actualizador.rank,
            "updated": True,
            "most_played_build": ["Espada"],
        },
    )
    matriz = actualizador.fetch_matrix(perfil)
    assert set(matriz) == {rango for rango, _ in OPCIONES_RANGO}
    assert all(bloque["mid"]["rank"] == rango for rango, bloque in matriz.items())
    actualizador.rank = "diamond"
    assert (
        actualizador._position_entry(
            {"12": {"8": {"5": [1]}, "5": {"5": [2]}}}, "support"
        )
        is None
    )
    assert actualizador._position_entry({"12": {"8": {"5": [1]}}}, "mid") is None


def test_variante_no_hereda_filtros(
    actualizador: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Una fuente parcial nunca recupera runas o builds antiguos de otro filtro."""
    perfil = dict(
        actualizador.repositorio.perfiles()[0],
        runes=[{"antiguo": True}],
        most_played_build=["Viejo"],
    )
    monkeypatch.setattr(actualizador, "update_champion", Mock(return_value=True))
    resultado = actualizador.fetch_variant(perfil, "support")
    assert "runes" not in resultado and "most_played_build" not in resultado
    assert resultado["role"] == "support"


def test_fuente_sin_muestra(
    actualizador: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Distingue fuente sin muestra de error de actualización para campeón nuevo."""
    monkeypatch.setattr(
        actualizador, "fetch_matrix", Mock(return_value={"diamond": {}})
    )
    assert actualizador.actualizar_todo("Akali") == (1, 0)
    assert (
        actualizador.repositorio.consultar("Akali", "mid", "diamond").estado
        == EstadoDatos.SIN_DATOS_FUENTE
    )


def test_preparacion_invalida_revision(
    tmp_path: Path, documento: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Actualiza disco entre lecturas y evita reutilizar preparación de la revisión anterior."""
    from app.services.analisis_local_service import AnalisisLocalService
    from app.services.catalogo_analisis_local import CatalogoAnalisisLocal

    repo = RepositorioCampeones(tmp_path)
    repo.guardar("Ahri", documento)
    monkeypatch.setattr(
        "requests.sessions.Session.request", Mock(side_effect=AssertionError("Red"))
    )
    servicio = AnalisisLocalService(
        CatalogoAnalisisLocal({}, [], {}), tmp_path, "16.17.1"
    )
    primero = servicio.cargar(
        documento["profile"], "mid", "emerald_plus", {}, lambda: False
    )
    repetido = servicio.cargar(
        documento["profile"], "mid", "emerald_plus", {}, lambda: False
    )
    assert repetido["tiempos"]["recursos_ms"] == 0
    documento["ranks"]["emerald_plus"]["mid"]["most_played_build"] = ["Nuevo"]
    RepositorioCampeones(tmp_path).guardar("Ahri", documento)
    siguiente = servicio.cargar(
        documento["profile"], "mid", "emerald_plus", {}, lambda: False
    )
    assert primero["perfil"]["most_played_build"] == ["Espada"]
    assert siguiente["perfil"]["most_played_build"] == ["Nuevo"]


def test_versiones_fuente_observadas(
    actualizador: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Registra solo parches de descargas exitosas y reutiliza la caché del proveedor."""
    contenido = {"12": {"17": {}}}
    descarga = Mock(return_value=contenido)
    monkeypatch.setattr(actualizador, "_get_json", descarga)
    monkeypatch.setattr(actualizador, "_patches", Mock(return_value=["26.18"]))
    assert actualizador._overview(103) == contenido
    assert actualizador._overview(103) == contenido
    assert descarga.call_count == 1
    assert actualizador._builds(103) == contenido
    assert actualizador._archetype_overview(103, "ap-") == contenido
    assert all(
        version == "26.18" for version in actualizador._versiones_fuente.values()
    )
