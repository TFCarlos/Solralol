"""Instalación global y roles semánticos de presentación, independientes del dominio."""

from PySide6.QtCore import QEvent, QObject, QSize, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QLabel,
    QMessageBox,
    QProxyStyle,
    QScrollArea,
    QSlider,
    QStyle,
    QStyleFactory,
    QStyleOption,
    QWidget,
)

from app.ui.estilo_global import ESTILO_GLOBAL
from app.ui.iconos import icono_accion
from app.ui.sistema_visual import ESPACIADO, PALETA, TAMANO_ICONO

ESTADOS = {
    "positivo": "exito",
    "positive": "exito",
    "ally": "exito",
    "blue": "exito",
    "negativo": "error",
    "negative": "error",
    "enemy": "error",
    "red": "error",
    "neutral": "informacion",
    "warning": "advertencia",
    "success": "exito",
    "danger": "error",
    "loading": "cargando",
}
ICONOS_TEXTO = {
    "×": "cerrar",
    "✕": "cerrar",
    "✖": "cerrar",
    "▶": "play",
    "►": "play",
    "⏸": "pausa",
    "❚❚": "pausa",
    "⏹": "parar",
    "■": "parar",
    "⏪": "retroceder",
    "⏩": "avanzar",
    "◀": "retroceder",
    "🔊": "volumen",
    "🔇": "silencio",
    "⛶": "pantalla",
    "↻": "actualizar",
    "🔄": "actualizar",
    "📁": "carpeta",
    "🗑": "eliminar",
    "⚔": "draft",
    "📊": "analisis",
    "🤖": "ia",
    "⚙": "ajustes",
    "💾": "guardar",
    "✎": "editar",
}


def color_con_alfa(clave: str, alfa: int = 255) -> QColor:
    """Devuelve el color del token recibido con alfa acotado a 0–255."""
    color = QColor(PALETA[clave])
    color.setAlpha(max(0, min(255, alfa)))
    return color


def actualizar_estilo(componente: QWidget) -> None:
    """Reevalúa propiedades visuales del componente recibido; retorna None."""
    componente.style().unpolish(componente)
    componente.style().polish(componente)
    componente.update()


def aplicar_estado(componente: QWidget, estado: str) -> None:
    """Asigna un estado semántico recibido, conservando texto y comportamiento."""
    componente.setProperty("estado", ESTADOS.get(estado, estado))


def aplicar_color(componente: QWidget, color: str) -> None:
    """Traduce un color de token recibido a un estado visual semántico compartido."""
    estados = {
        PALETA["ventaja"]: "exito",
        PALETA["desventaja"]: "error",
        PALETA["teal"]: "informacion",
        PALETA["informacion"]: "informacion",
        PALETA["oro"]: "advertencia",
        PALETA["oro_suave"]: "advertencia",
        PALETA["magenta"]: "informacion",
    }
    aplicar_estado(componente, estados.get(color, "normal"))


def aplicar_apariencia(componente: QWidget, rol: str) -> None:
    """Asigna un rol compartido al componente sin estilos locales; retorna None."""
    if isinstance(componente, QLabel) and rol in {"tarjeta", "compacta", "destacada"}:
        componente.setProperty(
            "nivel",
            "badge" if "badge" in componente.objectName().lower() else "tarjeta",
        )
        componente.setWordWrap(True)
        return
    elif isinstance(componente, QAbstractButton) and rol == "tarjeta":
        rol = "secundaria"
    elif isinstance(componente, QScrollArea):
        rol = "transparente"
    if rol in {
        "tarjeta",
        "compacta",
        "interactiva",
        "destacada",
        "transparente",
        "separador",
    }:
        componente.setProperty("superficie", rol)
        if (
            rol in {"tarjeta", "compacta", "interactiva", "destacada"}
            and componente.layout()
        ):
            espacio = ESPACIADO["3"] if rol == "compacta" else ESPACIADO["5"]
            componente.layout().setContentsMargins(espacio, espacio, espacio, espacio)
            componente.layout().setSpacing(ESPACIADO["3"])
    elif rol in {"primaria", "secundaria", "fantasma", "peligro", "icono"}:
        componente.setProperty("variante", rol)
    else:
        componente.setProperty("nivel", rol)
        if isinstance(componente, QLabel) and rol in {
            "pagina",
            "seccion",
            "tarjeta",
            "metadatos",
            "ayuda",
            "estado",
        }:
            componente.setWordWrap(True)


def establecer_icono_accion(
    boton: QAbstractButton, nombre: str, texto: str = ""
) -> None:
    """Asigna icono y texto recibidos con descripción accesible; retorna None."""
    boton.setIcon(icono_accion(nombre))
    boton.setIconSize(QSize(TAMANO_ICONO, TAMANO_ICONO))
    boton.setText(texto)
    descripcion = texto or {
        "play": "Reproducir",
        "pausa": "Pausar",
        "parar": "Detener",
        "cerrar": "Cerrar",
        "retroceder": "Retroceder",
        "avanzar": "Avanzar",
        "volumen": "Volumen",
        "silencio": "Silenciar",
        "pantalla": "Pantalla completa",
    }.get(nombre, nombre.capitalize())
    boton.setAccessibleName(descripcion)
    if not texto:
        boton.setToolTip(descripcion)
        boton.setProperty("variante", "icono")


def actualizar_texto_boton(boton: QAbstractButton, texto: str) -> None:
    """Actualiza texto de acción recibido y conserva iconos vectoriales en cambios de estado."""
    limpio = texto.replace("\ufe0f", "")
    for simbolo, accion in ICONOS_TEXTO.items():
        if limpio.startswith(simbolo):
            establecer_icono_accion(boton, accion, limpio[len(simbolo) :].strip())
            return
    boton.setText(texto)


def preparar_componente(componente: QWidget) -> None:
    """Clasifica el componente al crearse y aplica geometría y accesibilidad comunes."""
    nombre = componente.objectName().lower()
    rol_previo = componente.property("role")
    if rol_previo and isinstance(componente, QLabel):
        aplicar_apariencia(
            componente,
            {
                "title": "seccion",
                "hero": "pagina",
                "eyebrow": "etiqueta",
                "muted": "metadatos",
                "body": "cuerpo",
                "value": "metrica",
            }.get(rol_previo, "cuerpo"),
        )
    if componente.property("card") == "true":
        aplicar_apariencia(componente, "tarjeta")
    if (
        componente.isWindow()
        and not componente.property("superficie")
        and not componente.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    ):
        componente.setProperty("superficie", "ventana")
    if isinstance(componente, QLabel) and not componente.property("nivel"):
        nivel = None
        if any(p in nombre for p in ("status", "estado", "connection")):
            nivel = "estado"
        elif any(
            p in nombre
            for p in (
                "empty",
                "summary",
                "subtitle",
                "detail",
                "muted",
                "hint",
                "description",
                "helper",
                "playerid",
            )
        ):
            nivel = "metadatos"
        elif "badge" in nombre:
            nivel = "badge"
        elif any(
            p in nombre
            for p in ("herotitle", "postgametitle", "inspectortitle", "startupbrand")
        ):
            nivel = "pagina"
        elif any(
            p in nombre for p in ("sectiontitle", "heading", "groupTitle".lower())
        ):
            nivel = "seccion"
        elif "title" in nombre or "championname" in nombre:
            nivel = "tarjeta"
        elif any(p in nombre for p in ("caption", "eyebrow", "settingslabel")):
            nivel = "etiqueta"
        elif "metricvalue" in nombre or nombre == "livetime":
            nivel = "metrica"
        if nivel:
            aplicar_apariencia(componente, nivel)
    if (
        isinstance(componente, QFrame)
        and not componente.property("superficie")
        and not nombre.startswith("local")
    ):
        if "accent" in nombre or "divider" in nombre:
            aplicar_apariencia(componente, "separador")
        elif any(
            p in nombre for p in ("card", "panel", "header", "section", "controlsframe")
        ):
            aplicar_apariencia(componente, "tarjeta")
        elif any(p in nombre for p in ("row", "chip")):
            aplicar_apariencia(componente, "compacta")
    if isinstance(componente, QFrame) and componente.property("superficie") in {
        "tarjeta",
        "compacta",
        "interactiva",
        "destacada",
    }:
        aplicar_apariencia(componente, componente.property("superficie"))
    if isinstance(componente, QFrame) and nombre == "cardloadout":
        componente.setProperty("superficie", "transparente")
        if componente.layout():
            componente.layout().setContentsMargins(0, 0, 0, 0)
            componente.layout().setSpacing(1)
    if isinstance(componente, QAbstractButton):
        if not componente.property("variante"):
            variante = (
                "peligro"
                if "danger" in nombre
                else "primaria"
                if "primary" in nombre
                else "secundaria"
            )
            componente.setProperty("variante", variante)
        texto = componente.text().replace("\ufe0f", "")
        for simbolo, accion in ICONOS_TEXTO.items():
            if texto.startswith(simbolo):
                establecer_icono_accion(
                    componente, accion, texto[len(simbolo) :].strip()
                )
                break
        if componente.text() and not componente.accessibleName():
            componente.setAccessibleName(componente.text())
        componente.setCursor(Qt.CursorShape.PointingHandCursor)
    if isinstance(componente, QComboBox):
        componente.setAccessibleName(
            componente.accessibleName() or componente.toolTip() or "Selector"
        )
        componente.view().setMouseTracking(True)
        componente.setMaxVisibleItems(8)
        vista = componente.view()
        vista.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        vista.setMaximumHeight(260)
        contenedor = vista.parentWidget()
        if contenedor is not None:
            contenedor.setMaximumHeight(260)
    if isinstance(componente, QSlider):
        componente.setAccessibleName(
            componente.accessibleName() or componente.toolTip() or "Valor ajustable"
        )
    if isinstance(componente, QMessageBox):
        componente.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        nombre_icono = {
            QMessageBox.Icon.Warning: "advertencia",
            QMessageBox.Icon.Critical: "advertencia",
            QMessageBox.Icon.Information: "informacion",
            QMessageBox.Icon.Question: "informacion",
        }.get(componente.icon())
        if nombre_icono:
            componente.setIconPixmap(icono_accion(nombre_icono).pixmap(32, 32))
    if (
        componente.layout()
        and isinstance(componente, QDialog)
        and componente.isWindow()
    ):
        componente.layout().setContentsMargins(*([ESPACIADO["5"]] * 4))
        componente.layout().setSpacing(ESPACIADO["3"])
    if isinstance(componente, QLabel) and nombre == "cardlevelbadge":
        componente.setProperty("nivel", "live_badge")
        componente.setWordWrap(False)
    componente.setProperty("visualListo", True)


class EstiloSolralol(QProxyStyle):
    """Métricas nativas previsibles sobre Fusion, manteniendo navegación de teclado."""

    def pixelMetric(
        self,
        metric: QStyle.PixelMetric,
        option: QStyleOption | None = None,
        widget: QWidget | None = None,
    ) -> int:
        """Devuelve métricas comunes o delega las recibidas al estilo base."""
        valores = {
            QStyle.PixelMetric.PM_SmallIconSize: TAMANO_ICONO,
            QStyle.PixelMetric.PM_ScrollBarExtent: 10,
            QStyle.PixelMetric.PM_ButtonMargin: 12,
        }
        return valores.get(metric, super().pixelMetric(metric, option, widget))

    def styleHint(
        self,
        hint: QStyle.StyleHint,
        option: QStyleOption | None = None,
        widget: QWidget | None = None,
        returnData: object | None = None,
    ) -> int:
        """Establece el retraso de tooltips; delega el resto de consultas recibidas."""
        if hint == QStyle.StyleHint.SH_ToolTip_WakeUpDelay:
            return 400
        return super().styleHint(hint, option, widget, returnData)


class SistemaVisual(QObject):
    """Aplica roles una vez y repinta solamente cambios de propiedades visuales."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Prepara widgets o actualiza sus propiedades sin consumir el evento recibido."""
        if isinstance(watched, QWidget):
            if event.type() == QEvent.Type.Polish and not watched.property(
                "visualListo"
            ):
                preparar_componente(watched)
            elif (
                event.type() == QEvent.Type.DynamicPropertyChange
                and watched.property("visualListo")
                and bytes(event.propertyName())
                in {
                    b"estado",
                    b"superficie",
                    b"variante",
                    b"nivel",
                    b"cargando",
                    b"interruptor",
                    b"seleccionado",
                    b"state",
                    b"result",
                }
            ):
                actualizar_estilo(watched)
        return False


def instalar_sistema_visual(aplicacion: QApplication) -> SistemaVisual:
    """Instala una sola vez tema, paleta y filtro en la aplicación recibida."""
    existente = getattr(aplicacion, "sistema_visual", None)
    if existente is not None:
        return existente
    aplicacion.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)
    aplicacion.setStyle(EstiloSolralol(QStyleFactory.create("Fusion")))
    paleta = QPalette()
    for rol, clave in (
        (QPalette.ColorRole.Window, "superficie"),
        (QPalette.ColorRole.Base, "superficie"),
        (QPalette.ColorRole.AlternateBase, "elevada"),
        (QPalette.ColorRole.WindowText, "texto"),
        (QPalette.ColorRole.Text, "texto"),
        (QPalette.ColorRole.Button, "superficie"),
        (QPalette.ColorRole.ButtonText, "oro_suave"),
        (QPalette.ColorRole.Highlight, "oro_oscuro"),
        (QPalette.ColorRole.HighlightedText, "marfil"),
        (QPalette.ColorRole.PlaceholderText, "secundario"),
        (QPalette.ColorRole.Link, "oro_suave"),
        (QPalette.ColorRole.ToolTipBase, "elevada"),
        (QPalette.ColorRole.ToolTipText, "marfil"),
    ):
        paleta.setColor(rol, QColor(PALETA[clave]))
    for rol in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.ButtonText,
    ):
        paleta.setColor(
            QPalette.ColorGroup.Disabled, rol, QColor(PALETA["texto_deshabilitado"])
        )
    aplicacion.setPalette(paleta)
    aplicacion.setStyleSheet(ESTILO_GLOBAL)
    sistema = SistemaVisual(aplicacion)
    aplicacion.sistema_visual = sistema
    aplicacion.installEventFilter(sistema)
    return sistema


def aplicar_tema(componente: QWidget) -> None:
    """Asegura el tema global para ventanas independientes y limpia su hoja local."""
    aplicacion = QApplication.instance()
    if isinstance(aplicacion, QApplication):
        instalar_sistema_visual(aplicacion)
    componente.setStyleSheet("")
