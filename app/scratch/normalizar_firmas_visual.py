"""Completa anotaciones y documentación de métodos de presentación migrados."""

import ast
import io
import tokenize
from pathlib import Path

from app.scratch.migrar_sistema_visual import reemplazar_fuente


def normalizar(ruta: Path) -> None:
    """Completa firmas de funciones visuales modificadas conservando sus cuerpos."""
    fuente = ruta.read_text(encoding="utf-8")
    arbol = ast.parse(fuente)
    cambios = []
    for funcion in ast.walk(arbol):
        if not isinstance(funcion, ast.FunctionDef):
            continue
        llamadas = [n for n in ast.walk(funcion) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
        if not any(n.func.id in {"aplicar_tema", "aplicar_apariencia", "aplicar_color", "aplicar_estado", "color_con_alfa", "Reflujo", "actualizar_texto_boton", "Interruptor"} for n in llamadas):
            continue
        for argumento in (*funcion.args.posonlyargs, *funcion.args.args, *funcion.args.kwonlyargs):
            if argumento.arg not in {"self", "cls"} and argumento.annotation is None:
                argumento.annotation = ast.Name(id="Any", ctx=ast.Load())
        if funcion.args.vararg and funcion.args.vararg.annotation is None:
            funcion.args.vararg.annotation = ast.Name(id="Any", ctx=ast.Load())
        if funcion.args.kwarg and funcion.args.kwarg.annotation is None:
            funcion.args.kwarg.annotation = ast.Name(id="Any", ctx=ast.Load())
        if funcion.returns is None:
            devoluciones = [n for n in ast.walk(funcion) if isinstance(n, ast.Return) and n.value is not None]
            funcion.returns = ast.Name(id="Any" if devoluciones else "None", ctx=ast.Load())
        tokens = list(tokenize.generate_tokens(io.StringIO(fuente).readline))
        inicio = next(i for i, t in enumerate(tokens) if t.string == "def" and t.start[0] == funcion.lineno)
        profundidad = 0
        for token in tokens[inicio + 1:]:
            if token.string in {"(", "[", "{"}:
                profundidad += 1
            elif token.string in {")", "]", "}"}:
                profundidad -= 1
            elif token.string == ":" and profundidad == 0:
                cabecera = ast.Constant()
                cabecera.lineno, cabecera.col_offset = funcion.lineno, funcion.col_offset
                cabecera.end_lineno, cabecera.end_col_offset = token.end
                texto = f"def {funcion.name}({ast.unparse(funcion.args)}) -> {ast.unparse(funcion.returns)}:"
                cambios.append((cabecera, texto))
                break
        if not ast.get_docstring(funcion):
            primera = funcion.body[0]
            linea = ast.Constant()
            linea.lineno = linea.end_lineno = primera.lineno
            linea.col_offset = linea.end_col_offset = primera.col_offset
            descripcion = "Construye la presentación" if "create" in funcion.name or "build" in funcion.name else "Actualiza la presentación"
            cambios.append((linea, f'"""{descripcion} con los parámetros recibidos y devuelve el resultado existente."""\n' + " " * primera.col_offset))
    if cambios:
        fuente = reemplazar_fuente(fuente, cambios)
        if "from typing import Any" not in fuente:
            posicion = fuente.index("from __future__ import annotations") if "from __future__ import annotations" in fuente else -1
            if posicion >= 0:
                fuente = fuente.replace("from __future__ import annotations", "from __future__ import annotations\nfrom typing import Any", 1)
            else:
                fuente = "from typing import Any\n" + fuente
        ruta.write_text(fuente, encoding="utf-8")


if __name__ == "__main__":
    for ruta in Path("app/ui").glob("*.py"):
        if ruta.name not in {"tema.py", "componentes_visuales.py"}:
            normalizar(ruta)
