import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WebPerformanceContractTests(unittest.TestCase):
    def test_static_assets_use_cache_validation_and_gzip(self):
        source = (ROOT / "backend" / "LottoWebServer.java").read_text(encoding="utf-8")

        self.assertIn("staticAssetCache", source)
        self.assertIn('"ETag"', source)
        self.assertIn('"If-None-Match"', source)
        self.assertIn("GZIPOutputStream", source)
        self.assertIn('"Content-Encoding", "gzip"', source)
        self.assertIn('"Vary", "Accept-Encoding"', source)

    def test_frontend_scripts_are_deferred_without_remote_icon_dependency(self):
        source = (ROOT / "frontend" / "vietlott-web.html").read_text(encoding="utf-8")

        for filename in (
            "vietlott-web-stats.js",
            "vietlott-web-data.js",
            "vietlott-web-core.js",
        ):
            self.assertIn(f'<link rel="preload" href="/{filename}" as="script" />', source)
            self.assertIn(f'<script defer src="/{filename}"></script>', source)
        self.assertNotIn("unpkg.com/ionicons", source)
        self.assertNotIn("<ion-icon", source)

    def test_store_saves_are_coalesced_and_unchanged_snapshots_are_skipped(self):
        source = (ROOT / "frontend" / "vietlott-web-core.js").read_text(encoding="utf-8")

        self.assertIn("pendingStoreSave", source)
        self.assertIn("flushStoreSaveQueue", source)
        self.assertIn("lastSavedStoreSnapshotText", source)
        self.assertIn(
            "if (snapshotText === lastSavedStoreSnapshotText && !storeSaveLoopPromise) return true;",
            source,
        )

    def test_enter_app_renders_before_background_refresh(self):
        source = (ROOT / "frontend" / "vietlott-web-core.js").read_text(encoding="utf-8")
        start = source.index("async function enterApp")
        end = source.index("async function logout", start)
        block = source[start:end]

        self.assertIn("applyAppPageLayout();", block)
        self.assertIn("runWhenBrowserIdle", block)
        self.assertNotIn("await refreshKenoPredictionDataForHistory", block.split("runWhenBrowserIdle", 1)[0])
        self.assertIn("Math.max(0, 250 - elapsed)", source)

    def test_background_timers_pause_when_tab_is_hidden(self):
        core = (ROOT / "frontend" / "vietlott-web-core.js").read_text(encoding="utf-8")
        data = (ROOT / "frontend" / "vietlott-web-data.js").read_text(encoding="utf-8")

        self.assertIn("function startLuckyWheelUiTimer()", core)
        self.assertIn("if (document.hidden) return;", core)
        self.assertGreaterEqual(data.count("if (document.hidden) return;"), 2)

    def test_windows_launcher_falls_back_to_installed_jdk(self):
        source = (ROOT / "scripts" / "chay_lotto_web.bat").read_text(encoding="utf-8")

        self.assertIn("%JAVA_HOME%\\bin\\java.exe", source)
        self.assertIn("where javac.exe", source)
        self.assertIn('if exist "%%~dpDjava.exe"', source)
        self.assertIn('pushd "%PROJECT_ROOT%"', source)
        self.assertIn('-d "backend\\bin" "backend\\LottoWebServer.java"', source)
        self.assertNotIn('-d "%PROJECT_ROOT%\\backend\\bin"', source)


if __name__ == "__main__":
    unittest.main()
