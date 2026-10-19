"""Panel de gestión visual para las ventanas reales del overlay."""

from __future__ import annotations

from typing import Any, ClassVar

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsScene,
    QGraphicsView,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app.ui.componentes_visuales import Interruptor
from app.ui.overlay_window import (
    AlertsPanel,
    GoldPanel,
    OverlayWindow,
    PanelCompraRecomendada,
    ThreatPanel,
)


class VistaPreviaOverlay(QGraphicsView):
    """Presenta el widget real del overlay a escala dentro de Ajustes."""

    def __init__(self, panel: QWidget, parent: QWidget | None = None) -> None:
        """Inserta un panel real en una vista no interactiva.

        Parámetros: widget clonado del overlay y padre de la vista.
        Retorno: None; configura escala, opacidad y fondo de la vista.
        """
        super().__init__(parent)
        self.setObjectName("overlayPreviewViewport")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setFixedHeight(246)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        panel.setWindowFlags(Qt.WindowType.Widget)
        panel.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        panel.adjustSize()
        self.proxy = self.scene.addWidget(panel)
        panel.show()
        self.proxy.setOpacity(1.0)
        self._panel = panel
        self.preview_scale = 1.0
        self.setStyleSheet(
            "background: #15251f; border: 1px solid #344256; border-radius: 9px;"
        )

    def showEvent(self, event: QShowEvent) -> None:
        """Ajusta el encuadre al mostrarse la vista previa.

        Parámetros: evento de visibilidad de Qt.
        Retorno: None; escala el panel real completo al área disponible.
        """
        super().showEvent(event)
        self._fit_panel()

    def _fit_panel(self) -> None:
        """Calcula la escala para que el panel entero quepa en el preview.

        Parámetros: ninguno.
        Retorno: None; centra el widget proxy sin recortar sus filas.
        """
        if self._panel.width() > 0 and self._panel.height() > 0:
            self.resetTransform()
            self.setSceneRect(self.proxy.boundingRect())
            self.fitInView(self.proxy, Qt.AspectRatioMode.KeepAspectRatio)
            self.scale(self.preview_scale, self.preview_scale)

    def set_preview_opacity(self, percentage: int) -> None:
        """Refleja la opacidad configurada en el panel real.

        Parámetros: opacidad de 0 a 100.
        Retorno: None; aplica opacidad al proxy sin reconstruir el preview.
        """
        self.proxy.setOpacity(max(0, min(100, percentage)) / 100)

    def set_preview_scale(self, percentage: int) -> None:
        """Refleja el factor configurado manteniendo la proporción del HUD.

        Parámetros: escala porcentual entre 50 y 150.
        Retorno: None; reencuadra la instancia real en la tarjeta.
        """
        self.preview_scale = max(50, min(150, int(percentage))) / 100
        self._fit_panel()

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Escala el widget completo al cambiar el ancho de la tarjeta.

        Parámetros: evento de redimensionado de Qt.
        Retorno: None; conserva el panel centrado y sin recortes.
        """
        super().resizeEvent(event)
        self._fit_panel()


class RejillaAjustesOverlay(QWidget):
    """Cuadrícula responsiva que conserva sus tarjetas al redimensionarse."""

    def __init__(self, cards: list[QWidget], parent: QWidget | None = None) -> None:
        """Crea una cuadrícula de cuatro, dos o una columna.

        Parámetros: tarjetas de configuración y widget padre.
        Retorno: None; distribuye los widgets dados.
        """
        super().__init__(parent)
        self.cards = cards
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(12)
        self.grid.setVerticalSpacing(12)
        self.columns = 0
        self._relayout()

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Recalcula columnas solo cuando cambia el umbral responsive.

        Parámetros: evento de redimensionado de Qt.
        Retorno: None; recoloca las mismas tarjetas y controles.
        """
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self) -> None:
        """Distribuye las tarjetas según el ancho actual.

        Parámetros: ninguno.
        Retorno: None; aplica una, dos o cuatro columnas.
        """
        width = self.width()
        columns = 4 if width >= 1280 else 2 if width >= 620 else 1
        if columns == self.columns:
            return
        self.columns = columns
        while self.grid.count():
            self.grid.takeAt(0)
        for index, card in enumerate(self.cards):
            self.grid.addWidget(card, index // columns, index % columns)


class OverlaySettingsDashboard(QWidget):
    """Ajustes de los cuatro overlays con previews de los widgets de juego."""

    PANEL_INFO: ClassVar[dict[str, tuple[str, str]]] = {
        "alerts": ("Alertas", "Objetivos, compras y eventos importantes."),
        "gold": ("Diferencias de oro", "Ventaja estimada por líneas."),
        "threat": ("Amenaza (BattleScore)", "Rivales con mayor y menor puntuación."),
        "purchase": ("Compra recomendada", "Tres objetos con puntuación de afinidad."),
    }

    def __init__(
        self,
        overlay: OverlayWindow,
        item_catalog: dict[str, Any],
        parent: QWidget | None = None,
    ) -> None:
        """Construye el dashboard y conecta todos los controles persistentes.

        Parámetros: gestor de overlays, catálogo Data Dragon y widget padre.
        Retorno: None; guarda vistas previas y referencias a controles.
        """
        super().__init__(parent)
        self.overlay = overlay
        self.item_catalog = item_catalog
        self.assets = None
        self.controls: dict[str, dict[str, Any]] = {}
        self.previews: dict[str, VistaPreviaOverlay] = {}
        self.setObjectName("overlaySettingsDashboard")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)
        root.addWidget(self._build_header())
        self.show_all_button = QPushButton("Mostrar todos los overlays")
        self.show_all_button.setObjectName("primaryButton")
        self.show_all_button.clicked.connect(self.overlay.toggle_all)
        root.addWidget(self.show_all_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.preview_test_button = QPushButton("Probar overlays en pantalla")
        self.preview_test_button.setObjectName("secondaryButton")
        self.preview_test_button.setCheckable(True)
        self.preview_test_button.toggled.connect(self._toggle_demo_overlays)
        root.addWidget(self.preview_test_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.cards = [self._build_card(key) for key in self.PANEL_INFO]
        self.grid = RejillaAjustesOverlay(self.cards)
        root.addWidget(self.grid)
        root.addWidget(self._build_general_settings())
        self.status = QLabel()
        self.status.setObjectName("mutedText")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.overlay.state_changed.connect(self.sync)
        self.sync()

    def _toggle_demo_overlays(self, enabled: bool) -> None:
        """Activa o termina la prueba temporal de ventanas flotantes.

        Parámetros: True para mostrar muestras en las ventanas reales.
        Retorno: None; delega el ciclo de demostración al gestor.
        """
        if enabled:
            self.overlay.show_demo_overlays()
            self.preview_test_button.setText("Cerrar prueba de overlays")
        else:
            self.overlay.end_demo_overlays()
            self.preview_test_button.setText("Probar overlays en pantalla")

    def _build_header(self) -> QWidget:
        """Crea título, descripción e información de contexto.

        Parámetros: ninguno.
        Retorno: QWidget con encabezado de la página de overlays.
        """
        wrapper = QWidget()
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        title_group = QVBoxLayout()
        title = QLabel("Overlay y avisos")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Personaliza qué información aparece durante la partida, cómo se muestra y cuándo aparece."
        )
        subtitle.setObjectName("mutedText")
        subtitle.setWordWrap(True)
        title_group.addWidget(title)
        title_group.addWidget(subtitle)
        layout.addLayout(title_group, 2)
        info = QLabel(
            "ⓘ  Los overlays aparecen solo durante partidas de League of Legends. "
            "Cada panel mantiene su posición y ajustes independientes."
        )
        info.setObjectName("overlayInfoBanner")
        info.setWordWrap(True)
        layout.addWidget(info, 1)
        return wrapper

    def _build_card(self, key: str) -> QFrame:
        """Crea la tarjeta de un panel con preview y controles propios.

        Parámetros: clave del panel del gestor.
        Retorno: QFrame configurado y conectado al overlay correspondiente.
        """
        title_text, description_text = self.PANEL_INFO[key]
        card = QFrame()
        card.setObjectName("overlaySettingsCard")
        card.setMinimumWidth(270)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 13, 14, 14)
        layout.setSpacing(8)
        heading = QHBoxLayout()
        title = QLabel(title_text)
        title.setObjectName("overlaySettingsTitle")
        heading.addWidget(title, 1)
        if key == "purchase":
            badge = QLabel("NUEVO")
            badge.setObjectName("overlayNewBadge")
            heading.addWidget(badge)
        layout.addLayout(heading)
        description = QLabel(description_text)
        description.setObjectName("mutedText")
        description.setWordWrap(True)
        layout.addWidget(description)
        preview = VistaPreviaOverlay(self._create_preview_panel(key))
        layout.addWidget(preview)
        self.previews[key] = preview
        visible = Interruptor("Overlay visible")
        visible.toggled.connect(
            lambda value, panel=key: self.overlay.set_panel_enabled(panel, value)
        )
        tab = Interruptor("Solo con TAB")
        tab.toggled.connect(
            lambda value, panel=key: self.overlay.set_tab_only(panel, value)
        )
        clicks = Interruptor("Permitir clics al juego")
        clicks.setToolTip("Al activarlo, los clics atraviesan este panel.")
        clicks.toggled.connect(
            lambda value, panel=key: self.overlay.set_panel_click_through(panel, value)
        )
        for control in (visible, tab, clicks):
            layout.addWidget(control)
        opacity_row = QHBoxLayout()
        opacity_label = QLabel("Opacidad")
        opacity_label.setObjectName("settingsLabel")
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        value_label = QLabel()
        value_label.setMinimumWidth(36)
        value_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        slider.valueChanged.connect(
            lambda value, panel=key, view=preview, text=value_label: (
                self._change_opacity(panel, value, view, text)
            )
        )
        opacity_row.addWidget(opacity_label)
        opacity_row.addWidget(slider, 1)
        opacity_row.addWidget(value_label)
        layout.addLayout(opacity_row)
        scale_row = QHBoxLayout()
        scale_label = QLabel("Tamaño")
        scale_label.setObjectName("settingsLabel")
        scale_slider = QSlider(Qt.Orientation.Horizontal)
        scale_slider.setRange(50, 150)
        scale_value = QLabel()
        scale_value.setMinimumWidth(40)
        scale_value.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        scale_slider.valueChanged.connect(
            lambda value, panel=key, view=preview, text=scale_value: self._change_scale(
                panel, value, view, text
            )
        )
        scale_row.addWidget(scale_label)
        scale_row.addWidget(scale_slider, 1)
        scale_row.addWidget(scale_value)
        layout.addLayout(scale_row)
        action_row = QHBoxLayout()
        reset_size = QPushButton("Restablecer tamaño")
        reset_size.clicked.connect(
            lambda _checked=False, panel=key: self.overlay.set_panel_scale(panel, 1.0)
        )
        edit_size = QPushButton("Editar posición y tamaño")
        edit_size.setCheckable(True)
        edit_size.toggled.connect(
            lambda enabled, panel=key: self._toggle_editing(panel, enabled)
        )
        action_row.addWidget(reset_size)
        action_row.addWidget(edit_size)
        layout.addLayout(action_row)
        duration = None
        if key == "alerts":
            test_button = QPushButton("Probar alerta")
            test_button.clicked.connect(self.overlay.test_alert)
            layout.addWidget(test_button)
            duration_row = QHBoxLayout()
            duration_row.addWidget(QLabel("Duración del aviso"))
            duration = QComboBox()
            for seconds in (3, 5, 8, 10):
                duration.addItem(f"{seconds} segundos", seconds)
            duration.currentIndexChanged.connect(
                lambda _index, selector=duration: (
                    self.overlay.set_alert_duration_seconds(int(selector.currentData()))
                )
            )
            duration_row.addWidget(duration, 1)
            layout.addLayout(duration_row)
        self.controls[key] = {
            "visible": visible,
            "tab": tab,
            "clicks": clicks,
            "opacity": slider,
            "opacity_value": value_label,
            "scale": scale_slider,
            "scale_value": scale_value,
            "reset_size": reset_size,
            "edit_size": edit_size,
            "duration": duration,
            "test": test_button if key == "alerts" else None,
        }
        return card

    def _create_preview_panel(self, key: str) -> QWidget:
        """Genera datos demostrativos solo para el preview del panel real.

        Parámetros: clave del panel que se previsualiza.
        Retorno: una instancia del mismo widget utilizado sobre el juego.
        """
        panel = {
            "gold": GoldPanel(self.item_catalog),
            "alerts": AlertsPanel(self.item_catalog),
            "threat": ThreatPanel(self.item_catalog),
            "purchase": PanelCompraRecomendada(self.item_catalog),
        }[key]
        panel.set_assets(getattr(self, "assets", None))
        self._render_sample(key, panel)
        return panel

    def _render_sample(self, key: str, panel: QWidget) -> None:
        """Pinta datos de muestra exclusivamente en una instancia de preview.

        Parámetros: clave del panel e instancia real clonada para Ajustes.
        Retorno: None; no envía valores de demostración al overlay de partida.
        """
        if key == "gold":
            allies = ["Garen", "Vi", "Ahri", "Jinx", "Leona"]
            enemies = ["Darius", "LeeSin", "Yasuo", "Caitlyn", "Nautilus"]
            ally_gold = [3200, 2800, 4100, 3700, 1950]
            enemy_gold = [2700, 3000, 3300, 3050, 1800]
            roles = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]
            lanes = [
                {
                    "role": role,
                    "ally": {"champion": ally, "gold": ally_value},
                    "enemy": {"champion": enemy, "gold": enemy_value},
                    "paired": True,
                    "delta": ally_value - enemy_value,
                }
                for role, ally, enemy, ally_value, enemy_value in zip(
                    roles, allies, enemies, ally_gold, enemy_gold, strict=True
                )
            ]
            panel.render({"team": {"delta": 1900}, "lanes": lanes})
        elif key == "alerts":
            panel.render(
                [
                    {
                        "kind": "objective",
                        "key": "objective:dragon",
                        "name": "Dragón en 45 s",
                        "remaining": 45,
                        "urgent": False,
                        "spawn_at": 1500,
                    }
                ]
            )
            panel.alert_timer.stop()
        elif key == "threat":
            panel.render(
                {
                    "strongest": {"champion": "Garen", "role": "TOP", "score": 1324},
                    "weakest": {"champion": "Yone", "role": "JUNGLE", "score": 642},
                }
            )
        else:
            panel.render(
                "Gragas",
                [
                    {"item_id": "6655", "name": "Tormenta de Luden", "score": 92.0},
                    {
                        "item_id": "3157",
                        "name": "Reloj de arena de Zhonya",
                        "score": 85.0,
                    },
                    {
                        "item_id": "3089",
                        "name": "Sombrero mortal de Rabadon",
                        "score": 78.0,
                    },
                ],
            )

    def _change_opacity(
        self, key: str, value: int, preview: VistaPreviaOverlay, label: QLabel
    ) -> None:
        """Aplica la opacidad al panel de juego y a su preview.

        Parámetros: clave, valor, vista previa y etiqueta numérica.
        Retorno: None; guarda la preferencia y refleja el cambio inmediatamente.
        """
        self.overlay.set_panel_opacity(key, value)
        preview.set_preview_opacity(value)
        label.setText(f"{value}%")

    def _change_scale(
        self, key: str, value: int, preview: VistaPreviaOverlay, label: QLabel
    ) -> None:
        """Sincroniza escala del juego, el preview y su etiqueta.

        Parámetros: clave, porcentaje, preview y etiqueta de valor.
        Retorno: None; comparte la escala persistente del overlay.
        """
        self.overlay.set_panel_scale(key, value / 100)
        preview.set_preview_scale(value)
        label.setText(f"{value}%")

    def _toggle_editing(self, key: str, enabled: bool) -> None:
        """Activa el panel editable o finaliza el modo de edición.

        Parámetros: clave de tarjeta y estado del botón.
        Retorno: None; el botón queda disponible para terminar la edición.
        """
        if enabled:
            self.overlay.begin_editing(key)
        elif self.overlay.editing_panel == key:
            self.overlay.end_editing()

    def _build_general_settings(self) -> QFrame:
        """Agrupa anticipación y sonido, que son ajustes realmente compartidos.

        Parámetros: ninguno.
        Retorno: tarjeta general con controles de alertas y volumen.
        """
        frame = QFrame()
        frame.setObjectName("overlayGeneralCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 13, 16, 14)
        title = QLabel("Ajustes generales del overlay")
        title.setObjectName("overlaySettingsTitle")
        layout.addWidget(title)
        volume_row = QHBoxLayout()
        self.sound_enabled_checkbox = Interruptor("Sonidos de avisos")
        self.sound_enabled_checkbox.toggled.connect(self.overlay.set_sound_enabled)
        volume_row.addWidget(self.sound_enabled_checkbox)
        volume_row.addWidget(QLabel("Volumen"))
        self.sound_volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.sound_volume_slider.setRange(0, 100)
        self.sound_volume_slider.valueChanged.connect(
            lambda value: self.overlay.set_sound_volume(value / 100)
        )
        volume_row.addWidget(self.sound_volume_slider, 1)
        self.sound_volume_value = QLabel()
        volume_row.addWidget(self.sound_volume_value)
        layout.addLayout(volume_row)
        self.sound_objective_checkbox = Interruptor("Objetivos")
        self.sound_objective_checkbox.toggled.connect(
            lambda value: self.overlay.set_sound_kind_enabled("objective", value)
        )
        self.sound_dragon_checkbox = Interruptor("Dragón")
        self.sound_dragon_checkbox.toggled.connect(
            lambda value: self.overlay.set_sound_kind_enabled("dragon", value)
        )
        self.sound_enemy_buy_checkbox = Interruptor("Compras rivales")
        self.sound_enemy_buy_checkbox.toggled.connect(
            lambda value: self.overlay.set_sound_kind_enabled("enemy_buy", value)
        )
        sound_kinds = QHBoxLayout()
        for control in (
            self.sound_objective_checkbox,
            self.sound_dragon_checkbox,
            self.sound_enemy_buy_checkbox,
        ):
            sound_kinds.addWidget(control)
        layout.addLayout(sound_kinds)
        return frame

    def set_assets(self, assets: Any) -> None:
        """Conecta el servicio Data Dragon a los widgets de vista previa.

        Parámetros: servicio ya inicializado por la ventana principal.
        Retorno: None; alimenta las instancias de preview con la caché existente.
        """
        self.assets = assets
        for preview in self.previews.values():
            panel = preview._panel
            panel.set_assets(assets)
            self._render_sample(panel.key, panel)

    def sync(self) -> None:
        """Refleja la configuración guardada en todos los controles.

        Parámetros: ninguno.
        Retorno: None; sincroniza estados, volúmenes y mensaje de partida.
        """
        for key, controls in self.controls.items():
            for name, value in (
                ("visible", self.overlay.is_panel_enabled(key)),
                ("tab", self.overlay.is_tab_only(key)),
                ("clicks", self.overlay.panel_clicks_locked(key)),
            ):
                controls[name].blockSignals(True)
                controls[name].setChecked(value)
                controls[name].blockSignals(False)
            slider = controls["opacity"]
            slider.blockSignals(True)
            slider.setValue(self.overlay.panel_opacity(key))
            slider.blockSignals(False)
            controls["opacity_value"].setText(f"{slider.value()}%")
            self.previews[key].set_preview_opacity(slider.value())
            scale = controls["scale"]
            scale.blockSignals(True)
            scale.setValue(round(self.overlay.panel_scale(key) * 100))
            scale.blockSignals(False)
            controls["scale_value"].setText(f"{scale.value()}%")
            self.previews[key].set_preview_scale(scale.value())
            controls["edit_size"].blockSignals(True)
            controls["edit_size"].setChecked(self.overlay.editing_panel == key)
            controls["edit_size"].setText(
                "Finalizar edición"
                if self.overlay.editing_panel == key
                else "Editar posición y tamaño"
            )
            controls["edit_size"].blockSignals(False)
            if controls["duration"] is not None:
                duration = controls["duration"]
                duration.blockSignals(True)
                index = duration.findData(self.overlay.alert_duration_seconds)
                duration.setCurrentIndex(max(0, index))
                duration.blockSignals(False)
        self.show_all_button.setText(
            "Ocultar todos los overlays"
            if self.overlay.any_enabled()
            else "Mostrar todos los overlays"
        )
        self.preview_test_button.blockSignals(True)
        self.preview_test_button.setChecked(self.overlay._demo_mode)
        self.preview_test_button.setText(
            "Cerrar prueba de overlays"
            if self.overlay._demo_mode
            else "Probar overlays en pantalla"
        )
        self.preview_test_button.blockSignals(False)
        self.sound_enabled_checkbox.blockSignals(True)
        self.sound_enabled_checkbox.setChecked(self.overlay.is_sound_enabled())
        self.sound_enabled_checkbox.blockSignals(False)
        self.sound_volume_slider.blockSignals(True)
        volume = round(self.overlay.sound_service.volume * 100)
        self.sound_volume_slider.setValue(volume)
        self.sound_volume_slider.blockSignals(False)
        self.sound_volume_value.setText(f"{volume}%")
        for control, kind in (
            (self.sound_objective_checkbox, "objective"),
            (self.sound_dragon_checkbox, "dragon"),
            (self.sound_enemy_buy_checkbox, "enemy_buy"),
        ):
            control.blockSignals(True)
            control.setChecked(self.overlay.sound_service.kind_enabled(kind))
            control.blockSignals(False)
        self.status.setText(
            "Los overlays están en pantalla durante la partida."
            if self.overlay.in_game
            else "Los previews usan datos de demostración; los overlays de juego aparecen al iniciar una partida."
        )
