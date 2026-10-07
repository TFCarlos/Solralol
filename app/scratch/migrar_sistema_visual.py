"""Migración reproducible de declaraciones visuales; no transforma lógica de dominio."""

import ast
import colorsys
import re
from pathlib import Path


def token_color(color: str) -> str:
    """Clasifica un color hexadecimal heredado en la paleta aprobada."""
    color = color.lstrip("#")
    if len(color) == 3:
        color = "".join(c * 2 for c in color)
    rojo, verde, azul = (int(color[i:i + 2], 16) / 255 for i in (0, 2, 4))
    tono, saturacion, valor = colorsys.rgb_to_hsv(rojo, verde, azul)
    if valor < .12:
        return "base"
    if valor < .19:
        return "superficie"
    if valor < .26:
        return "elevada"
    if valor < .38:
        return "borde"
    if saturacion < .22:
        return "texto" if valor > .8 else "secundario" if valor > .55 else "tenue"
    if tono < .05 or tono > .88:
        return "desventaja"
    if tono < .19:
        return "oro_suave" if valor > .85 else "oro"
    if tono < .45:
        return "ventaja"
    if tono < .7:
        return "teal"
    return "magenta"


def reemplazar_fuente(fuente: str, cambios: list[tuple[ast.AST, str]]) -> str:
    """Aplica sustituciones no solapadas usando posiciones UTF-8 del AST."""
    datos = fuente.encode("utf-8")
    lineas = datos.splitlines(keepends=True)
    inicios = [0]
    for linea in lineas:
        inicios.append(inicios[-1] + len(linea))
    intervalos = [(inicios[n.lineno - 1] + n.col_offset,
                   inicios[n.end_lineno - 1] + n.end_col_offset, texto.encode("utf-8"))
                  for n, texto in cambios]
    for inicio, fin, texto in sorted(intervalos, reverse=True):
        datos = datos[:inicio] + texto + datos[fin:]
    return datos.decode("utf-8")


def rol_estatico(estilo: str) -> str:
    """Mapea una declaración antigua a una variante de componente compartida."""
    inferior = estilo.lower()
    if "transparent" in inferior and "border:" not in inferior:
        return "transparente"
    if "background" in inferior and ("border-radius" in inferior or "border:" in inferior):
        return "tarjeta"
    if "background" in inferior:
        return "separador"
    tamano = re.search(r"font-size:\s*(\d+)", inferior)
    if tamano and int(tamano[1]) >= 18:
        return "pagina"
    if tamano and int(tamano[1]) >= 14:
        return "tarjeta"
    if "bold" in inferior or re.search(r"font-weight:\s*[6789]", inferior):
        return "etiqueta"
    return "metadatos"


def migrar_archivo(ruta: Path) -> None:
    """Migra QSS local y colores dibujados del archivo UI recibido."""
    fuente = ruta.read_text(encoding="utf-8")
    arbol = ast.parse(fuente)
    cambios = []
    for n in ast.walk(arbol):
        if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Attribute) or n.func.attr != "setStyleSheet":
            continue
        destino = ast.unparse(n.func.value)
        argumento = n.args[0]
        if ruta.name == "local_analysis_dialog.py" and n.lineno < 1910:
            continue
        if isinstance(argumento, ast.Name) and argumento.id in {"CONTROL_WINDOW_STYLE", "STARTUP_STYLE", "PANEL_STYLE", "_PANEL_STYLE"}:
            nuevo = f"aplicar_tema({destino})"
        elif destino == "self" and ruta.name in {"main_window.py", "draft_tool_dialog.py", "live_timeline.py"}:
            nuevo = f"aplicar_tema({destino})"
        elif isinstance(argumento, ast.Name) and argumento.id == "tint":
            nuevo = f"aplicar_estado({destino}, self.polarity)"
        elif isinstance(argumento, ast.IfExp):
            nuevo = f'aplicar_estado({destino}, "error" if {ast.unparse(argumento.test)} else "informacion")'
        elif isinstance(argumento, ast.JoinedStr):
            variables = [v.value for v in argumento.values if isinstance(v, ast.FormattedValue)]
            nuevo = f"aplicar_color({destino}, {ast.unparse(variables[0])})" if variables else f'aplicar_apariencia({destino}, "metadatos")'
        elif isinstance(argumento, ast.Constant) and isinstance(argumento.value, str):
            rol = rol_estatico(argumento.value)
            nuevo = f'aplicar_apariencia({destino}, "{rol}")'
        else:
            raise ValueError((ruta, n.lineno, ast.unparse(argumento)))
        cambios.append((n, nuevo))
    fuente = reemplazar_fuente(fuente, cambios)
    arbol = ast.parse(fuente)
    cambios = []
    for n in ast.walk(arbol):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "QColor" and len(n.args) in {3, 4}:
            if all(isinstance(a, ast.Constant) and isinstance(a.value, int) for a in n.args):
                rgb = "#" + "".join(f"{a.value:02x}" for a in n.args[:3])
                alfa = n.args[3].value if len(n.args) == 4 else 255
                cambios.append((n, f'color_con_alfa("{token_color(rgb)}", {alfa})'))
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", n.value):
            if ruta.name == "local_analysis_dialog.py":
                continue
            cambios.append((n, f'PALETA["{token_color(n.value)}"]'))
    fuente = reemplazar_fuente(fuente, cambios)
    if cambios or "aplicar_" in fuente:
        fuente = 'from app.ui.tema import aplicar_tema, aplicar_apariencia, aplicar_estado, aplicar_color, color_con_alfa\nfrom app.ui.sistema_visual import PALETA\n' + fuente if "from __future__" not in fuente else fuente.replace("from __future__ import annotations", "from __future__ import annotations\n\nfrom app.ui.tema import aplicar_tema, aplicar_apariencia, aplicar_estado, aplicar_color, color_con_alfa\nfrom app.ui.sistema_visual import PALETA", 1)
    ruta.write_text(fuente, encoding="utf-8")


if __name__ == "__main__":
    for nombre in ("main_window", "control_window", "draft_tool_dialog", "live_match_analysis_dialog", "live_timeline", "champion_card", "postgame_sidebar", "postgame_replay_window", "overlay_window", "recommendation_panel", "startup_window", "soloq_graph_widget", "recordings_page", "local_analysis_dialog"):
        migrar_archivo(Path("app/ui") / (nombre + ".py"))
