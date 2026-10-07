"""Cobertura de los seis filtros, limpieza segura y separación de proveedores."""

import copy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

pytest_plugins = ["app.scratch.test_repositorio_campeones"]
from app.services.rangos_campeones import (
    CLAVES_RANGOS,
    OPCIONES_RANGO,
    POR_CLAVE,
    RANGO_PREDETERMINADO,
    RANGOS_COMPATIBLES,
    normalizar_rango,
)
from app.services.repositorio_campeones import EstadoDatos, RepositorioCampeones


@pytest.mark.parametrize(
    "valor", ["Emerald+", "EMERALD_PLUS", "emerald_plus", "Emerald Plus"]
)
def test_normalizacion(valor: str) -> None:
    """Acepta formatos heredados de un filtro compatible y conserva su semántica."""
    assert normalizar_rango(valor) == "emerald_plus"


@pytest.mark.parametrize(
    "valor",
    ["gold", "all", "challenger", "grandmaster", "diamond_plus_100", "Esmeralda"],
)
def test_no_compatibles(valor: str) -> None:
    """Rechaza filtros obsoletos y etiquetas españolas usadas como identificador."""
    assert normalizar_rango(valor) is None


def test_configuracion() -> None:
    """Comprueba orden, etiquetas exactas, valor inicial y códigos independientes de U.GG."""
    assert tuple(etiqueta for _, etiqueta in OPCIONES_RANGO) == (
        "Esmeralda",
        "Esmeralda+",
        "Diamante",
        "Diamante+",
        "Master",
        "Master+",
    )
    assert len(CLAVES_RANGOS) == 6
    assert RANGO_PREDETERMINADO in CLAVES_RANGOS
    assert tuple(rango.ugg for rango in RANGOS_COMPATIBLES) == (
        "16",
        "17",
        "3",
        "11",
        "2",
        "14",
    )
    assert len({rango.ugg for rango in RANGOS_COMPATIBLES}) == 6


def test_limpieza_local(
    tmp_path: Path, documento: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Depura archivo antiguo atómicamente y conserva las variantes compatibles sin red."""
    repo = RepositorioCampeones(tmp_path)
    antiguo = copy.deepcopy(documento)
    antiguo["ranks"]["gold"] = {"contenido": "obsoleto"}
    antiguo["ranks"]["Diamond Plus"] = copy.deepcopy(antiguo["ranks"]["emerald_plus"])
    antiguo["ranks"]["Diamond Plus"]["mid"]["rank"] = "Diamond+"
    repo.ruta("Ahri").write_text(json.dumps(antiguo), encoding="utf8")
    monkeypatch.setattr(
        "requests.sessions.Session.request",
        Mock(side_effect=AssertionError("Red prohibida")),
    )
    assert repo.consultar("Ahri", "mid", "Diamond+").estado == EstadoDatos.DISPONIBLE
    guardado = json.loads(repo.ruta("Ahri").read_text(encoding="utf8"))
    assert set(guardado["ranks"]) == {"emerald_plus", "diamond_plus"}
    assert guardado["ranks"]["emerald_plus"] == documento["ranks"]["emerald_plus"]
    assert repo.consultar("Ahri", "mid", "gold").estado == EstadoDatos.NO_COMPATIBLE
    assert (
        repo.consultar("Ahri", "mid", "master").estado == EstadoDatos.SIN_DATOS_FUENTE
    )
    assert not list(tmp_path.glob("*.tmp"))


def test_limpieza_fallida_preserva_archivo(
    tmp_path: Path, documento: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un fallo de reemplazo durante limpieza deja el archivo anterior completo."""
    repo = RepositorioCampeones(tmp_path)
    antiguo = copy.deepcopy(documento)
    antiguo["ranks"]["gold"] = {}
    contenido = json.dumps(antiguo)
    repo.ruta("Ahri").write_text(contenido, encoding="utf8")
    monkeypatch.setattr(
        "app.services.repositorio_campeones.os.replace",
        Mock(side_effect=OSError("Disco")),
    )
    assert repo.obtener_campeon("Ahri").estado == EstadoDatos.CORRUPTOS
    assert repo.ruta("Ahri").read_text(encoding="utf8") == contenido
    assert not list(tmp_path.glob("*.tmp"))


def test_conflicto_preservado(tmp_path: Path, documento: dict) -> None:
    """No elimina variantes contradictorias cuando dos alias reclaman la misma combinación."""
    repo = RepositorioCampeones(tmp_path)
    antiguo = copy.deepcopy(documento)
    antiguo["ranks"]["Emerald+"] = copy.deepcopy(antiguo["ranks"]["emerald_plus"])
    antiguo["ranks"]["Emerald+"]["mid"]["most_played_build"] = ["Otro"]
    contenido = json.dumps(antiguo)
    repo.ruta("Ahri").write_text(contenido, encoding="utf8")
    assert repo.obtener_campeon("Ahri").estado == EstadoDatos.CORRUPTOS
    assert repo.ruta("Ahri").read_text(encoding="utf8") == contenido


def test_validacion_y_resumen(documento: dict) -> None:
    """Rechaza guardado obsoleto y limpia el resumen global de una muestra antigua."""
    antiguo = copy.deepcopy(documento)
    antiguo["ranks"]["gold"] = {}
    antiguo["profile"]["lane_stats"] = {"rank": "gold", "lanes": {}}
    with pytest.raises(ValueError):
        RepositorioCampeones.validar(antiguo, "Ahri")
    limpio = RepositorioCampeones.depurar_rangos(antiguo)
    assert "lane_stats" not in limpio["profile"]
    RepositorioCampeones.validar(limpio, "Ahri")


@pytest.mark.parametrize("destino", ["Ahri", ""])
def test_actualizaciones_seis_rangos(
    actualizador: object, destino: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Actualiza uno o todos con seis etapas por campeón y guarda solamente claves compatibles."""
    monkeypatch.setattr(actualizador, "_overview", Mock(return_value={"12": {}}))
    monkeypatch.setattr(
        actualizador, "_lane_stats", Mock(return_value={"mid": {"games": 100}})
    )
    solicitudes: list[str] = []

    def variante(perfil: dict, linea: str) -> dict:
        """Registra rango solicitado y devuelve una variante mínima válida."""
        solicitudes.append(actualizador.rank)
        return {
            "role": linea,
            "rank": actualizador.rank,
            "updated": True,
            "most_played_build": ["Objeto"],
        }

    monkeypatch.setattr(actualizador, "fetch_variant", variante)
    progreso = Mock()
    cantidad = 1 if destino else 2
    assert actualizador.actualizar_todo(destino, progress_callback=progreso) == (
        cantidad,
        cantidad,
    )
    assert solicitudes == [rango.clave for rango in RANGOS_COMPATIBLES] * cantidad
    for perfil in actualizador.repositorio.perfiles():
        if not destino or perfil["character"] == destino:
            datos = actualizador.repositorio.obtener_campeon(perfil["character"]).datos
            assert set(datos["ranks"]) == CLAVES_RANGOS
    etapas = Mock()
    actualizador.fetch_matrix({"character": "Ahri"}, progress_callback=etapas)
    assert [llamada.args[:2] for llamada in etapas.call_args_list] == [
        (indice, 6) for indice in range(1, 7)
    ]


@pytest.mark.parametrize("rango", RANGOS_COMPATIBLES)
def test_proveedores(
    actualizador: object, rango: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cada rango selecciona exclusivamente su bloque U.GG y parámetro OP.GG independiente."""
    actualizador.rank = rango.clave
    datos = {
        "12": {entrada.ugg: {"5": [entrada.clave]} for entrada in RANGOS_COMPATIBLES}
    }
    assert actualizador._position_entry(datos, "mid") == [rango.clave]
    peticion = Mock(return_value={})
    monkeypatch.setattr(actualizador, "_get_json", peticion)
    actualizador._parse_opgg("ahri", "mid")
    assert f"tier={POR_CLAVE[rango.clave].opgg}" in peticion.call_args.args[0]
    pagina = Mock(return_value=None)
    monkeypatch.setattr(actualizador, "_get", pagina)
    actualizador._lolalytics_page("ahri", "mid")
    assert f"tier={rango.lolalytics}" in pagina.call_args.args[0]


def test_contexto_rango(actualizador: object) -> None:
    """Normaliza rango temporal, restaura estado y rechaza valores obsoletos antes de consultar."""
    anterior = actualizador.rank
    with actualizador._for_rank("Diamond Plus"):
        assert actualizador.rank == "diamond_plus"
    assert actualizador.rank == anterior
    with pytest.raises(ValueError), actualizador._for_rank("gold"):
        pass
    assert actualizador.rank == anterior


def test_identidad_y_cache(tmp_path: Path, documento: dict) -> None:
    """Limpieza inválida conserva identidad y cachés detectan reemplazos entre repositorios."""
    repo = RepositorioCampeones(tmp_path)
    otro = RepositorioCampeones(tmp_path)
    repo.guardar("Ahri", documento)
    primero = repo.consultar("Ahri", "mid", "Emerald+")
    antiguo = copy.deepcopy(documento)
    antiguo["ranks"]["gold"] = {}
    repo.ruta("Ahri").write_text(json.dumps(antiguo), encoding="utf8")
    assert otro.obtener_campeon("Ahri").estado == EstadoDatos.DISPONIBLE
    segundo = repo.consultar("Ahri", "mid", "emerald_plus")
    assert segundo.datos == primero.datos
    assert segundo.revision != primero.revision
    assert repo._cerrojo is otro._cerrojo
    antiguo["ranks"]["emerald_plus"]["mid"]["rank"] = "diamond"
    with pytest.raises(ValueError):
        repo.depurar_rangos(antiguo)


def test_seis_filtros_rapidos_locales(
    tmp_path: Path, documento: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recorre los seis filtros sin red, con una sola deserialización del campeón solicitado."""
    repo = RepositorioCampeones(tmp_path)
    datos = copy.deepcopy(documento)
    datos["ranks"] = {}
    for rango in RANGOS_COMPATIBLES:
        bloque = copy.deepcopy(documento["ranks"]["emerald_plus"])
        bloque["mid"]["rank"] = rango.clave
        datos["ranks"][rango.clave] = bloque
    repo.guardar("Ahri", datos)
    deserializar = Mock(wraps=json.loads)
    monkeypatch.setattr("app.services.repositorio_campeones.json.loads", deserializar)
    monkeypatch.setattr(
        "requests.sessions.Session.request",
        Mock(side_effect=AssertionError("Red prohibida")),
    )
    for _ in range(10):
        for rango in RANGOS_COMPATIBLES:
            assert (
                repo.consultar("Ahri", "mid", rango.clave).estado
                == EstadoDatos.DISPONIBLE
            )
    assert deserializar.call_count == 1


@pytest.mark.parametrize("perfil_invalido", [None, [], "invalido"])
def test_perfil_corrupto_no_se_sobrescribe(
    tmp_path: Path, documento: dict, perfil_invalido: object
) -> None:
    """Una estructura global mal formada produce estado corrupto y conserva bytes originales."""
    repo = RepositorioCampeones(tmp_path)
    antiguo = dict(documento, profile=perfil_invalido)
    contenido = json.dumps(antiguo)
    repo.ruta("Ahri").write_text(contenido, encoding="utf8")
    assert repo.obtener_campeon("Ahri").estado == EstadoDatos.CORRUPTOS
    assert repo.ruta("Ahri").read_text(encoding="utf8") == contenido
