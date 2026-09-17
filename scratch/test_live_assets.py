"""Icon regressions. Network smoke: SOLRALOL_TEST_NETWORK=1 python -m unittest scratch.test_live_assets -v."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkReply
from PySide6.QtWidgets import QApplication, QLabel

from app.services.data_dragon_assets import DataDragonAssetService
from app.ui.live_match_analysis_dialog import LiveMatchAnalysisDialog

ROOT = Path(__file__).resolve().parents[1]


class LiveAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = patch("app.services.data_dragon_assets.Path.home", return_value=Path(self.temp.name))
        self.home.start()
        self.objects = []
        self.http = patch("requests.get", side_effect=AssertionError("No synchronous network expected"))
        self.http.start()

    def tearDown(self):
        for obj in reversed(self.objects):
            obj.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.http.stop()
        self.home.stop()
        self.temp.cleanup()

    def service(self):
        service = DataDragonAssetService()
        self.objects.append(service)
        return service

    def test_version_tracks_local_catalog_including_future_patches(self):
        for version in ("16.18.1", "17.1.1", "15.16.1"):
            with self.subTest(version=version):
                with patch.object(DataDragonAssetService, "_load_json", return_value={"version": version}):
                    service = self.service()
                self.assertEqual(service.version, version)
                for item_id in (2510, 222510, 1001):
                    self.assertEqual(
                        service.item_url(item_id),
                        f"https://ddragon.leagueoflegends.com/cdn/{version}/img/item/{item_id}.png",
                    )

    def test_unavailable_or_invalid_catalog_has_safe_fallback(self):
        for catalog in ({}, None, [], {"version": None}, {"version": 1618},
                        {"version": ""}, {"version": "../invalid"}):
            with self.subTest(catalog=catalog):
                with patch.object(DataDragonAssetService, "_load_json", return_value=catalog), \
                     patch.object(DataDragonAssetService, "_load_catalogs"):
                    self.assertEqual(self.service().version, "15.16.1")

    def test_real_catalog_contains_dusk_and_dawn_and_sets_patch(self):
        catalog = json.loads((ROOT / "data" / "items.json").read_text(encoding="utf-8"))
        self.assertEqual(catalog["items"]["2510"]["name_en"], "Dusk and Dawn")
        self.assertEqual(self.service().version, catalog["version"])

    def inventory(self, service, catalog):
        host = SimpleNamespace(
            assets=service, item_catalog=catalog,
            _latest_player_point=lambda key: {"items": [2510, "222510", 0, None, "invalid"]},
        )
        panel = LiveMatchAnalysisDialog._create_inventory_panel(host, {}, "enemy")
        self.objects.append(panel)
        icons = panel.findChildren(QLabel, "liveEventIcon")
        self.assertEqual(len(icons), 2)
        return icons

    def test_inventory_paints_dusk_and_dawn_from_disk_cache(self):
        service = self.service()
        catalog = json.loads((ROOT / "data" / "items.json").read_text(encoding="utf-8"))
        for item_id in (2510, 222510):
            image = QPixmap(64, 64)
            image.fill("magenta")
            path = service._cache_path(service.item_url(item_id))
            path.parent.mkdir(parents=True, exist_ok=True)
            self.assertTrue(image.save(str(path), "PNG"))
        with patch.object(service.network, "get", side_effect=AssertionError("Cache should avoid HTTP")):
            for wrapped in (catalog, catalog["items"]):
                icons = self.inventory(service, wrapped)
                for icon in icons:
                    self.assertEqual(icon.toolTip(), catalog["items"]["2510"]["name"])
                    self.assertFalse(icon.pixmap().isNull())
                    self.assertEqual((icon.pixmap().width(), icon.pixmap().height()), (32, 32))

    def test_failed_image_is_not_cached_and_can_retry(self):
        service = self.service()
        url = service.item_url(2510)
        reply = Mock()
        reply.error.return_value = QNetworkReply.NetworkError.ContentNotFoundError
        with patch.object(service.network, "get", return_value=reply) as get:
            self.assertTrue(service.request_pixmap(url, "dusk").isNull())
            service._receive(reply, url, "dusk")
            self.assertNotIn(url, service.pending)
            self.assertFalse(service._cache_path(url).exists())
            self.assertTrue(service.request_pixmap(url, "dusk").isNull())
            self.assertEqual(get.call_count, 2)
        service.pending.clear()

    @unittest.skipUnless(os.environ.get("SOLRALOL_TEST_NETWORK") == "1", "Opt-in CDN smoke")
    def test_cold_cdn_download_paints_inventory_and_warm_cache(self):
        # Real Qt network + real CDN + real inventory, isolated from user's cache.
        service = self.service()
        catalog = json.loads((ROOT / "data" / "items.json").read_text(encoding="utf-8"))
        icons = self.inventory(service, catalog)
        deadline = time.monotonic() + 30
        while service.pending and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertFalse(service.pending, "CDN download timed out")
        for item_id, icon in zip((2510, 222510), icons):
            self.assertFalse(icon.pixmap().isNull(), service.item_url(item_id))
            self.assertEqual(icon.pixmap().width(), 32)
            self.assertTrue(service._cache_path(service.item_url(item_id)).exists())
        with patch.object(service.network, "get", side_effect=AssertionError("Warm cache should avoid HTTP")):
            for icon in self.inventory(service, catalog):
                self.assertFalse(icon.pixmap().isNull())
        print(f"\nCDN {service.version}: Dusk and Dawn 2510/222510, cold inventory + warm cache OK")


if __name__ == "__main__":
    unittest.main()