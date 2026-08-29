from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow
from data_dragon import load_item_catalog


def main() -> int:
    app = QApplication(sys.argv)

    app.setApplicationName("Solralol")
    app.setOrganizationName("Solralol")

    print("Descargando catálogo de objetos actual...")

    version, item_catalog = load_item_catalog()

    print(
        f"Catálogo Data Dragon listo "
        f"(parche {version})."
    )

    window = MainWindow(
        version=version,
        item_catalog=item_catalog,
    )

    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())