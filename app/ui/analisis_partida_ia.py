"""Dashboard nativo para interpretaciones estructuradas de Gemini."""

from __future__ import annotations

import re
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.services.match_analysis_models import enriquecer_analisis_partida
from app.services.match_log_service import MatchLogService
from app.services.resolucion_hitos_fases import hitos_relevantes_fase
from app.ui.tema import aplicar_tema


class AnalisisPartidaIA(QWidget):
    """Muestra análisis validado en secciones navegables y texto plano."""

    def __init__(
        self,
        sesion: dict[str, Any],
        registro: dict[str, Any],
        assets: Any = None,
        parent: QWidget | None = None,
        item_catalog: dict[str, Any] | None = None,
    ) -> None:
        """Inicializa el tablero a partir de la partida y su registro validado."""
        super().__init__(parent)
        self.sesion = sesion
        self.registro = registro
        self.assets = assets
        self.item_catalog = item_catalog or {}
        if str(registro.get("saved_match_id") or "") != str(
            sesion.get("session_id") or ""
        ):
            raise ValueError("El análisis guardado no pertenece a esta partida.")
        contexto = MatchLogService().build_match_log(sesion)
        contexto.update(
            champion_name=sesion.get("champion_name"),
            player_name=sesion.get("player_name") or sesion.get("player_riot_id"),
        )
        self.contexto = contexto
        self.analisis = enriquecer_analisis_partida(registro.get("analysis"), contexto)
        self._rival_seleccionado = 0
        self._botones_rivales: list[QPushButton] = []
        self._tarjetas_rivales: list[QFrame] = []
        self.setObjectName("structuredMatchAnalysis")
        self.setProperty("superficie", "ventana")
        self._construir()
        aplicar_tema(self)
        self.setFont(QFont("Segoe UI", 10))

    def _etiqueta(self, texto: Any, rol: str = "body") -> QLabel:
        """Crea una etiqueta de texto plano con ajuste y tamaño flexible."""
        etiqueta = QLabel(str(texto or ""))
        etiqueta.setFont(QFont("Segoe UI", 10))
        etiqueta.setTextFormat(Qt.TextFormat.PlainText)
        etiqueta.setWordWrap(True)
        etiqueta.setMinimumWidth(0)
        etiqueta.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        etiqueta.setProperty("role", rol)
        etiqueta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return etiqueta

    def _tarjeta(self, titulo: str, contenido: list[str]) -> QFrame:
        """Compone un bloque de análisis con título y texto legible."""
        marco = QFrame()
        marco.setObjectName("matchAnalysisCard")
        marco.setProperty("superficie", "tarjeta")
        disposicion = QVBoxLayout(marco)
        disposicion.setContentsMargins(14, 12, 14, 12)
        disposicion.setSpacing(7)
        disposicion.addWidget(self._etiqueta(titulo, "section"))
        for linea in contenido:
            if linea.strip():
                disposicion.addWidget(self._etiqueta(self._sanear_texto(linea)))
        return marco

    def _sanear_texto(self, valor: Any) -> str:
        """Traduce etiquetas internas y elimina identificadores técnicos visibles."""
        texto = str(valor or "")
        local = str(self.contexto.get("metadata", {}).get("local_team") or "").upper()
        rival = "ORDER" if local == "CHAOS" else "CHAOS"
        for codigo, etiqueta in (("CHAOS", "equipo aliado"), ("ORDER", "equipo rival")):
            texto = re.sub(
                rf"\b{codigo}\b",
                etiqueta
                if codigo == local
                else ("equipo rival" if codigo == rival else "equipo"),
                texto,
                flags=re.IGNORECASE,
            )
        texto = re.sub(r"\bevent-\d+\b", "", texto, flags=re.IGNORECASE)
        texto = re.sub(
            r"\b(?:gold_on_hand_available|schema_version|event_id|champion_id)\s*(?:es|=|:)\s*(?:falso|false|true|verdadero|\w+)",
            "",
            texto,
            flags=re.IGNORECASE,
        )
        for clave in (
            "gold_on_hand_available",
            "schema_version",
            "event_id",
            "champion_id",
            "item_id",
            "recipe_valid",
            "evidence_type",
            "catalog_patch",
        ):
            texto = re.sub(rf"\b{clave}\b", "", texto, flags=re.IGNORECASE)
        for estado, visible in (
            ("POSTGAME_FINAL", "partida finalizada"),
            ("POSTGAME_PENDING", "marcador incompleto"),
            ("INVALID_ARGUMENT", "configuración no válida"),
        ):
            texto = re.sub(rf"\b{estado}\b", visible, texto, flags=re.IGNORECASE)
        items = self.item_catalog.get("items", self.item_catalog)
        if not items:
            try:
                import json

                from _paths import DATA_DIR

                items = json.loads(
                    (DATA_DIR / "items.json").read_text(encoding="utf-8")
                ).get("items", {})
            except (OSError, ValueError):
                items = {}
        for identificador, item in items.items():
            if isinstance(identificador, str) and identificador.isdigit():
                nombre = (
                    item.get("name_es") or item.get("name")
                    if isinstance(item, dict)
                    else None
                )
                if nombre:
                    texto = re.sub(
                        rf"\b{re.escape(identificador)}\b", str(nombre), texto
                    )
        return re.sub(r"\s{2,}", " ", texto).strip()

    def _etiqueta_grado(self, grado: str) -> QLabel:
        """Crea una insignia tipográfica de coaching según el rango de letra."""
        etiqueta = self._etiqueta(f"Grado · {grado}", "grade")
        etiqueta.setProperty(
            "banda", grado[:1] if grado[:1] in {"A", "B", "C", "D", "F"} else ""
        )
        return etiqueta

    def _rejilla(self, widgets: list[QWidget], columnas: int = 2) -> QWidget:
        """Ordena tarjetas en una cuadrícula compacta y adaptable."""
        contenedor = QWidget()
        layout = QGridLayout(contenedor)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(10)
        for indice, widget in enumerate(widgets):
            layout.addWidget(widget, indice // columnas, indice % columnas)
        return contenedor

    def get_champion_icon(self, nombre_o_id: str) -> str | None:
        """Resuelve un retrato de campeón desde el catálogo Data Dragon."""
        if not nombre_o_id:
            return None
        try:
            resolver = getattr(self.assets, "resolve_champion_id", None)
            identificador = resolver(str(nombre_o_id)) if callable(resolver) else None
            if not identificador:
                from app.services.match_analysis_evidence_service import (
                    MatchAnalysisEvidenceService,
                )

                identificador = MatchAnalysisEvidenceService._canonical_champion_id(
                    str(nombre_o_id)
                )
            if identificador:
                try:
                    from data_dragon import get_champion_icon_path

                    ruta_local = get_champion_icon_path(
                        identificador,
                        self._version_assets(),
                        download=False,
                    )
                    if ruta_local and ruta_local.is_file():
                        return str(ruta_local)
                except (ImportError, OSError, TypeError, ValueError):
                    pass
                return self.assets.champion_url(identificador) if self.assets else None
            catalogo = getattr(self.assets, "champions", {})
            nombre = str(nombre_o_id).strip().casefold()
            if isinstance(catalogo, dict) and any(
                nombre == str(clave).casefold() or nombre == str(valor).casefold()
                for clave, valor in catalogo.items()
            ):
                return self.assets.champion_url(str(nombre_o_id))
        except (AttributeError, TypeError, ValueError):
            return None
        return None

    def get_item_icon(self, identificador_o_nombre: str | int) -> str | None:
        """Resuelve el icono de objeto por ID o nombre del catálogo local."""
        items = self.item_catalog.get("items", self.item_catalog)
        if not items:
            try:
                import json

                from _paths import DATA_DIR

                items = json.loads(
                    (DATA_DIR / "items.json").read_text(encoding="utf-8")
                ).get("items", {})
            except (OSError, ValueError):
                items = {}
        valor = str(identificador_o_nombre).strip()
        if not valor:
            return None
        if not valor.isdigit():
            valor_normalizado = valor.casefold()
            coincidencia = next(
                (
                    clave
                    for clave, item in items.items()
                    if isinstance(item, dict)
                    and str(item.get("name", "")).casefold() == valor_normalizado
                ),
                None,
            )
            if coincidencia is None:
                return None
            valor = str(coincidencia)
        known_ids = (
            {str(clave) for clave in items} if isinstance(items, dict) else set()
        )
        asset_ids = {str(clave) for clave in getattr(self.assets, "items", {})}
        if valor not in known_ids and valor not in asset_ids:
            return None
        try:
            if self.assets:
                return self.assets.item_url(int(valor))
            from data_dragon import get_item_icon_path

            ruta = get_item_icon_path(
                int(valor), {"items": items}, self._version_assets(), download=False
            )
            return str(ruta) if ruta and ruta.is_file() else None
        except (AttributeError, TypeError, ValueError):
            return None
        except ImportError:
            return None

    def get_rune_icon(self, nombre: str) -> str | None:
        """Resuelve una runa desde la caché local sin iniciar descargas."""
        equivalente = {
            "Ataque intensificado": "Press the Attack",
            "Lluvia de cuchillas": "Hail of Blades",
        }.get(nombre, nombre)
        return self._resolver_icono_local("rune", equivalente)

    def get_spell_icon(self, nombre: str) -> str | None:
        """Resuelve un hechizo desde la caché local sin iniciar descargas."""
        return self._resolver_icono_local("spell", nombre)

    def get_ability_icon(self, campeon: str, clave_o_nombre: str) -> str | None:
        """Resuelve una habilidad Q/W/E/R si existe en el catálogo local."""
        coincidencia = re.search(r"\b([QWER])\b", clave_o_nombre, re.IGNORECASE)
        if not coincidencia or not campeon:
            return None
        try:
            from data_dragon import get_ability_icon_path

            ruta = get_ability_icon_path(
                campeon,
                coincidencia.group(1),
                getattr(self.assets, "version", ""),
                download=False,
            )
        except (ImportError, OSError, TypeError, ValueError):
            return None
        return str(ruta) if ruta and ruta.is_file() else None

    def _resolver_icono_local(self, tipo: str, nombre: str) -> str | None:
        """Busca iconos locales de runas o hechizos sin acceso de red."""
        try:
            import data_dragon

            resolver = {
                "rune": data_dragon.get_rune_icon_path,
                "spell": data_dragon.get_spell_icon_path,
            }[tipo]
            ruta = resolver(nombre, self._version_assets(), download=False)
        except (ImportError, KeyError, OSError, TypeError, ValueError):
            return None
        return str(ruta) if ruta and ruta.is_file() else None

    def _version_assets(self) -> str:
        """Obtiene la versión de catálogo local para resolver iconos en caché."""
        version = getattr(self.assets, "version", None)
        if version:
            return str(version)
        try:
            import json

            from _paths import DATA_DIR

            datos = json.loads((DATA_DIR / "items.json").read_text(encoding="utf-8"))
            return str(datos.get("version") or "")
        except (OSError, ValueError):
            return ""

    def _icono(
        self, tipo: str, referencia: str, campeon: str = "", size: int = 32
    ) -> QLabel:
        """Crea un icono de juego o un distintivo textual seguro como fallback."""
        etiqueta = QLabel(
            "·" if referencia.isdigit() else referencia[:2].upper() or "?"
        )
        etiqueta.setFixedSize(size, size)
        etiqueta.setObjectName("matchAnalysisIcon")
        etiqueta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        etiqueta.setToolTip("Referencia visual" if referencia.isdigit() else referencia)
        ruta = {
            "champion": lambda: self.get_champion_icon(referencia),
            "item": lambda: self.get_item_icon(referencia),
            "rune": lambda: self.get_rune_icon(referencia),
            "spell": lambda: self.get_spell_icon(referencia),
            "ability": lambda: self.get_ability_icon(campeon, referencia),
        }.get(tipo, lambda: None)()
        if not ruta:
            return etiqueta
        if ruta.startswith(("http://", "https://")) and self.assets:
            try:
                self.assets.set_label_image(
                    etiqueta, ruta, f"match-analysis:{tipo}:{referencia}:{size}", size
                )
            except (AttributeError, RuntimeError, TypeError, ValueError):
                return etiqueta
        else:
            pixmap = QPixmap(ruta)
            if not pixmap.isNull():
                etiqueta.setPixmap(
                    pixmap.scaled(
                        size,
                        size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        return etiqueta

    def _retrato(self, campeon: str) -> QLabel:
        """Carga el retrato local o cacheado del campeón indicado."""
        return self._icono("champion", campeon, size=38)

    def _pagina(self, widgets: list[QWidget]) -> QWidget:
        """Crea una página desplazable de una sola sección de análisis."""
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        contenido = QWidget()
        disposicion = QVBoxLayout(contenido)
        disposicion.setContentsMargins(6, 8, 10, 8)
        disposicion.setSpacing(12)
        for widget in widgets:
            disposicion.addWidget(widget)
        disposicion.addStretch(1)
        area.setWidget(contenido)
        return area

    def _construir(self) -> None:
        """Crea navegación y páginas desde los campos que entregó el modelo."""
        principal = QVBoxLayout(self)
        principal.setContentsMargins(0, 0, 0, 0)
        principal.setSpacing(8)
        metadatos = self.registro
        proveedor = f"Gemini · {metadatos.get('model', 'modelo no indicado')}"
        marca = self._etiqueta(
            f"Análisis guardado · {proveedor} · {metadatos.get('created_at', '')}",
            "muted",
        )
        principal.addWidget(marca)
        self.pestanas = QTabWidget()
        self.pestanas.setObjectName("matchAnalysisSections")
        paginas = (
            ("Resumen", self._resumen()),
            ("Fases", self._fases()),
            ("Rendimiento", [self._rejilla(self._rendimiento(), 2)]),
            ("Build", self._build()),
            ("Rivales", [self._rejilla(self._enfrentamientos(), 2)]),
            ("Mejoras", [self._rejilla(self._mejoras(), 2)]),
        )
        for titulo, pagina in paginas:
            self.pestanas.addTab(self._pagina(pagina), titulo)
        principal.addWidget(self.pestanas, 1)

    def _resumen(self) -> list[QWidget]:
        """Organiza identidad, lectura, aciertos y giro en bloques compactos."""
        resumen = self.analisis["summary"]
        identidad = str(
            resumen.get("champion_name")
            or self.sesion.get("champion_name")
            or "Partida guardada"
        )
        estadisticas = self._estadisticas_factuales()
        jugador = (
            resumen.get("player_name") or self.sesion.get("player_name") or "Jugador"
        )
        cabecera = self._tarjeta(f"{jugador} · {estadisticas}", [])
        fila_identidad = QWidget()
        identidad_layout = QHBoxLayout(fila_identidad)
        identidad_layout.setContentsMargins(0, 0, 0, 0)
        identidad_layout.addWidget(self._retrato(identidad))
        identidad_layout.addWidget(self._etiqueta(identidad, "section"), 1)
        resultado = self._resultado_partida()
        if resultado:
            identidad_layout.addWidget(self._etiqueta(resultado, "accent"))
        grados = self.analisis.get("coaching_grades") or {}
        grado = grados.get("overall") if isinstance(grados, dict) else None
        identidad_layout.addWidget(
            self._etiqueta_grado(grado or "Sin datos suficientes")
        )
        cabecera.layout().insertWidget(1, fila_identidad)
        try:
            from app.services.resumen_rendimiento_historial import (
                etiqueta_puntuacion,
                resumen_puntuacion_local,
            )

            puntuacion = resumen_puntuacion_local(self.sesion)
        except (ImportError, KeyError, TypeError, ValueError):
            puntuacion = None
        if puntuacion:
            cabecera.layout().insertWidget(
                2,
                self._etiqueta(
                    f"Puntuación SOLRALOL · {etiqueta_puntuacion(puntuacion)}",
                    "accent",
                ),
            )
        lectura = self._sanear_texto(
            resumen.get("short_summary")
            or "La lectura usa los datos confirmados de la partida."
        )
        fortalezas = resumen.get("strengths", [])
        debilidades = resumen.get("weaknesses", [])
        prioridades = self.analisis.get("next_game_priorities") or self.analisis.get(
            "improvement_priorities", []
        )
        error_principal = resumen.get("main_error") or next(
            iter(debilidades), "Sin error principal confirmado en el informe."
        )
        prioridad_principal = resumen.get("core_priority") or (
            f"{prioridades[0].get('title', '')}: {prioridades[0].get('explanation', '')}"
            if prioridades
            else "Revisa la cronología para elegir una prioridad concreta."
        )
        observaciones = self._rejilla(
            [
                self._tarjeta(
                    "Qué funcionó",
                    fortalezas[:3] or ["Sin evidencia positiva adicional."],
                ),
                self._tarjeta("Qué revisar", debilidades[:3] or [error_principal]),
            ],
            2,
        )
        decisivo = self._tarjeta("Momento decisivo", [])
        eventos = resumen.get("decisive_events", [])
        if len(eventos) >= 2:
            for indice, evento in enumerate(eventos[:2]):
                fila = QHBoxLayout()
                if evento.get("champion_id"):
                    fila.addWidget(
                        self._icono("champion", str(evento["champion_id"]), size=32)
                    )
                fila.addWidget(
                    self._etiqueta(str(evento.get("time_label") or ""), "accent")
                )
                fila.addWidget(
                    self._etiqueta(
                        self._sanear_texto(evento.get("description")), "body"
                    ),
                    1,
                )
                decisivo.layout().addLayout(fila)
                if indice == 0:
                    decisivo.layout().addWidget(
                        self._etiqueta(
                            f"↓ {eventos[1].get('seconds_after', '')} segundos después · proximidad temporal, sin causalidad confirmada",
                            "muted",
                        )
                    )
        else:
            decisivo.layout().addWidget(
                self._etiqueta(
                    self._sanear_texto(
                        resumen.get("main_turning_point")
                        or "No se identificó un evento decisivo verificable."
                    )
                )
            )
        prioridad = self._tarjeta(
            "Prioridad para la próxima partida", [prioridad_principal]
        )
        return [
            cabecera,
            self._tarjeta("Lectura del partido", self._frases_breves(lectura)),
            observaciones,
            decisivo,
            prioridad,
        ]

    @staticmethod
    def _frases_breves(texto: str) -> list[str]:
        """Divide la valoración en un máximo de cuatro bloques fáciles de recorrer."""
        frases = [
            frase.strip()
            for frase in re.split(r"(?<=[.!?])\s+", texto)
            if frase.strip()
        ]
        if len(frases) > 4:
            frases = frases[:3] + [" ".join(frases[3:])]
        return frases or ["La lectura usa los datos confirmados de la partida."]

    def _resultado_partida(self) -> str:
        """Devuelve el resultado del marcador con una etiqueta comprensible."""
        scoreboard = self.sesion.get("final_scoreboard", {})
        clave = str(self.sesion.get("local_player_key") or "")
        local = scoreboard.get(clave, {}) if isinstance(scoreboard, dict) else {}
        jugadores = self.sesion.get("players", {})
        jugador = jugadores.get(clave, {}) if isinstance(jugadores, dict) else {}
        win = local.get("win", jugador.get("win"))
        return "Victoria" if win is True else "Derrota" if win is False else ""

    def _estadisticas_factuales(self) -> str:
        """Obtiene KDA y CS existentes sin pedir al modelo que los regenere."""
        jugadores = self.sesion.get("players", {})
        clave_local = str(self.sesion.get("local_player_key") or "")
        local = jugadores.get(clave_local, {}) if isinstance(jugadores, dict) else {}
        scoreboard = self.sesion.get("final_scoreboard", {})
        final_local = (
            scoreboard.get(clave_local, {}) if isinstance(scoreboard, dict) else {}
        )
        origen = final_local or local
        valores = []
        for clave, etiqueta in (("kills", "B"), ("deaths", "M"), ("assists", "A")):
            if origen.get(clave) is not None:
                valores.append((etiqueta, origen.get(clave)))
        texto = (
            "KDA " + "/".join(str(valor) for _, valor in valores)
            if len(valores) == 3
            else "KDA no disponible"
        )
        cs = origen.get("cs", origen.get("total_minions_killed"))
        if cs is not None:
            texto += f" · {cs} CS"
            duracion = float(self.sesion.get("duration", 0) or 0)
            if duracion > 0:
                texto += f" ({float(cs) / (duracion / 60):.1f}/min)"
        resultado = final_local.get("win", local.get("win"))
        if resultado is not None:
            texto += " · " + ("Victoria" if resultado else "Derrota")
        return texto

    def _fases(self) -> list[QWidget]:
        """Presenta tres paneles compactos con coaching e hitos resueltos."""
        fases = self.analisis.get("game_phases", {})
        nombres = {
            "early": "Temprano · 0–15 min",
            "mid": "Medio · 15–25 min",
            "late": "Tardío · 25+ min",
        }
        widgets = []
        for clave, titulo in nombres.items():
            fase = fases.get(clave)
            if not fase:
                continue
            tarjeta = QFrame()
            tarjeta.setObjectName("matchAnalysisCard")
            tarjeta.setProperty("superficie", "tarjeta")
            contenido = QVBoxLayout(tarjeta)
            contenido.setContentsMargins(16, 14, 16, 14)
            contenido.setSpacing(10)
            encabezado = QHBoxLayout()
            encabezado.addWidget(self._etiqueta(titulo.upper(), "section"), 1)
            juicio = fase.get("title")
            if juicio and str(juicio).casefold() not in {
                "inicio",
                "mitad",
                "cierre",
                clave,
            }:
                etiqueta_juicio = self._etiqueta(str(juicio), "accent")
                etiqueta_juicio.setProperty("estado", "advertencia")
                encabezado.addWidget(etiqueta_juicio)
            contenido.addLayout(encabezado)
            resumen = fase.get("summary") or fase.get("assessment")
            if resumen:
                contenido.addWidget(self._etiqueta(self._sanear_texto(resumen)))
            eventos = hitos_relevantes_fase(fase, clave, self.contexto)
            if eventos:
                contenido.addWidget(self._separador_fase())
                contenido.addWidget(self._etiqueta("HITOS DE LA PARTIDA", "eyebrow"))
                for evento in eventos[:6]:
                    fila_widget = QWidget()
                    fila_widget.setObjectName("phaseEventRow")
                    fila = QHBoxLayout(fila_widget)
                    fila.setContentsMargins(0, 3, 0, 3)
                    fila.setSpacing(9)
                    hora = self._etiqueta(
                        str(evento.get("time_label") or "--:--"), "accent"
                    )
                    hora.setMinimumWidth(46)
                    hora.setAlignment(Qt.AlignmentFlag.AlignTop)
                    fila.addWidget(hora)
                    campeones = evento.get("champion_ids", [])
                    if evento.get("category") == "purchase" and evento.get("item_id"):
                        objeto = self._icono("item", str(evento["item_id"]), size=28)
                        objeto.setToolTip(
                            str(evento.get("item_name") or "Objeto comprado")
                        )
                        fila.addWidget(objeto)
                    elif campeones:
                        for campeon in campeones[:2]:
                            retrato = self._icono("champion", str(campeon), size=28)
                            retrato.setToolTip(str(campeon))
                            fila.addWidget(retrato)
                    else:
                        icono = QLabel(
                            self._glifo_evento(str(evento.get("category") or "other"))
                        )
                        icono.setFixedSize(28, 28)
                        icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
                        icono.setObjectName("phaseEventSymbol")
                        icono.setProperty(
                            "event_type", str(evento.get("category") or "other")
                        )
                        icono.setToolTip(str(evento.get("category") or "Evento"))
                        fila.addWidget(icono)
                    descripcion = self._etiqueta(
                        self._sanear_texto(evento.get("title") or "Evento registrado"),
                        "body",
                    )
                    descripcion.setObjectName("phaseEventTitle")
                    descripcion.setToolTip(
                        self._sanear_texto(evento.get("description") or "")
                    )
                    fila.addWidget(descripcion, 1)
                    contenido.addWidget(fila_widget)
            aciertos = self._combinar_textos(
                fase.get("what_worked"), fase.get("strengths")
            )
            errores = self._combinar_textos(
                fase.get("what_failed"), fase.get("mistakes")
            )
            acciones = self._combinar_textos(
                fase.get("adaptation"), fase.get("recommendations")
            )
            self._agregar_bloque_fase(contenido, "ACIERTOS", aciertos, "exito", "✓")
            self._agregar_bloque_fase(contenido, "A MEJORAR", errores, "error", "!")
            self._agregar_bloque_fase(
                contenido, "PRÓXIMA PARTIDA", acciones, "advertencia", "→"
            )
            widgets.append(tarjeta)
        return widgets or [
            self._tarjeta(
                titulo,
                [
                    "No hay eventos suficientes para evaluar esta fase.",
                    "Revisa el registro para concretar una adaptación.",
                ],
            )
            for titulo in (
                "Temprano · 0–15 min",
                "Medio · 15–25 min",
                "Tardío · 25+ min",
            )
        ]

    @staticmethod
    def _combinar_textos(principal: Any, adicionales: Any) -> list[str]:
        """Une contenido equivalente y elimina duplicados exactos normalizados."""
        valores = [principal] if isinstance(principal, str) else []
        if isinstance(adicionales, list):
            valores.extend(valor for valor in adicionales if isinstance(valor, str))
        resultado = []
        vistos = set()
        for valor in valores:
            limpio = str(valor).strip()
            clave = re.sub(r"\W+", " ", limpio.casefold()).strip()
            if limpio and clave not in vistos:
                vistos.add(clave)
                resultado.append(limpio)
        return resultado

    def _agregar_bloque_fase(
        self,
        layout: QVBoxLayout,
        titulo: str,
        textos: list[str],
        estado: str,
        glifo: str,
    ) -> None:
        """Añade una sección compacta y semánticamente acentuada a una fase."""
        if not textos:
            return
        fila = QHBoxLayout()
        fila.setSpacing(8)
        distintivo = QLabel(glifo)
        distintivo.setFixedSize(22, 22)
        distintivo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        distintivo.setObjectName("phaseCoachingSymbol")
        distintivo.setProperty("estado", estado)
        fila.addWidget(distintivo, 0, Qt.AlignmentFlag.AlignTop)
        bloque = QVBoxLayout()
        bloque.setSpacing(3)
        etiqueta = self._etiqueta(titulo, "eyebrow")
        etiqueta.setProperty(
            "role",
            {
                "exito": "phaseStrength",
                "error": "phaseError",
                "advertencia": "phaseAction",
            }.get(estado, "phaseAction"),
        )
        bloque.addWidget(etiqueta)
        for texto in textos[:2]:
            bloque.addWidget(self._etiqueta(self._sanear_texto(texto)))
        fila.addLayout(bloque, 1)
        layout.addLayout(fila)

    @staticmethod
    def _separador_fase() -> QFrame:
        """Crea un separador visual discreto para los hitos de fase."""
        separador = QFrame()
        separador.setObjectName("phaseDivider")
        separador.setFrameShape(QFrame.Shape.HLine)
        return separador

    @staticmethod
    def _glifo_evento(categoria: str) -> str:
        """Devuelve un símbolo semántico para eventos sin retrato aplicable."""
        return {"objective": "◎", "structure": "▣", "purchase": "◇", "kill": "⚔"}.get(
            categoria, "·"
        )

    def _rendimiento(self) -> list[QWidget]:
        """Agrupa categorías de rendimiento con la acción recomendada."""
        rendimiento = self.analisis.get("performance", {})
        nombres = {
            "farming": "Farmeo",
            "combat": "Combate",
            "objectives": "Objetivos",
            "vision": "Visión",
            "survivability": "Supervivencia",
            "decision_making": "Decisiones y posicionamiento",
        }
        tarjetas = []
        grados = self.analisis.get("coaching_grades", {})
        grados_categoria = (
            grados.get("categories", {}) if isinstance(grados, dict) else {}
        )
        categoria_grado = {
            "farming": "economia",
            "combat": "combate",
            "objectives": "objetivos",
            "vision": "vision",
            "survivability": "supervivencia",
        }
        for clave, titulo in nombres.items():
            datos = rendimiento.get(clave, {})
            lineas = [datos.get("assessment", "")]
            if datos.get("tip"):
                lineas.append(f"Siguiente paso: {datos['tip']}")
            if any(lineas):
                tarjeta = self._tarjeta(titulo, lineas)
                grado = grados_categoria.get(categoria_grado.get(clave, ""))
                if grado:
                    tarjeta.layout().insertWidget(1, self._etiqueta_grado(grado))
                tarjetas.append(tarjeta)
        tarjetas.extend(
            self._secciones(
                (
                    ("purchase_timing", "Compras y recalls"),
                    ("objective_conversion", "Conversión de objetivos"),
                    ("death_impact", "Impacto de las muertes"),
                )
            )
        )
        return tarjetas

    def _build(self) -> list[QWidget]:
        """Presenta identidad, inventario, revisiones, opciones y runas sin claves internas."""
        tarjetas: list[QWidget] = []
        datos = self.analisis.get("itemization", {})
        evaluacion = self.analisis.get("build_assessment") or datos.get(
            "assessment", ""
        )
        identidad = self.analisis.get("build_archetype") or datos.get("archetype")
        if evaluacion or identidad:
            tarjetas.append(
                self._tarjeta("Identidad y sinergia de build", [identidad, evaluacion])
            )
        inventario = self.contexto.get("user_stats", {}).get("items", [])
        if inventario:
            tarjeta = self._tarjeta("Inventario final observado", [])
            fila = QHBoxLayout()
            items = self.item_catalog.get("items", self.item_catalog)
            for identificador in inventario:
                item = (
                    items.get(str(identificador), {}) if isinstance(items, dict) else {}
                )
                nombre = (
                    str(item.get("name_es") or item.get("name") or "Objeto")
                    if isinstance(item, dict)
                    else "Objeto"
                )
                icono = self._icono("item", str(identificador), size=40)
                icono.setToolTip(nombre)
                fila.addWidget(icono)
            fila.addStretch(1)
            tarjeta.layout().addLayout(fila)
            tarjetas.append(tarjeta)
        for revision in self.analisis.get("item_reviews", []):
            tarjeta = self._tarjeta(
                f"{revision.get('verdict', 'Evaluación')} · {revision.get('name', 'Objeto observado')}",
                [
                    self._sanear_texto(revision.get("assessment", "")),
                    self._sanear_texto(revision.get("model_assessment", "")),
                ],
            )
            tarjeta.layout().insertWidget(
                1, self._icono("item", str(revision.get("item_id") or ""), size=34)
            )
            amenaza_ids = revision.get("threat_champion_ids", [])
            if amenaza_ids:
                fila = QHBoxLayout()
                fila.addWidget(self._etiqueta("Amenazas relacionadas", "muted"))
                for campeon in amenaza_ids[:3]:
                    retrato = self._retrato(str(campeon))
                    retrato.setToolTip(str(campeon))
                    fila.addWidget(retrato)
                tarjeta.layout().addLayout(fila)
            if revision.get("purchase_time"):
                tarjeta.layout().addWidget(
                    self._etiqueta(
                        f"Compra registrada · {revision['purchase_time']}", "muted"
                    )
                )
            tarjetas.append(tarjeta)
        for alternativa in self.analisis.get("item_alternatives", []):
            objetivo = (
                alternativa.get("target_item_name")
                or alternativa.get("name")
                or "Objeto"
            )
            tarjeta = self._tarjeta(
                f"Alternativa · {objetivo}",
                [
                    f"Amenaza · {alternativa.get('threat_champion', 'rival')}",
                    f"Ruta · {alternativa.get('component_name', 'componente')} → {objetivo}",
                    f"Cambiar o retrasar · {alternativa.get('replace_or_delay_item', 'sin referencia')}",
                    self._sanear_texto(alternativa.get("mechanical_advantage", "")),
                    self._sanear_texto(alternativa.get("tradeoff", "")),
                    self._sanear_texto(alternativa.get("timing", "")),
                ],
            )
            fila = QHBoxLayout()
            amenaza = alternativa.get("threat_champion_id")
            if amenaza:
                retrato = self._retrato(str(amenaza))
                retrato.setToolTip(str(amenaza))
                fila.addWidget(retrato)
            for clave in ("component_id", "replace_or_delay_item_id", "item_id"):
                if alternativa.get(clave):
                    icono = self._icono("item", str(alternativa[clave]), size=34)
                    icono.setToolTip(
                        str(
                            alternativa.get(
                                {
                                    "component_id": "component_name",
                                    "replace_or_delay_item_id": "replace_or_delay_item",
                                    "item_id": "target_item_name",
                                }[clave]
                            )
                            or "Objeto"
                        )
                    )
                    fila.addWidget(icono)
            tarjeta.layout().insertLayout(1, fila)
            if not alternativa.get("gold_on_hand_confirmed"):
                tarjeta.layout().addWidget(
                    self._etiqueta(
                        self._sanear_texto(
                            alternativa.get("affordability")
                            or "El oro exacto disponible en ese momento no consta en el registro."
                        ),
                        "muted",
                    )
                )
            tarjetas.append(tarjeta)
        if self.analisis.get("item_alternatives") and any(
            not item.get("gold_on_hand_confirmed")
            for item in self.analisis["item_alternatives"]
        ):
            tarjetas.append(
                self._tarjeta(
                    "Límite de asequibilidad",
                    [
                        "El oro exacto disponible en cada regreso no está registrado. Los costes comparan rutas; no confirman que pudieras comprarlas entonces."
                    ],
                )
            )
        runas = self.analisis.get("rune_comments", [])
        evaluacion_runa = self.analisis.get("rune_evaluation")
        nombres_runas = self._nombres_runa_observados()
        if runas or nombres_runas or evaluacion_runa:
            tarjeta = self._tarjeta("Runas · evaluación de sinergia", [])
            fila = QHBoxLayout()
            actual = (
                evaluacion_runa.get("current", {})
                if isinstance(evaluacion_runa, dict)
                else {}
            )
            nombre_actual = actual.get("name") or (
                nombres_runas[0] if nombres_runas else ""
            )
            if nombre_actual:
                fila.addWidget(self._icono("rune", str(nombre_actual), size=36))
                fila.addWidget(self._etiqueta(str(nombre_actual), "section"))
                if isinstance(evaluacion_runa, dict):
                    fila.addWidget(
                        self._etiqueta(
                            str(
                                evaluacion_runa.get("verdict") or "Evaluación limitada"
                            ),
                            "accent",
                        )
                    )
            alternativa = (
                evaluacion_runa.get("alternative")
                if isinstance(evaluacion_runa, dict)
                else None
            )
            if isinstance(alternativa, dict):
                nombre_alternativa = str(alternativa.get("name") or "")
                fila.addWidget(self._icono("rune", nombre_alternativa, size=36))
                fila.addWidget(self._etiqueta(nombre_alternativa, "section"))
            for nombre in nombres_runas[1:]:
                fila.addWidget(self._icono("rune", nombre, size=32))
                fila.addWidget(self._etiqueta(nombre, "muted"))
            fila.addStretch(1)
            tarjeta.layout().addLayout(fila)
            textos = (
                [evaluacion_runa.get("conclusion")]
                if isinstance(evaluacion_runa, dict)
                else runas
            )
            textos = [self._sanear_texto(texto) for texto in textos if texto]
            for texto in textos:
                tarjeta.layout().addWidget(self._etiqueta(texto))
            tarjetas.append(tarjeta)
        hechizos = self.contexto.get("user_stats", {}).get("summoner_spells", {})
        nombres_hechizos = self._nombres_desde_registro(hechizos)
        if nombres_hechizos:
            tarjeta = self._tarjeta("Hechizos de invocador", [])
            fila = QHBoxLayout()
            for nombre in nombres_hechizos:
                fila.addWidget(self._icono("spell", nombre, size=34))
                fila.addWidget(self._etiqueta(nombre, "muted"))
            fila.addStretch(1)
            tarjeta.layout().addLayout(fila)
            tarjetas.append(tarjeta)
        return tarjetas or [
            self._tarjeta(
                "Build",
                ["El registro no contiene inventario ni evaluación de objetos."],
            )
        ]

    def _nombres_runa_observados(self) -> list[str]:
        """Extrae nombres reales de runas desde el jugador guardado."""
        runas = self.contexto.get("user_stats", {}).get("runes", {})
        if not isinstance(runas, dict):
            return []
        nombres = []
        for clave in (
            "keystone",
            "primaryRuneTree",
            "primary_tree",
            "secondaryRuneTree",
            "secondary_tree",
        ):
            valor = runas.get(clave)
            nombre = self._nombre_de_registro(valor)
            if nombre and nombre not in nombres:
                nombres.append(nombre)
        if not nombres and isinstance(runas.get("live"), list):
            nombres.extend(
                nombre
                for nombre in (
                    self._nombre_de_registro(valor) for valor in runas["live"]
                )
                if nombre and nombre not in nombres
            )
        return nombres[:6]

    def _nombres_desde_registro(self, registro: Any) -> list[str]:
        """Extrae nombres de hechizos/runa desde valores LCU o serializados."""
        if isinstance(registro, dict):
            valores = list(registro.values())
        elif isinstance(registro, list):
            valores = registro
        else:
            valores = []
        nombres = [
            nombre
            for nombre in (self._nombre_de_registro(valor) for valor in valores)
            if nombre
        ]
        return list(dict.fromkeys(nombres))[:6]

    @staticmethod
    def _nombre_de_registro(valor: Any) -> str:
        """Lee un nombre visible en estructuras locales de runa o hechizo."""
        if isinstance(valor, dict):
            valor = (
                valor.get("displayName")
                or valor.get("name")
                or valor.get("display_name")
            )
        return str(valor).strip() if valor else ""

    def _secciones(self, secciones: tuple[tuple[str, str], ...]) -> list[QWidget]:
        """Convierte campos opcionales en tarjetas de lectura, sin inventar secciones."""
        widgets = []
        etiquetas = {
            "assessment": "Evaluación",
            "strengths": "Aciertos",
            "mistakes": "Errores",
            "recommendations": "Recomendaciones",
            "alternative_items": "Alternativas",
        }
        for clave, titulo in secciones:
            datos = self.analisis.get(clave)
            if not datos:
                continue
            lineas = []
            for propiedad, valor in datos.items():
                etiqueta = etiquetas.get(propiedad, propiedad)
                lineas.extend(
                    [f"{etiqueta}: {texto}" for texto in valor]
                    if isinstance(valor, list)
                    else [f"{etiqueta}: {valor}"]
                )
            widgets.append(self._tarjeta(titulo, lineas))
        return widgets or [
            self._tarjeta("Sin datos", ["El análisis no incluye estos apartados."])
        ]

    def _enfrentamientos(self) -> list[QWidget]:
        """Presenta tarjetas completas para los principales rivales observados."""
        rivales = self.analisis.get("key_enemies", [])
        if not rivales:
            return [
                self._tarjeta(
                    "Enfrentamientos",
                    [
                        "La partida guardada no contiene participantes enemigos identificables."
                    ],
                )
            ]
        grupo = QButtonGroup(self)
        grupo.setExclusive(True)
        tarjetas = []
        for indice, rival in enumerate(rivales):
            nombre = str(rival.get("champion_name") or f"Rival {indice + 1}")
            rol = str(rival.get("role") or "Rol no disponible")
            amenaza = str(
                rival.get("threat_level") or rival.get("difficulty") or "observado"
            )
            boton = QPushButton(f"{nombre}  ·  {rol}  ·  Amenaza {amenaza}")
            boton.setFont(QFont("Segoe UI", 10))
            boton.setCheckable(True)
            boton.setProperty("difficulty", self._clave_dificultad(amenaza))
            boton.setObjectName("matchupChampionButton")
            boton.setToolTip(nombre)
            grupo.addButton(boton, indice)
            tarjeta = QFrame()
            tarjeta.setObjectName("matchAnalysisCard")
            tarjeta.setProperty("superficie", "tarjeta")
            tarjeta.setProperty("seleccionado", "false")
            contenido = QHBoxLayout(tarjeta)
            contenido.setContentsMargins(12, 10, 12, 10)
            contenido.setSpacing(10)
            bloque = QVBoxLayout()
            bloque.addWidget(boton)
            kda = rival.get("kda")
            if isinstance(kda, dict):
                bloque.addWidget(
                    self._etiqueta(
                        f"KDA {kda.get('kills', 0)}/{kda.get('deaths', 0)}/{kda.get('assists', 0)}",
                        "muted",
                    )
                )
            contenido.addWidget(self._retrato(nombre))
            contenido.addLayout(bloque, 1)
            boton.clicked.connect(
                lambda checked=False, posicion=indice: self._seleccionar_rival(posicion)
            )
            detalle = QVBoxLayout()
            for titulo, clave in (
                ("Por qué importó", "why_it_was_a_problem"),
                ("Fortalezas observadas", "strengths"),
                ("Herramientas peligrosas", "dangerous_tools"),
                ("Cómo jugarle", "how_to_play_against"),
                ("Nota de línea", "matchup_note"),
                ("Interacción de objetos", "itemization_interaction"),
            ):
                valor = rival.get(clave)
                if not valor:
                    continue
                detalle.addWidget(self._etiqueta(titulo, "eyebrow"))
                textos = valor if isinstance(valor, list) else [str(valor)]
                for texto in textos:
                    fila = QHBoxLayout()
                    habilidad = re.search(r"\b([QWER])\b", texto, re.IGNORECASE)
                    if habilidad:
                        fila.addWidget(
                            self._icono("ability", habilidad.group(1), nombre, 28)
                        )
                    fila.addWidget(self._etiqueta(texto), 1)
                    detalle.addLayout(fila)
            for habilidad in rival.get("dangerous_abilities", []):
                if not isinstance(habilidad, dict):
                    continue
                fila = QHBoxLayout()
                fila.addWidget(
                    self._icono("ability", str(habilidad.get("slot") or ""), nombre, 30)
                )
                descripcion = str(habilidad.get("description") or "")
                contrajuego = str(habilidad.get("counterplay") or "")
                nombre_habilidad = str(
                    habilidad.get("name") or habilidad.get("slot") or ""
                )
                fila.addWidget(
                    self._etiqueta(
                        f"{nombre_habilidad}: {descripcion} {contrajuego} (mecánica del campeón; no consta como lanzamiento observado)",
                        "muted",
                    ),
                    1,
                )
                detalle.addLayout(fila)
            referencias = rival.get("interaction_references", [])
            if referencias:
                detalle.addWidget(
                    self._etiqueta(
                        "Interacciones registradas · " + ", ".join(referencias[:6]),
                        "accent",
                    )
                )
            contenido.addLayout(detalle, 2)
            tarjetas.append(tarjeta)
            self._botones_rivales.append(boton)
            self._tarjetas_rivales.append(tarjeta)
        self._botones_rivales[0].setChecked(True)
        self._seleccionar_rival(0)
        return tarjetas

    @staticmethod
    def _clave_dificultad(dificultad: str) -> str:
        """Clasifica la dificultad textual para aplicar un acento semántico."""
        texto = dificultad.casefold()
        if "difícil" in texto or "dificil" in texto or "hard" in texto:
            return "hard"
        if "fácil" in texto or "facil" in texto or "easy" in texto:
            return "easy"
        return "normal"

    def _seleccionar_rival(self, indice: int) -> None:
        """Actualiza el panel del rival seleccionado sin reconstruir la navegación."""
        rivales = self.analisis.get("key_enemies", [])
        if not 0 <= indice < len(rivales):
            return
        self._rival_seleccionado = indice
        for posicion, boton in enumerate(self._botones_rivales):
            boton.setChecked(posicion == indice)
            tarjeta = self._tarjetas_rivales[posicion]
            tarjeta.setProperty(
                "seleccionado", "true" if posicion == indice else "false"
            )
            tarjeta.style().unpolish(tarjeta)
            tarjeta.style().polish(tarjeta)
        for posicion, tarjeta in enumerate(self._tarjetas_rivales):
            tarjeta.setProperty(
                "seleccionado", "true" if posicion == indice else "false"
            )
            tarjeta.style().unpolish(tarjeta)
            tarjeta.style().polish(tarjeta)

    def _mejoras(self) -> list[QWidget]:
        """Ordena prioridades y presenta una acción concreta por tarjeta."""
        prioridades = self.analisis.get("next_game_priorities") or self.analisis.get(
            "improvement_priorities", []
        )
        prioridades = sorted(
            prioridades,
            key=lambda elemento: {"high": 0, "medium": 1, "low": 2}.get(
                str(elemento.get("priority", "")).lower(), 3
            ),
        )
        widgets = []
        for elemento in prioridades:
            prioridad = {
                "high": "ALTA",
                "medium": "MEDIA",
                "low": "ENFOQUE",
            }.get(str(elemento.get("priority", "")).lower(), "PRIORIDAD")
            contenido = [elemento.get("explanation", "")]
            if elemento.get("evidence"):
                contenido.append(f"Evidencia: {elemento['evidence']}")
            accion = elemento.get("concrete_action") or elemento.get("action")
            if accion:
                contenido.append(f"Siguiente partida: {accion}")
            tarjeta = self._tarjeta(
                f"{prioridad or 'PRIORIDAD'} · {elemento.get('title', 'Mejora')}",
                contenido,
            )
            contexto = {
                "objective": "OBJETIVOS",
                "early_game": "INICIO",
                "late_game": "CIERRE",
                "item": "OBJETOS",
                "vision": "VISIÓN",
                "lane": "LÍNEA",
                "teamfight": "COMBATES",
                "matchup": "ENFRENTAMIENTO",
                "ability": "HABILIDAD",
                "macro": "MACRO",
            }.get(str(elemento.get("context_type", "")), "")
            referencia = elemento.get("reference", "")
            if elemento.get("item_id"):
                tarjeta.layout().insertWidget(
                    1, self._icono("item", str(elemento["item_id"]), size=36)
                )
            elif elemento.get("champion_id"):
                tarjeta.layout().insertWidget(
                    1, self._icono("champion", str(elemento["champion_id"]), size=36)
                )
            elif referencia:
                tarjeta.layout().insertWidget(
                    1, self._etiqueta(f"Referencia · {referencia}", "accent")
                )
            elif contexto:
                insignia = self._etiqueta(contexto.replace("_", " ").upper(), "accent")
                tarjeta.layout().insertWidget(1, insignia)
            widgets.append(tarjeta)
        return widgets or [
            self._tarjeta(
                "Prioridades para la próxima partida",
                ["El informe no proporcionó prioridades estructuradas."],
            )
        ]
