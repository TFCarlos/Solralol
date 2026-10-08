"""Vista compacta con el rendimiento de los diez participantes y sus equipos."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.services.identidad_jugador import nombre_riot_visible
from app.services.servicio_puntuacion_rendimiento import (
    REFERENCIAS,
    TITULOS_CATEGORIA,
)
from app.ui.sistema_visual import COLORES_CATEGORIA_RENDIMIENTO, PALETA

CATEGORIAS_VISTA = ("combate", "economia", "objetivos", "vision", "supervivencia")
ROLES_ORDEN = {
    "TOP": 0,
    "JUNGLE": 1,
    "JUNG": 1,
    "MIDDLE": 2,
    "MID": 2,
    "BOTTOM": 3,
    "BOT": 3,
    "UTILITY": 4,
    "SUPPORT": 4,
    "SUP": 4,
}
ROLES_NOMBRE = {
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
CATEGORIAS_ETIQUETA = {
    "combate": "Combate",
    "economia": "Economía",
    "objetivos": "Objetivos",
    "vision": "Visión",
    "supervivencia": "Supervivencia",
}


class EtiquetaElidida(QLabel):
    """Elide una identidad con su texto completo disponible en tooltip."""

    def __init__(self, texto: str, padre: QWidget | None = None) -> None:
        """Inicializa el nombre completo y su etiqueta de tamaño adaptable."""
        super().__init__(padre)
        self.texto_completo = texto
        self.setText(
            self.fontMetrics().elidedText(texto, Qt.TextElideMode.ElideRight, 180)
        )
        self.setMinimumWidth(0)
        self.setMaximumWidth(180)
        self.setToolTip(texto)

    def paintEvent(self, event: Any) -> None:
        """Dibuja la identidad elidida sin provocar cambios geométricos."""
        pintor = QPainter(self)
        texto = self.fontMetrics().elidedText(
            self.texto_completo, Qt.TextElideMode.ElideRight, max(1, self.width())
        )
        pintor.setFont(self.font())
        pintor.setPen(self.palette().color(self.foregroundRole()))
        pintor.drawText(self.rect(), int(self.alignment()), texto)


class RetratoCampeon(QLabel):
    """Pinta el retrato del campeón recortado y enmarcado con esquinas suaves."""

    def __init__(self, texto: str, padre: QWidget | None = None) -> None:
        """Crea un retrato con texto alternativo mientras falta la imagen."""
        super().__init__(texto, padre)
        self.setObjectName("allPlayerPortrait")
        self.setFixedSize(54, 54)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def paintEvent(self, event: Any) -> None:
        """Dibuja imagen o fallback dentro del recorte redondeado."""
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        ruta = QPainterPath()
        ruta.addRoundedRect(area, 9, 9)
        pintor.save()
        pintor.setClipPath(ruta)
        pixmap = self.pixmap()
        if pixmap is not None and not pixmap.isNull():
            ancho = pixmap.width()
            alto = pixmap.height()
            lado = min(ancho, alto)
            origen = QRectF((ancho - lado) / 2, (alto - lado) / 2, lado, lado)
            pintor.drawPixmap(area, pixmap, origen)
        else:
            pintor.fillPath(ruta, QColor(PALETA["superficie"]))
            pintor.setPen(QColor(PALETA["marfil"]))
            pintor.drawText(area, Qt.AlignmentFlag.AlignCenter, self.text())
        pintor.restore()
        pintor.setPen(QPen(QColor(PALETA["oro_oscuro"]), 1))
        pintor.drawPath(ruta)


class BarraMiniRendimiento(QWidget):
    """Dibuja una barra compacta con referencia común y excedente visible."""

    def __init__(
        self,
        categoria: str,
        puntos: float | None,
        referencia: float,
        cobertura: float | None = None,
        padre: QWidget | None = None,
    ) -> None:
        """Configura categoría, puntos observados, referencia y cobertura."""
        super().__init__(padre)
        self.categoria = categoria
        self.puntos = puntos
        self.referencia = max(1.0, float(referencia))
        self.porcentaje = puntos / self.referencia * 100 if puntos is not None else None
        self.setObjectName("performanceMiniBar")
        self.setProperty("category", categoria)
        self.setFixedHeight(9)
        self.setMinimumWidth(24)
        if puntos is None:
            self.setToolTip("Datos no disponibles para esta categoría.")
        else:
            texto = (
                f"{TITULOS_CATEGORIA.get(categoria, categoria)}\n\n"
                f"{puntos:.1f} / {self.referencia:.0f} puntos\n"
                f"{self.porcentaje:.1f}% del rendimiento de referencia"
            )
            if self.porcentaje is not None and self.porcentaje > 100:
                texto += f"\nSupera la referencia en {self.porcentaje - 100:.1f}%"
            if cobertura is not None and cobertura < 1:
                texto += f"\nCobertura de datos: {cobertura:.0%}; hay métricas no disponibles."
            texto += "\nHaz clic en la tarjeta para ver el desglose."
            self.setToolTip(texto)

    def paintEvent(self, event: Any) -> None:
        """Pinta la pista y relleno redondeados sin exceder el ancho disponible."""
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radio = area.height() / 2
        pista = QPainterPath()
        pista.addRoundedRect(area, radio, radio)
        pintor.fillPath(pista, QColor("#0c1016"))
        if self.porcentaje is None or self.width() <= 0:
            return
        cantidad = min(1.0, max(0.0, self.porcentaje / 100))
        if cantidad > 0:
            relleno = QRectF(area)
            relleno.setWidth(max(area.height(), area.width() * cantidad))
            forma_relleno = QPainterPath()
            forma_relleno.addRoundedRect(relleno, radio, radio)
            pintor.save()
            pintor.setClipPath(pista)
            pintor.fillPath(
                forma_relleno,
                QColor(COLORES_CATEGORIA_RENDIMIENTO[self.categoria]),
            )
            if self.porcentaje > 100:
                pintor.fillRect(
                    QRectF(area.right() - 3, area.top(), 2, area.height()),
                    QColor(PALETA["oro_suave"]),
                )
            pintor.restore()


class TarjetaJugadorCompacta(QFrame):
    """Muestra la identidad y cinco indicadores compactos de un jugador."""

    def __init__(
        self,
        jugador: dict[str, Any],
        resultado: dict[str, Any],
        assets: Any,
        abrir: Callable[[str], None],
        equipo_aliado: bool,
        estadisticas_finales: dict[str, Any],
        punto_actual: dict[str, Any],
        padre: QWidget | None = None,
    ) -> None:
        """Construye una tarjeta enlazada a la clave del participante."""
        super().__init__(padre)
        self.participant_id = str(resultado.get("participant_id", ""))
        self.setObjectName("allPlayerPerformanceCard")
        self.setProperty("side", "ally" if equipo_aliado else "enemy")
        self.setProperty("rank", str(resultado.get("global_rank", "")))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(
            f"{jugador.get('champion_name') or resultado.get('champion') or 'Campeón'}, "
            f"{nombre_riot_visible(jugador) or resultado.get('riot_id') or 'jugador'}, "
            f"puesto {resultado.get('global_rank', 'no disponible')}"
        )
        self.setAccessibleDescription("Abrir el análisis detallado de rendimiento")
        self.setToolTip("Abrir análisis de rendimiento")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 9)
        root.setSpacing(5)
        encabezado = QHBoxLayout()
        retrato = RetratoCampeon("")
        campeon = str(
            jugador.get("champion_name") or resultado.get("champion") or "Campeón"
        )
        retrato.setText(campeon[:2].upper())
        if assets is not None:
            assets.set_label_image(
                retrato, assets.champion_url(campeon), f"all-player:{campeon}:54", 50
            )
        encabezado.addWidget(retrato)
        identidad = QVBoxLayout()
        identidad.setSpacing(1)
        nombre_campeon = QLabel(campeon)
        nombre_campeon.setObjectName("allPlayerChampion")
        nombre_completo = (
            nombre_riot_visible(jugador)
            or nombre_riot_visible({"riot_id": resultado.get("riot_id")})
            or "Invocador no disponible"
        )
        cuenta = EtiquetaElidida(nombre_completo)
        cuenta.setObjectName("allPlayerRiotId")
        identidad.addWidget(nombre_campeon)
        identidad.addWidget(cuenta)
        rol = str(jugador.get("role") or resultado.get("role") or "").upper()
        etiqueta_rol = QLabel(ROLES_NOMBRE.get(rol, rol or "ROL NO DISPONIBLE"))
        etiqueta_rol.setObjectName("allPlayerRole")
        identidad.addWidget(etiqueta_rol)
        encabezado.addLayout(identidad, 1)
        premios = list(resultado.get("awards", []))
        if (
            resultado.get("finalization_state") == "LIVE_PROVISIONAL"
            and resultado.get("global_rank") == 1
        ):
            premios = ["LÍDER PROVISIONAL"]
        texto_premio = " · ".join(premios)
        propiedad_premio = "provisional"
        if "MVP/SVP" in premios:
            texto_premio, propiedad_premio = "♛ MVP/SVP", "mvpsvp"
        elif "MVP" in premios:
            texto_premio, propiedad_premio = "♛ MVP", "mvp"
        elif "SVP" in premios:
            texto_premio, propiedad_premio = "★ SVP", "svp"
        premio = QLabel(texto_premio)
        premio.setObjectName("allPlayerAward")
        premio.setProperty("award", propiedad_premio)
        premio.setAlignment(Qt.AlignmentFlag.AlignCenter)
        premio.setVisible(bool(premios))
        encabezado.addWidget(premio, alignment=Qt.AlignmentFlag.AlignTop)
        root.addLayout(encabezado)
        valores = QHBoxLayout()
        puesto = QLabel(f"{resultado.get('global_rank', '—')}º")
        puesto.setObjectName("allPlayerRank")
        puesto.setProperty("rank", str(resultado.get("global_rank", "")))
        total = QLabel(f"{int(resultado.get('total', 0))} PUNTOS")
        total.setObjectName("allPlayerTotal")
        valores.addWidget(puesto)
        valores.addStretch(1)
        valores.addWidget(total)
        root.addLayout(valores)
        stats = (
            jugador.get("stats", {}) if isinstance(jugador.get("stats"), dict) else {}
        )
        kills = estadisticas_finales.get(
            "kills", punto_actual.get("kills", stats.get("kills"))
        )
        deaths = estadisticas_finales.get(
            "deaths", punto_actual.get("deaths", stats.get("deaths"))
        )
        assists = estadisticas_finales.get(
            "assists", punto_actual.get("assists", stats.get("assists"))
        )
        kda = QLabel(
            f"KDA  {kills if kills is not None else '—'} / {deaths if deaths is not None else '—'} / {assists if assists is not None else '—'}"
        )
        kda.setObjectName("allPlayerKda")
        root.addWidget(kda)
        for categoria in CATEGORIAS_VISTA:
            datos = resultado.get("categories", {}).get(categoria, {})
            referencia = max(1, int(REFERENCIAS[categoria]))
            puntos = (
                float(datos.get("final"))
                if float(datos.get("completeness", 0) or 0) > 0
                and datos.get("final") is not None
                else None
            )
            porcentaje = puntos / referencia * 100 if puntos is not None else None
            fila = QHBoxLayout()
            fila.setSpacing(5)
            nombre = QLabel(CATEGORIAS_ETIQUETA[categoria])
            nombre.setObjectName("allPlayerCategoryName")
            nombre.setMinimumWidth(84)
            barra = BarraMiniRendimiento(
                categoria,
                puntos,
                referencia,
                float(datos.get("completeness", 0) or 0),
            )
            etiqueta = QLabel(f"{porcentaje:.0f}%" if porcentaje is not None else "N/D")
            etiqueta.setObjectName("allPlayerCategoryPercent")
            etiqueta.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            etiqueta.setMinimumWidth(40)
            fila.addWidget(nombre)
            fila.addWidget(barra, 1)
            fila.addWidget(etiqueta)
            root.addLayout(fila)
        if resultado.get("faker_unlocked"):
            faker = QLabel(
                "★ ¿Faker?"
                + (" · PROVISIONAL" if resultado.get("faker_provisional") else "")
            )
            faker.setObjectName("specialPerformanceAchievement")
            root.addWidget(faker)
        self._abrir = abrir

    def mouseReleaseEvent(self, event: Any) -> None:
        """Abre el análisis al soltar el clic dentro de la tarjeta.

        Args:
            event: evento de ratón proporcionado por Qt.

        Returns:
            None.
        """
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self._abrir(self.participant_id)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: Any) -> None:
        """Activa el análisis mediante Intro o Espacio.

        Args:
            event: evento de teclado proporcionado por Qt.

        Returns:
            None.
        """
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._abrir(self.participant_id)
            event.accept()
            return
        super().keyPressEvent(event)


class DistribucionComparativa(QWidget):
    """Distribuye dos paneles simétricos o los apila en anchos reducidos."""

    def __init__(
        self,
        panel_aliado: QWidget,
        separador: QWidget,
        panel_rival: QWidget,
        padre: QWidget | None = None,
    ) -> None:
        """Crea el comparador con paneles y divisor proporcionados."""
        super().__init__(padre)
        self._paneles = (panel_aliado, separador, panel_rival)
        self._rejilla = QGridLayout(self)
        self._rejilla.setContentsMargins(0, 0, 0, 0)
        self._rejilla.setHorizontalSpacing(12)
        self._rejilla.setVerticalSpacing(8)
        self._rejilla.setColumnStretch(0, 1)
        self._rejilla.setColumnStretch(1, 0)
        self._rejilla.setColumnStretch(2, 1)
        separador.setMaximumWidth(190)
        separador.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )
        self._colocado: bool | None = None
        self._recolocar()

    def resizeEvent(self, event: Any) -> None:
        """Ajusta el comparador a dos columnas o a una columna."""
        super().resizeEvent(event)
        self._recolocar()

    def _recolocar(self) -> None:
        """Coloca los paneles lado a lado desde 900 px y los apila por debajo."""
        apilado = self.width() < 900
        if apilado == self._colocado:
            return
        for panel in self._paneles:
            self._rejilla.removeWidget(panel)
        if apilado:
            self._rejilla.addWidget(self._paneles[0], 0, 0)
            self._rejilla.addWidget(self._paneles[1], 1, 0)
            self._rejilla.addWidget(self._paneles[2], 2, 0)
        else:
            self._rejilla.addWidget(self._paneles[0], 0, 0)
            self._rejilla.addWidget(
                self._paneles[1],
                0,
                1,
                alignment=Qt.AlignmentFlag.AlignCenter,
            )
            self._rejilla.addWidget(self._paneles[2], 0, 2)
        self._colocado = apilado


class GrupoJugadores(QWidget):
    """Distribuye las tarjetas del equipo en una cuadrícula adaptable."""

    def __init__(
        self,
        titulo: str,
        jugadores: list[QWidget],
        equipo_aliado: bool,
        padre: QWidget | None = None,
    ) -> None:
        """Crea un grupo con un título y las tarjetas recibidas."""
        super().__init__(padre)
        self.setObjectName("allPlayersTeamGroup")
        self.setProperty("side", "ally" if equipo_aliado else "enemy")
        self._jugadores = jugadores
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(9)
        self._grid.setVerticalSpacing(9)
        self._titulo = QLabel(titulo)
        self._titulo.setObjectName("allPlayersTeamTitle")
        self._titulo.setProperty("side", "ally" if equipo_aliado else "enemy")
        self._grid.addWidget(self._titulo, 0, 0, 1, 5)
        for jugador in jugadores:
            jugador.setParent(self)
        self._recolocar()

    def resizeEvent(self, event: Any) -> None:
        """Recalcula las columnas al cambiar el ancho disponible."""
        super().resizeEvent(event)
        self._recolocar()

    def _recolocar(self) -> None:
        """Coloca de una a cinco tarjetas según el ancho del grupo."""
        for tarjeta in self._jugadores:
            self._grid.removeWidget(tarjeta)
        ancho = max(1, self.width())
        columnas = min(5, max(1, ancho // 220))
        self._titulo.setParent(None)
        self._grid.addWidget(self._titulo, 0, 0, 1, columnas)
        for indice, tarjeta in enumerate(self._jugadores):
            self._grid.addWidget(tarjeta, 1 + indice // columnas, indice % columnas)


class VistaTodosRendimiento(QWidget):
    """Presenta ambos equipos, sus diez jugadores y los promedios colectivos."""

    def __init__(
        self,
        session: dict[str, Any],
        ranking: dict[str, Any],
        assets: Any,
        abrir_jugador: Callable[[str], None],
        padre: QWidget | None = None,
    ) -> None:
        """Construye el overview desde la sesión y clasificación autoritativas."""
        super().__init__(padre)
        exterior = QVBoxLayout(self)
        exterior.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea(self)
        self.scroll.setObjectName("allPlayersOverviewScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        contenido = QWidget()
        self.contenido = contenido
        layout = QVBoxLayout(contenido)
        layout.setContentsMargins(4, 4, 4, 8)
        layout.setSpacing(12)
        modo = str(ranking.get("mode", "live")).upper()
        cabecera = QHBoxLayout()
        titulo = QLabel("CLASIFICACIÓN DE LA PARTIDA")
        titulo.setObjectName("allPlayersOverviewTitle")
        estado = QLabel("FINAL" if modo == "POSTGAME" else "PROVISIONAL")
        estado.setObjectName("allPlayersOverviewState")
        cabecera.addWidget(titulo)
        cabecera.addStretch(1)
        cabecera.addWidget(estado)
        layout.addLayout(cabecera)
        jugadores = session.get("players", {})
        por_equipo: dict[str, list[tuple[str, dict[str, Any], dict[str, Any]]]] = {}
        resultados = ranking.get("by_id", {})
        for clave, jugador in jugadores.items():
            resultado = resultados.get(str(clave))
            if not resultado or not isinstance(jugador, dict):
                continue
            equipo = str(jugador.get("team") or resultado.get("team") or "")
            por_equipo.setdefault(equipo, []).append((str(clave), jugador, resultado))
        for miembros in por_equipo.values():
            miembros.sort(
                key=lambda fila: (
                    ROLES_ORDEN.get(str(fila[1].get("role", "")).upper(), 9),
                    fila[0],
                )
            )
        self.grupos: list[GrupoJugadores] = []
        equipo_local = str(session.get("local_team") or "")
        equipos_orden = list(por_equipo)
        if equipo_local in equipos_orden:
            equipos_orden.remove(equipo_local)
            equipos_orden.insert(0, equipo_local)
        finales = session.get("final_scoreboard", {})
        puntos_actuales = session.get("snapshots", [])
        puntos_actuales = (
            puntos_actuales[-1].get("players", {})
            if puntos_actuales and isinstance(puntos_actuales[-1], dict)
            else {}
        )
        for indice, equipo in enumerate(equipos_orden):
            miembros = por_equipo[equipo]
            tarjetas = [
                TarjetaJugadorCompacta(
                    jugador,
                    resultado,
                    assets,
                    abrir_jugador,
                    indice == 0,
                    finales.get(clave, {}) if isinstance(finales, dict) else {},
                    puntos_actuales.get(clave, {})
                    if isinstance(puntos_actuales, dict)
                    else {},
                    contenido,
                )
                for clave, jugador, resultado in miembros
            ]
            grupo = GrupoJugadores(
                "EQUIPO ALIADO" if indice == 0 else "EQUIPO RIVAL",
                tarjetas,
                indice == 0,
                contenido,
            )
            grupo.setProperty("team", equipo)
            self.grupos.append(grupo)
            layout.addWidget(grupo)
        layout.addWidget(
            self._crear_comparacion(ranking.get("teams", {}), equipos_orden)
        )
        layout.addStretch(1)
        self.scroll.setWidget(contenido)
        exterior.addWidget(self.scroll)

    def _crear_comparacion(self, equipos: dict[str, Any], orden: list[str]) -> QFrame:
        """Construye los paneles sim?tricos y la diferencia de rendimiento.

        Args:
            equipos: promedios derivados del ranking autoritativo.
            orden: identificadores del equipo local y del equipo rival.

        Returns:
            Marco con comparaci?n accesible y adaptable.
        """
        marco = QFrame()
        marco.setObjectName("teamPerformanceComparison")
        layout = QVBoxLayout(marco)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(8)
        titulo = QLabel("COMPARACI?N DE EQUIPOS")
        titulo.setObjectName("allPlayersTeamTitle")
        layout.addWidget(titulo, alignment=Qt.AlignmentFlag.AlignCenter)
        comparacion_valida = len(orden) == 2 and all(
            equipos.get(equipo, {}).get("comparable") for equipo in orden
        )
        aliado = equipos.get(orden[0], {}) if orden else {}
        rival = equipos.get(orden[1], {}) if len(orden) > 1 else {}
        panel_aliado = self._crear_panel_equipo(
            aliado, "ally", comparacion_valida, rival
        )
        panel_rival = self._crear_panel_equipo(
            rival, "enemy", comparacion_valida, aliado
        )
        divisor = QFrame()
        divisor.setObjectName("teamComparisonDivider")
        divisor_layout = QVBoxLayout(divisor)
        divisor_layout.setContentsMargins(4, 0, 4, 0)
        divisor_layout.addStretch(1)
        vs = QLabel("VS")
        vs.setObjectName("teamComparisonVs")
        vs.setAlignment(Qt.AlignmentFlag.AlignCenter)
        divisor_layout.addWidget(vs)
        diferencia = None
        if (
            comparacion_valida
            and aliado.get("score") is not None
            and rival.get("score") is not None
        ):
            diferencia = abs(float(aliado["score"]) - float(rival["score"]))
        texto_diferencia = (
            f"{int(diferencia + 0.5):,}".replace(",", ".") + " puntos de diferencia"
            if diferencia is not None
            else "Comparaci?n parcial"
        )
        etiqueta_diferencia = QLabel(texto_diferencia)
        etiqueta_diferencia.setObjectName("teamPerformanceAverage")
        etiqueta_diferencia.setAlignment(Qt.AlignmentFlag.AlignCenter)
        divisor_layout.addWidget(etiqueta_diferencia)
        divisor_layout.addStretch(1)
        layout.addWidget(
            DistribucionComparativa(panel_aliado, divisor, panel_rival, marco)
        )
        return marco

    def _crear_panel_equipo(
        self,
        resumen: dict[str, Any],
        lado: str,
        comparacion_valida: bool,
        contrario: dict[str, Any],
    ) -> QFrame:
        """Crea una ficha de equipo con escala fija y datos de resultado.

        Args:
            resumen: promedio colectivo calculado por el servicio de puntuaci?n.
            lado: lado visual aliado o rival.
            comparacion_valida: indica si ambas plantillas son comparables.
            contrario: media de la plantilla opuesta.

        Returns:
            Panel de equipo con sus cinco barras de categor?a.
        """
        panel = QFrame()
        panel.setObjectName("teamPerformancePanel")
        panel.setProperty("side", lado)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(16, 14, 16, 14)
        panel_layout.setSpacing(8)
        nombre = QLabel("EQUIPO ALIADO" if lado == "ally" else "EQUIPO RIVAL")
        nombre.setObjectName("allPlayersTeamTitle")
        resultado = resumen.get("result")
        estado = QLabel(
            ("VICTORIA" if resultado == "victoria" else "DERROTA")
            if resultado
            else "RESULTADO NO CONFIRMADO"
        )
        estado.setObjectName("teamMatchResult")
        estado.setProperty("result", resultado or "unknown")
        encabezado = QHBoxLayout()
        encabezado.addWidget(nombre)
        encabezado.addStretch(1)
        encabezado.addWidget(estado)
        panel_layout.addLayout(encabezado)
        puntos = resumen.get("score")
        texto_puntos = (
            f"{int(float(puntos) + 0.5):,}".replace(",", ".") + " PUNTOS"
            if puntos is not None
            else "MEDIA NO DISPONIBLE"
        )
        puntuacion = QLabel(texto_puntos)
        puntuacion.setObjectName("teamPerformanceScore")
        panel_layout.addWidget(puntuacion)
        cobertura = float(resumen.get("completeness", 0) or 0)
        subtitulo = QLabel(
            "Promedio provisional de 5 jugadores"
            if resumen.get("mode") == "live"
            else "Promedio de 5 jugadores"
            if resumen.get("player_count") == 5 and comparacion_valida
            else f"Media parcial ? cobertura {cobertura:.0%}"
        )
        subtitulo.setObjectName("teamPerformanceAverage")
        panel_layout.addWidget(subtitulo)
        other_score = contrario.get("score")
        mayor_media = QLabel(
            "MAYOR MEDIA DE RENDIMIENTO"
            if comparacion_valida
            and puntos is not None
            and other_score is not None
            and puntos > other_score
            else "MISMA MEDIA DE RENDIMIENTO"
            if comparacion_valida and puntos is not None and puntos == other_score
            else ""
        )
        mayor_media.setObjectName("teamPerformanceLead")
        mayor_media.setVisible(bool(mayor_media.text()))
        panel_layout.addWidget(mayor_media)
        if resumen.get("t1_unlocked") or resumen.get("t1_provisional"):
            logro = QLabel(
                "?? ?T1?" + (" ? PROVISIONAL" if resumen.get("t1_provisional") else "")
            )
            logro.setObjectName("specialPerformanceAchievement")
            logro.setAccessibleName("Logro de equipo ?T1?")
            panel_layout.addWidget(logro, alignment=Qt.AlignmentFlag.AlignLeft)
        for categoria in CATEGORIAS_VISTA:
            puntos_categoria = resumen.get("categories", {}).get(categoria)
            if resumen.get("player_count") != 5:
                puntos_categoria = None
            fila = QHBoxLayout()
            fila.setSpacing(8)
            etiqueta = QLabel(CATEGORIAS_ETIQUETA[categoria])
            etiqueta.setObjectName("allPlayerCategoryName")
            etiqueta.setMinimumWidth(91)
            barra = BarraMiniRendimiento(
                categoria,
                float(puntos_categoria) if puntos_categoria is not None else None,
                REFERENCIAS[categoria],
                cobertura if puntos_categoria is not None else None,
            )
            valor = QLabel(
                f"{float(puntos_categoria):.1f}".replace(".", ",") + " p"
                if puntos_categoria is not None
                else "N/D"
            )
            valor.setObjectName("teamCategoryValue")
            fila.addWidget(etiqueta)
            fila.addWidget(barra, 1)
            fila.addWidget(valor)
            if comparacion_valida and puntos_categoria is not None:
                puntos_opuestos = contrario.get("categories", {}).get(categoria)
                if puntos_opuestos is not None:
                    delta = float(puntos_categoria) - float(puntos_opuestos)
                    delta_etiqueta = QLabel(
                        f"+{delta:.0f}"
                        if delta > 0
                        else f"?{abs(delta):.0f}"
                        if delta < 0
                        else "0"
                    )
                    delta_etiqueta.setObjectName("teamCategoryAdvantage")
                    delta_etiqueta.setProperty(
                        "advantage",
                        "ahead" if delta > 0 else "behind" if delta < 0 else "tie",
                    )
                    delta_etiqueta.setAlignment(Qt.AlignmentFlag.AlignRight)
                    delta_etiqueta.setMinimumWidth(35)
                    fila.addWidget(delta_etiqueta)
            panel_layout.addLayout(fila)
        return panel
