"""Agranda el icono de la app en la barra de tareas (Windows).

Windows dibuja el icono en un cuadro de tamaño fijo, así que el único modo de
que se vea más grande en la barra de tareas es que el logo ocupe más del
lienzo: en ``data/LogoApp.png`` el contenido solo cubría ~67% y el resto era
margen transparente. Este script recorta el lienzo al contenido real del logo
(sin reescalar píxeles, mantiene la nitidez) y lo vuelve a encajar dejando un
10% de aire, de forma que el logo pasa a ocupar ~90%. Después regenera
``data/LogoApp.ico`` (icono del .exe) con los mismos tamaños que ya tenía.

Uso::

    .venv\\Scripts\\python.exe scratch\\enlarge_app_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PNG_PATH = ROOT / "data" / "LogoApp.png"
ICO_PATH = ROOT / "data" / "LogoApp.ico"
PREVIEW_PATH = ROOT / "scratch" / "icon_taskbar_preview.png"

#: Fracción del lienzo que debe ocupar el logo (el resto es aire).
FILL = 0.90
#: Alfa mínimo para contar un píxel como parte del logo: evita que vecinos
#: casi invisibles inflen el bounding box.
ALPHA_MIN = 16
#: Tamaños que Windows usa y que ya tenía el .ico original.
ICO_SIZES = [
    (16, 16),
    (24, 24),
    (32, 32),
    (48, 48),
    (64, 64),
    (128, 128),
    (256, 256),
]


def _content_bbox(image: Image.Image) -> tuple[int, int, int, int]:
    """Bounding box del logo usando solo el canal alfa umbralizado."""
    alpha = image.getchannel("A").point(lambda a: 255 if a >= ALPHA_MIN else 0)
    bbox = alpha.getbbox()
    if bbox is None:
        raise SystemExit(f"{PNG_PATH.name} no tiene contenido visible (alfa 0).")
    return bbox


def enlarge_icon() -> tuple[Image.Image, Image.Image]:
    """Recorta y reencuadra el PNG; devuelve (original, redimensionada)."""
    source = Image.open(PNG_PATH).convert("RGBA")
    left, top, right, bottom = _content_bbox(source)
    content_w, content_h = right - left, bottom - top

    side = round(max(content_w, content_h) / FILL)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(
        source.crop((left, top, right, bottom)),
        ((side - content_w) // 2, (side - content_h) // 2),
    )
    canvas.save(PNG_PATH)

    written = _write_ico(canvas)
    expected = sorted(ICO_SIZES)
    if written != expected:
        raise SystemExit(f"El .ico no tiene los tamaños esperados: {written}")

    old_pct = max(content_w / source.size[0], content_h / source.size[1])
    new_pct = max(content_w / side, content_h / side)
    print(f"PNG {PNG_PATH.name}: {source.size} -> {canvas.size}")
    print(f"Logo en el lienzo: {old_pct:.0%} -> {new_pct:.0%}")
    print(f"ICO regenerado con tamaños: {written}")
    return source, canvas


def _write_ico(image: Image.Image) -> list[tuple[int, int]]:
    """Guarda el .ico con todos los tamaños y devuelve los escritos."""
    image.save(ICO_PATH, sizes=ICO_SIZES)
    return sorted(Image.open(ICO_PATH).ico.sizes())


def _preview(before: Image.Image, after: Image.Image) -> None:
    """Vista previa antes/después a tamaño real de barra de tareas."""
    from PIL import ImageDraw, ImageFont

    zoom = 5
    sizes = (16, 24, 32, 48)
    bg = (45, 45, 48)
    fg = (235, 235, 235)
    margin, gap, header = 16, 18, 30
    cell_w = max(size * zoom for size in sizes) + gap
    row_h = max(size * zoom for size in sizes) + gap
    canvas = Image.new(
        "RGB",
        (margin * 2 + cell_w * len(sizes), header + row_h * 2),
        bg,
    )
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 13)
    except OSError:
        font = ImageFont.load_default()

    for col, size in enumerate(sizes):
        x = margin + col * cell_w
        draw.text((x, 8), f"{size}px", fill=fg, font=font)
        for row, (label, image) in enumerate((("antes", before), ("después", after))):
            y = header + row * row_h
            if col == 0:
                draw.text((2, y + 4), label, fill=fg, font=font)
            # Tamaño real sobre fondo de barra de tareas y zoom con vecino más
            # cercano para ver el resultado píxel a píxel.
            real = image.resize((size, size), Image.LANCZOS)
            cell = real.resize((size * zoom, size * zoom), Image.NEAREST)
            canvas.paste(cell, (x, y), cell.split()[3])

    canvas.save(PREVIEW_PATH)
    print(f"Vista previa: {PREVIEW_PATH}")


def main() -> None:
    backup = ROOT / "scratch" / "LogoApp_old.png"
    before, after = enlarge_icon()
    if backup.exists():
        _preview(Image.open(backup).convert("RGBA"), after)
    else:
        print(f"Sin copia previa ({backup.name}): se omite la vista previa.")


if __name__ == "__main__":
    main()
