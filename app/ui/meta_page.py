"""Página Meta con estadísticas LoLalytics Emerald+ y notas oficiales de Riot."""

from __future__ import annotations

import copy
import re
from typing import Any
from uuid import uuid4

from PySide6.QtCore import QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QDesktopServices,
    QImage,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.services.meta_service import ServicioMeta
from app.services.settings_service import SettingsService
from app.ui.async_task import run_async
from app.ui.sistema_visual import PALETA


class PaginaMeta(QWidget):
    """Presenta filtros competitivos, tier list y las últimas notas del parche."""

    ORDEN_TIERS = (
        "S+",
        "S",
        "S-",
        "A+",
        "A",
        "A-",
        "B+",
        "B",
        "B-",
        "C+",
        "C",
        "C-",
        "D+",
        "D",
        "D-",
    )
    ACENTOS_TIER = {
        "S": PALETA["oro_suave"],
        "A": PALETA["teal"],
        "B": "#829bb6",
        "C": "#c99a68",
        "D": PALETA["desventaja"],
    }

    def __init__(self, assets: Any = None, parent: QWidget | None = None) -> None:
        """Prepara interfaz y carga las fuentes en segundo plano; retorna None."""
        super().__init__(parent)
        self.setObjectName("metaPage")
        self.servicio = ServicioMeta()
        self.settings_service = SettingsService()
        self.assets = assets
        self.datos_tier: dict[str, Any] = {}
        self.datos_notas: dict[str, Any] = {}
        self._columnas_tier = 0
        self._cuadriculas_tier: list[tuple[QGridLayout, list[TarjetaMetaCampeon]]] = []
        self._temporizador_redimension_tier = QTimer(self)
        self._temporizador_redimension_tier.setSingleShot(True)
        self._temporizador_redimension_tier.setInterval(140)
        self._temporizador_redimension_tier.timeout.connect(
            self._recolocar_tier_tras_resize
        )
        self._estado_tier_base = "Consultando LoLalytics Emerald+…"
        self._tiers_expandidos: dict[str, bool] = {}
        self.setStyleSheet(
            f"""
            QWidget#metaPage {{ background:transparent; color:{PALETA["texto"]}; }}
            QFrame#metaCard {{ background:{PALETA["superficie"]}; border:1px solid {PALETA["oro_oscuro"]}; border-radius:12px; }}
            QFrame#metaTierSection {{ background:{PALETA["superficie"]}; border:1px solid {PALETA["borde_sutil"]}; border-radius:14px; }}
            QFrame#metaChampionCard {{ background:{PALETA["elevada"]}; border:1px solid {PALETA["borde_sutil"]}; border-radius:12px; }}
            QFrame#metaChampionCard:hover {{ background:{PALETA["hover"]}; border-color:{PALETA["oro_oscuro"]}; }}
            QPushButton {{ background:{PALETA["elevada"]}; color:{PALETA["texto"]}; border:1px solid {PALETA["borde"]}; border-radius:7px; padding:7px 12px; }}
            QPushButton:hover {{ border-color:{PALETA["oro"]}; }}
            QComboBox,QLineEdit {{ background:{PALETA["base"]}; color:{PALETA["texto"]}; border:1px solid {PALETA["borde"]}; border-radius:6px; padding:6px; }}
            QScrollArea {{ background:transparent; border:0; }}
            """
        )
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(18, 12, 18, 18)
        raiz.setSpacing(12)
        titulo = QLabel("Meta de League of Legends")
        titulo.setStyleSheet(
            f"font-size:24px;font-weight:700;color:{PALETA['marfil']};"
        )
        raiz.addWidget(titulo)
        subtitulo = QLabel(
            "Clasificaciones de campeones, estadísticas competitivas y últimas actualizaciones."
        )
        subtitulo.setStyleSheet(f"color:{PALETA['secundario']};")
        raiz.addWidget(subtitulo)
        self.info = QLabel(
            "Fuente: LoLalytics · Esmeralda+ · Parche: — · Actualizado: — · Europe West (EUW) · Ranked Solo/Duo"
        )
        self.info.setObjectName("metaInfo")
        self.info.setWordWrap(True)
        raiz.addWidget(self.info)
        filtros = QHBoxLayout()
        self.rol = self._combo(
            filtros,
            "Rol",
            [
                ("top", "Top"),
                ("jungle", "Jungle"),
                ("mid", "Mid"),
                ("adc", "ADC"),
                ("support", "Support"),
            ],
        )
        self.region = self._combo(
            filtros,
            "Región",
            [
                ("euw", "Europe West (EUW)"),
                ("na", "North America (NA)"),
                ("kr", "Korea (KR)"),
                ("all", "World"),
            ],
        )
        region_guardada = str(
            self.settings_service.load().get("meta_region", "euw")
        ).casefold()
        indice_region = self.region.findData(region_guardada)
        self.region.setCurrentIndex(
            indice_region if indice_region >= 0 else self.region.findData("euw")
        )
        rango_fijo = QVBoxLayout()
        rango_titulo = QLabel("RANGO")
        rango_titulo.setStyleSheet(f"font-size:11px;color:{PALETA['secundario']};")
        rango_fijo.addWidget(rango_titulo)
        self.rango_etiqueta = QLabel("Esmeralda+")
        self.rango_etiqueta.setObjectName("metaRankFixed")
        self.rango_etiqueta.setToolTip(
            "Todas las estadísticas usan el bracket Emerald+ de LoLalytics"
        )
        self.rango_etiqueta.setStyleSheet(
            f"color:{PALETA['oro_suave']};font-weight:700;padding:6px 10px;border:1px solid {PALETA['oro_oscuro']};border-radius:6px;background:{PALETA['base']};"
        )
        rango_fijo.addWidget(self.rango_etiqueta)
        filtros.addLayout(rango_fijo)
        self.busqueda = QLineEdit()
        self.busqueda.setPlaceholderText("Buscar campeón")
        filtros.addWidget(self.busqueda, 1)
        refrescar = QPushButton("Actualizar")
        refrescar.clicked.connect(self.actualizar)
        filtros.addWidget(refrescar)
        fuente_lolalytics = QPushButton("LoLalytics ↗")
        fuente_lolalytics.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(ServicioMeta.URL_TIER))
        )
        filtros.addWidget(fuente_lolalytics)
        raiz.addLayout(filtros)
        self.pestanas = QTabWidget()
        self.pestanas.setObjectName("metaTabs")
        raiz.addWidget(self.pestanas, 1)
        self.tier_tab = QWidget()
        tier_tab_layout = QVBoxLayout(self.tier_tab)
        tier_tab_layout.setContentsMargins(0, 10, 0, 0)
        tier_tab_layout.setSpacing(10)
        self.resumen_tier = QFrame()
        self.resumen_tier.setObjectName("metaCard")
        resumen_layout = QHBoxLayout(self.resumen_tier)
        resumen_layout.setContentsMargins(14, 10, 14, 10)
        resumen_layout.setSpacing(10)
        self.resumen_conteo = QLabel("Esperando datos de LoLalytics")
        self.resumen_conteo.setStyleSheet(f"color:{PALETA['marfil']};font-weight:700;")
        resumen_layout.addWidget(self.resumen_conteo, 1)
        orden_layout = QHBoxLayout()
        orden_titulo = QLabel("ORDENAR")
        orden_titulo.setStyleSheet(
            f"font-size:10px;color:{PALETA['secundario']};font-weight:700;"
        )
        orden_layout.addWidget(orden_titulo)
        self.orden_tier = QComboBox()
        self.orden_tier.addItem("Ranking LoLalytics", "position")
        self.orden_tier.addItem("Win rate", "win_rate")
        self.orden_tier.addItem("Pick rate", "pick_rate")
        self.orden_tier.addItem("Ban rate", "ban_rate")
        self.orden_tier.addItem("Muestra", "sample_size")
        self.orden_tier.currentIndexChanged.connect(self._pintar_tier)
        orden_layout.addWidget(self.orden_tier)
        resumen_layout.addLayout(orden_layout)
        tier_tab_layout.addWidget(self.resumen_tier)
        self.estado_card = QFrame()
        self.estado_card.setObjectName("metaCard")
        estado_layout = QHBoxLayout(self.estado_card)
        estado_layout.setContentsMargins(14, 9, 14, 9)
        self.estado_marca = QLabel("◌")
        self.estado_marca.setFixedWidth(20)
        self.estado_marca.setStyleSheet(f"color:{PALETA['oro_suave']};font-weight:700;")
        estado_layout.addWidget(self.estado_marca)
        self.estado = QLabel("Consultando LoLalytics y fuentes oficiales de Riot…")
        self.estado.setWordWrap(True)
        estado_layout.addWidget(self.estado, 1)
        tier_tab_layout.addWidget(self.estado_card)
        self.tier_scroll = QScrollArea()
        self.tier_scroll.setWidgetResizable(True)
        self.tier_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.tier_contenido = QWidget()
        self.tier_layout = QVBoxLayout(self.tier_contenido)
        self.tier_layout.setContentsMargins(2, 2, 8, 12)
        self.tier_layout.setSpacing(12)
        self.tier_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.tier_scroll.setWidget(self.tier_contenido)
        tier_tab_layout.addWidget(self.tier_scroll, 1)
        self.pestanas.addTab(self.tier_tab, "Tier List")
        self.notas_scroll = QScrollArea()
        self.notas_scroll.setWidgetResizable(True)
        self.notas_contenido = QWidget()
        self.notas_layout = QVBoxLayout(self.notas_contenido)
        self.notas_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.notas_scroll.setWidget(self.notas_contenido)
        self.pestanas.addTab(self.notas_scroll, "Notas del parche")
        self.temporizador_notas = QTimer(self)
        self.temporizador_notas.setInterval(6 * 60 * 60 * 1000)
        self.temporizador_notas.timeout.connect(self._comprobar_notas)
        self.temporizador_notas.start()
        for combo in (self.rol, self.region):
            combo.currentIndexChanged.connect(self._filtro_cambiado)
        self.region.currentIndexChanged.connect(self._guardar_region)
        self.busqueda.textChanged.connect(self._pintar_tier)
        self._mostrar_estado(self._estado_tier_base, "cargando")
        self.actualizar_tier(False)
        run_async(
            lambda: self.servicio.obtener_notas(False), on_finished=self._recibir_notas
        )

    def _combo(
        self, layout: QHBoxLayout, etiqueta: str, opciones: list[tuple[str, str]]
    ) -> QComboBox:
        """Añade un selector etiquetado; recibe disposición/opciones y retorna selector."""
        envoltura = QVBoxLayout()
        nombre = QLabel(etiqueta)
        nombre.setStyleSheet(f"font-size:11px;color:{PALETA['secundario']};")
        combo = QComboBox()
        for clave, texto in opciones:
            combo.addItem(texto, clave)
        envoltura.addWidget(nombre)
        envoltura.addWidget(combo)
        layout.addLayout(envoltura)
        return combo

    def actualizar(self) -> None:
        """Lanza en background la lectura de notas y clasificación; retorna None."""
        self.actualizar_tier(True)
        run_async(
            lambda: self.servicio.obtener_notas(True), on_finished=self._recibir_notas
        )

    def _comprobar_notas(self) -> None:
        """Comprueba periódicamente si Riot publicó una versión más reciente."""
        run_async(
            lambda: self.servicio.obtener_notas(False), on_finished=self._recibir_notas
        )

    def _filtro_cambiado(self, indice: int) -> None:
        """Recarga el contexto nuevo sin forzar una descarga fuera de TTL."""
        self.actualizar_tier(False)

    def _guardar_region(self, indice: int) -> None:
        """Persiste la última región elegida para restaurarla en futuras aperturas."""
        try:
            ajustes = self.settings_service.load()
            ajustes["meta_region"] = str(self.region.currentData() or "euw")
            self.settings_service.save(ajustes)
        except (OSError, ValueError, TypeError):
            return

    def actualizar_tier(self, forzar: bool = False) -> None:
        """Solicita estadísticas para el contexto seleccionado sin bloquear Qt."""
        filtros = {
            "role": str(self.rol.currentData()),
            "rank": ServicioMeta.RANGO_TIER,
            "region": str(self.region.currentData()),
            "mode": ServicioMeta.COLA_TIER,
        }
        self.datos_tier = {}
        self._estado_tier_base = "Consultando LoLalytics Emerald+…"
        self._mostrar_estado(self._estado_tier_base, "cargando")
        self._actualizar_info()
        run_async(
            lambda: self.servicio.obtener_lista_niveles(filtros, forzar),
            on_finished=self._recibir_tier,
            token=filtros,
        )

    def _recibir_tier(self, token: Any, datos: Any, error: str | None) -> None:
        """Actualiza la tabla o presenta error y caché local; retorna None."""
        filtros_actuales = {
            "role": str(self.rol.currentData()),
            "rank": ServicioMeta.RANGO_TIER,
            "region": str(self.region.currentData()),
            "mode": ServicioMeta.COLA_TIER,
        }
        if token != filtros_actuales:
            return
        if isinstance(datos, dict):
            self.datos_tier = datos
            if datos.get("stale"):
                estado = "LoLalytics · caché posiblemente desactualizada. "
            elif datos.get("cached"):
                estado = "LoLalytics · caché válida. "
            else:
                estado = "LoLalytics · actualizado. "
            self._estado_tier_base = estado + str(
                datos.get("cache_error") or error or ""
            )
        else:
            self.datos_tier = {}
            self._estado_tier_base = f"No se pudieron recuperar estadísticas de LoLalytics Emerald+. {error or ''} No hay una caché válida para estos filtros; no se muestran datos sustitutos. Pulsa Actualizar para reintentar."
        self._pintar_tier()
        if self.datos_tier:
            self._actualizar_info()

    def _pintar_tier(self) -> None:
        """Agrupa campeones por tier y dibuja tarjetas ordenables sin pedir datos nuevos."""
        filas = self.datos_tier.get("champions", [])
        texto = self.busqueda.text().casefold().strip()
        filas = [
            fila
            for fila in filas
            if texto
            in f"{fila.get('name', '')} {fila.get('source_name', '')}".casefold()
        ]
        self._vaciar_layout(self.tier_layout)
        tiers = sorted(
            {str(campeon.get("tier") or "?") for campeon in filas},
            key=lambda tier: (
                self.ORDEN_TIERS.index(tier)
                if tier in self.ORDEN_TIERS
                else len(self.ORDEN_TIERS)
            ),
        )
        cantidad = len(filas)
        self.resumen_conteo.setText(
            f"{cantidad} campeones  ·  {len(tiers)} tiers  ·  {self.rol.currentText()}  ·  {self.region.currentText()}"
        )
        if self.datos_tier and not filas:
            consulta = self.busqueda.text().strip()
            mensaje = (
                f"Sin campeones que coincidan con «{consulta}»."
                if consulta
                else "La fuente no devolvió campeones para estos filtros."
            )
            self._mostrar_estado(mensaje, "vacio")
        else:
            tipo = (
                "error"
                if self._estado_tier_base.startswith("No se pudieron")
                else "obsoleto"
                if self.datos_tier.get("stale")
                else "cache"
                if self.datos_tier.get("cached")
                else "cargando"
                if self._estado_tier_base.startswith("Consultando")
                else "correcto"
            )
            self._mostrar_estado(self._estado_tier_base, tipo)
        if not filas:
            self._añadir_estado_contenido()
            return
        orden = str(self.orden_tier.currentData() or "position")
        columnas = max(
            1, min(3, (self.tier_scroll.viewport().width() or self.width()) // 420)
        )
        self._columnas_tier = columnas
        self._cuadriculas_tier = []
        for tier in tiers:
            campeones = [item for item in filas if str(item.get("tier") or "?") == tier]
            descendente = orden != "position"
            campeones.sort(key=lambda item: self._clave_orden(item, orden, descendente))
            self._crear_seccion_tier(tier, campeones, columnas)
        self.tier_layout.addStretch(1)

    def _recolocar_tier_tras_resize(self) -> None:
        """Recoloca las tarjetas existentes tras estabilizar el ancho, sin reconstruirlas."""
        ancho = self.tier_scroll.viewport().width() or self.width()
        columnas = max(1, min(3, ancho // 420))
        if columnas == self._columnas_tier:
            return
        self._columnas_tier = columnas
        actualizaciones_activas = self.tier_scroll.updatesEnabled()
        if actualizaciones_activas:
            self.tier_scroll.setUpdatesEnabled(False)
        try:
            for cuadrilla, tarjetas in self._cuadriculas_tier:
                while cuadrilla.count():
                    cuadrilla.takeAt(0)
                for indice, tarjeta in enumerate(tarjetas):
                    cuadrilla.addWidget(tarjeta, indice // columnas, indice % columnas)
                for columna in range(max(3, columnas)):
                    cuadrilla.setColumnStretch(columna, int(columna < columnas))
        finally:
            if actualizaciones_activas:
                self.tier_scroll.setUpdatesEnabled(True)
                self.tier_scroll.viewport().update()

    def _añadir_estado_contenido(self) -> None:
        """Muestra un estado visual intencional cuando aún no hay tarjetas disponibles."""
        cargando = self._estado_tier_base.startswith("Consultando")
        error = self._estado_tier_base.startswith("No se pudieron")
        titulo = "Consultando LoLalytics" if cargando else "No hay datos para mostrar"
        detalle = (
            "Se está cargando la clasificación Esmeralda+ para los filtros seleccionados."
            if cargando
            else self._estado_tier_base
            if error
            else "Prueba con otro nombre de campeón o actualiza la clasificación para estos filtros."
        )
        tarjeta = QFrame()
        tarjeta.setObjectName("metaCard")
        tarjeta.setMinimumHeight(160)
        tarjeta_layout = QVBoxLayout(tarjeta)
        tarjeta_layout.setContentsMargins(22, 20, 22, 20)
        marca = QLabel("META  /  TIER LIST")
        marca.setObjectName("metaEyebrow")
        encabezado = QLabel(titulo)
        encabezado.setObjectName("metaSectionTitle")
        encabezado.setAlignment(Qt.AlignmentFlag.AlignCenter)
        texto = QLabel(detalle)
        texto.setObjectName("metaMuted")
        texto.setWordWrap(True)
        texto.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tarjeta_layout.addWidget(marca, alignment=Qt.AlignmentFlag.AlignCenter)
        tarjeta_layout.addStretch(1)
        tarjeta_layout.addWidget(encabezado)
        tarjeta_layout.addWidget(texto)
        tarjeta_layout.addStretch(1)
        self.tier_layout.addWidget(tarjeta)

    @staticmethod
    def _clave_orden(
        campeon: dict[str, Any], clave: str, descendente: bool
    ) -> tuple[bool, float]:
        """Devuelve orden numérico estable y mantiene valores ausentes al final."""
        valor = campeon.get(clave)
        if not isinstance(valor, (int, float)):
            return True, 0.0
        return False, -float(valor) if descendente else float(valor)

    @staticmethod
    def _vaciar_layout(layout: QVBoxLayout) -> None:
        """Retira y programa la liberación de widgets anteriores de una disposición."""
        while layout.count():
            elemento = layout.takeAt(0)
            widget = elemento.widget()
            if widget is not None:
                widget.deleteLater()

    def _crear_seccion_tier(
        self, tier: str, campeones: list[dict[str, Any]], columnas: int
    ) -> None:
        """Construye bloque plegable de tier con mosaico de tarjetas de campeón."""
        seccion = QFrame()
        seccion.setObjectName("metaTierSection")
        acento = self.ACENTOS_TIER.get(tier[:1], PALETA["oro"])
        seccion.setStyleSheet(
            f"QFrame#metaTierSection {{ border:1px solid {PALETA['borde_sutil']}; border-left:3px solid {acento}; background:{PALETA['superficie']}; border-radius:14px; }}"
        )
        seccion_layout = QVBoxLayout(seccion)
        seccion_layout.setContentsMargins(10, 8, 10, 10)
        seccion_layout.setSpacing(7)
        cabecera = QHBoxLayout()
        toggle = QToolButton()
        toggle.setCheckable(True)
        expandido = self._tiers_expandidos.get(tier, True)
        toggle.setChecked(expandido)
        toggle.setText("⌄" if expandido else "›")
        toggle.setFixedSize(22, 22)
        toggle.setStyleSheet(
            f"QToolButton {{ background:transparent; color:{acento}; border:0; font-size:16px; font-weight:700; }}"
        )
        cabecera.addWidget(toggle)
        insignia = QLabel(f"TIER  {tier}")
        insignia.setStyleSheet(
            f"background:{PALETA['base']};color:{acento};border:1px solid {acento};border-radius:7px;padding:4px 9px;font-weight:800;letter-spacing:1px;"
        )
        cabecera.addWidget(insignia)
        cabecera.addWidget(QLabel(f"{len(campeones)} campeones"))
        cabecera.addStretch(1)
        nota = QLabel("CLASIFICACIÓN LO LALYTICS")
        nota.setStyleSheet(
            f"color:{PALETA['tenue']};font-size:10px;font-weight:700;letter-spacing:1px;"
        )
        cabecera.addWidget(nota)
        seccion_layout.addLayout(cabecera)
        cuerpo = QWidget()
        cuerpo.setStyleSheet("background:transparent;")
        cuadrilla = QGridLayout(cuerpo)
        cuadrilla.setContentsMargins(0, 0, 0, 0)
        cuadrilla.setHorizontalSpacing(10)
        cuadrilla.setVerticalSpacing(8)
        tarjetas: list[TarjetaMetaCampeon] = []
        for indice, campeon in enumerate(campeones):
            tarjeta = TarjetaMetaCampeon(campeon, acento, self.assets)
            tarjeta.activado.connect(self._abrir_detalle_campeon)
            tarjetas.append(tarjeta)
            cuadrilla.addWidget(tarjeta, indice // columnas, indice % columnas)
        for columna in range(columnas):
            cuadrilla.setColumnStretch(columna, 1)
        self._cuadriculas_tier.append((cuadrilla, tarjetas))
        cuerpo.setVisible(expandido)
        seccion_layout.addWidget(cuerpo)
        toggle.toggled.connect(
            lambda abierto, panel=cuerpo, boton=toggle, clave=tier: (
                self._cambiar_expansion_tier(clave, panel, boton, abierto)
            )
        )
        self.tier_layout.addWidget(seccion)

    def _cambiar_expansion_tier(
        self, tier: str, cuerpo: QWidget, boton: QToolButton, expandido: bool
    ) -> None:
        """Guarda estado plegado del tier y muestra el indicador correspondiente."""
        self._tiers_expandidos[tier] = expandido
        cuerpo.setVisible(expandido)
        boton.setText("⌄" if expandido else "›")

    def _mostrar_estado(self, texto: str, tipo: str) -> None:
        """Viste carga, caché, vacío o error en una tarjeta de estado premium."""
        color = {
            "cargando": PALETA["oro_suave"],
            "correcto": PALETA["ventaja"],
            "cache": PALETA["informacion"],
            "obsoleto": PALETA["advertencia"],
            "vacio": PALETA["advertencia"],
            "error": PALETA["desventaja"],
        }.get(tipo, PALETA["secundario"])
        self.estado.setText(texto)
        self.estado_marca.setText("◌" if tipo == "cargando" else "●")
        self.estado_marca.setStyleSheet(f"color:{color};font-weight:700;")
        self.estado.setStyleSheet(
            f"color:{color if tipo in {'error', 'obsoleto'} else PALETA['texto']};"
        )
        self.estado_card.setVisible(tipo != "correcto")

    def resizeEvent(self, evento: QResizeEvent) -> None:
        """Recalcula columnas del mosaico al cambiar el tamaño de la página."""
        super().resizeEvent(evento)
        ancho = self.tier_scroll.viewport().width() or self.width()
        columnas = max(1, min(3, ancho // 420))
        if self.datos_tier.get("champions") and columnas != self._columnas_tier:
            self._temporizador_redimension_tier.start()

    def _abrir_detalle_campeon(self, campeon: dict[str, Any]) -> None:
        """Abre detalles de LoLalytics para la tarjeta de campeón activada."""
        dialogo = QDialog(self)
        dialogo.setWindowTitle(str(campeon.get("name", "Campeón")))
        dialogo.setMinimumWidth(380)
        layout = QVBoxLayout(dialogo)
        for etiqueta, clave in (
            ("Tier LoLalytics", "tier"),
            ("Posición", "position"),
            ("Rol", "role"),
            ("Win rate", "win_rate"),
            ("Pick rate", "pick_rate"),
            ("Ban rate", "ban_rate"),
            ("Muestra", "sample_size"),
            ("Parche", "patch"),
            ("Región", "region"),
            ("Rango", "rank"),
            ("Cola", "queue"),
        ):
            if campeon.get(clave) is not None:
                layout.addWidget(QLabel(f"{etiqueta}: {campeon[clave]}"))
        if self.assets:
            boton = QPushButton("Abrir análisis local")
            boton.clicked.connect(
                lambda: self._abrir_analisis(campeon.get("name", ""), dialogo)
            )
            layout.addWidget(boton)
        dialogo.exec()

    def _abrir_analisis(self, campeon: str, dialogo: QDialog) -> None:
        """Abre análisis existente para el campeón seleccionado y cierra detalle."""
        dialogo.accept()
        ventana = self.window()
        if hasattr(ventana, "analysis_button"):
            ventana.analysis_button.click()
            pagina = ventana.pages.widget(1)
            selector = getattr(pagina, "champion_combo", None)
            if selector is not None:
                selector.setCurrentText(campeon)

    def _recibir_notas(self, token: Any, datos: Any, error: str | None) -> None:
        """Pinta el lector jerárquico de notas oficiales o indica fallo de consulta."""
        if isinstance(datos, dict):
            self.datos_notas = datos
        else:
            self.datos_notas = self.servicio.cargar_cache("patch_notes.json") or {}
            if self.datos_notas:
                self.datos_notas["cached"] = True
        if (
            self.datos_notas
            and self.datos_notas.get("schema_version")
            != ServicioMeta.VERSION_ESQUEMA_NOTAS
        ):
            self.datos_notas = self._adaptar_cache_notas_antigua(self.datos_notas)
        while self.notas_layout.count():
            elemento = self.notas_layout.takeAt(0)
            if elemento.widget():
                elemento.widget().deleteLater()
        if not self.datos_notas:
            self.notas_layout.addWidget(
                self._tarjeta_mensaje(
                    f"No se pudieron cargar las notas oficiales. {error or 'Comprueba la conexión e inténtalo de nuevo.'}"
                )
            )
            return
        datos = self.datos_notas
        cabecera = QFrame()
        cabecera.setObjectName("metaCard")
        cabecera_layout = QVBoxLayout(cabecera)
        cabecera_layout.setContentsMargins(20, 16, 20, 16)
        fila = QHBoxLayout()
        encabezado = QLabel(
            f"Parche {datos.get('version')} · {datos.get('title', 'Notas oficiales')}"
        )
        encabezado.setWordWrap(True)
        encabezado.setStyleSheet(
            f"font-size:20px;font-weight:700;color:{PALETA['marfil']};"
        )
        fila.addWidget(encabezado, 1)
        boton = QPushButton("Ver notas oficiales")
        boton.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl(datos.get("url", ServicioMeta.URL_NOTAS))
            )
        )
        fila.addWidget(boton)
        cabecera_layout.addLayout(fila)
        fecha = self._formatear_fecha(
            datos.get("published") or datos.get("retrieved_at", "")
        )
        estado = "Copia local" if datos.get("cached") else "Fuente oficial de Riot"
        subtitulo = QLabel(f"Publicado: {fecha} · {estado}")
        subtitulo.setStyleSheet(f"color:{PALETA['secundario']};")
        cabecera_layout.addWidget(subtitulo)
        self.notas_layout.addWidget(cabecera)
        ruta_imagen = datos.get("hero_image_path")
        imagen = QPixmap(str(ruta_imagen)) if ruta_imagen else QPixmap()
        if not imagen.isNull():
            visual = ImagenParche(imagen)
            self.notas_layout.addWidget(visual)
        secciones = datos.get("sections", [])
        if not secciones:
            self.notas_layout.addWidget(
                self._tarjeta_mensaje(
                    "La nota oficial está disponible, pero no se encontraron secciones legibles en su estructura."
                )
            )
        for indice, seccion in enumerate(secciones):
            self.notas_layout.addWidget(
                self._crear_acordeon(seccion, nivel=0, clave=f"patch-{indice}")
            )
        if datos.get("cached"):
            self.notas_layout.addWidget(
                self._tarjeta_mensaje(
                    "Mostrando la última copia oficial guardada localmente."
                )
            )
        self._actualizar_info()

    @staticmethod
    def _adaptar_cache_notas_antigua(datos: dict[str, Any]) -> dict[str, Any]:
        """Agrupa una caché plana anterior para que siga siendo legible sin datos nuevos."""
        secciones_anteriores = datos.get("sections", [])

        def contiene_identidad(nodos: list[dict[str, Any]]) -> bool:
            return any(
                isinstance(nodo, dict)
                and (
                    nodo.get("kind") in {"champion", "item"}
                    or contiene_identidad(nodo.get("children", []))
                )
                for nodo in nodos
            )

        if contiene_identidad(secciones_anteriores):
            estructura = copy.deepcopy(secciones_anteriores)
            servicio = ServicioMeta.__new__(ServicioMeta)
            servicio._campeones = ServicioMeta._cargar_catalogo_campeones()
            servicio._objetos = ServicioMeta._cargar_catalogo_objetos()

            def enriquecer(
                nodos: list[dict[str, Any]], campeon_padre: str | None = None
            ) -> None:
                """Completa identidad de icono en nodos de una caché estructurada."""
                for nodo in nodos:
                    if not isinstance(nodo, dict):
                        continue
                    nodo["blocks"] = [
                        bloque
                        for bloque in nodo.get("blocks", [])
                        if not (
                            isinstance(bloque, dict)
                            and bloque.get("type") == "image"
                            and ServicioMeta._es_icono_data_dragon(
                                str(bloque.get("url") or "")
                            )
                        )
                    ]
                    clase = nodo.get("kind")
                    campeon = campeon_padre
                    if clase == "champion":
                        campeon = nodo.get("champion_id") or servicio._resolver_campeon(
                            str(nodo.get("title") or "")
                        )
                        nodo["champion_id"] = campeon
                    elif clase == "item" and not nodo.get("item_id"):
                        nodo["item_id"] = servicio._resolver_objeto(
                            str(nodo.get("title") or "")
                        )
                    elif clase == "detail" and campeon:
                        coincidencia = re.match(
                            r"^(Pasiva|[QWER])\s*[-–:]",
                            str(nodo.get("title") or ""),
                            re.I,
                        )
                        if coincidencia:
                            ranura = coincidencia.group(1).casefold()
                            nodo["ability_slot"] = (
                                "passive" if ranura == "pasiva" else ranura
                            )
                            nodo["champion_id"] = campeon
                    enriquecer(nodo.get("children", []), campeon)

            enriquecer(estructura)
            return {
                **datos,
                "schema_version": ServicioMeta.VERSION_ESQUEMA_NOTAS,
                "sections": estructura,
            }

        agrupadas: dict[str, dict[str, Any]] = {}
        for bloque in datos.get("sections", []):
            if not isinstance(bloque, dict):
                continue
            titulo = str(bloque.get("category") or "Cambios")
            grupo = agrupadas.setdefault(
                titulo,
                {"title": titulo, "kind": "section", "blocks": [], "children": []},
            )
            texto = str(bloque.get("text") or "").strip()
            if texto:
                grupo["blocks"].append(
                    {
                        "type": "change",
                        "text": texto,
                        "change_type": bloque.get("change_type"),
                    }
                )
        grupos = list(agrupadas.values())
        aviso = {
            "title": "Copia local anterior",
            "kind": "section",
            "blocks": [
                {
                    "type": "paragraph",
                    "text": "No se pudo actualizar la estructura desde Riot. Se muestra la última copia guardada, agrupada por los encabezados que conservaba.",
                }
            ],
            "children": grupos,
        }
        return {
            **datos,
            "schema_version": ServicioMeta.VERSION_ESQUEMA_NOTAS,
            "sections": [aviso],
        }

    def _crear_acordeon(self, nodo: dict[str, Any], nivel: int, clave: str) -> QFrame:
        """Construye una sección plegable con bloques y entradas hijas recursivas."""
        tarjeta = QFrame()
        tarjeta.setObjectName("metaCard")
        tarjeta.setStyleSheet(
            f"QFrame#metaCard{{background:{PALETA['superficie']};border:1px solid {PALETA['borde']};border-radius:11px;}}"
        )
        exterior = QVBoxLayout(tarjeta)
        exterior.setContentsMargins(10 if nivel else 14, 5, 10 if nivel else 14, 8)
        exterior.setSpacing(6)
        cabecera = QToolButton()
        cabecera.setCheckable(True)
        cabecera.setChecked(
            nivel == 0 and self._clave_seccion(nodo.get("title", "")) == "campeones"
        )
        cabecera.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        cabecera.setArrowType(
            Qt.ArrowType.DownArrow if cabecera.isChecked() else Qt.ArrowType.RightArrow
        )
        titulo = str(nodo.get("title", "Cambios"))
        hijos = nodo.get("children", [])
        cabecera.setText(f"{titulo}   ·   {len(hijos)}" if hijos else titulo)
        cabecera.setStyleSheet(
            f"QToolButton{{color:{PALETA['oro_suave'] if nivel == 0 else PALETA['marfil']};font-size:{15 if nivel == 0 else 13}px;font-weight:700;text-align:left;border:0;padding:8px 6px;}} QToolButton:hover{{color:{PALETA['marfil']};background:rgba(182,154,80,0.08);border-radius:7px;}}"
        )
        fila_cabecera = QHBoxLayout()
        fila_cabecera.setSpacing(8)
        icono_entidad = self._crear_icono_nota(nodo)
        if icono_entidad is not None:
            fila_cabecera.addWidget(icono_entidad)
        fila_cabecera.addWidget(
            cabecera, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        fila_cabecera.addStretch(1)
        exterior.addLayout(fila_cabecera)
        cuerpo = QWidget()
        cuerpo_layout = QVBoxLayout(cuerpo)
        cuerpo_layout.setContentsMargins(8, 2, 8, 8)
        cuerpo_layout.setSpacing(8)
        cuerpo.setVisible(cabecera.isChecked())
        cabecera.toggled.connect(
            lambda abierto, panel=cuerpo, boton=cabecera: self._alternar_acordeon(
                panel, boton, abierto
            )
        )
        if nodo.get("kind") in {"champion", "item"}:
            fila_entidad = QHBoxLayout()
            identificador = nodo.get("champion_id")
            if identificador and self.assets:
                retrato = RetratoRedondeado()
                retrato.setFixedSize(42, 42)
                self.assets.set_label_image(
                    retrato,
                    self.assets.champion_url(identificador),
                    f"meta-notas:{identificador.casefold()}",
                    42,
                )
                fila_entidad.addWidget(retrato)
            resumen_tipo = nodo.get("change_type")
            if resumen_tipo:
                color = (
                    PALETA["ventaja"]
                    if resumen_tipo == "Buff"
                    else PALETA["desventaja"]
                    if resumen_tipo == "Nerf"
                    else PALETA["informacion"]
                )
                etiqueta = QLabel(resumen_tipo)
                etiqueta.setStyleSheet(
                    f"color:{color};font-weight:700;border:1px solid {color};border-radius:8px;padding:4px 9px;"
                )
                fila_entidad.addWidget(etiqueta)
            fila_entidad.addStretch(1)
            cuerpo_layout.addLayout(fila_entidad)
        for bloque in nodo.get("blocks", []):
            if bloque.get("type") == "image":
                miniatura = ImagenNotaInteractiva(
                    str(bloque.get("url") or ""),
                    str(bloque.get("alt") or "Imagen de las notas"),
                    self.assets,
                )
                cuerpo_layout.addWidget(miniatura, 0, Qt.AlignmentFlag.AlignLeft)
                continue
            texto = str(bloque.get("text", ""))
            if not texto:
                continue
            linea = QLabel(("•  " if bloque.get("type") == "change" else "") + texto)
            linea.setWordWrap(True)
            linea.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            linea.setStyleSheet(
                f"color:{PALETA['texto']};font-size:13px;line-height:1.45;padding:5px 9px;border-left:2px solid {PALETA['oro_oscuro']};"
            )
            cuerpo_layout.addWidget(linea)
        for indice, hijo in enumerate(hijos):
            cuerpo_layout.addWidget(
                self._crear_acordeon(hijo, nivel + 1, f"{clave}-{indice}")
            )
        exterior.addWidget(cuerpo)
        return tarjeta

    def _crear_icono_nota(self, nodo: dict[str, Any]) -> QLabel | None:
        """Crea el icono del encabezado de un objeto o habilidad del campeón.

        Parámetros: nodo estructurado de notas.
        Retorno: etiqueta con recurso remoto o placeholder si procede.
        """
        url = None
        tamano = 30
        clave = ""
        if nodo.get("kind") == "item":
            identificador = str(nodo.get("item_id") or "")
            if identificador.isdigit() and self.assets:
                url = self.assets.item_url(int(identificador))
                clave = f"meta-notas:item:{identificador}"
        elif nodo.get("kind") == "detail" and nodo.get("ability_slot"):
            campeon = str(nodo.get("champion_id") or "")
            if campeon and self.assets and hasattr(self.assets, "champion_ability_url"):
                url = self.assets.champion_ability_url(
                    campeon, str(nodo["ability_slot"])
                )
                if url:
                    clave = f"meta-notas:ability:{campeon}:{nodo['ability_slot']}"
        if (
            not url
            and nodo.get("kind") != "item"
            and not (nodo.get("kind") == "detail" and nodo.get("ability_slot"))
        ):
            return None
        icono = QLabel("◇")
        icono.setObjectName("patchNoteIconFallback")
        icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icono.setFixedSize(tamano, tamano)
        icono.setCursor(Qt.CursorShape.ArrowCursor)
        icono.setStyleSheet(
            f"background:{PALETA['elevada']};color:{PALETA['oro_suave']};"
            f"border:1px solid {PALETA['borde_sutil']};border-radius:6px;"
        )
        if url and self.assets:
            self.assets.set_label_image(
                icono,
                url,
                clave,
                tamano,
                Qt.AspectRatioMode.KeepAspectRatio,
            )
        return icono

    @staticmethod
    def _alternar_acordeon(panel: QWidget, boton: QToolButton, abierto: bool) -> None:
        """Abre o cierra el contenido de una sección y actualiza su indicador visual."""
        panel.setVisible(abierto)
        boton.setArrowType(
            Qt.ArrowType.DownArrow if abierto else Qt.ArrowType.RightArrow
        )

    @staticmethod
    def _clave_seccion(texto: str) -> str:
        """Normaliza el nombre de sección para elegir la apertura inicial de Campeones."""
        import unicodedata

        return "".join(
            caracter
            for caracter in unicodedata.normalize("NFKD", texto).casefold()
            if not unicodedata.combining(caracter)
        )

    @staticmethod
    def _tarjeta_mensaje(texto: str) -> QFrame:
        """Crea un aviso legible dentro de una tarjeta coherente con la página Meta."""
        tarjeta = QFrame()
        tarjeta.setObjectName("metaCard")
        layout = QVBoxLayout(tarjeta)
        etiqueta = QLabel(texto)
        etiqueta.setWordWrap(True)
        etiqueta.setStyleSheet(f"color:{PALETA['secundario']};padding:10px;")
        layout.addWidget(etiqueta)
        return tarjeta

    def _actualizar_info(self) -> None:
        """Sincroniza parche, última lectura y filtros activos en la cabecera."""
        filtros = (
            f"{self.region.currentText()} · {self.rol.currentText()} · Ranked Solo/Duo"
        )
        parche = self.datos_tier.get("patch") or "—"
        actualizacion = self._formatear_fecha(self.datos_tier.get("retrieved_at"))
        self.info.setText(
            f"Fuente: LoLalytics · Esmeralda+ · Parche {parche} · Actualizado: {actualizacion} · {filtros}"
        )

    @staticmethod
    def _formatear_fecha(valor: Any) -> str:
        """Presenta en hora local una fecha ISO o indica que aún no se ha descargado."""
        if not valor:
            return "—"
        try:
            from datetime import datetime

            fecha = datetime.fromisoformat(str(valor)).astimezone()
            return fecha.strftime("%d/%m/%Y %H:%M")
        except (ValueError, TypeError):
            return "—"


class TarjetaMetaCampeon(QFrame):
    """Tarjeta compacta de campeón con retrato, tier y estadísticas principales."""

    activado = Signal(dict)

    def __init__(
        self,
        campeon: dict[str, Any],
        acento: str,
        assets: Any = None,
        parent: QWidget | None = None,
    ) -> None:
        """Construye una tarjeta compacta y clicable con métricas LoLalytics."""
        super().__init__(parent)
        self.campeon = campeon
        self.setObjectName("metaChampionCard")
        self.setMinimumHeight(126)
        self.setMinimumWidth(360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Doble clic para consultar todas las estadísticas")
        exterior = QHBoxLayout(self)
        exterior.setContentsMargins(9, 8, 10, 8)
        exterior.setSpacing(9)
        puesto = QLabel(f"#{campeon.get('position', '—')}")
        puesto.setAlignment(Qt.AlignmentFlag.AlignCenter)
        puesto.setFixedWidth(34)
        puesto.setStyleSheet(
            f"color:{PALETA['oro_suave']};font-size:12px;font-weight:800;background:{PALETA['base']};border:1px solid {PALETA['oro_oscuro']};border-radius:7px;padding:4px;"
        )
        exterior.addWidget(puesto)
        marco = QFrame()
        marco.setFixedSize(54, 54)
        marco.setStyleSheet(
            f"background:{PALETA['base']};border:1px solid {acento};border-radius:8px;"
        )
        retrato_layout = QVBoxLayout(marco)
        retrato_layout.setContentsMargins(3, 3, 3, 3)
        retrato = RetratoRedondeado()
        retrato.setFixedSize(46, 46)
        if assets:
            identificador = str(campeon.get("champion_id") or campeon.get("name") or "")
            assets.set_label_image(
                retrato,
                assets.champion_url(identificador),
                f"meta:{identificador.casefold()}",
                46,
            )
        else:
            retrato.setText(str(campeon.get("name", "?"))[:2].upper())
            retrato.setAlignment(Qt.AlignmentFlag.AlignCenter)
            retrato.setStyleSheet(f"color:{PALETA['oro_suave']};font-weight:700;")
        retrato_layout.addWidget(retrato)
        exterior.addWidget(marco)
        contenido = QVBoxLayout()
        contenido.setSpacing(5)
        cabecera = QHBoxLayout()
        cabecera.setSpacing(5)
        nombre = QLabel(
            str(campeon.get("name") or campeon.get("source_name") or "Campeón")
        )
        nombre.setStyleSheet(
            f"color:{PALETA['marfil']};font-size:16px;font-weight:800;"
        )
        cabecera.addWidget(nombre, 1)
        tier = QLabel(str(campeon.get("tier") or "—"))
        tier.setStyleSheet(
            f"color:{acento};background:{PALETA['base']};border:1px solid {acento};border-radius:6px;padding:3px 8px;font-size:12px;font-weight:800;"
        )
        cabecera.addWidget(tier)
        contenido.addLayout(cabecera)
        metricas = QHBoxLayout()
        metricas.setContentsMargins(0, 0, 0, 0)
        metricas.setSpacing(5)
        metricas.addWidget(
            self._chip_metrica("WR", campeon.get("win_rate"), acento, True)
        )
        metricas.addWidget(self._separador_metrica())
        metricas.addWidget(self._chip_metrica("PICK", campeon.get("pick_rate"), acento))
        metricas.addWidget(self._separador_metrica())
        metricas.addWidget(self._chip_metrica("BAN", campeon.get("ban_rate"), acento))
        metricas.addStretch(1)
        contenido.addLayout(metricas)
        muestra = campeon.get("sample_size")
        muestra_texto = (
            f"{int(muestra):,}".replace(",", ".") + " partidas"
            if isinstance(muestra, (int, float))
            else "Muestra —"
        )
        pie = QLabel(muestra_texto)
        pie.setStyleSheet(
            f"color:{PALETA['secundario']};font-size:11px;font-weight:600;"
        )
        contenido.addWidget(pie)
        exterior.addLayout(contenido, 1)

    @staticmethod
    def _porcentaje(valor: Any) -> str:
        """Formatea tasa numérica con dos decimales o indica dato no disponible."""
        return f"{valor:.2f}%" if isinstance(valor, (int, float)) else "—"

    @staticmethod
    def _chip_metrica(
        etiqueta: str, valor: Any, acento: str, principal: bool = False
    ) -> QWidget:
        """Muestra valor y etiqueta en texto plano con altura suficiente para leerlos."""
        bloque = QWidget()
        bloque.setMinimumWidth(66 if principal else 58)
        bloque.setMinimumHeight(43)
        disposicion = QVBoxLayout(bloque)
        disposicion.setContentsMargins(0, 0, 0, 0)
        disposicion.setSpacing(2)
        numero = QLabel(TarjetaMetaCampeon._porcentaje(valor))
        numero.setStyleSheet(
            f"color:{PALETA['marfil'] if principal else PALETA['texto']};font-size:{20 if principal else 15}px;font-weight:800;"
        )
        numero.setFixedHeight(25 if principal else 21)
        nombre = QLabel(etiqueta)
        nombre.setStyleSheet(
            f"color:{acento if principal else PALETA['secundario']};font-size:11px;font-weight:700;letter-spacing:0.3px;"
        )
        nombre.setFixedHeight(16)
        nombre.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        numero.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        bloque.setMinimumWidth(
            max(
                numero.fontMetrics().horizontalAdvance(numero.text()),
                nombre.fontMetrics().horizontalAdvance(nombre.text()),
            )
            + 4
        )
        disposicion.addWidget(numero)
        disposicion.addWidget(nombre)
        return bloque

    @staticmethod
    def _separador_metrica() -> QFrame:
        """Crea un separador vertical sutil entre los grupos de estadísticas."""
        separador = QFrame()
        separador.setFrameShape(QFrame.Shape.VLine)
        separador.setFixedHeight(31)
        separador.setStyleSheet(f"color:{PALETA['borde_sutil']};")
        return separador

    def mouseDoubleClickEvent(self, evento: QMouseEvent) -> None:
        """Emite el campeón asociado al activar dos veces la tarjeta."""
        self.activado.emit(self.campeon)
        super().mouseDoubleClickEvent(evento)


class ImagenParche(QLabel):
    """Presenta la imagen oficial del parche completa y escalada al ancho disponible."""

    def __init__(self, imagen: QPixmap, parent: QWidget | None = None) -> None:
        """Prepara una imagen destacada sin recortarla ni deformarla."""
        super().__init__(parent)
        self._imagen_original = imagen.toImage()
        self._ultimo_tamano_objetivo = (0, 0)
        self._token_escalado: tuple[int, int, int] = (0, 0, 0)
        self.setObjectName("metaCard")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Abrir la imagen del parche en tamaño grande")
        self.setMinimumHeight(160)
        self.setMaximumHeight(520)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._temporizador_escala = QTimer(self)
        self._temporizador_escala.setSingleShot(True)
        self._temporizador_escala.setInterval(120)
        self._temporizador_escala.timeout.connect(self._escalar_imagen)
        self.setStyleSheet(
            f"QLabel#metaCard{{background:{PALETA['superficie']};"
            f"border:1px solid {PALETA['oro_oscuro']};border-radius:12px;}}"
            f"QLabel#metaCard:hover{{border:1px solid {PALETA['oro']};}}"
        )
        self._temporizador_escala.start()

    def mousePressEvent(self, evento: QMouseEvent) -> None:
        """Abre el visor grande al pulsar la imagen destacada.

        Parámetros: evento de ratón recibido.
        Retorno: None; muestra un diálogo modal redimensionable.
        """
        if evento.button() == Qt.MouseButton.LeftButton:
            visor = DialogoImagenParche(QPixmap.fromImage(self._imagen_original), self)
            visor.exec()
            evento.accept()
            return
        super().mousePressEvent(evento)

    def resizeEvent(self, evento: QResizeEvent) -> None:
        """Vuelve a escalar la imagen al cambiar el ancho de la ventana."""
        super().resizeEvent(evento)
        self._temporizador_escala.start()

    def _escalar_imagen(self) -> None:
        """Programa el escalado de la imagen fuera del hilo gráfico."""
        ancho = max(1, min(self.width() - 16, 1500))
        alto = max(1, min(self.height() - 16, 520))
        if (ancho, alto) == self._ultimo_tamano_objetivo:
            return
        self._ultimo_tamano_objetivo = (ancho, alto)
        self._token_escalado = (self._token_escalado[0] + 1, ancho, alto)
        token = self._token_escalado
        original = self._imagen_original
        run_async(
            lambda: original.scaled(
                ancho,
                alto,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ),
            on_finished=self._aplicar_escalado,
            token=token,
        )

    def _aplicar_escalado(
        self, token: tuple[int, int, int], imagen: Any, error: str | None
    ) -> None:
        """Publica la imagen escalada vigente sin aceptar resultados obsoletos."""
        if error or token != self._token_escalado or not isinstance(imagen, QImage):
            return
        if imagen.isNull():
            return
        self.setPixmap(QPixmap.fromImage(imagen))


class DialogoImagenParche(QDialog):
    """Muestra una imagen oficial grande, con ajuste al tamaño y cierre por Escape."""

    def __init__(self, imagen: QPixmap, parent: QWidget | None = None) -> None:
        """Crea un visor redimensionable para una imagen local ya cargada.

        Parámetros: pixmap de imagen y widget padre opcional.
        Retorno: None; prepara el diálogo y el botón de cierre.
        """
        super().__init__(parent)
        self._imagen_original = imagen
        self.setWindowTitle("Imagen de las notas del parche")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumSize(600, 400)
        self.resize(1100, 760)
        self.setStyleSheet(
            f"QDialog{{background:{PALETA['base']};color:{PALETA['texto']};}}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        self.imagen = QLabel()
        self.imagen.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.imagen.setMinimumSize(1, 1)
        self.imagen.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.imagen.setStyleSheet(
            f"background:{PALETA['superficie']};border:1px solid {PALETA['borde']};"
            "border-radius:9px;"
        )
        layout.addWidget(self.imagen, 1)
        cerrar = QPushButton("Cerrar")
        cerrar.setDefault(True)
        cerrar.clicked.connect(self.accept)
        layout.addWidget(cerrar, 0, Qt.AlignmentFlag.AlignRight)
        self._actualizar_imagen()

    def resizeEvent(self, evento: QResizeEvent) -> None:
        """Ajusta el pixmap al espacio visible conservando su proporción."""
        super().resizeEvent(evento)
        self._actualizar_imagen()

    def _actualizar_imagen(self) -> None:
        """Escala la imagen a los límites actuales del visor sin deformarla."""
        if self._imagen_original.isNull():
            return
        objetivo = self.imagen.size()
        if objetivo.width() < 2 or objetivo.height() < 2:
            return
        self.imagen.setPixmap(
            self._imagen_original.scaled(
                objetivo,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )


class ImagenNotaInteractiva(QLabel):
    """Carga una imagen de sección en segundo plano y permite abrirla en grande."""

    def __init__(
        self,
        url: str,
        texto_alternativo: str,
        assets: Any,
        parent: QWidget | None = None,
    ) -> None:
        """Prepara una miniatura remota con fallback si el recurso no llega.

        Parámetros: URL, texto alternativo, servicio de imágenes y padre opcional.
        Retorno: None; inicia la carga mediante el caché asíncrono compartido.
        """
        super().__init__(texto_alternativo, parent)
        self.setObjectName("patchNoteMedia")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(220, 136)
        self.setWordWrap(True)
        self.setToolTip("Abrir imagen en tamaño grande")
        self.setStyleSheet(
            f"QLabel#patchNoteMedia{{background:{PALETA['elevada']};"
            f"color:{PALETA['secundario']};border:1px solid {PALETA['borde_sutil']};"
            "border-radius:8px;padding:5px;}"
            f"QLabel#patchNoteMedia:hover{{border-color:{PALETA['oro']};}}"
        )
        if url.startswith(("https://", "http://")) and assets:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            assets.set_label_image(
                self,
                url,
                f"meta-notas:media:{uuid4().hex}",
                210,
                Qt.AspectRatioMode.KeepAspectRatio,
                height=126,
            )

    def mousePressEvent(self, evento: QMouseEvent) -> None:
        """Abre el visor solo si la miniatura se cargó correctamente."""
        pixmap = self.pixmap()
        if (
            evento.button() == Qt.MouseButton.LeftButton
            and pixmap is not None
            and not pixmap.isNull()
        ):
            DialogoImagenParche(pixmap, self).exec()
            evento.accept()
            return
        super().mousePressEvent(evento)


class RetratoRedondeado(QLabel):
    """Pinta el retrato Data Dragon con recorte redondeado."""

    def paintEvent(self, evento: Any) -> None:
        """Recorta el pixmap al radio visual del retrato; recibe evento y retorna None."""
        imagen = self.pixmap()
        if imagen.isNull():
            super().paintEvent(evento)
            return
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        ruta = QPainterPath()
        ruta.addRoundedRect(QRectF(self.rect()), 6, 6)
        pintor.setClipPath(ruta)
        pintor.drawPixmap(self.rect(), imagen)
