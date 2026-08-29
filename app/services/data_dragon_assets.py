from __future__ import annotations

import weakref
import json
from pathlib import Path
from urllib.parse import quote

import requests
from PySide6.QtCore import (
    QObject,
    QUrl,
    Qt,
    Signal,
    Slot,
)

from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QLabel


class DataDragonAssetService(QObject):
    """Descarga y cachea imágenes estáticas de Data Dragon."""

    image_ready = Signal(str, QPixmap)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.version = "15.16.1"
        self.language = "en_US"
        self.cache_dir = Path.home() / ".solralol" / "ddragon"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.network = QNetworkAccessManager(self)
        self.pending: dict[str, QNetworkReply] = {}
        self.champions: dict[str, str] = {}
        self.items: dict[int, str] = {}
        self._load_catalogs()

    def _load_catalogs(self) -> None:
        self._load_champion_catalog()
        self._load_item_catalog()

    def _load_champion_catalog(self) -> None:
        path = self.cache_dir / f"champions_{self.version}.json"
        data = self._load_json(path)
        if data is None:
            try:
                response = requests.get(
                    f"https://ddragon.leagueoflegends.com/cdn/"
                    f"{self.version}/data/{self.language}/champion.json",
                    timeout=10,
                )
                response.raise_for_status()
                data = response.json()
                path.write_text(
                    json.dumps(data, ensure_ascii=False),
                    encoding="utf-8",
                )
            except (requests.RequestException, OSError, ValueError):
                data = {}

        for key, value in data.get("data", {}).items():
            if isinstance(value, dict):
                self.champions[value.get("name", key)] = value.get("id", key)

    def item_name(self, item_id: int, language: str = "es_ES") -> str:
        """
        Obtiene el nombre de un objeto desde Data Dragon.
        """
        if not item_id or item_id == 0:
            return f"Objeto {item_id}"
        
        # Intentar con el catálogo en inglés (ya cargado)
        item_key = self.items.get(item_id)
        if item_key:
            # Cargar catálogo de nombres en inglés
            path = self.cache_dir / f"items_{self.version}_{self.language}.json"
            data = self._load_json(path)
            item_data = data.get("data", {}).get(str(item_id))
            if item_data and isinstance(item_data, dict):
                return item_data.get("name", f"Objeto {item_id}")
        
        # Fallback: petición directa en español
        try:
            url = (
                f"https://ddragon.leagueoflegends.com/cdn/"
                f"{self.version}/data/{language}/item.json"
            )
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            data = response.json()
            item_data = data.get("data", {}).get(str(item_id))
            if item_data:
                return item_data.get("name", f"Objeto {item_id}")
        except Exception:
            pass
        
        return f"Objeto {item_id}"

    def _load_item_catalog(self) -> None:
        path = self.cache_dir / f"items_{self.version}_{self.language}.json"
        data = self._load_json(path)
        if data is None:
            try:
                response = requests.get(
                    f"https://ddragon.leagueoflegends.com/cdn/"
                    f"{self.version}/data/{self.language}/item.json",
                    timeout=10,
                )
                response.raise_for_status()
                data = response.json()
                path.write_text(
                    json.dumps(data, ensure_ascii=False),
                    encoding="utf-8",
                )
            except (requests.RequestException, OSError, ValueError):
                data = {}

        for key in data.get("data", {}):
            try:
                self.items[int(key)] = key
            except ValueError:
                continue

    @staticmethod
    def _load_json(path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}

    def champion_url(self, champion_name: str) -> str:
        champion_id = self.champions.get(champion_name, champion_name)
        return (
            f"https://ddragon.leagueoflegends.com/cdn/"
            f"{self.version}/img/champion/{quote(champion_id)}.png"
        )

    def item_url(self, item_id: int) -> str:
        return (
            f"https://ddragon.leagueoflegends.com/cdn/"
            f"{self.version}/img/item/{int(item_id)}.png"
        )

    def _cache_path(self, url: str) -> Path:
        filename = url.rsplit("/", 1)[-1]
        category = "items" if "/item/" in url else "champions"
        return self.cache_dir / category / filename

    def request_pixmap(self, url: str, key: str) -> QPixmap:
        path = self._cache_path(url)
        if path.exists():
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                return pixmap

        if url not in self.pending:
            path.parent.mkdir(parents=True, exist_ok=True)
            request = QNetworkRequest(QUrl(url))
            reply = self.network.get(request)
            self.pending[url] = reply
            reply.finished.connect(
                lambda reply=reply, url=url, key=key: self._receive(
                    reply, url, key
                )
            )

        return QPixmap()

    def _receive(self, reply: QNetworkReply, url: str, key: str) -> None:
        self.pending.pop(url, None)
        pixmap = QPixmap()
        if reply.error() == QNetworkReply.NetworkError.NoError:
            pixmap.loadFromData(reply.readAll())
            if not pixmap.isNull():
                path = self._cache_path(url)
                path.parent.mkdir(parents=True, exist_ok=True)
                pixmap.save(str(path), "PNG")
        reply.deleteLater()
        if not pixmap.isNull():
            self.image_ready.emit(key, pixmap)

    def set_label_image(
        self,
        label: QLabel,
        url: str,
        key: str,
        size: int,
        mode: Qt.AspectRatioMode = (
            Qt.AspectRatioMode.KeepAspectRatioByExpanding
        ),
    ) -> None:
        label.setProperty("asset_key", key)
        label.setProperty("asset_size", size)
        label.setProperty("asset_mode", mode)

        label_ref = weakref.ref(label)

        def apply_image(
            received_key: str,
            pixmap: QPixmap,
        ) -> None:
            target = label_ref()

            if target is None:
                return

            try:
                self._apply_if_current(
                    received_key,
                    pixmap,
                    target,
                )
            except RuntimeError:
                return

        self.image_ready.connect(apply_image)

        def disconnect_callback(*args) -> None:
            try:
                self.image_ready.disconnect(apply_image)
            except (RuntimeError, TypeError):
                pass

        label.destroyed.connect(disconnect_callback)

        pixmap = self.request_pixmap(url, key)

        if not pixmap.isNull():
            label.setPixmap(
                pixmap.scaled(
                    size,
                    size,
                    mode,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    @staticmethod
    def _apply_if_current(
        key: str,
        pixmap: QPixmap,
        label: QLabel,
    ) -> None:
        try:
            if label.property("asset_key") != key:
                return

            size = int(
                label.property("asset_size") or 32
            )

            mode = label.property("asset_mode")

            if not isinstance(
                mode,
                Qt.AspectRatioMode,
            ):
                mode = (
                    Qt.AspectRatioMode
                    .KeepAspectRatioByExpanding
                )

            label.setPixmap(
                pixmap.scaled(
                    size,
                    size,
                    mode,
                    Qt.TransformationMode
                    .SmoothTransformation,
                )
            )
        except RuntimeError:
            return
