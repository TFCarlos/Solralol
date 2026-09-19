from __future__ import annotations

import os
import sys

from PySide6.QtCore import QtMsgType, qInstallMessageHandler
from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow
from data_dragon import load_item_catalog


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


def main() -> int:
    install_message_filter()

    app = QApplication(sys.argv)

    app.setApplicationName("Solralol")
    app.setOrganizationName("Solralol")

    try:
        print("Descargando catálogo de objetos actual...", flush=True)

        version, item_catalog = load_item_catalog()

        print(
            f"Catálogo Data Dragon listo "
            f"(parche {version}).",
            flush=True,
        )

        window = MainWindow(
            version=version,
            item_catalog=item_catalog,
        )
    except KeyboardInterrupt:
        # Ctrl+C mientras se descarga el catálogo: sin nada que limpiar.
        print("\nCancelado por el usuario.")
        return 0

    window.showMaximized()

    try:
        return app.exec()
    except KeyboardInterrupt:
        # Ctrl+C en la consola: cerrar la ventana detiene el sondeo de TAB y
        # los hilos de fondo (closeEvent), sin volcar un traceback.
        try:
            window.close()
        except RuntimeError:
            pass

        return 0


if __name__ == "__main__":
    raise SystemExit(main())