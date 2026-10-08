"""Diálogo compartido para explicar la puntuación de rendimiento."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.services.identidad_jugador import nombre_riot_visible
from app.services.servicio_puntuacion_rendimiento import (
    FUENTES_METRICAS,
    NOMBRES_METRICAS,
    TITULOS_CATEGORIA,
)

ROLES_VISIBLES = {
    "TOP": "TOP",
    "JUNGLE": "JUNGLA",
    "JUNG": "JUNGLA",
    "MIDDLE": "MEDIO",
    "MID": "MEDIO",
    "BOTTOM": "TIRADOR",
    "BOT": "TIRADOR",
    "UTILITY": "APOYO",
    "SUPPORT": "APOYO",
    "SUP": "APOYO",
}


class DialogoDesgloseRendimiento(QDialog):
    """Presenta identidad, categorías y cálculos del resultado recibido."""

    def __init__(self, resultado: dict[str, Any], padre=None) -> None:
        """Construye el diálogo desde el resultado y el padre Qt recibidos."""
        super().__init__(padre)
        self.resultado = resultado
        self.setWindowTitle("Análisis de rendimiento SOLRALOL")
        self.setObjectName("performanceBreakdownDialog")
        self._ajustar_a_pantalla()
        exterior = QVBoxLayout(self)
        exterior.setContentsMargins(12, 10, 12, 10)
        exterior.setSpacing(8)
        exterior.addWidget(self._crear_cabecera(resultado))
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setObjectName("performanceCategoryScroll")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignTop)
        contenido = QWidget()
        self.columnas_widget = contenido
        contenido_layout = QVBoxLayout(contenido)
        contenido_layout.setContentsMargins(0, 0, 0, 0)
        contenido_layout.setSpacing(8)
        columnas = QHBoxLayout()
        columnas.setContentsMargins(2, 2, 8, 2)
        columnas.setSpacing(12)
        contenido_layout.addLayout(columnas)
        self.columnas: dict[str, QVBoxLayout] = {}
        for nombre in ("izquierda", "derecha"):
            columna = QVBoxLayout()
            columna.setContentsMargins(0, 0, 0, 0)
            columna.setSpacing(8)
            columna.setAlignment(Qt.AlignmentFlag.AlignTop)
            self.columnas[nombre] = columna
            columnas.addLayout(columna, 1)
        self.barras: dict[str, QProgressBar] = {}
        self.detalles: dict[str, QWidget] = {}
        self.porcentajes: dict[str, QLabel] = {}
        self.tarjetas: dict[str, QFrame] = {}
        self.puntos_categoria: dict[str, QLabel] = {}
        self.insignias_logro: dict[str, QLabel] = {}
        self.botones_detalle: dict[str, QPushButton] = {}
        categorías = list(resultado.get("categories", {}).items())
        mapa_columnas = {
            "combate": "izquierda",
            "objetivos": "izquierda",
            "economia": "derecha",
            "vision": "derecha",
        }
        tarjeta_supervivencia: QFrame | None = None
        for clave, categoría in categorías:
            tarjeta = self._crear_tarjeta(clave, categoría)
            if clave == "supervivencia":
                tarjeta_supervivencia = tarjeta
            else:
                self.columnas[mapa_columnas.get(clave, "izquierda")].addWidget(tarjeta)
        self.columnas["izquierda"].addStretch(1)
        self.columnas["derecha"].addStretch(1)
        if tarjeta_supervivencia is not None:
            contenido_layout.addWidget(tarjeta_supervivencia)
        contenido_layout.addStretch(1)
        self.scroll_area.setWidget(contenido)
        exterior.addWidget(self.scroll_area, 1)
        exterior.addWidget(self._crear_pie(resultado))

    def _ajustar_a_pantalla(self) -> None:
        """Limita el diálogo al área útil disponible y prioriza el resumen compacto."""
        pantalla = self.screen()
        geometría = pantalla.availableGeometry() if pantalla else None
        ancho = min(1080, geometría.width() - 32) if geometría else 1080
        alto = min(660, geometría.height() - 48) if geometría else 660
        self.setMinimumSize(min(760, ancho), min(500, alto))
        self.resize(max(self.minimumWidth(), ancho), max(self.minimumHeight(), alto))

    def _crear_cabecera(self, resultado: dict[str, Any]) -> QFrame:
        """Crea cabecera compacta con campeón, cuenta, rol y total."""
        marco = QFrame()
        marco.setObjectName("performanceHeader")
        fila = QHBoxLayout(marco)
        fila.setContentsMargins(16, 9, 16, 9)
        identidad = QVBoxLayout()
        identidad.setContentsMargins(0, 0, 0, 0)
        identidad.setSpacing(1)
        título = QLabel("ANÁLISIS DE RENDIMIENTO SOLRALOL")
        título.setObjectName("performanceEyebrow")
        campeón = QLabel(str(resultado.get("champion") or "Campeón no disponible"))
        campeón.setObjectName("performanceChampionName")
        campeón.setWordWrap(True)
        riot_id = nombre_riot_visible({"riot_id": resultado.get("riot_id")})
        cuenta = QLabel(riot_id or "Invocador no disponible")
        cuenta.setObjectName("performancePlayerName")
        cuenta.setWordWrap(True)
        self.etiqueta_campeon = campeón
        self.etiqueta_cuenta = cuenta
        rol_recibido = str(resultado.get("role") or "").strip().upper()
        rol = QLabel(ROLES_VISIBLES.get(rol_recibido, "ROL NO DISPONIBLE"))
        rol.setObjectName("performanceRole")
        identidad.addWidget(título)
        identidad.addWidget(campeón)
        identidad.addWidget(cuenta)
        identidad.addWidget(rol)
        fila.addLayout(identidad, 1)
        puntos = QLabel(f"{int(resultado.get('total', 0))} PUNTOS")
        puntos.setObjectName("performanceTotal")
        self.etiqueta_total = puntos
        puntos.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        fila.addWidget(puntos)
        return marco

    def _crear_tarjeta(self, clave: str, categoría: dict[str, Any]) -> QFrame:
        """Crea una tarjeta compacta cuyo contenido se expande de forma independiente."""
        tarjeta = QFrame()
        tarjeta.setObjectName("performanceCategoryCard")
        tarjeta.setProperty("category", clave)
        tarjeta.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.tarjetas[clave] = tarjeta
        diseño = QVBoxLayout(tarjeta)
        diseño.setContentsMargins(12, 8, 12, 8)
        diseño.setSpacing(4)
        fila = QHBoxLayout()
        fila.setSpacing(6)
        título = QLabel(TITULOS_CATEGORIA.get(clave, clave.title()))
        título.setObjectName("performanceCategoryTitle")
        título.setWordWrap(True)
        fila.addWidget(título, 1)
        logro = categoría.get("achievement_name") or categoría.get(
            "provisional_achievement_name"
        )
        insignia_logro = QLabel("★")
        insignia_logro.setObjectName("performanceAchievement")
        insignia_logro.setToolTip(str(logro or ""))
        insignia_logro.setVisible(bool(logro))
        self.insignias_logro[clave] = insignia_logro
        fila.addWidget(insignia_logro)
        puntos = QLabel(f"{categoría['final']} / {categoría['reference']} p")
        puntos.setObjectName("performanceCategoryPoints")
        self.puntos_categoria[clave] = puntos
        fila.addWidget(puntos)
        diseño.addLayout(fila)
        porcentaje = categoría["final"] / max(1, categoría["reference"]) * 100
        progreso = QProgressBar()
        progreso.setObjectName("performanceProgressBar")
        progreso.setProperty("category", clave)
        progreso.setRange(0, 100)
        progreso.setValue(min(100, int(porcentaje)))
        progreso.setFormat("")
        progreso.setFixedHeight(9)
        progreso.setMaximumWidth(360)
        self.barras[clave] = progreso
        progreso_fila = QHBoxLayout()
        progreso_fila.setSpacing(7)
        progreso_fila.addWidget(progreso, 1)
        texto_porcentaje = QLabel(f"{porcentaje:.1f}%")
        texto_porcentaje.setObjectName("performancePercentage")
        self.porcentajes[clave] = texto_porcentaje
        progreso_fila.addWidget(texto_porcentaje)
        diseño.addLayout(progreso_fila)
        botón = QPushButton("Ver desglose  ▾")
        botón.setObjectName("performanceDetailsButton")
        botón.setMinimumHeight(30)
        botón.setCheckable(True)
        self.botones_detalle[clave] = botón
        detalles = self._crear_detalles(categoría)
        detalles.hide()
        self.detalles[clave] = detalles
        botón.toggled.connect(
            lambda visible, categoría=clave: self._alternar_detalle(categoría, visible)
        )
        botón.toggled.connect(
            lambda visible, control=botón: control.setText(
                "Ocultar desglose  ▴" if visible else "Ver desglose  ▾"
            )
        )
        diseño.addWidget(botón)
        diseño.addWidget(detalles)
        return tarjeta

    def _crear_detalles(self, categoría: dict[str, Any]) -> QWidget:
        """Organiza etapas y contribuciones del cálculo como filas legibles."""
        contenido = QWidget()
        distribución = QVBoxLayout(contenido)
        distribución.setContentsMargins(0, 5, 0, 4)
        distribución.setSpacing(4)
        etiqueta_contribución = QLabel("CONTRIBUCIÓN AL RENDIMIENTO")
        etiqueta_contribución.setObjectName("performanceDetailHeading")
        distribución.addWidget(etiqueta_contribución)
        rejilla = QGridLayout()
        rejilla.setContentsMargins(0, 0, 0, 2)
        rejilla.setHorizontalSpacing(12)
        rejilla.setVerticalSpacing(3)
        filas = [
            (
                NOMBRES_METRICAS.get(nombre, nombre.replace("_", " ").capitalize()),
                f"{valor:.1f} p",
                FUENTES_METRICAS.get(nombre, ""),
            )
            for nombre, valor in categoría.get("submetrics", {}).items()
        ]
        filas.extend(
            (
                NOMBRES_METRICAS.get(nombre, nombre.replace("_", " ").capitalize()),
                "No disponible",
                FUENTES_METRICAS.get(nombre, "La fuente no proporciona este campo."),
            )
            for nombre in categoría.get("unavailable_metrics", [])
        )
        for índice, (nombre, valor, fuente) in enumerate(filas):
            etiqueta = QLabel(nombre)
            valor_etiqueta = QLabel(valor)
            valor_etiqueta.setObjectName("performanceMetricValue")
            if fuente:
                etiqueta.setToolTip(fuente)
            if valor == "No disponible":
                valor_etiqueta.setToolTip(etiqueta.toolTip())
            rejilla.addWidget(etiqueta, índice, 0)
            rejilla.addWidget(valor_etiqueta, índice, 1, Qt.AlignmentFlag.AlignRight)
        distribución.addLayout(rejilla)
        separador = QFrame()
        separador.setFrameShape(QFrame.Shape.HLine)
        distribución.addWidget(separador)
        etiqueta_cálculo = QLabel("CÁLCULO DE PUNTUACIÓN")
        etiqueta_cálculo.setObjectName("performanceDetailSecondaryHeading")
        distribución.addWidget(etiqueta_cálculo)
        cálculo = QGridLayout()
        cálculo.setContentsMargins(0, 0, 0, 0)
        cálculo.setHorizontalSpacing(12)
        cálculo.setVerticalSpacing(2)
        etapas = (
            ("Puntuación base", f"{categoría['raw']:.1f} p"),
            (
                "Multiplicador",
                f"×{self.resultado.get('multiplicador_duracion', 1):.2f}",
            ),
            ("Tras duración", f"{categoría['multiplied']} p"),
            ("Referencia", f"{categoría['reference']} p"),
            ("Excedente", f"{categoría['excess']} p"),
            (
                "Excedente retenido",
                f"{categoría['final'] - categoría['reference'] if categoría['final'] > categoría['reference'] else 0} p",
            ),
            ("Puntuación final", f"{categoría['final']} p"),
            ("Cobertura de datos", f"{categoría['completeness']:.0%}"),
        )
        for índice, (nombre, valor) in enumerate(etapas):
            etiqueta = QLabel(nombre)
            etiqueta.setObjectName("performanceCalculationLabel")
            valor_etiqueta = QLabel(valor)
            valor_etiqueta.setObjectName("performanceCalculationLabel")
            cálculo.addWidget(etiqueta, índice, 0)
            cálculo.addWidget(valor_etiqueta, índice, 1, Qt.AlignmentFlag.AlignRight)
        defensive_metrics = categoría.get("defensive_metrics")
        if isinstance(defensive_metrics, dict):
            fila = len(etapas)
            filas_defensivas = (
                ("Daño total recibido", defensive_metrics.get("damage_taken"), False),
                (
                    "Participación en eliminaciones",
                    defensive_metrics.get("kill_participation"),
                    True,
                ),
                (
                    "Daño recibido ponderado",
                    defensive_metrics.get("useful_damage_taken"),
                    False,
                ),
                (
                    "Daño propio mitigado registrado",
                    defensive_metrics.get("damage_self_mitigated"),
                    False,
                ),
                (
                    "Daño mitigado ponderado",
                    defensive_metrics.get("useful_mitigated_damage"),
                    False,
                ),
            )
            for nombre, valor, porcentaje in filas_defensivas:
                etiqueta = QLabel(nombre)
                etiqueta.setObjectName("performanceCalculationLabel")
                texto = "No disponible"
                if valor is not None:
                    texto = f"{valor:.1%}" if porcentaje else f"{valor:,.0f}"
                valor_etiqueta = QLabel(texto)
                valor_etiqueta.setObjectName("performanceCalculationLabel")
                cálculo.addWidget(etiqueta, fila, 0)
                cálculo.addWidget(valor_etiqueta, fila, 1, Qt.AlignmentFlag.AlignRight)
                fila += 1
        distribución.addLayout(cálculo)
        return contenido

    def _alternar_detalle(self, clave: str, visible: bool) -> None:
        """Ajusta solo la tarjeta indicada y recalcula el área desplazable."""
        barra = self.scroll_area.verticalScrollBar()
        posición = barra.value()
        self.detalles[clave].setVisible(visible)
        tarjeta = self.tarjetas[clave]
        tarjeta.layout().invalidate()
        tarjeta.adjustSize()
        self.columnas_widget.layout().invalidate()
        self.columnas_widget.adjustSize()
        self.scroll_area.widget().updateGeometry()
        if visible:
            self.scroll_area.ensureWidgetVisible(self.detalles[clave], 0, 8)
        else:
            barra.setValue(min(posición, barra.maximum()))

    def _crear_pie(self, resultado: dict[str, Any]) -> QFrame:
        """Mantiene rango, premio, duración, multiplicador y cierre siempre visibles."""
        marco = QFrame()
        marco.setObjectName("performanceSummary")
        fila = QHBoxLayout(marco)
        fila.setContentsMargins(12, 7, 10, 7)
        resumen = QVBoxLayout()
        resumen.setContentsMargins(0, 0, 0, 0)
        resumen.setSpacing(1)
        rango = resultado.get("global_rank")
        premios = resultado.get("awards", [])
        estado = resultado.get("finalization_state")
        if premios:
            distinción = " · ".join(premios)
        elif estado == "POSTGAME_PENDING":
            distinción = "Clasificación pendiente"
        elif not resultado.get("awards_finalized") and rango == 1:
            distinción = "LÍDER PROVISIONAL"
        elif not resultado.get("awards_finalized"):
            distinción = "Puntuación provisional"
        else:
            distinción = "Sin distinción"
        rango_texto = QLabel(
            f"{rango}º" if rango is not None else "Puesto no disponible"
        )
        rango_texto.setObjectName("performanceSummaryValue")
        premio_texto = QLabel(distinción)
        premio_texto.setObjectName("performanceAwardValue")
        self.etiqueta_pie_rango = rango_texto
        self.etiqueta_pie_premio = premio_texto
        resumen.addWidget(rango_texto)
        resumen.addWidget(premio_texto)
        fila.addLayout(resumen, 1)
        logro_especial = QLabel()
        logro_especial.setObjectName("specialPerformanceAchievement")
        self.etiqueta_logro_especial = logro_especial
        self._actualizar_logro_especial(resultado)
        fila.addWidget(logro_especial)
        segundos = max(0, int(resultado.get("duration_seconds", 0)))
        minutos, resto = divmod(segundos, 60)
        duración = QLabel(
            f"Duración {minutos}:{resto:02d}  ·  "
            f"Multiplicador ×{resultado.get('multiplicador_duracion', 1):.2f}"
        )
        duración.setObjectName("performanceFooterMeta")
        duración.setWordWrap(True)
        self.etiqueta_pie_meta = duración
        fila.addWidget(duración)
        cerrar = QPushButton("Cerrar")
        cerrar.setObjectName("performanceCloseButton")
        cerrar.clicked.connect(self.accept)
        fila.addWidget(cerrar)
        return marco

    def actualizar_resultado(self, resultado: dict[str, Any]) -> None:
        """Actualiza el diálogo abierto con la nueva clasificación compartida."""
        self.resultado = resultado
        self.etiqueta_campeon.setText(
            str(resultado.get("champion") or "Campeón no disponible")
        )
        riot_id = nombre_riot_visible({"riot_id": resultado.get("riot_id")})
        self.etiqueta_cuenta.setText(riot_id or "Invocador no disponible")
        self.etiqueta_total.setText(f"{int(resultado.get('total', 0))} PUNTOS")
        for clave in self.tarjetas:
            categoría = resultado.get("categories", {}).get(clave)
            if categoría is None:
                continue
            porcentaje = categoría["final"] / max(1, categoría["reference"]) * 100
            self.puntos_categoria[clave].setText(
                f"{categoría['final']} / {categoría['reference']} p"
            )
            self.barras[clave].setValue(min(100, int(porcentaje)))
            self.porcentajes[clave].setText(f"{porcentaje:.1f}%")
            logro = categoría.get("achievement_name") or categoría.get(
                "provisional_achievement_name"
            )
            self.insignias_logro[clave].setToolTip(str(logro or ""))
            self.insignias_logro[clave].setVisible(bool(logro))
            self._actualizar_detalles(clave, categoría)
        rango = resultado.get("global_rank")
        self.etiqueta_pie_rango.setText(
            f"{rango}º" if rango is not None else "Puesto no disponible"
        )
        premios = resultado.get("awards", [])
        estado = resultado.get("finalization_state")
        if premios:
            distinción = " · ".join(premios)
        elif estado == "POSTGAME_PENDING":
            distinción = "Clasificación pendiente"
        elif not resultado.get("awards_finalized") and rango == 1:
            distinción = "LÍDER PROVISIONAL"
        elif not resultado.get("awards_finalized"):
            distinción = "Puntuación provisional"
        else:
            distinción = "Sin distinción"
        self.etiqueta_pie_premio.setText(distinción)
        segundos = max(0, int(resultado.get("duration_seconds", 0)))
        minutos, resto = divmod(segundos, 60)
        self.etiqueta_pie_meta.setText(
            f"Duración {minutos}:{resto:02d}  ·  "
            f"Multiplicador ×{resultado.get('multiplicador_duracion', 1):.2f}"
        )
        self._actualizar_logro_especial(resultado)

    def _actualizar_logro_especial(self, resultado: dict[str, Any]) -> None:
        """Actualiza la insignia ¿Faker? con el resultado recibido.

        Args:
            resultado: resultado autoritativo y estado de finalización.

        Returns:
            None.
        """
        visible = bool(resultado.get("faker_unlocked"))
        self.etiqueta_logro_especial.setText(
            "★ ¿Faker?"
            + (" · PROVISIONAL" if resultado.get("faker_provisional") else "")
        )
        self.etiqueta_logro_especial.setVisible(visible)

    def _actualizar_detalles(self, clave: str, categoría: dict[str, Any]) -> None:
        """Reemplaza los detalles de una tarjeta sin cambiar su expansion.

        Args:
            clave: categoria cuyo resultado ha cambiado.
            categoria: datos y contribuciones recalculadas.

        Returns:
            None.
        """
        anterior = self.detalles[clave]
        reemplazo = self._crear_detalles(categoría)
        reemplazo.setVisible(self.botones_detalle[clave].isChecked())
        self.tarjetas[clave].layout().replaceWidget(anterior, reemplazo)
        self.detalles[clave] = reemplazo
        anterior.deleteLater()
