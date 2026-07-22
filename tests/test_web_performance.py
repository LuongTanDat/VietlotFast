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

    def test_dvlf_brand_is_consistent_and_reloads_the_page(self):
        html = (ROOT / "frontend" / "vietlott-web.html").read_text(encoding="utf-8")
        core = (ROOT / "frontend" / "vietlott-web-core.js").read_text(encoding="utf-8")
        styles = (ROOT / "frontend" / "vietlott-web-extra.css").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("<title>DVLF</title>", html)
        self.assertIn('id="brandReloadBtn"', html)
        self.assertIn("DVLF là tên viết tắt của Deep Vietlott Fast", html)
        self.assertIn('const APP_SHORT_NAME = "DVLF";', core)
        self.assertIn('const APP_FULL_NAME = "Deep Vietlott Fast";', core)
        self.assertIn("brandReloadBtn.onclick = () => window.location.reload();", core)
        self.assertIn(".brand-reload-btn:hover::after", styles)
        self.assertTrue(readme.startswith("# DVLF\n"))

        old_name = "Vietlott Tra Cứu Nhanh" + " Pro"
        for source in (html, core, readme):
            self.assertNotIn(old_name, source)

    def test_header_tools_and_account_menu_are_compact_and_functional(self):
        html = (ROOT / "frontend" / "vietlott-web.html").read_text(encoding="utf-8")
        core = (ROOT / "frontend" / "vietlott-web-core.js").read_text(encoding="utf-8")
        styles = (ROOT / "frontend" / "vietlott-web-extra.css").read_text(encoding="utf-8")

        top_right = html[html.index('<div class="top-right">'):html.index("</header>")]
        side_menu = html[html.index('<aside id="sideMenu"'):html.index('<div class="wrap">')]
        settings_panel = html[html.index('id="settingsPanel"'):html.index("</div>\n        </div>\n      </div>", html.index('id="settingsPanel"'))]

        for element_id in ("whoami", "openAccountBtn"):
            self.assertNotIn(f'id="{element_id}"', top_right)
            self.assertIn(f'id="{element_id}"', side_menu)
        self.assertNotIn('id="logoutBtn"', side_menu)
        for element_id in ("notificationBtn", "notificationPanel", "settingsBtn", "settingsPanel"):
            self.assertIn(f'id="{element_id}"', top_right)
        self.assertIn('id="themeToggleBtn"', settings_panel)
        self.assertIn('id="logoutBtn"', settings_panel)
        self.assertIn('id="notificationClearBtn"', top_right)
        self.assertIn("function renderHeaderNotifications()", core)
        self.assertIn("function clearHeaderNotifications()", core)
        self.assertIn("HEADER_NOTIFICATION_DISMISSED_KEY", core)
        self.assertIn("function syncSideAccountIdentity()", core)
        self.assertIn('toggleHeaderPopover("notificationBtn", "notificationPanel")', core)
        self.assertIn(".header-icon-badge", styles)
        self.assertIn(".side-account-card", styles)

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

    def test_prediction_results_are_not_rebuilt_every_second(self):
        source = (ROOT / "frontend" / "vietlott-web-data.js").read_text(encoding="utf-8")
        start = source.index("function startLiveDrawCountdown")
        end = source.index("function formatCountdownSeconds", start)
        timer_block = source[start:end]

        self.assertNotIn("renderPredictOutput()", timer_block)
        self.assertNotIn("renderPredictVipOutput()", timer_block)
        self.assertIn("updateLiveResultsCountdownText()", timer_block)

    def test_live_cards_refresh_only_the_selected_lottery_type(self):
        data = (ROOT / "frontend" / "vietlott-web-data.js").read_text(encoding="utf-8")
        core = (ROOT / "frontend" / "vietlott-web-core.js").read_text(encoding="utf-8")
        backend = (ROOT / "backend" / "LottoWebServer.java").read_text(encoding="utf-8")

        self.assertIn("data-live-refresh-type", data)
        self.assertIn("async function syncSingleLiveResult", data)
        self.assertIn("/api/live-results?type=${encodeURIComponent(type)}", data)
        self.assertIn("liveResultsState = scopedType ? { ...liveResultsState, ...resultMap } : resultMap;", data)
        self.assertIn('currentCard.outerHTML = cardHtml[scopedIndex];', data)
        self.assertIn('renderLiveResultsBoard({ force: true, onlyType: type });', data)
        self.assertIn("if (!scopedType) {\n        refreshStatsV2AfterLiveUpdate();", data)
        self.assertIn('event.target.closest("[data-live-refresh-type]")', core)
        self.assertIn('String type = normalizeLiveType(query.get("type"));', backend)

    def test_heavy_keno_history_is_loaded_on_demand(self):
        core = (ROOT / "frontend" / "vietlott-web-core.js").read_text(encoding="utf-8")
        start = core.index("async function enterApp")
        end = core.index("async function logout", start)
        block = core[start:end]

        self.assertNotIn("restoreKenoCsvFeedCache();", block)
        self.assertNotIn("refreshKenoPredictionDataForHistory", block)
        self.assertIn("hasCachedLiveResults", block)

    def test_hidden_auxiliary_pages_are_not_rendered_on_login(self):
        core = (ROOT / "frontend" / "vietlott-web-core.js").read_text(encoding="utf-8")
        start = core.index("async function enterApp")
        end = core.index("async function logout", start)
        block = core[start:end]

        self.assertNotIn("renderLuckyWheelPanel();", block)
        self.assertNotIn("renderPaypalDepositSection();", block)
        self.assertIn("applyAppPageLayout();", block)

    def test_hidden_stats_tabs_are_initialized_on_demand(self):
        core = (ROOT / "frontend" / "vietlott-web-core.js").read_text(encoding="utf-8")
        start = core.index("const initialPdType")
        end = core.index("const vipTypeSelect", start)
        block = core[start:end]

        for renderer in (
            "renderStatsPanel();",
            "renderStatsV2Panel();",
            "renderChartStatsPanel();",
            "renderDashboardPanel();",
        ):
            self.assertIn(renderer, block)
        self.assertNotIn("renderAnalysis(null);\n      renderChartStatsPanel();", block)

    def test_dashboard_view_normalizers_use_declared_helper_names(self):
        core = (ROOT / "frontend" / "vietlott-web-core.js").read_text(encoding="utf-8")
        stats = (ROOT / "frontend" / "vietlott-web-stats.js").read_text(encoding="utf-8")
        source = core + stats

        self.assertIn("function normalizeDashboardActivityView(value)", core)
        self.assertIn("function normalizeDashboardDistributionView(value)", core)
        self.assertNotIn("normalizeDashboardActivityViewMode(", source)
        self.assertNotIn("normalizeDashboardDistributionViewMode(", source)

    def test_live_history_has_java_csv_fast_path(self):
        source = (ROOT / "backend" / "LottoWebServer.java").read_text(encoding="utf-8")

        self.assertIn("buildCanonicalHistoryPayload", source)
        self.assertIn("parseCanonicalDrawIds", source)
        self.assertIn('"X-Lotto-History-Source", "java-csv"', source)

    def test_prediction_history_requests_only_needed_draw_ids(self):
        source = (ROOT / "frontend" / "vietlott-web-data.js").read_text(encoding="utf-8")
        start = source.index("async function fetchPredictionHistoryDraws")
        end = source.index("async function refreshKenoPredictionDataForHistory", start)
        block = source[start:end]

        self.assertIn('drawIds: drawIds.join(",")', block)
        self.assertNotIn('fetchLiveHistory(type, "all"', block)
        self.assertIn("const mergedFeed = cloneLiveHistoryFeed(getLiveHistoryFeed(type))", block)
        self.assertIn("mergeLiveHistoryDraw(mergedFeed, ky, nextFeed.results?.[ky])", block)

    def test_prediction_history_manual_refresh_repairs_and_scores_before_reconcile(self):
        data = (ROOT / "frontend" / "vietlott-web-data.js").read_text(encoding="utf-8")
        core = (ROOT / "frontend" / "vietlott-web-core.js").read_text(encoding="utf-8")
        start = data.index("async function refreshPredictionHistoryData")
        end = data.index("async function refreshKenoPredictionDataForHistory", start)
        block = data[start:end]

        self.assertIn("await repairPredictionHistoryCanonical(normalizedType)", block)
        self.assertLess(block.index("await repairPredictionHistoryCanonical"), block.index("await fetchPredictionHistoryDraws"))
        self.assertLess(block.index("await fetchPredictionHistoryDraws"), block.index("await scorePendingPredictionLedger"))
        self.assertLess(block.index("await scorePendingPredictionLedger"), block.index("reconcilePredictionLogsForType"))
        self.assertIn("if (repairedFeed.order.length) setLiveHistoryFeed(type, repairedFeed)", data)
        self.assertIn("async function startPredictionHistoryRefresh", data)
        self.assertIn("silent: false, repairCanonical: true", core)

    def test_heavy_analysis_endpoints_use_versioned_cache(self):
        source = (ROOT / "backend" / "LottoWebServer.java").read_text(encoding="utf-8")

        self.assertIn("heavyApiCache", source)
        self.assertIn('heavyApiCacheKey("stats-v2"', source)
        self.assertIn('heavyApiCacheKey("analysis"', source)
        self.assertIn("canonicalDataVersion", source)
        self.assertIn('"X-Lotto-Cache", "HIT"', source)

    def test_large_prediction_records_render_collapsed(self):
        source = (ROOT / "frontend" / "vietlott-web-data.js").read_text(encoding="utf-8")

        self.assertIn("canCollapseTickets", source)
        self.assertIn("allTickets.slice(0, ticketLimit)", source)
        self.assertIn("data-prediction-history-toggle", source)

    def test_stats_prediction_cycle_is_persisted_and_scored(self):
        stats = (ROOT / "frontend" / "vietlott-web-stats.js").read_text(encoding="utf-8")
        data = (ROOT / "frontend" / "vietlott-web-data.js").read_text(encoding="utf-8")
        core = (ROOT / "frontend" / "vietlott-web-core.js").read_text(encoding="utf-8")

        self.assertIn("function ensureStatsPredictionCycle", stats)
        self.assertIn("predictionMode: PREDICTION_MODE_STATS", stats)
        self.assertIn("sourceEntries.slice(0, -1)", stats)
        self.assertIn("await scorePendingPredictionLedger(type)", stats)
        self.assertIn('api("/api/ml/score-pending", "POST", { type })', data)
        self.assertIn("findLegacyLedgerRow", data)
        compact_start = core.index("function compactPredictionLogForStore")
        compact_end = core.index("function buildPersistableStoreSnapshot", compact_start)
        compact_block = core[compact_start:compact_end]
        self.assertIn('predictionId: String(entry.predictionId || "")', compact_block)
        self.assertIn("scoreMetrics:", compact_block)

    def test_live_update_log_keeps_only_latest_run(self):
        source = (ROOT / "backend" / "LottoWebServer.java").read_text(encoding="utf-8")

        self.assertIn("ProcessBuilder.Redirect.to(logFile)", source)
        self.assertNotIn("ProcessBuilder.Redirect.appendTo(logFile)", source)

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
