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

    def test_header_vip_membership_badge_tracks_expiry_and_renewal(self):
        html = (ROOT / "frontend" / "vietlott-web.html").read_text(encoding="utf-8")
        core = (ROOT / "frontend" / "vietlott-web-core.js").read_text(encoding="utf-8")
        styles = (ROOT / "frontend" / "vietlott-web-extra.css").read_text(encoding="utf-8")
        top_right = html[html.index('<div class="top-right">'):html.index("</header>")]

        for element_id in (
            "vipMembershipWrap",
            "vipMembershipBtn",
            "vipMembershipPanel",
            "vipMembershipStateBadge",
            "vipMembershipRemaining",
            "vipMembershipExpiry",
            "vipMembershipRenewBtn",
            "vipMembershipRenewMessage",
        ):
            self.assertIn(f'id="{element_id}"', top_right)
        self.assertIn('class="vip-membership-logo"', top_right)
        self.assertIn('class="vip-membership-logo-text"', top_right)
        self.assertIn('fill="url(#vipLogoGradient)"', top_right)
        self.assertNotIn("pngtree.com", top_right)

        self.assertIn('vipStartedAt: ""', core)
        self.assertIn('vipExpiresAt: ""', core)
        self.assertIn("base.vipExpiresAt = String(parsed.vipExpiresAt || \"\")", core)
        self.assertIn("function getVipMembershipState", core)
        self.assertIn("function formatVipMembershipRemaining", core)
        self.assertIn("function hasActiveVipMembership", core)
        self.assertIn("function renderVipMembership", core)
        self.assertIn("function requestVipMembershipRenewal", core)
        self.assertNotIn("window.setVipMembershipExpiry", core)
        self.assertNotIn("function setVipMembershipExpiry", core)
        self.assertIn('new CustomEvent("vip-renew-request"', core)
        self.assertIn('document.documentElement.dataset.vipMembership = state.active ? "active" : "expired"', core)
        self.assertIn("if (document.hidden) return;", core)
        self.assertIn('toggleHeaderPopover("vipMembershipBtn", "vipMembershipPanel")', core)

        self.assertIn(".vip-membership-wrap.is-active .vip-membership-btn", styles)
        self.assertIn(".vip-membership-wrap.is-expired .vip-membership-btn", styles)
        self.assertIn(".vip-membership-logo-text", styles)
        self.assertIn(".vip-membership-wrap:hover::after", styles)
        self.assertIn(".vip-membership-renew-btn", styles)
        self.assertIn("@keyframes vip-membership-active-glow", styles)

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

    def test_manual_prediction_has_a_dedicated_navigation_mode(self):
        html = (ROOT / "frontend" / "vietlott-web.html").read_text(encoding="utf-8")
        core = (ROOT / "frontend" / "vietlott-web-core.js").read_text(encoding="utf-8")
        data = (ROOT / "frontend" / "vietlott-web-data.js").read_text(encoding="utf-8")
        stats = (ROOT / "frontend" / "vietlott-web-stats.js").read_text(encoding="utf-8")
        styles = (ROOT / "frontend" / "vietlott-web-extra.css").read_text(encoding="utf-8")

        self.assertIn('id="predictModeManualTab"', html)
        self.assertIn('data-predict-mode-tab="manual">Dự đoán thủ công</button>', html)
        self.assertIn('id="predictRootManual"', html)
        self.assertIn('const PREDICTION_MODE_MANUAL = "manual";', core)
        self.assertIn("if (normalized === PREDICTION_MODE_MANUAL)", core)
        self.assertIn('document.getElementById("predictRootManual")', stats)
        self.assertIn("manualRoot.hidden = predictPageModeValue !== PREDICTION_MODE_MANUAL", stats)
        self.assertIn("grid-template-columns: repeat(8, minmax(0, 1fr));", styles)
        for element_id in (
            "manualPredictTypeSelect",
            "manualPredictPlayMode",
            "manualPredictBaoLevel",
            "manualPredictKenoLevel",
            "manualPredict3dPage",
            "manualPredictBundleCount",
            "manualPredictBundleTabs",
            "manualPredictBundleRange",
            "manualPredictBundlePrev",
            "manualPredictBundleNext",
            "manualPredictEditorEmpty",
            "manualPredictEditorContent",
            "manualPredictNumberGrid",
            "manualPredictSpecialGrid",
            "manualPredictFortuneBtn",
            "manualPredictCustomRandomBtn",
            "manualPredictRealtimeCounter",
            "manualPredictRandomLog",
            "manualPredictRandomLogContent",
            "manualPredictSelectedNumbers",
            "manualPredictSaveBtn",
            "manualPredictResetBtn",
            "manualPredictionHistoryBtn",
        ):
            self.assertIn(f'id="{element_id}"', html)
        self.assertIn("function renderManualPredictionPanel()", stats)
        self.assertIn("function toggleManualPredictionNumber(kind, rawValue)", stats)
        self.assertIn("function setManualPredictionBundleCount(value)", stats)
        self.assertIn("function activateManualPredictionBundle(index)", stats)
        self.assertIn("function resetManualPredictionBundles(notice", stats)
        self.assertIn("hasManualSpecial: Boolean(source.hasSpecial)", stats)
        self.assertIn("getPredictBaoLevels(type)", stats)
        self.assertIn("required: isBao", stats)
        self.assertIn("manualPredictBundles.filter", stats)
        self.assertIn("replace(/\\D/g, \"\")", core)
        self.assertIn("Array.from({ length: 100 }", stats)
        self.assertIn(".manual-predict-number-grid", styles)
        self.assertIn(".manual-predict-bundle-tabs", styles)
        self.assertIn(".manual-predict-workspace", styles)
        self.assertIn("grid-template-columns: repeat(var(--manual-toolbar-columns), minmax(0, 1fr));", styles)
        self.assertIn('toolbar.style.setProperty("--manual-toolbar-columns"', stats)
        self.assertIn(".manual-predict-control[hidden]", styles)
        self.assertIn('.manual-predict-toolbar .manual-predict-control input:not([type="checkbox"]):not([type="radio"])', styles)
        self.assertNotIn("manual-predict-toolbar-fields", html)
        self.assertIn("overflow-y: auto;", styles)
        self.assertIn("manualPredictEditorOpenValue = true", stats)
        self.assertIn("const MANUAL_PREDICT_BUNDLE_PAGE_SIZE = 10;", core)
        self.assertIn("function changeManualPredictionBundlePage(offset)", stats)
        self.assertIn("slice(bundlePageStart, bundlePageEnd)", stats)
        self.assertIn("grid-auto-rows: 40px;", styles)
        self.assertIn("--manual-workspace-min-height: 214px;", styles)
        self.assertIn('workspace.style.setProperty("--manual-workspace-min-height"', stats)
        self.assertNotIn("activeTab.scrollIntoView", stats)
        self.assertNotIn('id="manualPredictSelectedSpecial"', html)
        self.assertIn('class="manual-predict-selected-ball is-special"', stats)
        self.assertIn(".manual-predict-selected-ball.is-special", styles)
        self.assertNotIn(".manual-predict-selected-special", styles)
        self.assertIn('manualPredictionHistoryBtn.addEventListener("click"', core)
        self.assertIn('document.getElementById("manualPredictionHistoryBtn")', data)
        self.assertIn(".manual-predict-history-btn", styles)
        self.assertIn('title="Lịch sử dự đoán">Lịch Sử</button>', html)
        self.assertNotIn('<span aria-hidden="true">↺</span>', html)
        self.assertIn("async function saveManualPrediction()", stats)
        self.assertIn("predictionMode: PREDICTION_MODE_MANUAL", stats)
        self.assertIn('saveStore({ reason: "manual_prediction_save" })', stats)
        self.assertIn(".manual-predict-save-btn", styles)
        self.assertIn("predictionHistoryDisplayModeValue", data)
        self.assertIn("function randomizeManualPredictionBundle(variant", stats)
        self.assertIn("function sampleManualPredictionNumbers(", stats)
        self.assertIn(".manual-predict-random-actions", styles)
        self.assertIn(".manual-predict-random-counter", styles)
        self.assertIn(".manual-predict-random-log", styles)

    def test_manual_random_one_matches_required_vectors(self):
        stats = (ROOT / "frontend" / "vietlott-web-stats.js").read_text(encoding="utf-8")

        self.assertIn("function reduceToRange(", stats)
        self.assertIn("function resolveDuplicate(", stats)
        self.assertIn("function generateNumbers(", stats)
        self.assertIn("function captureManualPredictionTimeValue()", stats)
        self.assertIn("const effectiveTimeValue = timeValue === 0 ? maxNumber : timeValue;", stats)
        generate_start = stats.index("function generateNumbers(")
        generate_end = stats.index("function getManualPredictionRealtimeNow()", generate_start)
        self.assertNotIn(".sort(", stats[generate_start:generate_end])

        def reduce_to_range(value, max_number):
            while value > max_number:
                quotient = value // max_number
                remainder = value % max_number
                value = quotient + remainder
            return max_number if value == 0 else value

        def resolve_duplicate(value, used_numbers, max_number):
            checked_count = 0
            while value in used_numbers:
                value += 1
                if value > max_number:
                    value = 1
                checked_count += 1
                if checked_count >= max_number:
                    raise ValueError("Không còn số hợp lệ chưa được sử dụng.")
            return value

        self.assertEqual(reduce_to_range(90, 35), 22)
        self.assertEqual(reduce_to_range(180, 35), 10)
        self.assertEqual(reduce_to_range(540, 35), 30)
        self.assertEqual(reduce_to_range(1620, 35), 22)
        self.assertEqual(reduce_to_range(90, 12), 2)
        self.assertEqual(resolve_duplicate(22, {22}, 35), 23)
        self.assertEqual(resolve_duplicate(35, {35, 1, 2}, 35), 3)

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

    def test_dashboard_render_helpers_are_declared(self):
        stats = (ROOT / "frontend" / "vietlott-web-stats.js").read_text(encoding="utf-8")

        for helper_name in (
            "floorDashboardDate",
            "shiftDashboardDate",
            "addDashboardMonths",
            "getDashboardWeekStart",
            "formatDashboardDateKey",
            "formatDashboardShortDate",
            "formatDashboardMonthLabel",
            "formatDashboardNumber",
            "formatDashboardInteger",
            "formatDashboardRelativeTime",
            "filterDashboardEntriesInRange",
            "buildDashboardSmoothPath",
            "buildDashboardAreaPath",
        ):
            declaration = f"function {helper_name}("
            self.assertEqual(stats.count(declaration), 1)

        floor_start = stats.index("function floorDashboardDate")
        floor_end = stats.index("function shiftDashboardDate", floor_start)
        relative_start = stats.index("function formatDashboardRelativeTime")
        relative_end = stats.index("function filterDashboardEntriesInRange", relative_start)
        self.assertIn("getSyncedNowMs()", stats[floor_start:floor_end])
        self.assertIn("getSyncedNowMs()", stats[relative_start:relative_end])

    def test_dashboard_uses_compact_high_tech_theme(self):
        html = (ROOT / "frontend" / "vietlott-web.html").read_text(encoding="utf-8")
        styles = (ROOT / "frontend" / "vietlott-web-extra.css").read_text(encoding="utf-8")
        dashboard_html = html[html.index('id="predictRootDashboard"'):html.index('id="predictRootAnalysis"')]
        theme_start = styles.index("/* Compact high-tech Dashboard workspace. */")
        theme_end = styles.index("/* ----- Local DVLF chatbot ----- */", theme_start)
        dashboard_theme = styles[theme_start:theme_end]

        for token in (
            "--dash-bg:",
            "--dash-surface:",
            "--dash-border:",
            "--dash-text:",
            "--dash-accent:",
        ):
            self.assertIn(token, dashboard_theme)
        self.assertIn(".predict-root-dashboard .lotto-dashboard-tab", dashboard_theme)
        self.assertIn("width: auto;", dashboard_theme)
        self.assertIn("body.light-theme .predict-root.predict-root-dashboard", dashboard_theme)
        self.assertIn("grid-template-columns: repeat(6, minmax(0, 1fr));", dashboard_theme)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr));", dashboard_theme)
        self.assertIn("grid-auto-rows: 1fr;", dashboard_theme)
        self.assertIn('grid-template-areas:\n      "kicker title"\n      "subtitle subtitle";', dashboard_theme)
        self.assertIn('grid-template-areas:\n      "game title"\n      "meta note";', dashboard_theme)
        self.assertIn("grid-template-columns: max-content minmax(0, 1fr) max-content;", dashboard_theme)
        self.assertIn(".lotto-dashboard-hero-result-head {\n    display: contents;", dashboard_theme)
        self.assertIn("min-height: 96px;", dashboard_theme)
        self.assertIn("min-height: 62px;", dashboard_theme)
        self.assertIn('role="tab"', dashboard_html)
        self.assertIn('role="tabpanel"', dashboard_html)
        self.assertIn('aria-selected="true"', dashboard_html)
        self.assertIn("body.light-theme .predict-workspace-title", styles)
        self.assertNotIn("📊", dashboard_html)

        stats = (ROOT / "frontend" / "vietlott-web-stats.js").read_text(encoding="utf-8")
        self.assertIn('replace(/^#+\\s*/, "")', stats)
        self.assertIn("tabBar.scrollTo({", stats)

    def test_dashboard_hero_only_shows_draw_identity_and_schedule(self):
        stats = (ROOT / "frontend" / "vietlott-web-stats.js").read_text(encoding="utf-8")
        hero_start = stats.index("function renderDashboardHeroCard")
        hero_end = stats.index("function computeDashboardQuickStats", hero_start)
        hero_block = stats[hero_start:hero_end]

        for label in ("Kỳ:", "Ngày quay:", "Thời gian quay:"):
            self.assertIn(label, hero_block)
        self.assertIn('<div class="lotto-dashboard-hero-kicker">${escapeHtml(meta.label)}</div>', hero_block)
        for removed_text in ("Loại:", "kết quả ghi nhận", "Nhiệt bóng:", "ĐB nóng:"):
            self.assertNotIn(removed_text, hero_block)
        self.assertIn("latestEntry.draw?.time || feed?.latestTime", hero_block)

    def test_dashboard_scope_filter_supports_day_draw_today_and_all(self):
        html = (ROOT / "frontend" / "vietlott-web.html").read_text(encoding="utf-8")
        core = (ROOT / "frontend" / "vietlott-web-core.js").read_text(encoding="utf-8")
        stats = (ROOT / "frontend" / "vietlott-web-stats.js").read_text(encoding="utf-8")
        styles = (ROOT / "frontend" / "vietlott-web-extra.css").read_text(encoding="utf-8")

        for element_id in (
            "lottoDashboardScopeFilter",
            "lottoDashboardScopeSummary",
            "lottoDashboardScopeCount",
            "lottoDashboardScopeCustomPreset",
            "lottoDashboardScopeHint",
        ):
            self.assertIn(f'id="{element_id}"', html)
        self.assertIn('data-dashboard-scope-mode="day"', html)
        self.assertIn('data-dashboard-scope-mode="draw"', html)
        self.assertIn('data-dashboard-scope-preset="today"', html)
        self.assertIn('data-dashboard-scope-preset="custom"', html)
        self.assertIn('data-dashboard-scope-preset="all"', html)
        self.assertIn('<span class="lotto-dashboard-picker-label">Kiểu dữ liệu</span>', html)
        self.assertIn('inputmode="numeric"', html)
        self.assertIn('pattern="[0-9]*"', html)
        self.assertIn('maxlength="6"', html)

        self.assertIn('const DASHBOARD_SCOPE_MODES = ["day", "draw"];', core)
        self.assertIn('const DASHBOARD_SCOPE_PRESETS = ["custom", "today", "all"];', core)
        self.assertIn("function normalizeDashboardScopeCount", core)
        self.assertIn('dashboardScopePreset = "custom";', core)
        self.assertIn("DASHBOARD_SCOPE_MODE_KEY", core)
        self.assertIn("DASHBOARD_SCOPE_PRESET_KEY", core)
        self.assertIn("DASHBOARD_SCOPE_COUNT_KEY", core)
        self.assertIn("function sanitizeDashboardScopeDigits", core)
        self.assertIn('replace(/\\D+/g, "")', core)
        self.assertIn('addEventListener("beforeinput"', core)
        self.assertIn('addEventListener("paste"', core)
        self.assertIn('addEventListener("input", keepDashboardScopeDigitsOnly)', core)

        filter_start = stats.index("function filterDashboardEntriesByScope")
        filter_end = stats.index("function getDashboardBucketKey", filter_start)
        filter_block = stats[filter_start:filter_end]
        self.assertIn('preset === "today"', filter_block)
        self.assertIn('dashboardScopeMode) === "draw"', filter_block)
        self.assertIn("safeEntries.slice(-count)", filter_block)
        self.assertIn("shiftDashboardDate(latestDay, -(count - 1))", filter_block)
        self.assertIn("function renderDashboardScopeFilter", stats)
        self.assertIn('scope.mode === "draw" ? "kỳ" : "ngày"', stats)
        self.assertIn(".lotto-dashboard-scope-popover", styles)
        self.assertIn(".lotto-dashboard-scope-input-wrap input", styles)
        self.assertIn("grid-template-columns: repeat(2, minmax(165px, 196px))", styles)

    def test_dashboard_distribution_uses_clear_proportional_pie(self):
        stats = (ROOT / "frontend" / "vietlott-web-stats.js").read_text(encoding="utf-8")
        styles = (ROOT / "frontend" / "vietlott-web-extra.css").read_text(encoding="utf-8")
        pie_start = stats.index("function renderDashboardPieSegments")
        pie_end = stats.index("function renderDashboardDistributionPanel", pie_start)
        pie_block = stats[pie_start:pie_end]
        distribution_end = stats.index("function bindDashboardTemperatureLegend", pie_end)
        distribution_block = stats[pie_end:distribution_end]

        self.assertIn('class="lotto-dashboard-pie-segment"', pie_block)
        self.assertIn('class="lotto-dashboard-pie-slice-label', pie_block)
        self.assertIn("percent * 3.6", pie_block)
        self.assertIn("largeArcFlag", pie_block)
        self.assertIn("renderDashboardPieSegments(activeRows)", distribution_block)
        self.assertIn("lotto-dashboard-pie-summary", distribution_block)
        self.assertIn("lotto-dashboard-donut-legend-ratio", distribution_block)
        self.assertIn(".lotto-dashboard-pie-segment", styles)
        self.assertIn(".lotto-dashboard-pie-slice-label", styles)
        self.assertIn(".lotto-dashboard-donut-legend-ratio span", styles)

    def test_dashboard_temperature_groups_reveal_their_numbers(self):
        stats = (ROOT / "frontend" / "vietlott-web-stats.js").read_text(encoding="utf-8")
        core = (ROOT / "frontend" / "vietlott-web-core.js").read_text(encoding="utf-8")
        styles = (ROOT / "frontend" / "vietlott-web-extra.css").read_text(encoding="utf-8")

        temperature_start = stats.index("function buildDashboardTemperatureRows")
        temperature_end = stats.index("function computeDashboardDistributionRows", temperature_start)
        temperature_block = stats[temperature_start:temperature_end]
        render_start = stats.index("function renderDashboardTemperatureDetail")
        render_end = stats.index("function renderDashboardActivityStats", render_start)
        render_block = stats[render_start:render_end]

        self.assertIn("items: []", temperature_block)
        self.assertIn("groups[bucketIndex].items.push(item)", temperature_block)
        self.assertIn('data-dashboard-temperature-key="', render_block)
        self.assertIn('aria-controls="lottoDashboardTemperatureDetail"', render_block)
        self.assertIn('aria-expanded="', render_block)
        self.assertIn('role="listitem"', render_block)
        self.assertIn("bindDashboardTemperatureLegend(type, entries, mode)", render_block)
        self.assertIn('let dashboardSelectedTemperatureKey = "";', core)
        self.assertIn("dashboardSelectedTemperatureKey = \"\";", core)
        self.assertIn("button.lotto-dashboard-donut-legend-item", styles)
        self.assertIn(".lotto-dashboard-temperature-balls", styles)
        self.assertIn(".lotto-dashboard-temperature-ball", styles)

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
