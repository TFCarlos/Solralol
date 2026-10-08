"""Tokens compartidos derivados de los píxeles de LogoApp.png."""

from types import MappingProxyType

from PySide6.QtWidgets import QLayout

PALETA = MappingProxyType(
    {
        "base": "#05070c",
        "superficie": "#10151e",
        "elevada": "#19202a",
        "calida": "#1a0f0b",
        "oro_logo": "#ccaf42",
        "oro": "#b69a50",
        "oro_suave": "#d0bb7b",
        "oro_oscuro": "#544326",
        "marfil": "#e1dab2",
        "texto": "#eee8d8",
        "secundario": "#afa99c",
        "tenue": "#78818e",
        "borde": "#30343a",
        "teal": "#609a96",
        "magenta": "#8e657d",
        "ventaja": "#79af99",
        "desventaja": "#ca8580",
        "superficie_victoria": "#17201e",
        "superficie_victoria_fin": "#131c20",
        "superficie_derrota": "#21191b",
        "superficie_derrota_fin": "#1c171a",
        "hover": "#29251e",
        "activo": "#352c1b",
        "deshabilitado": "#15191f",
        "texto_deshabilitado": "#938d82",
        "inverso": "#10151e",
        "advertencia": "#d0bb7b",
        "informacion": "#86b5b0",
        "borde_sutil": "#252a31",
        "cyan": "#82afb5",
    }
)
COLORES_CATEGORIA_RENDIMIENTO = MappingProxyType(
    {
        "combate": "#c47d70",
        "economia": "#b69a50",
        "objetivos": "#829bb6",
        "vision": "#70a99b",
        "supervivencia": "#a08bb5",
    }
)

ESPACIO_MINIMO = 6
ESPACIO_PEQUENO = 12
ESPACIO_TARJETA = 20
ESPACIO_SECCION = 18
RADIO_ICONO = 8
RADIO_TARJETA = 16
DURACION_BARRA = 240
ANCHO_BARRA = 248
ANCHO_BARRA_COMPACTA = 84

TIPOGRAFIA = MappingProxyType(
    {
        "aplicacion": 26,
        "pagina": 24,
        "seccion": 16,
        "tarjeta": 14,
        "etiqueta": 13,
        "cuerpo": 13,
        "metadatos": 12,
        "ayuda": 12,
        "estado": 12,
        "tooltip": 12,
        "badge": 12,
        "metrica": 23,
        "nivel_live_compacto": 10,
        "nivel_live_estandar": 10,
        "nivel_live_amplio": 11,
    }
)
ESPACIADO = MappingProxyType({"1": 4, "2": 6, "3": 12, "4": 18, "5": 20, "6": 28})
RADIOS = MappingProxyType(
    {"pequeno": 4, "control": 8, "compacto": 12, "tarjeta": 16, "modal": 16}
)
TRANSICIONES = MappingProxyType({"hover": 150, "estado": 200, "sidebar": 240})
EFECTOS = MappingProxyType(
    {"ninguno": 0, "elevacion": 12, "hover": 18, "activo": 26, "modal": 32}
)
ALTURA_CONTROL = 36
TAMANO_ICONO = 20


def espaciar_tarjeta(disposicion: QLayout, compacta: bool = False) -> None:
    """Aplica a disposición el relleno normal o compacto recibido; retorna None."""
    margen = ESPACIO_PEQUENO if compacta else ESPACIO_TARJETA
    disposicion.setContentsMargins(margen, margen, margen, margen)
    disposicion.setSpacing(ESPACIO_PEQUENO)
