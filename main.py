from __future__ import annotations

import os
import sys
import traceback

from PySide6.QtCore import QtMsgType, qInstallMessageHandler
from PySide6.QtWidgets import QApplication

from app.ui import startup_window
from app.ui.main_window import MainWindow
from data_dragon import load_cached_item_catalog, load_item_catalog


# Avisos de Qt que solo ensucian la consola: Qt ya no incluye tipografías
# propias y FreeType a veces rechaza algún fichero del directorio de fuentes
# del sistema. En Windows las fuentes las resuelve el sistema, así que ninguno
# de los dos afecta a la aplicación; el resto de avisos se siguen mostrando.
QUIET_MESSAGE_FRAGMENTS = (
    "Cannot find font directory",
    "Note that Qt no longer ships fonts",
    "FT_New_Face failed",
)

_MESSAGE_LABELS = {
    QtMsgType.QtDebugMsg: "Debug",
    QtMsgType.QtInfoMsg: "Info",
    QtMsgType.QtWarningMsg: "Warning",
    QtMsgType.QtCriticalMsg: "Critical",
    QtMsgType.QtFatalMsg: "Fatal",
}


def install_message_filter() -> None:
    """Silencia solo los avisos inofensivos de fuentes; el resto pasa igual."""

    def handler(mode, context, message):
        if any(
            fragment in message for fragment in QUIET_MESSAGE_FRAGMENTS
        ):
            return

        line = f"{_MESSAGE_LABELS.get(mode, 'Message')}: {message}"

        if context.file:
            line += f" ({context.file}:{context.line})"

        sys.stderr.write(line + "\n")
        sys.stderr.flush()

        if mode == QtMsgType.QtFatalMsg:
            os._exit(1)

    qInstallMessageHandler(handler)


def build_main_window(
    result,
    error,
    holder: dict,
    loader: startup_window.StartupWindow,
) -> None:
    """Crea la ventana principal cuando el catálogo ya está disponible.

    Se ejecuta en el hilo de la GUI: la descarga del catálogo (red) ya la hizo
    el worker, así que aquí solo queda construir los widgets.
    """
    if error:
        print(
            f"Aviso: no se pudo actualizar el catálogo de objetos ({error}); "
            "se usará la copia local.",
            flush=True,
        )
        version, item_catalog = load_cached_item_catalog()
    else:
        version, item_catalog = result
        print(
            f"Catálogo Data Dragon listo (parche {version}).",
            flush=True,
        )

    loader.set_message("Preparando la interfaz…")
    QApplication.processEvents()

    try:
        window = MainWindow(version=version, item_catalog=item_catalog)
    except Exception:  # noqa: BLE001 - sin ventana no hay nada que mostrar
        loader.stop()
        traceback.print_exc()
        QApplication.exit(1)

        return

    holder["window"] = window
    window.showMaximized()
    loader.stop()


def main() -> int:
    install_message_filter()

    app = QApplication(sys.argv)

    app.setApplicationName("Solralol")
    app.setOrganizationName("Solralol")

    # El catálogo de objetos se descarga la primera vez de cada parche: el
    # trabajo va a un worker y la ventana de carga mantiene la interfaz viva
    # (barra animada y cronómetro) mientras tanto.
    holder: dict = {}
    loader = startup_window.StartupWindow(
        message="Descargando catálogo de objetos…",
        hint="Solo la primera vez de cada parche.",
    )
    loader.finished.connect(
        lambda result, error: build_main_window(result, error, holder, loader)
    )
    loader.show()
    loader.move_to_center()
    app.processEvents()

    try:
        loader.start(load_item_catalog)
    except KeyboardInterrupt:
        # Ctrl+C mientras se descarga el catálogo: sin nada que limpiar.
        print("\nCancelado por el usuario.", flush=True)
        loader.stop()
        return 0

    try:
        code = app.exec()
    except KeyboardInterrupt:
        # Ctrl+C en la consola: cerrar la ventana detiene el sondeo de TAB y
        # los hilos de fondo (closeEvent), sin volcar un traceback.
        window = holder.get("window")

        if window is not None:
            try:
                window.close()
            except RuntimeError:
                pass

        return 0

    return code


if __name__ == "__main__":
    raise SystemExit(main())