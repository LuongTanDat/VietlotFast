// ---abc--- Boot Error Guard ---

// ----- Chặn lỗi khi giao diện khởi động -----
    // Nếu script lỗi sớm, khối này cố gắng hiện banner để người dùng biết app chưa tải xong.
    (function () {
      function ensureStartupVisible(message) {
        const loader = document.getElementById("pageLoader");
        if (loader) loader.classList.add("hide");
        const appShell = document.getElementById("appShell");
        const authOverlay = document.getElementById("authOverlay");
        if (appShell && authOverlay && getComputedStyle(appShell).display === "none") {
          authOverlay.style.display = "flex";
        }
        if (!message) return;
        let box = document.getElementById("bootErrorBanner");
        if (!box) {
          box = document.createElement("div");
          box.id = "bootErrorBanner";
          box.style.cssText = [
            "position:fixed",
            "left:16px",
            "right:16px",
            "bottom:16px",
            "z-index:5000",
            "padding:12px 14px",
            "border-radius:12px",
            "border:1px solid rgba(255,120,120,.45)",
            "background:rgba(34,10,14,.92)",
            "color:#ffd9d9",
            "font:600 13px/1.45 'Segoe UI',sans-serif",
            "box-shadow:0 12px 28px rgba(0,0,0,.35)"
          ].join(";");
          document.body.appendChild(box);
        }
        box.textContent = message;
      }

      window.addEventListener("error", function (event) {
        const detail = event?.message ? `Lỗi tải giao diện: ${event.message}` : "Lỗi tải giao diện.";
        ensureStartupVisible(detail);
      });

      window.addEventListener("unhandledrejection", function (event) {
        const reason = event?.reason?.message || event?.reason || "Lỗi promise khi khởi động giao diện.";
        ensureStartupVisible(`Lỗi tải giao diện: ${reason}`);
      });

      window.setTimeout(function () {
        ensureStartupVisible("");
      }, 4500);
    })();

// ---abc--- App Logic ---

// ----- Hằng số và state toàn cục ----- 
    // Khai báo loại vé, cấu hình game, localStorage key và state dùng chung cho toàn bộ web app.
    const TYPES = {
      LOTO_5_35: { label: "Loto_5/35", mainMin: 1, mainMax: 35, mainCount: 5, hasSpecial: true, specialMin: 1, specialMax: 12 },
      LOTO_6_45: { label: "Mega_6/45", mainMin: 1, mainMax: 45, mainCount: 6, hasSpecial: false, specialMin: 0, specialMax: 0 },
      LOTO_6_55: { label: "Power_6/55", mainMin: 1, mainMax: 55, mainCount: 6, hasSpecial: true, specialMin: 1, specialMax: 55 },
      KENO: { label: "Keno", mainMin: 1, mainMax: 80, mainCount: 20, hasSpecial: false, specialMin: 0, specialMax: 0, keno: true, resultCount: 20, pickMinCount: 1, pickMaxCount: 10 },
      MAX_3D: { label: "Max 3D", mainMin: 0, mainMax: 999, mainCount: 2, hasSpecial: false, specialMin: 0, specialMax: 0, threeDigit: true },
      MAX_3D_PRO: { label: "Max 3D Pro", mainMin: 0, mainMax: 999, mainCount: 2, hasSpecial: false, specialMin: 0, specialMax: 0, threeDigit: true }
    };
    const PREDICTION_TOP_RANKING_RULES = Object.freeze({
      LOTO_5_35: Object.freeze({ mainMin: 7, mainMax: 15, specialMin: 3, specialMax: 6, specialExcludesMain: false }),
      LOTO_6_45: Object.freeze({ mainMin: 7, mainMax: 18, specialMin: 0, specialMax: 0, specialExcludesMain: false }),
      LOTO_6_55: Object.freeze({ mainMin: 7, mainMax: 18, specialMin: 3, specialMax: 9, specialExcludesMain: true }),
      KENO: Object.freeze({ mainMin: 10, mainMax: 20, specialMin: 0, specialMax: 0, specialExcludesMain: false }),
      MAX_3D: Object.freeze({ mainMin: 10, mainMax: 20, specialMin: 0, specialMax: 0, specialExcludesMain: false }),
      MAX_3D_PRO: Object.freeze({ mainMin: 10, mainMax: 20, specialMin: 0, specialMax: 0, specialExcludesMain: false }),
    });

    function getPredictionTopRankingRule(type) {
      return PREDICTION_TOP_RANKING_RULES[String(type || "").trim().toUpperCase()] || null;
    }

    function normalizePredictionTopRankings(type, mainRanking = [], specialRanking = [], tickets = []) {
      const normalizedType = String(type || "").trim().toUpperCase();
      const typeMeta = TYPES[normalizedType];
      const rule = getPredictionTopRankingRule(normalizedType);
      if (!typeMeta || !rule) return { main: [], special: [] };

      const collectUnique = (sources, minimum, maximum, excluded = new Set()) => {
        const output = [];
        const seen = new Set();
        sources.flat().forEach(rawValue => {
          const value = Number(rawValue);
          if (!Number.isInteger(value) || value < minimum || value > maximum || excluded.has(value) || seen.has(value)) return;
          seen.add(value);
          output.push(value);
        });
        return output;
      };
      const ticketRows = Array.isArray(tickets) ? tickets : [];
      const mainSources = [
        Array.isArray(mainRanking) ? mainRanking : [],
        ticketRows.flatMap(ticket => Array.isArray(ticket?.main) ? ticket.main : []),
      ];
      let main = collectUnique(mainSources, typeMeta.mainMin, typeMeta.mainMax);
      if (main.length && main.length < rule.mainMin) {
        main = collectUnique([main, Array.from({ length: typeMeta.mainMax - typeMeta.mainMin + 1 }, (_, index) => typeMeta.mainMin + index)], typeMeta.mainMin, typeMeta.mainMax);
      }
      main = main.slice(0, rule.mainMax);

      if (!rule.specialMax || !typeMeta.hasSpecial) return { main, special: [] };
      const ticketSpecials = ticketRows.map(ticket => ticket?.special);
      const hasSpecialSource = (Array.isArray(specialRanking) && specialRanking.length > 0)
        || ticketSpecials.some(value => Number.isInteger(Number(value)));
      const excluded = rule.specialExcludesMain ? new Set(main) : new Set();
      let special = collectUnique(
        [Array.isArray(specialRanking) ? specialRanking : [], ticketSpecials],
        typeMeta.specialMin,
        typeMeta.specialMax,
        excluded,
      );
      if (hasSpecialSource && special.length < rule.specialMin) {
        special = collectUnique([
          special,
          Array.from({ length: typeMeta.specialMax - typeMeta.specialMin + 1 }, (_, index) => typeMeta.specialMin + index),
        ], typeMeta.specialMin, typeMeta.specialMax, excluded);
      }
      return { main, special: special.slice(0, rule.specialMax) };
    }

    function normalizePredictionResultTopRankings(result, typeHint = "") {
      if (!result || typeof result !== "object") return result;
      const type = String(result.type || typeHint || "").trim().toUpperCase();
      const normalized = normalizePredictionTopRankings(
        type,
        result.topRanking || result.topMainRanking,
        result.topSpecialRanking,
        result.tickets,
      );
      return {
        ...result,
        topRanking: normalized.main,
        topSpecialRanking: normalized.special,
      };
    }
    const LOTTERY_MENU_TYPES = [
      { key: "LOTO_5_35", label: "Loto_5/35", desc: "Power slot nhiều cấp số đặc biệt", badge: "SẴN SÀNG", supported: true },
      { key: "LOTO_6_45", label: "Mega_6/45", desc: "Mega cơ bản cho nhập liệu và thống kê", badge: "SẴN SÀNG", supported: true },
      { key: "LOTO_6_55", label: "Power_6/55", desc: "Power jackpot có số đặc biệt", badge: "SẴN SÀNG", supported: true },
      { key: "KENO", label: "Keno", desc: "Nhiều bậc số, kết quả liên tục", badge: "SẴN SÀNG", supported: true },
      { key: "MAX_3D", label: "Max 3D", desc: "Đã nối AI, history và đối chiếu kiểu 3 chữ số", badge: "SẴN SÀNG", supported: true },
      { key: "MAX_3D_PRO", label: "Max 3D Pro", desc: "Đã nối AI, history và đối chiếu kiểu 3 chữ số", badge: "SẴN SÀNG", supported: true }
    ];
    const KENO_PAYOUT = {
      10: { 10: "2 tỷ *", 9: "150 triệu", 8: "7,4 triệu", 7: "600.000", 6: "80.000", 5: "20.000", 0: "10.000" },
      9: { 9: "800 triệu *", 8: "12 triệu", 7: "1,5 triệu", 6: "150.000", 5: "30.000", 4: "10.000", 0: "10.000" },
      8: { 8: "200 triệu *", 7: "5 triệu", 6: "500.000", 5: "50.000", 4: "10.000", 0: "10.000" },
      7: { 7: "40 triệu", 6: "1,2 triệu", 5: "100.000", 4: "20.000", 3: "10.000" },
      6: { 6: "12,5 triệu", 5: "450.000", 4: "40.000", 3: "10.000" },
      5: { 5: "4,4 triệu", 4: "150.000", 3: "10.000" },
      4: { 4: "400.000", 3: "50.000", 2: "10.000" },
      3: { 3: "200.000", 2: "20.000" },
      2: { 2: "90.000" },
      1: { 1: "20.000" }
    };
    const TYPE_KEYS = Object.keys(TYPES);
    const PRIZE_TYPE_SHORT_LABELS = {
      LOTO_5_35: "5/35",
      LOTO_6_45: "6/45",
      LOTO_6_55: "6/55",
      KENO: "Keno",
      MAX_3D: "3D",
      MAX_3D_PRO: "3D Pro"
    };
    const REMEMBER_KEY = "vietlott_web_remember_v1";
    const THEME_KEY = "vietlott_web_theme_v1";
    const LOCAL_USERS_KEY = "vietlott_local_users_v1";
    const LOCAL_STORES_KEY = "vietlott_local_stores_v1";
    const LOCAL_SESSION_KEY = "vietlott_local_session_v1";
    const LOCAL_KENO_CSV_CACHE_KEY = "vietlott_keno_csv_cache_v1";
    const KENO_TRAINING_CONFIG_KEY = "vietlott_keno_training_config_v1";
    const PREDICT_RISK_MODE_KEY = "vietlott_predict_risk_mode_v1";
    const PREDICT_UI_MODE_KEY = "vietlott_predict_ui_mode_v1";
    const DASHBOARD_SELECTED_GAME_KEY = "vietlott_dashboard_selected_game_v1";
    const DASHBOARD_ACTIVITY_VIEW_KEY = "vietlott_dashboard_activity_view_v1";
    const DASHBOARD_DISTRIBUTION_VIEW_KEY = "vietlott_dashboard_distribution_view_v1";
    const CHART_STATS_SELECTED_TYPE_KEY = "vietlott_chart_stats_selected_type_v1";
    const CHART_STATS_SELECTED_PRESET_KEY = "vietlott_chart_stats_selected_preset_v1";
    const CHART_STATS_CUSTOM_COUNT_KEY = "vietlott_chart_stats_custom_count_v1";
    const CHART_STATS_VIEW_MODE_KEY = "vietlott_chart_stats_view_mode_v1";
    const VIP_PREDICT_PLAY_MODE_KEY = "vietlott_vip_predict_play_mode_v1";
    const VIP_PREDICT_BAO_LEVEL_KEY = "vietlott_vip_predict_bao_level_v1";
    const VIP_PREDICT_ENGINE_KEY = "vietlott_vip_predict_engine_v1";
    const VIP_PREDICT_RISK_MODE_KEY = "vietlott_vip_predict_risk_mode_v1";
    const VIP_PREDICT_TYPE_KEY = "vietlott_vip_predict_type_v1";
    const VIP_PREDICT_COUNT_KEY = "vietlott_vip_predict_count_v1";
    const VIP_PREDICT_KENO_LEVEL_KEY = "vietlott_vip_predict_keno_level_v1";
    const STATS_SELECTED_TYPE_KEY = "vietlott_stats_selected_type_v1";
    const STATS_SELECTED_DAY_WINDOW_KEY = "vietlott_stats_selected_day_window_v1";
    const STATS_DATE_FROM_KEY = "vietlott_stats_date_from_v1";
    const STATS_DATE_TO_KEY = "vietlott_stats_date_to_v1";
    const STATS_RECENT_DISPLAY_MODE_KEY = "vietlott_stats_recent_display_mode_v1";
    const STATS_RECENT_KENO_LEVEL_KEY = "vietlott_stats_recent_keno_level_v1";
    const STATS_RECENT_SELECTED_SETS_KEY = "vietlott_stats_recent_selected_sets_v1";
    const STATS_V2_UI_KEY = "vietlott_stats_v2_ui_v1";
    const ANALYSIS_UI_KEY = "vietlott_analysis_ui_v1";
    const LIVE_RESULTS_CACHE_KEY = "vietlott_live_results_v1";
    const LIVE_HISTORY_CACHE_KEY = "vietlott_live_history_v1";
    const LIVE_SYNC_TIMING_CACHE_KEY = "vietlott_live_sync_timing_v1";
    const LIVE_UPDATE_BADGE_CACHE_KEY = "vietlott_live_update_badges_v1";
    const MAX_RESULTS_PER_TYPE = 60;
    const PREDICT_MAX_BUNDLES = 100;
    const APP_SHORT_NAME = "DVLF";
    const APP_FULL_NAME = "Deep Vietlott Fast";
    const HEADER_NOTIFICATION_READ_KEY = "dvlf_header_notification_read_v1";
    const HEADER_NOTIFICATION_DISMISSED_KEY = "dvlf_header_notification_dismissed_v1";
    const MAX_PICKS_PER_TYPE = 45;
    const LIVE_RESULT_TYPES = [
      { key: "LOTO_5_35", label: "Loto_5/35", importable: true },
      { key: "LOTO_6_45", label: "Mega_6/45", importable: true },
      { key: "LOTO_6_55", label: "Power_6/55", importable: true },
      { key: "KENO", label: "Keno", importable: true },
      { key: "MAX_3D", label: "Max 3D", importable: false },
      { key: "MAX_3D_PRO", label: "Max 3D Pro", importable: false }
    ];
    const LIVE_HISTORY_TYPES = [...LIVE_RESULT_TYPES];
    const LIVE_DRAW_SCHEDULES = {
      KENO: { kind: "interval", startMinutes: 6 * 60 + 8, endMinutes: 21 * 60 + 52, stepMinutes: 8 },
      LOTO_5_35: { kind: "daily", slots: ["13:00", "21:00"] },
      LOTO_6_45: { kind: "weekly", weekdays: [0, 3, 5], time: "18:00" },
      LOTO_6_55: { kind: "weekly", weekdays: [2, 4, 6], time: "18:00" },
      MAX_3D: { kind: "weekly", weekdays: [1, 3, 5], time: "18:00" },
      MAX_3D_PRO: { kind: "weekly", weekdays: [2, 4, 6], time: "18:00" },
    };
    const DEFAULT_LIVE_HISTORY_COUNT_OPTIONS = [
      { value: "2", label: "2 kỳ" },
      { value: "10", label: "10 kỳ" },
      { value: "20", label: "20 kỳ" },
      { value: "50", label: "50 kỳ" },
      { value: "100", label: "100 kỳ" },
      { value: "all", label: "Tất Cả" },
    ];
    const KENO_LIVE_HISTORY_COUNT_OPTIONS = [
      { value: "2", label: "2 kỳ" },
      { value: "today", label: "Hôm Nay" },
      { value: "3d", label: "3 Ngày" },
      { value: "1w", label: "1 Tuần" },
      { value: "1m", label: "1 Tháng" },
      { value: "3m", label: "3 Tháng" },
      { value: "6m", label: "6 Tháng" },
      { value: "1y", label: "1 Năm" },
      { value: "all", label: "Tất cả Kỳ" },
    ];
    const KENO_LIVE_HISTORY_COUNT_LABELS = Object.fromEntries(
      KENO_LIVE_HISTORY_COUNT_OPTIONS.map(item => [item.value, item.label])
    );
    const AI_PREDICT_TYPES = new Set(["KENO", "LOTO_5_35", "LOTO_6_45", "LOTO_6_55", "MAX_3D", "MAX_3D_PRO"]);
    const PREDICTION_LOG_TYPES = ["KENO", "LOTO_5_35", "LOTO_6_45", "LOTO_6_55", "MAX_3D", "MAX_3D_PRO"];
    const ML_PREDICTION_LOG_TYPES = new Set(["KENO", "LOTO_5_35", "LOTO_6_45", "LOTO_6_55"]);
    const PREDICT_RISK_MODES = [
      { key: "stable", label: "Ổn Định", summary: "Meta đang ưu tiên giữ nhịp và giảm dao động giữa 2 engine." },
      { key: "balanced", label: "Cân Bằng", summary: "Meta đang giữ cân bằng giữa độ ổn định và cơ hội bùng nhịp." },
      { key: "aggressive", label: "Tấn Công", summary: "Meta đang mở rộng cửa cho tín hiệu nóng và quota co giãn mạnh hơn." },
    ];
    const PREDICTION_MODE_NORMAL = "normal";
    const PREDICTION_MODE_VIP = "vip";
    const VIP_PREDICT_MAX_BUNDLES = 10;
    const PREDICTION_MODE_STATS = "stats";
    const PREDICTION_MODE_STATS_V2 = "stats-v2";
    const PREDICTION_MODE_CHARTS = "charts";
    const PREDICTION_MODE_DASHBOARD = "dashboard";
    const PREDICTION_MODE_ANALYSIS = "analysis";
    const STATS_V2_PERIOD_OPTIONS = [
      { value: "7d", label: "7 ngày" },
      { value: "30d", label: "30 ngày" },
      { value: "60d", label: "60 ngày" },
      { value: "1y", label: "1 năm" },
      { value: "custom", label: "Custom" },
    ];
    const STATS_V2_SORT_OPTIONS = [
      { value: "most", label: "Xuất hiện nhiều nhất" },
      { value: "least", label: "Xuất hiện ít nhất" },
      { value: "overdue", label: "Lâu chưa về nhất" },
      { value: "streak", label: "Đang ra liên tiếp" },
    ];
    const STATS_V2_MAX_COMBO_DEFAULT = 5;
    const STATS_V2_MAX_COMBO_KENO = 10;
    const STATS_V2_COMBO_OPTIONS = Array.from({ length: STATS_V2_MAX_COMBO_KENO }, (_, index) => {
      const value = index + 1;
      return { value, label: `${value} số` };
    });
    const STATS_V2_LOTO535_VIEW_OPTIONS = [
      { value: "jackpot", label: "Giá trị Độc đắc" },
      { value: "frequency", label: "Tần suất" },
    ];
    const STATS_PANEL_AUTO_REFRESH_MS = 180000;
    const STATS_RECENT_MODE_OPTIONS = [
      { value: "day", label: "Ngày" },
      { value: "draw", label: "Kỳ" },
    ];
    const STATS_RECENT_DAY_WINDOW_OPTIONS = [3, 5, 7, 15, 30, 60, 100, "all"];
    const STATS_RECENT_DRAW_WINDOW_OPTIONS = [5, 15, 30, 50, 100, 200, 300, "all"];
    const STATS_RECENT_WINDOW_DEFAULT = 100;
    const STATS_RECENT100_SIDE_LIMIT = 20;
    const STATS_V2_AUTO_REFRESH_MS = 90000;
    const MAX_STATS_V2_FAVORITES = 50;
    const MAX_STATS_V2_HISTORY = 80;
    const ANALYSIS_AUTO_REFRESH_MS = 90000;
    const MAX_ANALYSIS_HISTORY = 80;
    const ANALYSIS_PERIOD_OPTIONS = [
      { value: "7d", label: "7 ngày" },
      { value: "30d", label: "30 ngày" },
      { value: "60d", label: "60 ngày" },
      { value: "1y", label: "1 năm" },
      { value: "all", label: "Tất cả" },
      { value: "custom", label: "Custom" },
    ];
    const ANALYSIS_MODE_OPTIONS = [
      { value: "overview", label: "Tổng quan" },
      { value: "general", label: "Tổng quan bộ số" },
      { value: "distribution", label: "Phân phối" },
      { value: "ratios", label: "Chẵn/Lẻ - Cao/Thấp" },
      { value: "latest_draw", label: "Kỳ mới nhất" },
      { value: "consecutive", label: "Chuỗi liên tiếp" },
      { value: "overdue", label: "Gan / Overdue" },
      { value: "poisson", label: "Poisson" },
      { value: "knn", label: "KNN tương đồng" },
      { value: "chain", label: "Lead & Follow" },
      { value: "relationships", label: "Quan hệ cặp số" },
      { value: "modulo", label: "Modulo / Đuôi số" },
      { value: "advanced", label: "Nâng cao" },
      { value: "special", label: "Số đặc biệt" },
      { value: "smart_wheel", label: "Smart Wheel" },
      { value: "weekday", label: "Theo thứ" },
      { value: "score", label: "Chấm điểm" },
      { value: "all", label: "Tất cả" },
    ];
    const DASHBOARD_LOTTO_TYPES = ["KENO", "LOTO_5_35", "LOTO_6_45", "LOTO_6_55", "MAX_3D", "MAX_3D_PRO"];
    const DASHBOARD_ACTIVITY_VIEW_OPTIONS = ["day", "week", "month"];
    const DASHBOARD_DISTRIBUTION_VIEW_OPTIONS = ["range", "parity", "temperature", "head", "tail"];
    const DASHBOARD_ACTIVITY_BUCKET_LIMITS = {
      day: 14,
      week: 12,
      month: 12,
    };
    const DASHBOARD_DISTRIBUTION_COLORS = {
      strong: "#6d5cff",
      potential: "#4f8cff",
      neutral: "#89a4ff",
      weak: "#c4cafb",
      reject: "#eceffe",
      low: "#6b6ef9",
      midlow: "#8a63ff",
      midhigh: "#45a4ff",
      high: "#79d6ff",
      veryhigh: "#b9eafe",
      trusted: "#5c63ff",
      reliable: "#3f8cff",
      watching: "#7b92ff",
      volatile: "#adb9ff",
      risky: "#e7ebff",
    };
    const PREDICTION_HISTORY_TYPES = [
      { value: "KENO", label: "Keno" },
      { value: "LOTO_5_35", label: "Loto_5/35" },
      { value: "LOTO_6_45", label: "Mega_6/45" },
      { value: "LOTO_6_55", label: "Power_6/55" },
      { value: "MAX_3D", label: "Max 3D" },
      { value: "MAX_3D_PRO", label: "Max 3D Pro" },
    ];
    const STATS_TYPE_OPTIONS = [
      { value: "LOTO_5_35", label: "5/35" },
      { value: "LOTO_6_45", label: "6/45" },
      { value: "LOTO_6_55", label: "6/55" },
      { value: "KENO", label: "Keno" },
      { value: "MAX_3D", label: "3D" },
      { value: "MAX_3D_PRO", label: "3D Pro" },
    ];
    const CHART_STATS_TYPE_OPTIONS = [
      { value: "KENO", label: "Keno" },
      { value: "LOTO_5_35", label: "Lotto 5/35" },
      { value: "LOTO_6_45", label: "Mega 6/45" },
      { value: "LOTO_6_55", label: "Power 6/55" },
    ];
    const CHART_STATS_VIEW_OPTIONS = [
      { value: "all", label: "Tất cả biểu đồ" },
      { value: "frequency", label: "Tần suất theo nhóm" },
      { value: "percent", label: "Chỉ donut %" },
    ];
    const CHART_STATS_PRESET_OPTIONS = {
      KENO: ["1", "3", "5", "10", "15", "30", "50", "119", "1190", "2380", "3570", "all", "custom"],
      DEFAULT: ["1", "3", "5", "10", "20", "30", "50", "100", "200", "500", "all", "custom"],
    };
    const CHART_STATS_PRESET_LABELS = {
      "1": "1 kỳ",
      "3": "3 kỳ",
      "5": "5 kỳ",
      "10": "10 kỳ",
      "15": "15 kỳ",
      "20": "20 kỳ",
      "30": "30 kỳ",
      "50": "50 kỳ",
      "100": "100 kỳ",
      "119": "119 kỳ",
      "200": "200 kỳ",
      "500": "500 kỳ",
      "1190": "1190 kỳ",
      "2380": "2380 kỳ",
      "3570": "3570 kỳ",
      all: "All",
      custom: "Tùy chỉnh",
    };
    const CHART_STATS_GROUPS = {
      KENO: [
        { key: "1-10", label: "1-10", min: 1, max: 10, color: "#53d7ff" },
        { key: "11-20", label: "11-20", min: 11, max: 20, color: "#4fc49e" },
        { key: "21-30", label: "21-30", min: 21, max: 30, color: "#71e17f" },
        { key: "31-40", label: "31-40", min: 31, max: 40, color: "#b7ec6a" },
        { key: "41-50", label: "41-50", min: 41, max: 50, color: "#ffd76a" },
        { key: "51-60", label: "51-60", min: 51, max: 60, color: "#ffb865" },
        { key: "61-70", label: "61-70", min: 61, max: 70, color: "#ff8b74" },
        { key: "71-80", label: "71-80", min: 71, max: 80, color: "#d586ff" },
      ],
      LOTO_5_35: [
        { key: "1-10", label: "1-10", min: 1, max: 10, color: "#53d7a2" },
        { key: "11-20", label: "11-20", min: 11, max: 20, color: "#7ce29c" },
        { key: "21-30", label: "21-30", min: 21, max: 30, color: "#bde77e" },
        { key: "31-35", label: "31-35", min: 31, max: 35, color: "#ffd36b" },
      ],
      LOTO_6_45: [
        { key: "1-10", label: "1-10", min: 1, max: 10, color: "#66d5ff" },
        { key: "11-20", label: "11-20", min: 11, max: 20, color: "#5ebeff" },
        { key: "21-30", label: "21-30", min: 21, max: 30, color: "#6fa7ff" },
        { key: "31-40", label: "31-40", min: 31, max: 40, color: "#8b96ff" },
        { key: "41-45", label: "41-45", min: 41, max: 45, color: "#b986ff" },
      ],
      LOTO_6_55: [
        { key: "1-10", label: "1-10", min: 1, max: 10, color: "#ffd76a" },
        { key: "11-20", label: "11-20", min: 11, max: 20, color: "#ffc15d" },
        { key: "21-30", label: "21-30", min: 21, max: 30, color: "#ffac62" },
        { key: "31-40", label: "31-40", min: 31, max: 40, color: "#ff9468" },
        { key: "41-50", label: "41-50", min: 41, max: 50, color: "#ff7d73" },
        { key: "51-55", label: "51-55", min: 51, max: 55, color: "#ff6a9b" },
      ],
    };
    const PREDICT_BAO_LEVELS = {
      LOTO_5_35: [4, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
      LOTO_6_45: [5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 18],
      LOTO_6_55: [5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 18],
    };
    const STATS_DAY_WINDOWS = ["10", "20", "30", "120", "all", "custom"];
    const STATS_DAY_WINDOW_LABELS = {
      "10": "10 Ngày",
      "20": "20 Ngày",
      "30": "30 Ngày",
      "120": "120 Ngày",
      all: "Tất Cả Ngày",
      custom: "Khoảng Ngày",
    };
    const STATS_SIX_GRID_TYPES = new Set(["LOTO_5_35", "LOTO_6_45", "LOTO_6_55"]);
    function getPredictBaoLevels(typeKey) {
      const normalizedType = String(typeKey || "").trim().toUpperCase();
      return Array.isArray(PREDICT_BAO_LEVELS[normalizedType]) ? [...PREDICT_BAO_LEVELS[normalizedType]] : [];
    }
    function hasPredictBaoMode(typeKey) {
      return getPredictBaoLevels(typeKey).length > 0;
    }
    const MAX_PREDICTION_LOGS_PER_TYPE = 180;
    const STORE_PERSIST_PREDICTION_BACKTEST_KEYS = ["avgHitRate", "avgHits", "samples", "recentAvgHitRate", "agreementScore", "cooldownPenalty", "stabilityScore"];
    const STORE_PERSIST_RESULT_SUMMARY_KEYS = [
      "ticketCount",
      "bestMainHits",
      "avgMainHits",
      "specialHits",
      "thresholdTicketHits",
      "prizeTicketHits",
      "pricedPrizeHits",
      "totalPrizeAmount",
      "hasVariablePrize",
      "losingTicketCount",
      "prizeBreakdown",
    ];
    const MAX_PAYPAL_TOPUPS = 24;
    const PAYPAL_REAL_RATE = 1.25;
    const PAYPAL_TOPUP_PACKAGES = [
      { id: "mini", title: "10.000đ", amount: 10000, bonusRate: 0, bonus: "Gói thấp nhất để nạp nhanh" },
      { id: "small", title: "20.000đ", amount: 20000, bonusRate: 0, bonus: "Gói nhỏ, thao tác gọn" },
      { id: "starter", title: "50.000đ", amount: 50000, bonusRate: 0.01, bonus: "Thưởng thêm 1% PayPal" },
      { id: "boost", title: "100.000đ", amount: 100000, bonusRate: 0.015, bonus: "Thưởng thêm 1,5% PayPal" },
      { id: "plus", title: "200.000đ", amount: 200000, bonusRate: 0.02, bonus: "Thưởng thêm 2% PayPal" },
      { id: "pro", title: "500.000đ", amount: 500000, bonusRate: 0.025, bonus: "Thưởng thêm 2,5% PayPal" }
    ];
    const MAX_LUCKY_WHEEL_HISTORY = 30;
    const MAX_LUCKY_WHEEL_TOPUP_HISTORY = 12;
    const LUCKY_WHEEL_MAX_SPINS = 60;
    const LUCKY_WHEEL_REGEN_MS = 10 * 60 * 1000;
    const LUCKY_WHEEL_GIFT_MILESTONES = [80, 120, 200, 300, 500, 1000];
    const LUCKY_WHEEL_TOPUP_PAYPAL_PER_SPIN = 2000;
    const LUCKY_WHEEL_TOPUP_MAX_PER_ACTION = 50;
    const LUCKY_WHEEL_TOPUP_MAX_PER_DAY = 1000;
    const LIVE_HISTORY_RECENT_REPAIR_DAYS = 15;
    const LUCKY_WHEEL_SEGMENTS = [
      { label: "5 Kim cương + 100 PayPal", short: "5 KC + 100 PP", desc: "Phần thưởng", color: "#f4d35e", weight: 28, reward: { diamond: 5, paypal: 100 } },
      { label: "Thêm 1 lượt", short: "+1 Lượt", desc: "Lượt quay", color: "#ffd166", weight: 10, reward: { bonusSpins: 1 } },
      { label: "Thêm 3 lượt", short: "+3 Lượt", desc: "Lượt quay", color: "#ffb347", weight: 5, reward: { bonusSpins: 3 } },
      { label: "+100 Kim cương", short: "100 KC", desc: "Kim cương", color: "#ff8c42", weight: 1, reward: { diamond: 100 } },
      { label: "Thêm 50 lượt", short: "+50 Lượt", desc: "Lượt quay", color: "#ff5f6d", weight: 0.3, reward: { bonusSpins: 50 } },
      { label: "+10.000 PayPal", short: "10K PP", desc: "PayPal", color: "#7f6bff", weight: 0.4, reward: { paypal: 10000 } },
      { label: "+1.000 PayPal", short: "1K PP", desc: "PayPal", color: "#5867ff", weight: 5, reward: { paypal: 1000 } },
      { label: "+500 PayPal", short: "500 PP", desc: "PayPal", color: "#10b6dd", weight: 45, reward: { paypal: 500 } },
      { label: "+1.000 Kim cương", short: "1K KC", desc: "Kim cương", color: "#21c59a", weight: 0.3, reward: { diamond: 1000 } },
      { label: "+10 Kim cương", short: "10 KC", desc: "Kim cương", color: "#d95ef2", weight: 10, reward: { diamond: 10 } }
    ];

    const emptyStore = () => ({
      diamondBalance: 0,
      paypalBalance: 0,
      results: Object.fromEntries(TYPE_KEYS.map(k => [k, {}])),
      picks: Object.fromEntries(TYPE_KEYS.map(k => [k, {}])),
      resultOrder: Object.fromEntries(TYPE_KEYS.map(k => [k, []])),
      pickOrder: Object.fromEntries(TYPE_KEYS.map(k => [k, []])),
      predictionLogs: Object.fromEntries(PREDICTION_LOG_TYPES.map(k => [k, []])),
      statsV2Favorites: [],
      statsV2History: [],
      analysisHistory: [],
      paypalTopups: [],
      luckyWheelHistory: [],
      luckyWheelTopupHistory: [],
      luckyWheelSpinCount: 0,
      luckyWheelDailySpinCount: 0,
      luckyWheelDailyExchangeSpins: 0,
      luckyWheelExchangeDayKey: "",
      luckyWheelMilestoneDayKey: "",
      luckyWheelStoredSpins: LUCKY_WHEEL_MAX_SPINS,
      luckyWheelLastRegenAt: "",
      luckyWheelBonusSpins: 0,
      luckyWheelLastSpinDay: "",
      luckyWheelLastResult: null
    });

    let currentUser = null;
    let currentUserRole = "user";
    let store = emptyStore();
    let storeSaveState = {
      pending: false,
      ok: true,
      message: "",
      reason: "",
      savedAt: "",
      failedAt: "",
    };
    let storeSaveLoopPromise = null;
    let pendingStoreSave = null;
    let lastSavedStoreSnapshotText = "";
    let storeSaveGeneration = 0;
    let accountEditMode = false;
    let kenoCsvFeed = { results: {}, order: [], sourceLabels: [], loadedAt: "" };
    let kenoCsvFeedCacheRestored = false;
    let kenoPredictStatusMeta = { loadedAt: "", detail: "", level: "" };
    let liveResultsState = {};
    const liveSingleRefreshBusy = new Set();
    let liveUpdateBadgeState = {};
    let liveHistoryState = {};
    let liveHistoryLegacyApiMode = false;
    let liveHistoryRecentRefreshBusy = false;
    let dataTableSelectedType = "LOTO_5_35";
    let dataTableSelectedLimit = "500";
    let dataTableDateFilters = { weekday: "all", day: "all", month: "all", year: "all" };
    let dataTableLoading = false;
    let liveResultsFetchedAt = "";
    let liveAutoTimer = null;
    let liveResultsProgressTypeCursor = {};
    let liveResultsProgressHistoryRefreshCursor = {};
    let liveResultsProgressHistoryRefreshBusy = false;
    let predictPageModeValue = "normal";
    let predictPlayModeValue = "normal";
    let predictBaoLevelValue = "";
    let predictEngineValue = "both";
    let predictRiskModeValue = "balanced";
    let predictLastDisplayResult = null;
    let vipPredictPlayModeValue = "normal";
    let vipPredictBaoLevelValue = "";
    let vipPredictEngineValue = "both";
    let vipPredictRiskModeValue = "balanced";
    let vipPredictTypeValue = "KENO";
    let vipPredictCountValue = 1;
    let vipPredictKenoLevelValue = 5;
    let vipPredictLastDisplayResult = null;
    let statsSelectedType = "KENO";
    let statsSelectedDayWindow = "30";
    let statsDateFrom = "";
    let statsDateTo = "";
    let statsPanelLoading = false;
    let statsPanelError = "";
    let statsPanelRefreshToken = 0;
    let statsPanelAutoRefreshTimer = null;
    let statsPanelCountdownTimer = null;
    let statsPanelNextRefreshAt = 0;
    let statsRecentModeValue = "draw";
    let statsRecentWindowValue = STATS_RECENT_WINDOW_DEFAULT;
    let statsRecentDisplayModeValue = "order";
    let statsRecentKenoLevelValue = 10;
    let statsRecentSelectedByType = Object.create(null);
    let statsRecentActiveSetByType = Object.create(null);
    let statsModernInsightTab = "most";
    let statsModernInsightExpanded = false;
    const statsEntriesCache = new Map();
    const statsRecentComputationCache = new Map();
    const statsRecentWorkerJobs = new Map();
    const statsRecentWorkerJobKeys = new Map();
    let statsRecentWorker = null;
    let statsRecentWorkerSupported = true;
    let statsRecentWorkerSeq = 0;
    let statsRecentPendingComputationKey = "";
    let statsV2State = {
      type: "LOTO_5_35",
      period: "30d",
      sort: "most",
      comboSize: 1,
      group: "main",
      loto535View: "frequency",
      from: "",
      to: "",
      autoRefresh: false,
      loading: false,
      error: "",
      payload: null,
      selected: [],
      message: "",
      refreshToken: 0,
      timer: null
    };
    let chartStatsSelectedType = "KENO";
    let chartStatsSelectedPreset = "119";
    let chartStatsCustomCountValue = "";
    let chartStatsViewMode = "all";
    let chartStatsPanelLoading = false;
    let chartStatsPanelError = "";
    let chartStatsPanelRefreshToken = 0;
    let dashboardSelectedGame = "KENO";
    let dashboardActivityViewMode = "day";
    let dashboardDistributionViewMode = "range";
    let dashboardPanelLoading = false;
    let dashboardPanelError = "";
    let dashboardPanelRefreshToken = 0;
    const analysisState = {
      type: "LOTO_5_35",
      period: "30d",
      from: "",
      to: "",
      mode: "overview",
      limit: 20,
      k: 5,
      comboSize: 2,
      includeSpecial: true,
      autoRefresh: false,
      timer: null,
      lastPayload: null,
      loading: false,
      error: "",
      refreshToken: 0,
    };
    let predictLoadingStartAt = 0;
    let predictLoadingTimer = null;
    let predictLoadingEngineKey = "";
    let predictFlowBusy = false;
    let predictBothAvgDurationMs = 15000;
    let kenoTrainingEnabled = false;
    let kenoTrainingTimer = null;
    let kenoTrainingBusy = false;
    let kenoTrainingLastTriggeredKy = "";
    let kenoTrainingLastResolvedKy = "";
    let liveResultsProgressButtonReset = null;
    let liveResultsLegacyFallbackRunning = false;
    let predictionHistoryPanelOpen = false;
    let predictionHistorySelectedType = "KENO";
    let predictionHistorySelectedRange = "5k";
    let predictionHistorySelectedPlayMode = "normal";
    let predictionHistorySelectedBaoLevel = "all";
    let predictionHistoryExpandedKeys = new Set();
    let predictionHistoryCurrentIndex = 0;
    let predictionHistoryLoading = false;
    let predictionHistoryLoadingType = "";
    let predictionHistoryLoadingError = "";
    let predictionHistoryRefreshToken = 0;
    let vipPredictionHistoryPanelOpen = false;
    let vipPredictionHistorySelectedType = "KENO";
    let vipPredictionHistorySelectedRange = "5k";
    let vipPredictionHistorySelectedPlayMode = "normal";
    let vipPredictionHistorySelectedBaoLevel = "all";
    let vipPredictionHistoryCurrentIndex = 0;
    let vipPredictionHistoryLoading = false;
    let vipPredictionHistoryLoadingType = "";
    let vipPredictionHistoryLoadingError = "";
    let vipPredictionHistoryRefreshToken = 0;
    let selectedPaypalTopupPackageId = PAYPAL_TOPUP_PACKAGES[1]?.id || "";
    let luckyWheelRotation = 0;
    let luckyWheelSpinning = false;
    let luckyWheelAutoMode = false;
    let luckyWheelUiTimer = null;
    let luckyWheelResizeFrame = 0;
    let luckyWheelLastAvailable = null;
    let luckyWheelSpinMultiplier = 1;
    let luckyWheelSelectedTopupSpins = 0;
    let luckyWheelTopupHoldTimeout = null;
    let luckyWheelTopupHoldInterval = null;
    const IS_LOCAL_MODE = !(
      location.protocol.startsWith("http") &&
      /^(localhost|127\.0\.0\.1)$/i.test(location.hostname || "") &&
      String(location.port || "") === "8080"
    );
    const SERVER_TIME_SYNC_MS = 5 * 60 * 1000;
    let serverTimeOffsetMs = 0;
    let serverTimeSyncedAtMs = 0;
    let serverTimeSyncPromise = null;

    function applyServerTimeSync(serverTimeMs, clientReceivedAtMs = Date.now()) {
      const numeric = Number(serverTimeMs);
      if (!Number.isFinite(numeric) || numeric <= 0) return false;
      serverTimeOffsetMs = Math.round(numeric - Number(clientReceivedAtMs || Date.now()));
      serverTimeSyncedAtMs = Date.now();
      return true;
    }

    function syncServerTimeFromHeaders(headers, clientReceivedAtMs = Date.now()) {
      if (!headers || typeof headers.get !== "function") return false;
      return applyServerTimeSync(headers.get("X-Server-Time-Ms"), clientReceivedAtMs);
    }

    function getSyncedNowMs() {
      return Date.now() + serverTimeOffsetMs;
    }

    function getSyncedNowDate() {
      return new Date(getSyncedNowMs());
    }

    function getSyncedIsoString() {
      return getSyncedNowDate().toISOString();
    }

    function shouldSyncServerTime(force = false) {
      if (IS_LOCAL_MODE) return false;
      if (force || !serverTimeSyncedAtMs) return true;
      return Date.now() - serverTimeSyncedAtMs > SERVER_TIME_SYNC_MS;
    }

    async function syncServerTime({ force = false } = {}) {
      if (!shouldSyncServerTime(force)) return true;
      if (serverTimeSyncPromise) return serverTimeSyncPromise;
      serverTimeSyncPromise = fetch("/api/time", {
        method: "GET",
        credentials: "include",
        cache: "no-store",
      }).then(async response => {
        const receivedAtMs = Date.now();
        let synced = syncServerTimeFromHeaders(response.headers, receivedAtMs);
        let payload = {};
        try {
          payload = JSON.parse(await response.text() || "{}");
        } catch {
          payload = {};
        }
        if (!synced) synced = applyServerTimeSync(payload.serverTimeMs, receivedAtMs);
        return !!synced;
      }).catch(() => false).finally(() => {
        serverTimeSyncPromise = null;
      });
      return serverTimeSyncPromise;
    }

    function maybeSyncServerTimeSoon() {
      if (shouldSyncServerTime(false)) void syncServerTime({ force: false });
    }

    window.getSyncedNowMs = getSyncedNowMs;
    window.getSyncedNowDate = getSyncedNowDate;
    window.getSyncedIsoString = getSyncedIsoString;
    window.syncServerTime = syncServerTime;

    const APP_PAGE_PATHS = {
      home: "/",
      wheel: "/vong-quay",
      deposit: "/nap-tien",
      data: "/bang-du-lieu"
    };

    function normalizeUser(u) {
      return (u || "").trim().toLowerCase();
    }

    function getAppPageMode(pathname = location.pathname || "/") {
      const normalized = String(pathname || "/").toLowerCase();
      if (normalized === "/vong-quay" || normalized === "/vong-quay.html") return "wheel";
      if (normalized === "/nap-tien" || normalized === "/nap-tien.html") return "deposit";
      if (normalized === "/bang-du-lieu" || normalized === "/bang-du-lieu.html") return "data";
      return "home";
    }

    function getCurrentAppPageMode() {
      return getAppPageMode(location.pathname || "/");
    }

    function isElementActuallyVisible(el) {
      if (!el || el.hidden) return false;
      if (!document.body.contains(el)) return false;
      const style = window.getComputedStyle ? window.getComputedStyle(el) : null;
      if (style && (style.display === "none" || style.visibility === "hidden")) return false;
      return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
    }

    function isElementNearViewport(el, margin = 160) {
      if (!isElementActuallyVisible(el) || typeof el.getBoundingClientRect !== "function") return false;
      const rect = el.getBoundingClientRect();
      const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
      const viewportWidth = window.innerWidth || document.documentElement.clientWidth || 0;
      return rect.bottom >= -margin &&
        rect.top <= viewportHeight + margin &&
        rect.right >= -margin &&
        rect.left <= viewportWidth + margin;
    }

    function runWhenBrowserIdle(callback, timeoutMs = 1200) {
      if (typeof window.requestIdleCallback === "function") {
        return window.requestIdleCallback(callback, { timeout: timeoutMs });
      }
      return window.setTimeout(callback, Math.min(120, Math.max(0, timeoutMs)));
    }

    function isHomePageVisible() {
      return getCurrentAppPageMode() === "home";
    }

    function applyAppPageMetadata() {
      const mode = getCurrentAppPageMode();
      if (mode === "wheel") {
        document.title = `Vòng Quay May Mắn | ${APP_SHORT_NAME}`;
        return;
      }
      if (mode === "deposit") {
        document.title = `Nạp tiền tài khoản | ${APP_SHORT_NAME}`;
        return;
      }
      if (mode === "data") {
        document.title = `Bảng Dữ Liệu | ${APP_SHORT_NAME}`;
        return;
      }
      document.title = APP_SHORT_NAME;
    }

    // ----- Cache cục bộ và badge trạng thái -----
    // Quản lý dữ liệu lưu trên trình duyệt như badge cập nhật, cache live và dữ liệu tạm.
    function readJsonLocal(key, fallback) {
      try {
        const raw = localStorage.getItem(key);
        if (!raw) return fallback;
        const parsed = JSON.parse(raw);
        return parsed && typeof parsed === "object" ? parsed : fallback;
      } catch {
        return fallback;
      }
    }

    function writeJsonLocal(key, value) {
      localStorage.setItem(key, JSON.stringify(value));
    }

    function normalizePredictRiskMode(value) {
      const normalized = String(value || "").trim().toLowerCase();
      return PREDICT_RISK_MODES.some(item => item.key === normalized) ? normalized : "balanced";
    }

    function getPredictRiskModeMeta(value) {
      const normalized = normalizePredictRiskMode(value);
      return PREDICT_RISK_MODES.find(item => item.key === normalized) || PREDICT_RISK_MODES[1];
    }

    function readPredictRiskMode() {
      try {
        return normalizePredictRiskMode(localStorage.getItem(PREDICT_RISK_MODE_KEY) || "balanced");
      } catch {
        return "balanced";
      }
    }

    function savePredictRiskMode(value) {
      const normalized = normalizePredictRiskMode(value);
      predictRiskModeValue = normalized;
      try {
        localStorage.setItem(PREDICT_RISK_MODE_KEY, normalized);
      } catch {}
      return normalized;
    }

    predictRiskModeValue = readPredictRiskMode();

    function normalizePredictionMode(value) {
      const normalized = String(value || "").trim().toLowerCase();
      if (normalized === PREDICTION_MODE_VIP) return PREDICTION_MODE_VIP;
      if (normalized === PREDICTION_MODE_STATS) return PREDICTION_MODE_STATS;
      if (normalized === PREDICTION_MODE_STATS_V2) return PREDICTION_MODE_STATS_V2;
      if (normalized === PREDICTION_MODE_CHARTS) return PREDICTION_MODE_CHARTS;
      if (normalized === PREDICTION_MODE_DASHBOARD) return PREDICTION_MODE_DASHBOARD;
      if (normalized === PREDICTION_MODE_ANALYSIS) return PREDICTION_MODE_ANALYSIS;
      return PREDICTION_MODE_NORMAL;
    }

    function readPredictPageMode() {
      try {
        return normalizePredictionMode(localStorage.getItem(PREDICT_UI_MODE_KEY) || PREDICTION_MODE_NORMAL);
      } catch {
        return PREDICTION_MODE_NORMAL;
      }
    }

    function savePredictPageMode(value) {
      const normalized = normalizePredictionMode(value);
      predictPageModeValue = normalized;
      try {
        localStorage.setItem(PREDICT_UI_MODE_KEY, normalized);
      } catch {}
      return normalized;
    }

    function normalizeStatsType(value) {
      const normalized = String(value || "").trim().toUpperCase();
      return TYPE_KEYS.includes(normalized) ? normalized : "KENO";
    }

    function normalizeChartStatsType(value) {
      const normalized = String(value || "").trim().toUpperCase();
      return CHART_STATS_TYPE_OPTIONS.some(item => item.value === normalized) ? normalized : "KENO";
    }

    function getChartStatsDefaultPreset(type) {
      const normalizedType = normalizeChartStatsType(type);
      return normalizedType === "KENO" ? "119" : "100";
    }

    function getChartStatsPresetOptions(type) {
      const normalizedType = normalizeChartStatsType(type);
      return normalizedType === "KENO"
        ? [...CHART_STATS_PRESET_OPTIONS.KENO]
        : [...CHART_STATS_PRESET_OPTIONS.DEFAULT];
    }

    function normalizeChartStatsPreset(value, type) {
      const normalized = String(value || "").trim().toLowerCase();
      const allowed = getChartStatsPresetOptions(type);
      return allowed.includes(normalized) ? normalized : getChartStatsDefaultPreset(type);
    }

    function normalizeChartStatsViewMode(value) {
      const normalized = String(value || "").trim().toLowerCase();
      return CHART_STATS_VIEW_OPTIONS.some(item => item.value === normalized) ? normalized : "all";
    }

    function normalizeChartStatsCustomCount(value) {
      const parsed = Number(String(value || "").trim());
      return Number.isInteger(parsed) && parsed > 0 ? String(parsed) : "";
    }

    function normalizeDashboardActivityView(value) {
      const normalized = String(value || "").trim().toLowerCase();
      return DASHBOARD_ACTIVITY_VIEW_OPTIONS.includes(normalized) ? normalized : "day";
    }

    function normalizeDashboardDistributionView(value) {
      const normalized = String(value || "").trim().toLowerCase();
      return DASHBOARD_DISTRIBUTION_VIEW_OPTIONS.includes(normalized) ? normalized : "range";
    }

    function normalizeDashboardGame(value) {
      const normalized = String(value || "").trim().toUpperCase();
      return DASHBOARD_LOTTO_TYPES.includes(normalized) ? normalized : "KENO";
    }

    function getDashboardDistributionOptions(type) {
      const normalizedType = normalizeDashboardGame(type);
      if (normalizedType === "MAX_3D" || normalizedType === "MAX_3D_PRO") {
        return [
          { value: "head", label: "Theo Đầu Số" },
          { value: "tail", label: "Theo Đuôi Số" },
          { value: "temperature", label: "Theo Mức Nhiệt" },
        ];
      }
      if (normalizedType === "KENO") {
        return [
          { value: "range", label: "Theo Dải 10 Số" },
          { value: "parity", label: "Theo Chẵn / Lẻ" },
          { value: "temperature", label: "Theo Mức Nhiệt" },
        ];
      }
      return [
        { value: "range", label: "Theo Dải Số" },
        { value: "parity", label: "Theo Chẵn / Lẻ" },
        { value: "temperature", label: "Theo Mức Nhiệt" },
      ];
    }

    function readDashboardUiState() {
      try {
        dashboardSelectedGame = normalizeDashboardGame(localStorage.getItem(DASHBOARD_SELECTED_GAME_KEY) || "KENO");
        dashboardActivityViewMode = normalizeDashboardActivityView(localStorage.getItem(DASHBOARD_ACTIVITY_VIEW_KEY) || "day");
        dashboardDistributionViewMode = normalizeDashboardDistributionView(localStorage.getItem(DASHBOARD_DISTRIBUTION_VIEW_KEY) || getDashboardDistributionOptions(dashboardSelectedGame)[0]?.value || "range");
      } catch {}
      const allowed = getDashboardDistributionOptions(dashboardSelectedGame).map(item => item.value);
      if (!allowed.includes(dashboardDistributionViewMode)) {
        dashboardDistributionViewMode = allowed[0] || "range";
      }
    }

    function saveDashboardUiState() {
      try {
        localStorage.setItem(DASHBOARD_SELECTED_GAME_KEY, normalizeDashboardGame(dashboardSelectedGame));
        localStorage.setItem(DASHBOARD_ACTIVITY_VIEW_KEY, normalizeDashboardActivityView(dashboardActivityViewMode));
        localStorage.setItem(DASHBOARD_DISTRIBUTION_VIEW_KEY, normalizeDashboardDistributionView(dashboardDistributionViewMode));
      } catch {}
    }

    function normalizeStatsDayWindow(value) {
      const normalized = String(value || "").trim().toLowerCase();
      return STATS_DAY_WINDOWS.includes(normalized) ? normalized : "30";
    }

    function normalizeStatsRecentDisplayMode(value) {
      return String(value || "").trim().toLowerCase() === "count" ? "count" : "order";
    }

    function readStatsUiState() {
      try {
        statsSelectedType = normalizeStatsType(localStorage.getItem(STATS_SELECTED_TYPE_KEY) || "KENO");
        statsSelectedDayWindow = normalizeStatsDayWindow(localStorage.getItem(STATS_SELECTED_DAY_WINDOW_KEY) || "30");
        statsDateFrom = String(localStorage.getItem(STATS_DATE_FROM_KEY) || "").trim();
        statsDateTo = String(localStorage.getItem(STATS_DATE_TO_KEY) || "").trim();
        statsRecentDisplayModeValue = normalizeStatsRecentDisplayMode(localStorage.getItem(STATS_RECENT_DISPLAY_MODE_KEY) || statsRecentDisplayModeValue);
        statsRecentKenoLevelValue = normalizeStatsRecentKenoLevel(localStorage.getItem(STATS_RECENT_KENO_LEVEL_KEY) || statsRecentKenoLevelValue);
      } catch {}
    }

    function saveStatsUiState() {
      try {
        localStorage.setItem(STATS_SELECTED_TYPE_KEY, normalizeStatsType(statsSelectedType));
        localStorage.setItem(STATS_SELECTED_DAY_WINDOW_KEY, normalizeStatsDayWindow(statsSelectedDayWindow));
        localStorage.setItem(STATS_DATE_FROM_KEY, String(statsDateFrom || "").trim());
        localStorage.setItem(STATS_DATE_TO_KEY, String(statsDateTo || "").trim());
        localStorage.setItem(STATS_RECENT_DISPLAY_MODE_KEY, normalizeStatsRecentDisplayMode(statsRecentDisplayModeValue));
        localStorage.setItem(STATS_RECENT_KENO_LEVEL_KEY, String(normalizeStatsRecentKenoLevel(statsRecentKenoLevelValue)));
      } catch {}
    }

    function readStatsRecentSelectedState() {
      try {
        const saved = readJsonLocal(STATS_RECENT_SELECTED_SETS_KEY, {});
        const selectedByType = saved?.selectedByType && typeof saved.selectedByType === "object"
          ? saved.selectedByType
          : saved;
        statsRecentSelectedByType = selectedByType && typeof selectedByType === "object"
          ? selectedByType
          : Object.create(null);
        statsRecentActiveSetByType = saved?.activeSetByType && typeof saved.activeSetByType === "object"
          ? saved.activeSetByType
          : Object.create(null);
      } catch {
        statsRecentSelectedByType = Object.create(null);
        statsRecentActiveSetByType = Object.create(null);
      }
    }

    function saveStatsRecentSelectedState() {
      try {
        writeJsonLocal(STATS_RECENT_SELECTED_SETS_KEY, {
          version: 1,
          updatedAt: getSyncedIsoString(),
          selectedByType: statsRecentSelectedByType && typeof statsRecentSelectedByType === "object"
            ? statsRecentSelectedByType
            : {},
          activeSetByType: statsRecentActiveSetByType && typeof statsRecentActiveSetByType === "object"
            ? statsRecentActiveSetByType
            : {},
        });
        return true;
      } catch {
        return false;
      }
    }

    function ensureChartStatsPresetForType() {
      chartStatsSelectedType = normalizeChartStatsType(chartStatsSelectedType);
      chartStatsSelectedPreset = normalizeChartStatsPreset(chartStatsSelectedPreset, chartStatsSelectedType);
      if (chartStatsSelectedPreset !== "custom") {
        chartStatsCustomCountValue = "";
      } else {
        chartStatsCustomCountValue = normalizeChartStatsCustomCount(chartStatsCustomCountValue);
      }
      chartStatsViewMode = normalizeChartStatsViewMode(chartStatsViewMode);
    }

    function readChartStatsUiState() {
      try {
        chartStatsSelectedType = normalizeChartStatsType(localStorage.getItem(CHART_STATS_SELECTED_TYPE_KEY) || "KENO");
        chartStatsSelectedPreset = normalizeChartStatsPreset(localStorage.getItem(CHART_STATS_SELECTED_PRESET_KEY) || getChartStatsDefaultPreset(chartStatsSelectedType), chartStatsSelectedType);
        chartStatsCustomCountValue = normalizeChartStatsCustomCount(localStorage.getItem(CHART_STATS_CUSTOM_COUNT_KEY) || "");
        chartStatsViewMode = normalizeChartStatsViewMode(localStorage.getItem(CHART_STATS_VIEW_MODE_KEY) || "all");
      } catch {}
      ensureChartStatsPresetForType();
    }

    function saveChartStatsUiState() {
      ensureChartStatsPresetForType();
      try {
        localStorage.setItem(CHART_STATS_SELECTED_TYPE_KEY, chartStatsSelectedType);
        localStorage.setItem(CHART_STATS_SELECTED_PRESET_KEY, chartStatsSelectedPreset);
        localStorage.setItem(CHART_STATS_CUSTOM_COUNT_KEY, String(chartStatsCustomCountValue || "").trim());
        localStorage.setItem(CHART_STATS_VIEW_MODE_KEY, chartStatsViewMode);
      } catch {}
    }

    function readVipPredictState() {
      try {
        const nextType = String(localStorage.getItem(VIP_PREDICT_TYPE_KEY) || "KENO").trim().toUpperCase();
        const nextPlayMode = String(localStorage.getItem(VIP_PREDICT_PLAY_MODE_KEY) || "normal").trim().toLowerCase() === "bao" ? "bao" : "normal";
        const nextEngine = String(localStorage.getItem(VIP_PREDICT_ENGINE_KEY) || "both").trim().toLowerCase();
        const nextRiskMode = normalizePredictRiskMode(localStorage.getItem(VIP_PREDICT_RISK_MODE_KEY) || "balanced");
        const nextCount = Number(localStorage.getItem(VIP_PREDICT_COUNT_KEY) || 1);
        const nextKenoLevel = Number(localStorage.getItem(VIP_PREDICT_KENO_LEVEL_KEY) || 5);
        vipPredictTypeValue = TYPE_KEYS.includes(nextType) ? nextType : "KENO";
        vipPredictPlayModeValue = nextPlayMode;
        vipPredictBaoLevelValue = String(localStorage.getItem(VIP_PREDICT_BAO_LEVEL_KEY) || "").trim();
        vipPredictEngineValue = ["both", "luan_so", "gen_local"].includes(nextEngine) ? nextEngine : "both";
        vipPredictRiskModeValue = nextRiskMode;
        vipPredictCountValue = Number.isInteger(nextCount) && nextCount > 0 ? Math.min(VIP_PREDICT_MAX_BUNDLES, nextCount) : 1;
        vipPredictKenoLevelValue = Number.isInteger(nextKenoLevel) && nextKenoLevel >= 1 && nextKenoLevel <= 10 ? nextKenoLevel : 5;
      } catch {}
    }

    function saveVipPredictState() {
      try {
        localStorage.setItem(VIP_PREDICT_TYPE_KEY, vipPredictTypeValue);
        localStorage.setItem(VIP_PREDICT_PLAY_MODE_KEY, vipPredictPlayModeValue);
        localStorage.setItem(VIP_PREDICT_BAO_LEVEL_KEY, vipPredictBaoLevelValue);
        localStorage.setItem(VIP_PREDICT_ENGINE_KEY, vipPredictEngineValue);
        localStorage.setItem(VIP_PREDICT_RISK_MODE_KEY, vipPredictRiskModeValue);
        localStorage.setItem(VIP_PREDICT_COUNT_KEY, String(vipPredictCountValue));
        localStorage.setItem(VIP_PREDICT_KENO_LEVEL_KEY, String(vipPredictKenoLevelValue));
      } catch {}
    }

    predictPageModeValue = readPredictPageMode();
    readVipPredictState();
    readStatsUiState();
    readStatsRecentSelectedState();
    readChartStatsUiState();
    readDashboardUiState();

    function normalizeKenoTrainingConfig(raw) {
      const base = {
        enabled: false,
        type: "KENO",
        count: 3,
        engine: "both",
        kenoLevel: 5,
        lastTriggeredKy: "",
        lastResolvedKy: "",
      };
      if (!raw || typeof raw !== "object") return base;
      const count = Number(raw.count);
      const kenoLevel = Number(raw.kenoLevel);
      const engineKey = String(raw.engine || base.engine).trim().toLowerCase();
      base.enabled = Boolean(raw.enabled);
      base.type = "KENO";
      base.count = Number.isInteger(count) && count > 0 ? count : base.count;
      base.engine = ["both", "luan_so", "gen_local"].includes(engineKey) ? engineKey : base.engine;
      base.kenoLevel = Number.isInteger(kenoLevel) && kenoLevel >= 1 && kenoLevel <= 10 ? kenoLevel : base.kenoLevel;
      base.lastTriggeredKy = String(raw.lastTriggeredKy || "").trim();
      base.lastResolvedKy = String(raw.lastResolvedKy || "").trim();
      return base;
    }

    function readKenoTrainingConfig() {
      return normalizeKenoTrainingConfig(readJsonLocal(KENO_TRAINING_CONFIG_KEY, {}));
    }

    function saveKenoTrainingConfig(patch = {}) {
      const next = normalizeKenoTrainingConfig({
        ...readKenoTrainingConfig(),
        ...(patch && typeof patch === "object" ? patch : {}),
      });
      writeJsonLocal(KENO_TRAINING_CONFIG_KEY, next);
      kenoTrainingEnabled = next.enabled;
      kenoTrainingLastTriggeredKy = next.lastTriggeredKy;
      kenoTrainingLastResolvedKy = next.lastResolvedKy;
      return next;
    }

    function syncKenoTrainingConfigFromUi() {
      const pdType = String(document.getElementById("pdType")?.value || "").trim().toUpperCase();
      const current = readKenoTrainingConfig();
      if (pdType !== "KENO") return current;
      const count = Number(document.getElementById("pdCount")?.value || current.count || 3);
      const kenoLevel = Number(document.getElementById("pdKenoLevel")?.value || current.kenoLevel || 5);
      const engine = String(predictEngineValue || document.getElementById("pdEngine")?.value || current.engine || "both").trim().toLowerCase() || "both";
      return saveKenoTrainingConfig({
        count: Number.isInteger(count) && count > 0 ? count : current.count,
        kenoLevel: Number.isInteger(kenoLevel) && kenoLevel >= 1 && kenoLevel <= 10 ? kenoLevel : current.kenoLevel,
        engine,
      });
    }

    function defaultLiveUpdateBadge(typeKey) {
      return {
        type: String(typeKey || "").toUpperCase(),
        code: "pending",
        label: "Chờ cập nhật",
        message: "",
        updatedAt: "",
      };
    }

    function normalizeLiveUpdateBadgeEntry(typeKey, raw) {
      const base = defaultLiveUpdateBadge(typeKey);
      if (!raw || typeof raw !== "object") return base;
      const code = String(raw.code || base.code).trim().toLowerCase();
      const allowedCodes = new Set(["pending", "running", "success", "retry", "failure", "outside_hours"]);
      base.code = allowedCodes.has(code) ? code : base.code;
      base.label = String(raw.label || base.label).trim() || base.label;
      base.message = String(raw.message || "").trim();
      base.updatedAt = String(raw.updatedAt || "").trim();
      return base;
    }

    function normalizeLiveUpdateBadgeState(raw) {
      const normalized = {};
      LIVE_RESULT_TYPES.forEach(meta => {
        normalized[meta.key] = normalizeLiveUpdateBadgeEntry(meta.key, raw?.[meta.key]);
      });
      return normalized;
    }

    function readLiveUpdateBadgeCache() {
      return normalizeLiveUpdateBadgeState(readJsonLocal(LIVE_UPDATE_BADGE_CACHE_KEY, {}));
    }

    function saveLiveUpdateBadgeCache() {
      writeJsonLocal(LIVE_UPDATE_BADGE_CACHE_KEY, normalizeLiveUpdateBadgeState(liveUpdateBadgeState));
    }

    function restoreLiveUpdateBadgeCache() {
      liveUpdateBadgeState = readLiveUpdateBadgeCache();
    }

    function liveUpdateBadgeClass(code) {
      switch (String(code || "").trim().toLowerCase()) {
        case "success": return "ok";
        case "retry": return "retry";
        case "failure": return "failure";
        case "outside_hours": return "outside-hours";
        case "running": return "running";
        default: return "pending";
      }
    }

    function getLiveUpdateBadge(typeKey) {
      const key = String(typeKey || "").trim().toUpperCase();
      return normalizeLiveUpdateBadgeEntry(key, liveUpdateBadgeState?.[key]);
    }

    function setLiveUpdateBadge(typeKey, nextValue, { render = true } = {}) {
      const key = String(typeKey || "").trim().toUpperCase();
      if (!key) return false;
      const next = normalizeLiveUpdateBadgeEntry(key, nextValue);
      const prev = normalizeLiveUpdateBadgeEntry(key, liveUpdateBadgeState?.[key]);
      if (JSON.stringify(prev) === JSON.stringify(next)) return false;
      liveUpdateBadgeState = {
        ...(liveUpdateBadgeState && typeof liveUpdateBadgeState === "object" ? liveUpdateBadgeState : {}),
        [key]: next,
      };
      saveLiveUpdateBadgeCache();
      if (render) renderLiveResultsBoard();
      return true;
    }

    function resetLiveUpdateBadgesForManualRun({ render = true } = {}) {
      const updatedAt = getSyncedIsoString();
      const nextState = {};
      LIVE_RESULT_TYPES.forEach(meta => {
        nextState[meta.key] = {
          type: meta.key,
          code: "pending",
          label: "Chờ cập nhật",
          message: "",
          updatedAt,
        };
      });
      liveUpdateBadgeState = nextState;
      saveLiveUpdateBadgeCache();
      if (render) renderLiveResultsBoard();
    }

    function isWithinKenoBadgeWindow(now = getSyncedNowDate()) {
      const minutes = now.getHours() * 60 + now.getMinutes();
      return minutes >= 360 && minutes <= 1320;
    }

    function buildManualLiveUpdateBadge(typeKey, { hasError = false, errorMessage = "", label = "" } = {}) {
      const key = String(typeKey || "").trim().toUpperCase();
      if (!hasError) {
        return {
          type: key,
          code: "success",
          label: key === "KENO" ? "Hoàn Tất" : "Hoàn tất",
          message: "",
          updatedAt: getSyncedIsoString(),
        };
      }
      if (key === "KENO") {
        if (isWithinKenoBadgeWindow()) {
          return {
            type: key,
            code: "failure",
            label: "Thất Bại",
            message: errorMessage,
            updatedAt: getSyncedIsoString(),
          };
        }
        return {
          type: key,
          code: "outside_hours",
          label: "Thử Lại Trong Khung Giờ 6:00 - 22:00",
          message: errorMessage,
          updatedAt: getSyncedIsoString(),
        };
      }
      return {
        type: key,
        code: "retry",
        label: label || "Thử Lại",
        message: errorMessage,
        updatedAt: getSyncedIsoString(),
      };
    }

    function applyLiveUpdateBadgeFromProgressState(typeKey, state, { render = false } = {}) {
      const key = String(typeKey || "").trim().toUpperCase();
      if (!key || !LIVE_RESULT_TYPES.some(meta => meta.key === key)) return false;
      const progressState = state && typeof state === "object" ? state : {};
      const liveState = String(progressState.state || "").trim().toLowerCase();
      let nextBadge = null;
      if (String(progressState.resultCode || "").trim()) {
        nextBadge = {
          type: key,
          code: String(progressState.resultCode || "").trim().toLowerCase(),
          label: String(progressState.resultLabel || "").trim() || defaultLiveUpdateBadge(key).label,
          message: String(progressState.resultMessage || progressState.error || "").trim(),
          updatedAt: String(progressState.updatedAt || "").trim() || getSyncedIsoString(),
        };
      } else if (liveState === "done") {
        nextBadge = buildManualLiveUpdateBadge(key, { hasError: false });
      } else if (liveState === "error") {
        nextBadge = buildManualLiveUpdateBadge(key, {
          hasError: true,
          errorMessage: String(progressState.error || "").trim(),
        });
      } else if (liveState === "running") {
        nextBadge = {
          type: key,
          code: "running",
          label: "Đang cập nhật",
          message: "",
          updatedAt: String(progressState.updatedAt || "").trim() || getSyncedIsoString(),
        };
      } else if (liveState === "pending") {
        nextBadge = {
          type: key,
          code: "pending",
          label: "Chờ cập nhật",
          message: "",
          updatedAt: String(progressState.updatedAt || "").trim() || getSyncedIsoString(),
        };
      }
      if (!nextBadge) return false;
      return setLiveUpdateBadge(key, nextBadge, { render });
    }

    function applyManualLiveUpdateBadgesFromApiResponse(res, { render = true } = {}) {
      const outputs = Array.isArray(res?.canonicalBackfill?.outputs) ? res.canonicalBackfill.outputs : [];
      const liveResults = Array.isArray(res?.results) ? res.results : [];
      const directErrors = Array.isArray(res?.errors) ? res.errors : [];
      const backfillErrors = Array.isArray(res?.canonicalBackfill?.errors) ? res.canonicalBackfill.errors : [];
      const errorMap = new Map();
      const resultMap = new Map();
      liveResults.forEach(item => {
        const key = String(item?.key || item?.type || "").trim().toUpperCase();
        if (!key) return;
        const hasContent =
          (Array.isArray(item?.displayLines) && item.displayLines.some(line => String(line || "").trim())) ||
          (Array.isArray(item?.numbers) && item.numbers.length > 0) ||
          (Array.isArray(item?.main) && item.main.length > 0);
        if (hasContent) resultMap.set(key, item);
      });
      [...directErrors, ...backfillErrors].forEach(err => {
        const key = String(err?.type || err?.key || "").trim().toUpperCase();
        if (!key) return;
        const current = errorMap.get(key) || [];
        current.push(String(err?.message || "").trim());
        errorMap.set(key, current);
      });
      let changed = false;
      LIVE_RESULT_TYPES.forEach(meta => {
        const messages = errorMap.get(meta.key) || [];
        const hasLiveResult = resultMap.has(meta.key);
        const nextBadge = hasLiveResult
          ? {
              ...buildManualLiveUpdateBadge(meta.key, { hasError: false }),
              message: messages.join(" | "),
            }
          : buildManualLiveUpdateBadge(meta.key, {
              hasError: messages.length > 0,
              errorMessage: messages.join(" | "),
            });
        changed = setLiveUpdateBadge(meta.key, nextBadge, { render: false }) || changed;
      });
      outputs.forEach(output => {
        const key = String(output?.type || "").trim().toUpperCase();
        if (!key || errorMap.has(key)) return;
        changed = setLiveUpdateBadge(key, buildManualLiveUpdateBadge(key), { render: false }) || changed;
      });
      if (changed && render) renderLiveResultsBoard();
      return changed;
    }

    function markAllLiveUpdateBadgesFailed(message, { render = true } = {}) {
      let changed = false;
      LIVE_RESULT_TYPES.forEach(meta => {
        changed = setLiveUpdateBadge(
          meta.key,
          buildManualLiveUpdateBadge(meta.key, {
            hasError: true,
            errorMessage: String(message || "").trim(),
          }),
          { render: false }
        ) || changed;
      });
      if (changed && render) renderLiveResultsBoard();
      return changed;
    }

    function clearLegacyLiveHistoryCache() {
      try {
        localStorage.removeItem(LIVE_HISTORY_CACHE_KEY);
      } catch {}
    }

    function localUsers() {
      const users = readJsonLocal(LOCAL_USERS_KEY, {});
      if (!users.admin) {
        users.admin = { password: "admin", role: "admin", enabled: true };
        writeJsonLocal(LOCAL_USERS_KEY, users);
      }
      return users;
    }

    function saveLocalUsers(users) {
      writeJsonLocal(LOCAL_USERS_KEY, users || {});
    }

    function localStores() {
      return readJsonLocal(LOCAL_STORES_KEY, {});
    }

    function saveLocalStores(storesObj) {
      writeJsonLocal(LOCAL_STORES_KEY, storesObj || {});
    }

    function getLocalSessionUser() {
      return normalizeUser(localStorage.getItem(LOCAL_SESSION_KEY) || "");
    }

    function setLocalSessionUser(user) {
      if (!user) localStorage.removeItem(LOCAL_SESSION_KEY);
      else localStorage.setItem(LOCAL_SESSION_KEY, normalizeUser(user));
    }

    function getLocalStoreForUser(user) {
      const storesObj = localStores();
      const parsed = storesObj[user];
      const base = emptyStore();
      if (!parsed || typeof parsed !== "object") return base;
      base.diamondBalance = Math.max(0, Number(parsed.diamondBalance || 0));
      base.paypalBalance = Math.max(0, Number(parsed.paypalBalance || 0));
      for (const t of TYPE_KEYS) {
        base.results[t] = parsed.results?.[t] || {};
        base.picks[t] = parsed.picks?.[t] || {};
        base.resultOrder[t] = parsed.resultOrder?.[t] || Object.keys(base.results[t]);
        base.pickOrder[t] = parsed.pickOrder?.[t] || Object.keys(base.picks[t]);
      }
      for (const t of PREDICTION_LOG_TYPES) {
        base.predictionLogs[t] = Array.isArray(parsed.predictionLogs?.[t]) ? parsed.predictionLogs[t] : [];
      }
      base.statsV2Favorites = Array.isArray(parsed.statsV2Favorites) ? parsed.statsV2Favorites : [];
      base.statsV2History = Array.isArray(parsed.statsV2History) ? parsed.statsV2History : [];
      base.analysisHistory = Array.isArray(parsed.analysisHistory) ? parsed.analysisHistory : [];
      base.paypalTopups = Array.isArray(parsed.paypalTopups) ? parsed.paypalTopups : [];
      base.luckyWheelHistory = Array.isArray(parsed.luckyWheelHistory) ? parsed.luckyWheelHistory : [];
      base.luckyWheelTopupHistory = Array.isArray(parsed.luckyWheelTopupHistory) ? parsed.luckyWheelTopupHistory : [];
      base.luckyWheelSpinCount = Math.max(0, Number(parsed.luckyWheelSpinCount || 0));
      base.luckyWheelDailySpinCount = Math.max(0, Number(parsed.luckyWheelDailySpinCount || 0));
      base.luckyWheelDailyExchangeSpins = Math.max(0, Number(parsed.luckyWheelDailyExchangeSpins || 0));
      base.luckyWheelExchangeDayKey = String(parsed.luckyWheelExchangeDayKey || "");
      base.luckyWheelMilestoneDayKey = String(parsed.luckyWheelMilestoneDayKey || "");
      base.luckyWheelStoredSpins = Number.isFinite(Number(parsed.luckyWheelStoredSpins))
        ? Math.max(0, Math.min(LUCKY_WHEEL_MAX_SPINS, Math.floor(Number(parsed.luckyWheelStoredSpins))))
        : base.luckyWheelStoredSpins;
      base.luckyWheelLastRegenAt = String(parsed.luckyWheelLastRegenAt || "");
      base.luckyWheelBonusSpins = Math.max(0, Number(parsed.luckyWheelBonusSpins || 0));
      base.luckyWheelLastSpinDay = String(parsed.luckyWheelLastSpinDay || "");
      base.luckyWheelLastResult = parsed.luckyWheelLastResult && typeof parsed.luckyWheelLastResult === "object"
        ? parsed.luckyWheelLastResult
        : null;
      return base;
    }

    function setLocalStoreForUser(user, storeObj) {
      const storesObj = localStores();
      storesObj[user] = storeObj || emptyStore();
      saveLocalStores(storesObj);
    }

    function localHasData(user) {
      const s = getLocalStoreForUser(user);
      if ((s.diamondBalance || 0) > 0 || (s.paypalBalance || 0) > 0) return true;
      return TYPE_KEYS.some(t =>
        (s.resultOrder?.[t] || []).length > 0 || (s.pickOrder?.[t] || []).length > 0
      );
    }

    function localApi(path, method = "GET", data = null) {
      const m = String(method || "GET").toUpperCase();
      const users = localUsers();
      const sessionUser = getLocalSessionUser();
      const me = sessionUser && users[sessionUser] && users[sessionUser].enabled
        ? { username: sessionUser, role: users[sessionUser].role || "user" }
        : null;

      const requireAuth = () => {
        if (!me) throw new Error("Chưa đăng nhập");
        return me;
      };
      const requireAdmin = () => {
        const cur = requireAuth();
        if (cur.role !== "admin") throw new Error("Yêu cầu quyền admin");
        return cur;
      };

      if (path === "/api/me" && m === "GET") {
        return me ? { ok: true, username: me.username, role: me.role } : { ok: false };
      }

      if (path === "/api/register" && m === "POST") {
        const user = normalizeUser(data?.username);
        const pass = String(data?.password || "").trim();
        if (user.length < 3) throw new Error("Tên đăng nhập tối thiểu 3 ký tự");
        if (pass.length < 4) throw new Error("Mật khẩu tối thiểu 4 ký tự");
        if (users[user]) throw new Error("Tên đăng nhập đã tồn tại");
        const isFirst = Object.keys(users).length === 0;
        users[user] = { password: pass, role: isFirst ? "admin" : "user", enabled: true };
        saveLocalUsers(users);
        return { ok: true };
      }

      if (path === "/api/login" && m === "POST") {
        const user = normalizeUser(data?.username);
        const pass = String(data?.password || "").trim();
        const acc = users[user];
        if (!acc || !acc.enabled || String(acc.password || "") !== pass) {
          throw new Error("Sai tài khoản hoặc mật khẩu");
        }
        setLocalSessionUser(user);
        return { ok: true, username: user, role: acc.role || "user" };
      }

      if (path === "/api/logout" && m === "POST") {
        setLocalSessionUser("");
        return { ok: true };
      }

      if (path === "/api/store" && m === "GET") {
        const cur = requireAuth();
        return { ok: true, store: getLocalStoreForUser(cur.username) };
      }

      if (path === "/api/store" && m === "POST") {
        const cur = requireAuth();
        let parsed = {};
        try {
          parsed = JSON.parse(String(data?.store || "{}"));
        } catch {
          parsed = {};
        }
        setLocalStoreForUser(cur.username, parsed);
        return { ok: true };
      }

      if (path.startsWith("/api/stats-v2") && m === "GET") {
        requireAuth();
        throw new Error("Thống Kê V2 cần chạy qua http://localhost:8080 để server đọc canonical CSV.");
      }

      if (path === "/api/recover-admin" && m === "POST") {
        const pass = String(data?.password || "").trim();
        if (pass.length < 4) throw new Error("Mật khẩu tối thiểu 4 ký tự");
        let adminUser = Object.keys(users).find(u => users[u]?.role === "admin");
        if (!adminUser) adminUser = Object.keys(users)[0];
        if (!adminUser) {
          users.admin = { password: pass, role: "admin", enabled: true };
          saveLocalUsers(users);
          return { ok: true, username: "admin" };
        }
        users[adminUser].password = pass;
        users[adminUser].role = "admin";
        users[adminUser].enabled = true;
        saveLocalUsers(users);
        return { ok: true, username: adminUser };
      }

      if (path === "/api/admin/users" && m === "GET") {
        requireAdmin();
        const list = Object.keys(users).sort().map(u => ({
          username: u,
          role: users[u].role || "user",
          enabled: !!users[u].enabled,
          hasData: localHasData(u),
          diamondBalance: Number(getLocalStoreForUser(u).diamondBalance || 0),
          paypalBalance: Number(getLocalStoreForUser(u).paypalBalance || 0)
        }));
        return { ok: true, users: list };
      }

      if (path === "/api/admin/update-user" && m === "POST") {
        const cur = requireAdmin();
        const user = normalizeUser(data?.username);
        const role = String(data?.role || "user") === "admin" ? "admin" : "user";
        const enabled = String(data?.enabled) === "true" || String(data?.enabled) === "1";
        const acc = users[user];
        if (!acc) throw new Error("Không tìm thấy tài khoản");
        if (user === cur.username && !enabled) throw new Error("Không thể khóa tài khoản đang đăng nhập");
        const adminUsers = Object.keys(users).filter(u => users[u]?.role === "admin");
        if (acc.role === "admin" && role !== "admin" && adminUsers.length <= 1) throw new Error("Phải luôn có ít nhất 1 admin");
        if (acc.role === "admin" && !enabled && adminUsers.length <= 1) throw new Error("Không thể khóa admin cuối cùng");
        acc.role = role;
        acc.enabled = enabled;
        saveLocalUsers(users);
        return { ok: true };
      }

      if (path === "/api/admin/update-assets" && (m === "POST" || m === "GET")) {
        requireAdmin();
        const user = normalizeUser(data?.username);
        if (!users[user]) throw new Error("Không tìm thấy tài khoản");
        const s = getLocalStoreForUser(user);
        s.diamondBalance = Math.max(0, Number(data?.diamond || 0));
        s.paypalBalance = Math.max(0, Number(data?.paypal || 0));
        setLocalStoreForUser(user, s);
        return { ok: true };
      }

      if (path === "/api/admin/rename-user" && m === "POST") {
        const cur = requireAdmin();
        const user = normalizeUser(data?.username);
        const newUser = normalizeUser(data?.newUsername);
        if (newUser.length < 3) throw new Error("Tên mới tối thiểu 3 ký tự");
        if (!users[user]) throw new Error("Không tìm thấy tài khoản");
        if (users[newUser]) throw new Error("Tên tài khoản mới đã tồn tại");
        if (user === cur.username) throw new Error("Không đổi tên tài khoản đang đăng nhập trong phiên hiện tại.");
        const old = users[user];
        delete users[user];
        users[newUser] = old;
        const storesObj = localStores();
        if (storesObj[user]) {
          storesObj[newUser] = storesObj[user];
          delete storesObj[user];
          saveLocalStores(storesObj);
        }
        saveLocalUsers(users);
        return { ok: true };
      }

      if (path === "/api/admin/reset-password" && m === "POST") {
        requireAdmin();
        const user = normalizeUser(data?.username);
        const newPass = String(data?.newPassword || "").trim();
        if (newPass.length < 4) throw new Error("Mật khẩu tối thiểu 4 ký tự");
        if (!users[user]) throw new Error("Không tìm thấy tài khoản");
        users[user].password = newPass;
        saveLocalUsers(users);
        return { ok: true };
      }

      if (path === "/api/admin/delete-user" && m === "POST") {
        const cur = requireAdmin();
        const user = normalizeUser(data?.username);
        if (user === cur.username) throw new Error("Không thể xóa tài khoản đang đăng nhập");
        const acc = users[user];
        if (!acc) throw new Error("Không tìm thấy tài khoản");
        const adminUsers = Object.keys(users).filter(u => users[u]?.role === "admin");
        if (acc.role === "admin" && adminUsers.length <= 1) throw new Error("Không thể xóa admin cuối cùng");
        delete users[user];
        saveLocalUsers(users);
        const storesObj = localStores();
        delete storesObj[user];
        saveLocalStores(storesObj);
        return { ok: true };
      }

      throw new Error("Local Mode chưa hỗ trợ API này");
    }

    // ----- Gọi API và lưu store -----
    // Chứa lớp fetch tới Java server và đồng bộ dữ liệu người dùng vào store local/server.
    async function api(path, method = "GET", data = null) {
      if (IS_LOCAL_MODE) {
        return localApi(path, method, data);
      }
      const opts = { method, credentials: "include" };
      if (data) {
        const body = new URLSearchParams();
        Object.entries(data).forEach(([k, v]) => body.set(k, String(v)));
        opts.headers = { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" };
        opts.body = body.toString();
      }
      let res;
      try {
        res = await fetch(path, opts);
      } catch (err) {
        const msg = String(err?.message || "");
        if (msg.includes("Failed to fetch")) {
          throw new Error("Mat ket noi toi web server localhost:8080. Hay chay lai .\\chay_lotto_web.bat va giu cua so server mo.");
        }
        throw err;
      }
      const responseReceivedAtMs = Date.now();
      syncServerTimeFromHeaders(res.headers, responseReceivedAtMs);
      const text = await res.text();
      let payload = {};
      try {
        payload = JSON.parse(text || "{}");
      } catch {
        payload = { ok: false, message: text || "Lỗi phản hồi từ máy chủ." };
      }
      if (!res.ok || payload.ok === false) {
        const error = new Error(payload.message || `Lỗi ${res.status}`);
        error.status = res.status;
        error.payload = payload;
        throw error;
      }
      return payload;
    }

    function loadRememberedCreds() {
      try {
        const raw = localStorage.getItem(REMEMBER_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== "object") return null;
        const user = normalizeUser(parsed.user || "");
        const pass = String(parsed.pass || "");
        if (!user || !pass) return null;
        return { user, pass };
      } catch {
        return null;
      }
    }

    function saveRememberedCreds(user, pass) {
      localStorage.setItem(REMEMBER_KEY, JSON.stringify({ user, pass }));
    }

    function clearRememberedCreds() {
      localStorage.removeItem(REMEMBER_KEY);
    }

    // ---abc--- Lightweight Signatures / Anti-Lag Helpers ---
    function getPredictionLogEntrySignature(entry) {
      if (!entry || typeof entry !== "object") return "";
      const summary = entry.resultSummary && typeof entry.resultSummary === "object" ? entry.resultSummary : {};
      const actual = entry.actualDraw && typeof entry.actualDraw === "object" ? entry.actualDraw : {};
      const main = Array.isArray(actual.main) ? actual.main.join(",") : "";
      const special = actual.special == null ? "" : String(actual.special);
      return [
        String(entry.id || ""),
        String(entry.type || ""),
        String(entry.predictedKy || ""),
        entry.resolved ? "1" : "0",
        entry.resultMissingData ? "1" : "0",
        String(entry.resultMissingReason || ""),
        String(entry.resultStatus || ""),
        String(summary.prizeTicketHits || 0),
        String(summary.bestMainHits || 0),
        String(summary.totalPrizeAmount || 0),
        String(summary.losingTicketCount || 0),
        JSON.stringify(summary.prizeBreakdown || []),
        main,
        special
      ].join("|");
    }

    function getPredictionLogsSignature(collection) {
      if (Array.isArray(collection)) {
        return collection.map(getPredictionLogEntrySignature).join("||");
      }
      if (!collection || typeof collection !== "object") return "";
      return Object.keys(collection).sort().map(key => `${key}:${getPredictionLogsSignature(collection[key])}`).join("###");
    }

    function getLiveResultSignature(item) {
      if (!item || typeof item !== "object") return "";
      return [
        String(item.key || ""),
        String(item.ky || ""),
        String(item.date || ""),
        String(item.time || ""),
        Array.isArray(item.numbers) ? item.numbers.join(",") : "",
        String(item.special ?? ""),
        String(item.updatedAt || "")
      ].join("|");
    }

    function applyTheme(theme) {
      const isLight = theme === "light";
      document.body.classList.toggle("light-theme", isLight);
      document.documentElement.style.colorScheme = isLight ? "light" : "dark";
      const btn = document.getElementById("themeToggleBtn");
      if (btn) {
        btn.textContent = isLight ? "☀️" : "🌙";
        btn.title = isLight ? "Đang sáng, bấm để chuyển tối" : "Đang tối, bấm để chuyển sáng";
        btn.setAttribute("aria-label", btn.title);
        btn.setAttribute("aria-pressed", isLight ? "true" : "false");
      }
      localStorage.setItem(THEME_KEY, isLight ? "light" : "dark");
    }

    function syncSideAccountIdentity() {
      const identity = document.getElementById("whoami");
      const accountManagerButton = document.getElementById("openAccountBtn");
      if (identity) {
        const roleLabel = currentUserRole === "admin" ? "Quản trị viên" : "Người dùng";
        identity.textContent = currentUser ? `${currentUser} · ${roleLabel}` : "Chưa đăng nhập";
      }
      if (accountManagerButton) {
        accountManagerButton.style.display = currentUserRole === "admin" ? "flex" : "none";
      }
    }

    function getHeaderNotificationStorageKey(baseKey = HEADER_NOTIFICATION_READ_KEY) {
      const userKey = String(currentUser || "guest").trim().toLowerCase().replace(/[^a-z0-9_-]+/g, "_");
      return `${baseKey}:${userKey}`;
    }

    function getReadHeaderNotificationIds() {
      try {
        const parsed = JSON.parse(localStorage.getItem(getHeaderNotificationStorageKey(HEADER_NOTIFICATION_READ_KEY)) || "[]");
        return new Set(Array.isArray(parsed) ? parsed.map(String) : []);
      } catch {
        return new Set();
      }
    }

    function getDismissedHeaderNotificationIds() {
      try {
        const parsed = JSON.parse(localStorage.getItem(getHeaderNotificationStorageKey(HEADER_NOTIFICATION_DISMISSED_KEY)) || "[]");
        return new Set(Array.isArray(parsed) ? parsed.map(String) : []);
      } catch {
        return new Set();
      }
    }

    function collectHeaderNotifications() {
      const items = [];
      for (const item of Object.values(liveResultsState || {})) {
        if (!item || typeof item !== "object") continue;
        const type = String(item.key || "").toUpperCase();
        const ky = String(item.ky || "").trim();
        const timestamp = Date.parse(item.updatedAt || liveResultsFetchedAt || 0) || 0;
        items.push({
          id: `live:${type}:${ky || timestamp}`,
          kind: "live",
          title: `${TYPES[type]?.label || type || "Kết quả"} đã cập nhật`,
          detail: [ky ? `Kỳ ${ky.replace(/^#/, "#")}` : "", item.date || "", item.time || ""].filter(Boolean).join(" · "),
          timestamp,
        });
      }
      for (const type of PREDICTION_LOG_TYPES) {
        const logs = Array.isArray(store?.predictionLogs?.[type]) ? store.predictionLogs[type] : [];
        const pending = [...logs].reverse().find(entry => entry && !entry.resolved);
        if (!pending) continue;
        const ky = String(pending.predictedKy || "").trim();
        const timestamp = Date.parse(pending.createdAt || 0) || 0;
        items.push({
          id: `prediction:${type}:${pending.id || ky || timestamp}`,
          kind: "prediction",
          title: `${TYPES[type]?.label || type} đang chờ kết quả`,
          detail: [ky ? `Kỳ ${ky.replace(/^#/, "#")}` : "Kỳ tiếp theo", pending.bundleCount ? `${pending.bundleCount} bộ` : ""].filter(Boolean).join(" · "),
          timestamp,
        });
      }
      const dismissedIds = getDismissedHeaderNotificationIds();
      return items
        .filter(item => !dismissedIds.has(item.id))
        .sort((a, b) => b.timestamp - a.timestamp)
        .slice(0, 8);
    }

    function formatHeaderNotificationTime(timestamp) {
      if (!timestamp) return "Mới cập nhật";
      return new Date(timestamp).toLocaleString("vi-VN", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
    }

    function renderHeaderNotifications() {
      const list = document.getElementById("notificationList");
      const badge = document.getElementById("notificationBadge");
      const button = document.getElementById("notificationBtn");
      const markReadButton = document.getElementById("notificationMarkReadBtn");
      const clearButton = document.getElementById("notificationClearBtn");
      if (!list || !badge || !button) return;
      const items = collectHeaderNotifications();
      const readIds = getReadHeaderNotificationIds();
      const unreadCount = items.filter(item => !readIds.has(item.id)).length;
      badge.textContent = unreadCount > 9 ? "9+" : String(unreadCount);
      badge.hidden = unreadCount === 0;
      button.setAttribute("aria-label", unreadCount ? `Mở thông báo, ${unreadCount} tin chưa đọc` : "Mở thông báo");
      if (markReadButton) markReadButton.disabled = items.length === 0 || unreadCount === 0;
      if (clearButton) clearButton.disabled = items.length === 0;
      list.replaceChildren();
      if (!items.length) {
        const empty = document.createElement("div");
        empty.className = "header-notification-empty";
        empty.textContent = "Chưa có thông báo mới.";
        list.appendChild(empty);
        return;
      }
      for (const item of items) {
        const row = document.createElement("div");
        row.className = `header-notification-item${readIds.has(item.id) ? " is-read" : ""}`;
        const dot = document.createElement("span");
        dot.className = `header-notification-dot is-${item.kind}`;
        dot.setAttribute("aria-hidden", "true");
        const content = document.createElement("div");
        const title = document.createElement("strong");
        const detail = document.createElement("span");
        const time = document.createElement("time");
        title.textContent = item.title;
        detail.textContent = item.detail || "Dữ liệu mới đã sẵn sàng.";
        time.textContent = formatHeaderNotificationTime(item.timestamp);
        content.append(title, detail, time);
        row.append(dot, content);
        list.appendChild(row);
      }
    }

    function markHeaderNotificationsRead() {
      const ids = collectHeaderNotifications().map(item => item.id);
      localStorage.setItem(getHeaderNotificationStorageKey(HEADER_NOTIFICATION_READ_KEY), JSON.stringify(ids));
      renderHeaderNotifications();
    }

    function clearHeaderNotifications() {
      const dismissedIds = getDismissedHeaderNotificationIds();
      collectHeaderNotifications().forEach(item => dismissedIds.add(item.id));
      const limitedIds = [...dismissedIds].slice(-200);
      localStorage.setItem(getHeaderNotificationStorageKey(HEADER_NOTIFICATION_DISMISSED_KEY), JSON.stringify(limitedIds));
      renderHeaderNotifications();
    }

    function closeHeaderPopovers() {
      for (const [buttonId, panelId] of [["notificationBtn", "notificationPanel"], ["settingsBtn", "settingsPanel"]]) {
        const button = document.getElementById(buttonId);
        const panel = document.getElementById(panelId);
        if (panel) panel.hidden = true;
        if (button) button.setAttribute("aria-expanded", "false");
      }
    }

    function toggleHeaderPopover(buttonId, panelId) {
      const button = document.getElementById(buttonId);
      const panel = document.getElementById(panelId);
      if (!button || !panel) return;
      const willOpen = panel.hidden;
      closeHeaderPopovers();
      panel.hidden = !willOpen;
      button.setAttribute("aria-expanded", willOpen ? "true" : "false");
      if (willOpen && panelId === "notificationPanel") renderHeaderNotifications();
    }

    // ---abc--- Store / Session / Persistence ---
    function updateStoreSaveState(patch = {}) {
      storeSaveState = {
        ...storeSaveState,
        ...(patch && typeof patch === "object" ? patch : {}),
      };
      const snapshot = { ...storeSaveState };
      window.__storeSaveState = snapshot;
      try {
        window.dispatchEvent(new CustomEvent("store-save-status", { detail: snapshot }));
      } catch {}
      return snapshot;
    }

    function getStoreSaveState() {
      return { ...storeSaveState };
    }

    window.getStoreSaveState = getStoreSaveState;

    async function loadStoreFromServer() {
      storeSaveGeneration += 1;
      pendingStoreSave = null;
      lastSavedStoreSnapshotText = "";
      if (!currentUser) {
        store = emptyStore();
        updateStoreSaveState({
          pending: false,
          ok: true,
          message: "",
          reason: "no_user",
          savedAt: "",
          failedAt: "",
        });
        renderCurrencyBar();
        return;
      }
      const res = await api("/api/store");
      const parsed = res.store || {};
      const serverStoreSnapshotText = JSON.stringify(parsed);
      const base = emptyStore();
      base.diamondBalance = Math.max(0, Number(parsed.diamondBalance || 0));
      base.paypalBalance = Math.max(0, Number(parsed.paypalBalance || 0));
      for (const t of TYPE_KEYS) {
        base.results[t] = parsed.results?.[t] || {};
        base.picks[t] = parsed.picks?.[t] || {};
        base.resultOrder[t] = parsed.resultOrder?.[t] || Object.keys(base.results[t]);
        base.pickOrder[t] = parsed.pickOrder?.[t] || Object.keys(base.picks[t]);
      }
      for (const t of PREDICTION_LOG_TYPES) {
        const logs = Array.isArray(parsed.predictionLogs?.[t]) ? parsed.predictionLogs[t] : [];
        base.predictionLogs[t] = logs.slice(-MAX_PREDICTION_LOGS_PER_TYPE);
      }
      base.statsV2Favorites = Array.isArray(parsed.statsV2Favorites) ? parsed.statsV2Favorites : [];
      base.statsV2History = Array.isArray(parsed.statsV2History) ? parsed.statsV2History : [];
      base.paypalTopups = Array.isArray(parsed.paypalTopups) ? parsed.paypalTopups : [];
      base.luckyWheelHistory = Array.isArray(parsed.luckyWheelHistory) ? parsed.luckyWheelHistory : [];
      base.luckyWheelTopupHistory = Array.isArray(parsed.luckyWheelTopupHistory) ? parsed.luckyWheelTopupHistory : [];
      base.luckyWheelSpinCount = Math.max(0, Number(parsed.luckyWheelSpinCount || 0));
      base.luckyWheelDailySpinCount = Math.max(0, Number(parsed.luckyWheelDailySpinCount || 0));
      base.luckyWheelDailyExchangeSpins = Math.max(0, Number(parsed.luckyWheelDailyExchangeSpins || 0));
      base.luckyWheelExchangeDayKey = String(parsed.luckyWheelExchangeDayKey || "");
      base.luckyWheelMilestoneDayKey = String(parsed.luckyWheelMilestoneDayKey || "");
      base.luckyWheelStoredSpins = Number.isFinite(Number(parsed.luckyWheelStoredSpins))
        ? Math.max(0, Math.min(LUCKY_WHEEL_MAX_SPINS, Math.floor(Number(parsed.luckyWheelStoredSpins))))
        : base.luckyWheelStoredSpins;
      base.luckyWheelLastRegenAt = String(parsed.luckyWheelLastRegenAt || "");
      base.luckyWheelBonusSpins = Math.max(0, Number(parsed.luckyWheelBonusSpins || 0));
      base.luckyWheelLastSpinDay = String(parsed.luckyWheelLastSpinDay || "");
      base.luckyWheelLastResult = parsed.luckyWheelLastResult && typeof parsed.luckyWheelLastResult === "object"
        ? parsed.luckyWheelLastResult
        : null;
      const predictionLogsBeforeReconcile = getPredictionLogsSignature(base.predictionLogs);
      store = base;
      const compactSnapshotText = JSON.stringify(buildPersistableStoreSnapshot(base));
      const needsStoreCompaction = compactSnapshotText !== serverStoreSnapshotText;
      lastSavedStoreSnapshotText = needsStoreCompaction ? serverStoreSnapshotText : compactSnapshotText;
      reconcileAllPredictionLogs();
      const predictionLogsChanged = getPredictionLogsSignature(store.predictionLogs) !== predictionLogsBeforeReconcile;
      if (predictionLogsChanged || needsStoreCompaction) {
        saveStore({ reason: predictionLogsChanged ? "reconcile_prediction_logs" : "compact_store_payload" });
      }
      renderCurrencyBar();
    }

    async function flushStoreSaveQueue() {
      let allSaved = true;
      while (pendingStoreSave) {
        const request = pendingStoreSave;
        pendingStoreSave = null;
        if (request.username !== currentUser || request.generation !== storeSaveGeneration) continue;
        if (request.snapshotText === lastSavedStoreSnapshotText) continue;
        updateStoreSaveState({
          pending: true,
          ok: storeSaveState.ok,
          message: "",
          reason: request.reason,
        });
        try {
          await api("/api/store", "POST", { store: request.snapshotText });
          if (request.username !== currentUser || request.generation !== storeSaveGeneration) continue;
          lastSavedStoreSnapshotText = request.snapshotText;
          updateStoreSaveState({
            pending: !!pendingStoreSave,
            ok: true,
            message: "",
            reason: request.reason,
            savedAt: getSyncedIsoString(),
            failedAt: "",
          });
        } catch (error) {
          allSaved = false;
          if (request.username !== currentUser || request.generation !== storeSaveGeneration) continue;
          const message = String(error?.message || error || "Không lưu được dữ liệu tài khoản.");
          console.error(`[store-save:${request.reason}] payloadBytes=${request.payloadBytes}`, error);
          updateStoreSaveState({
            pending: !!pendingStoreSave,
            ok: false,
            message,
            reason: request.reason,
            failedAt: getSyncedIsoString(),
          });
        }
      }
      return allSaved;
    }

    async function saveStore(options = {}) {
      if (!currentUser) return false;
      const reason = String(options?.reason || "").trim() || "unspecified";
      const snapshotText = JSON.stringify(buildPersistableStoreSnapshot(store));
      if (IS_LOCAL_MODE) {
        if (snapshotText !== lastSavedStoreSnapshotText) {
          setLocalStoreForUser(currentUser, store);
          lastSavedStoreSnapshotText = snapshotText;
        }
        updateStoreSaveState({
          pending: false,
          ok: true,
          message: "",
          reason,
          savedAt: getSyncedIsoString(),
          failedAt: "",
        });
        return true;
      }
      if (snapshotText === lastSavedStoreSnapshotText && !storeSaveLoopPromise) return true;
      pendingStoreSave = {
        username: currentUser,
        generation: storeSaveGeneration,
        snapshotText,
        payloadBytes: estimateStorePayloadBytes(snapshotText),
        reason,
      };
      if (!storeSaveLoopPromise) {
        storeSaveLoopPromise = flushStoreSaveQueue().finally(() => {
          storeSaveLoopPromise = null;
        });
      }
      return storeSaveLoopPromise;
    }

    function renderCurrencyBar() {
      const d = document.getElementById("diamondBalance");
      const p = document.getElementById("paypalBalance");
      if (d) d.textContent = String(Math.max(0, Number(store?.diamondBalance || 0)));
      if (p) p.textContent = String(Math.max(0, Number(store?.paypalBalance || 0)));
      const dp = document.getElementById("depositPaypalBalance");
      if (dp) dp.textContent = formatLuckyWheelAmount(Math.max(0, Number(store?.paypalBalance || 0)));
      const ltb = document.getElementById("luckyWheelTopupBalance");
      if (ltb) ltb.textContent = `${formatLuckyWheelAmount(Math.max(0, Number(store?.paypalBalance || 0)))} PP`;
    }

    function ensurePaypalTopupState() {
      if (!Array.isArray(store.paypalTopups)) store.paypalTopups = [];
    }

    function getPaypalTopupPackageById(id) {
      return PAYPAL_TOPUP_PACKAGES.find(item => item.id === id) || null;
    }

    function convertRealMoneyToPaypal(amount) {
      const numeric = Math.max(0, Number(amount || 0));
      return Math.round(numeric * PAYPAL_REAL_RATE * 100) / 100;
    }

    function getPaypalBonusPackage(amount, preferredPackageId = "") {
      const numeric = Math.max(0, Number(amount || 0));
      const preferred = getPaypalTopupPackageById(preferredPackageId);
      if (preferred && Number(preferred.amount || 0) === numeric) return preferred;
      return PAYPAL_TOPUP_PACKAGES.find(item => Number(item.amount || 0) === numeric) || null;
    }

    function calculatePaypalCredit(amount, preferredPackageId = "") {
      const baseCredit = convertRealMoneyToPaypal(amount);
      const packageMeta = getPaypalBonusPackage(amount, preferredPackageId);
      const bonusRate = Math.max(0, Number(packageMeta?.bonusRate || 0));
      const bonusCredit = Math.round(baseCredit * bonusRate * 100) / 100;
      const totalCredit = Math.round((baseCredit + bonusCredit) * 100) / 100;
      return { baseCredit, bonusRate, bonusCredit, totalCredit, packageMeta };
    }

    function formatPaypalCredit(value) {
      const numeric = Math.max(0, Number(value || 0));
      const hasDecimal = Math.abs(numeric - Math.round(numeric)) > 1e-9;
      return numeric.toLocaleString("vi-VN", {
        minimumFractionDigits: hasDecimal ? 2 : 0,
        maximumFractionDigits: 2
      });
    }

    function formatPaypalPercent(value) {
      return Math.max(0, Number(value || 0)).toLocaleString("vi-VN", {
        minimumFractionDigits: 0,
        maximumFractionDigits: 1
      });
    }

    function formatPaypalPackagePart(value) {
      const numeric = Math.max(0, Number(value || 0));
      const hasDecimal = Math.abs(numeric - Math.round(numeric)) > 1e-9;
      return numeric.toLocaleString("en-US", {
        minimumFractionDigits: hasDecimal ? 2 : 0,
        maximumFractionDigits: 2
      });
    }

    function buildPaypalPackageSplitText(packageMeta) {
      const credit = calculatePaypalCredit(packageMeta?.amount || 0, packageMeta?.id || "");
      if (credit.bonusRate > 0) {
        return `${formatPaypalPackagePart(credit.baseCredit)}+${formatPaypalPackagePart(credit.bonusCredit)}`;
      }
      return formatPaypalPackagePart(credit.totalCredit);
    }

    function renderPaypalRatePreview(amountOverride = null) {
      const preview = document.getElementById("depositRatePreview");
      if (!preview) return;
      const selectedPackage = getPaypalTopupPackageById(selectedPaypalTopupPackageId);
      const rawAmount = amountOverride ?? document.getElementById("depositAmount")?.value ?? 0;
      const amount = Math.max(0, Number(rawAmount || 0));
      if (amount > 0) {
        const credit = calculatePaypalCredit(amount, selectedPaypalTopupPackageId);
        if (credit.bonusRate > 0) {
          preview.innerHTML = `Bạn nạp <b>${formatLuckyWheelAmount(amount)}đ</b> -> <b>${formatPaypalCredit(credit.baseCredit)} PayPal</b> + thưởng <b>${formatPaypalCredit(credit.bonusCredit)} PayPal</b> (${formatPaypalPercent(credit.bonusRate * 100)}%) = <b>${formatPaypalCredit(credit.totalCredit)} PayPal</b>.`;
          return;
        }
        preview.innerHTML = `Bạn nạp <b>${formatLuckyWheelAmount(amount)}đ</b> -> quy đổi <b>${formatPaypalCredit(credit.totalCredit)} PayPal</b>.`;
        return;
      }
      if (selectedPackage) {
        const credit = calculatePaypalCredit(selectedPackage.amount, selectedPackage.id);
        if (credit.bonusRate > 0) {
          preview.innerHTML = `Gói <b>${escapeHtml(selectedPackage.title)}</b> nhận <b>${formatPaypalCredit(credit.totalCredit)} PayPal</b>, đã gồm thưởng <b>${formatPaypalCredit(credit.bonusCredit)} PayPal</b> (${formatPaypalPercent(credit.bonusRate * 100)}%).`;
          return;
        }
        preview.innerHTML = `Gói <b>${escapeHtml(selectedPackage.title)}</b> quy đổi khoảng <b>${formatPaypalCredit(credit.totalCredit)} PayPal</b> theo tỷ giá hiện tại.`;
        return;
      }
      preview.innerHTML = `Tỷ giá hiện tại: <b>1 tiền thật = ${PAYPAL_REAL_RATE} PayPal</b>.`;
    }

    function setSelectedPaypalTopupPackage(packageId) {
      const found = getPaypalTopupPackageById(packageId) || PAYPAL_TOPUP_PACKAGES[0] || null;
      if (!found) return;
      selectedPaypalTopupPackageId = found.id;
      const selectedInput = document.getElementById("depositSelectedPackage");
      const amountInput = document.getElementById("depositAmount");
      const credit = calculatePaypalCredit(found.amount, found.id);
      if (selectedInput) {
        selectedInput.value = credit.bonusRate > 0
          ? `${found.title} - nhận ${formatPaypalCredit(credit.totalCredit)} PayPal (+${formatPaypalPercent(credit.bonusRate * 100)}%)`
          : `${found.title} - nhận ${formatPaypalCredit(credit.totalCredit)} PayPal`;
      }
      if (amountInput && !String(amountInput.value || "").trim()) amountInput.value = String(found.amount);
      document.querySelectorAll(".deposit-package-item").forEach(button => {
        button.classList.toggle("active", button.dataset.packageId === found.id);
      });
      renderPaypalRatePreview(amountInput?.value || found.amount);
    }

    function resetPaypalDepositForm() {
      const selectedInput = document.getElementById("depositSelectedPackage");
      const amountInput = document.getElementById("depositAmount");
      const emailInput = document.getElementById("depositPaypalEmail");
      const txnInput = document.getElementById("depositTxnCode");
      const senderInput = document.getElementById("depositSenderName");
      const timeInput = document.getElementById("depositTxnTime");
      const noteInput = document.getElementById("depositNote");
      if (selectedInput) selectedInput.value = "Chưa chọn gói";
      if (amountInput) amountInput.value = "";
      if (emailInput) emailInput.value = "";
      if (txnInput) txnInput.value = "";
      if (senderInput) senderInput.value = "";
      if (timeInput) timeInput.value = "";
      if (noteInput) noteInput.value = "";
      setSelectedPaypalTopupPackage(PAYPAL_TOPUP_PACKAGES[1]?.id || PAYPAL_TOPUP_PACKAGES[0]?.id || "");
    }

    function renderPaypalTopupPackages() {
      const host = document.getElementById("depositPackageGrid");
      if (!host) return;
      host.innerHTML = PAYPAL_TOPUP_PACKAGES.map(item => `
        <button type="button" class="deposit-package-item" data-package-id="${item.id}">
          <span class="deposit-package-amount">${item.title}</span>
          <span class="deposit-package-credit">Nhận ${formatPaypalCredit(calculatePaypalCredit(item.amount, item.id).totalCredit)} PayPal</span>
          <span class="deposit-package-bonus">${buildPaypalPackageSplitText(item)}</span>
        </button>
      `).join("");
      host.querySelectorAll(".deposit-package-item").forEach(button => {
        button.onclick = () => {
          const amountInput = document.getElementById("depositAmount");
          if (amountInput) amountInput.value = "";
          setSelectedPaypalTopupPackage(button.dataset.packageId || "");
        };
      });
      setSelectedPaypalTopupPackage(selectedPaypalTopupPackageId || PAYPAL_TOPUP_PACKAGES[1]?.id || PAYPAL_TOPUP_PACKAGES[0]?.id || "");
    }

    function renderPaypalTopupHistory() {
      ensurePaypalTopupState();
      const host = document.getElementById("depositHistoryList");
      const count = document.getElementById("depositHistoryCount");
      if (!host || !count) return;
      count.textContent = `${store.paypalTopups.length} yêu cầu`;
      if (!store.paypalTopups.length) {
        host.innerHTML = `<div class="deposit-empty">Chưa có yêu cầu nạp nào được lưu trong tài khoản này.</div>`;
        return;
      }
      host.innerHTML = store.paypalTopups.map(entry => `
        <div class="deposit-history-item">
          <div class="deposit-history-top">
            <strong>${escapeHtml(entry.packageTitle || "Tự nhập số tiền")}</strong>
            <span class="deposit-status-pill">${escapeHtml(entry.status || "Chờ xử lý")}</span>
          </div>
          <div class="deposit-history-meta">
            ${escapeHtml(entry.timeText || "")}<br>
            ${escapeHtml(entry.email || "")} | Mã GD: ${escapeHtml(entry.txnCode || "")}
          </div>
          <div class="deposit-history-note">
            Số tiền: <b>${escapeHtml(formatLuckyWheelAmount(entry.amount || 0))}đ</b><br>
            Quy đổi: <b>${escapeHtml(formatPaypalCredit(entry.creditAmount ?? calculatePaypalCredit(entry.amount || 0, entry.packageId || "").totalCredit))} PayPal</b><br>
            ${Number(entry.bonusRate || 0) > 0 ? `Bonus: <b>${escapeHtml(formatPaypalPercent((entry.bonusRate || 0) * 100))}% = ${escapeHtml(formatPaypalCredit(entry.bonusCredit || 0))} PayPal</b><br>` : ""}
            ${entry.note ? escapeHtml(entry.note) : "Không có ghi chú thêm."}
          </div>
        </div>
      `).join("");
    }

    function renderPaypalDepositSection() {
      ensurePaypalTopupState();
      renderPaypalTopupPackages();
      renderPaypalTopupHistory();
      renderCurrencyBar();
      renderPaypalRatePreview();
    }

    function submitPaypalTopupRequest() {
      ensurePaypalTopupState();
      const selectedPackage = getPaypalTopupPackageById(selectedPaypalTopupPackageId);
      const amount = Math.max(0, Number(document.getElementById("depositAmount")?.value || 0));
      const credit = calculatePaypalCredit(amount, selectedPaypalTopupPackageId);
      const email = String(document.getElementById("depositPaypalEmail")?.value || "").trim();
      const txnCode = String(document.getElementById("depositTxnCode")?.value || "").trim();
      const senderName = String(document.getElementById("depositSenderName")?.value || "").trim();
      const txnTime = String(document.getElementById("depositTxnTime")?.value || "").trim();
      const note = String(document.getElementById("depositNote")?.value || "").trim();
      const out = document.getElementById("depositMsg");

      if (!Number.isFinite(amount) || amount < 10000) {
        return line(out, "Số tiền nạp tối thiểu là 10.000 VNĐ.", "warn");
      }
      if (!email || !email.includes("@")) {
        return line(out, "Email PayPal không hợp lệ.", "warn");
      }
      if (!txnCode || txnCode.length < 6) {
        return line(out, "Mã giao dịch cần tối thiểu 6 ký tự.", "warn");
      }
      if (!senderName) {
        return line(out, "Hãy nhập người chuyển.", "warn");
      }

      const createdAt = getSyncedNowDate();
      const entry = {
        id: `pp_${createdAt.getTime()}`,
        packageId: selectedPackage?.id || "",
        packageTitle: selectedPackage?.title || "Tự nhập số tiền",
        amount,
        creditAmount: credit.totalCredit,
        baseCreditAmount: credit.baseCredit,
        bonusRate: credit.bonusRate,
        bonusCredit: credit.bonusCredit,
        email,
        txnCode,
        senderName,
        txnTime,
        note,
        status: "Chờ xử lý",
        createdAt: createdAt.toISOString(),
        timeText: createdAt.toLocaleString("vi-VN"),
      };
      store.paypalTopups.unshift(entry);
      while (store.paypalTopups.length > MAX_PAYPAL_TOPUPS) store.paypalTopups.pop();
      saveStore();
      renderPaypalTopupHistory();
      line(
        out,
        credit.bonusRate > 0
          ? `Đã tạo yêu cầu nạp ${formatLuckyWheelAmount(amount)}đ cho ${email}. Nhận ${formatPaypalCredit(credit.totalCredit)} PayPal, gồm bonus ${formatPaypalCredit(credit.bonusCredit)} PayPal (${formatPaypalPercent(credit.bonusRate * 100)}%). Mã giao dịch: ${txnCode}.`
          : `Đã tạo yêu cầu nạp ${formatLuckyWheelAmount(amount)}đ cho ${email}. Quy đổi ${formatPaypalCredit(credit.totalCredit)} PayPal. Mã giao dịch: ${txnCode}.`,
        "ok"
      );
    }

    function formatLuckyWheelAmount(value) {
      return Number(value || 0).toLocaleString("vi-VN");
    }

    function formatLuckyWheelPercent(value) {
      return Math.max(0, Number(value || 0)).toLocaleString("vi-VN", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      });
    }

    function getLuckyWheelRarityMeta(percentValue) {
      const safe = Math.max(0, Number(percentValue || 0));
      if (safe <= 0.5) {
        return { label: "Cực Hiếm", className: "rarity-extreme" };
      }
      if (safe < 5) {
        return { label: "Hiếm", className: "rarity-rare" };
      }
      if (safe < 15) {
        return { label: "Thường", className: "rarity-common" };
      }
      return { label: "Thường Xuyên", className: "rarity-frequent" };
    }

    function getLuckyWheelSpinMultiplier() {
      const safe = Math.max(1, Math.floor(Number(luckyWheelSpinMultiplier || 1)));
      return [1, 3, 5, 10].includes(safe) ? safe : 1;
    }

    function formatLuckyWheelCompactAmount(value) {
      const safe = Math.max(0, Number(value || 0));
      if (safe >= 1000) {
        const compact = safe / 1000;
        const isWhole = Math.abs(compact - Math.round(compact)) < 0.001;
        return `${compact.toLocaleString("vi-VN", {
          minimumFractionDigits: isWhole ? 0 : 1,
          maximumFractionDigits: isWhole ? 0 : 1
        })}K`;
      }
      return formatLuckyWheelAmount(safe);
    }

    function getLuckyWheelDisplayReward(reward = {}, multiplier = getLuckyWheelSpinMultiplier()) {
      const safeMultiplier = Math.max(1, Math.floor(Number(multiplier || 1)));
      return {
        diamond: Math.max(0, Number(reward.diamond || 0)) * safeMultiplier,
        paypal: Math.max(0, Number(reward.paypal || 0)) * safeMultiplier,
        bonusSpins: Math.max(0, Number(reward.bonusSpins || 0)) * safeMultiplier
      };
    }

    function buildLuckyWheelShortRewardText(reward = {}) {
      const parts = [];
      if (Number(reward.bonusSpins || 0) > 0) parts.push(`+${formatLuckyWheelAmount(reward.bonusSpins)} Lượt`);
      if (Number(reward.diamond || 0) > 0) parts.push(`${formatLuckyWheelCompactAmount(reward.diamond)} KC`);
      if (Number(reward.paypal || 0) > 0) parts.push(`${formatLuckyWheelCompactAmount(reward.paypal)} PP`);
      return parts.join(" + ") || "Quà";
    }

    function getLuckyWheelRewardVariant(reward = {}) {
      const hasSpins = Number(reward.bonusSpins || 0) > 0;
      const hasPaypal = Number(reward.paypal || 0) > 0;
      const hasDiamond = Number(reward.diamond || 0) > 0;
      const rewardTypes = [hasSpins, hasPaypal, hasDiamond].filter(Boolean).length;
      if (rewardTypes > 1) return "combo";
      if (hasPaypal) return "paypal";
      if (hasDiamond) return "diamond";
      if (hasSpins) return "spins";
      return "combo";
    }

    function buildLuckyWheelDisplaySegment(segment, multiplier = getLuckyWheelSpinMultiplier()) {
      const reward = getLuckyWheelDisplayReward(segment?.reward || {}, multiplier);
      const rewardTypes = [
        Number(reward.bonusSpins || 0) > 0,
        Number(reward.paypal || 0) > 0,
        Number(reward.diamond || 0) > 0
      ].filter(Boolean).length;

      let label = String(segment?.label || "");
      let short = String(segment?.short || label || "Quà");
      let desc = String(segment?.desc || "");
      let descVariant = getLuckyWheelRewardVariant(reward);

      if (rewardTypes === 1 && Number(reward.bonusSpins || 0) > 0) {
        label = `Thêm ${formatLuckyWheelAmount(reward.bonusSpins)} lượt`;
        short = `+${formatLuckyWheelAmount(reward.bonusSpins)} Lượt`;
        desc = "Lượt quay";
        descVariant = "spins";
      } else if (rewardTypes === 1 && Number(reward.paypal || 0) > 0) {
        label = `+${formatLuckyWheelAmount(reward.paypal)} PayPal`;
        short = `${formatLuckyWheelCompactAmount(reward.paypal)} PP`;
        desc = "PayPal";
        descVariant = "paypal";
      } else if (rewardTypes === 1 && Number(reward.diamond || 0) > 0) {
        label = `+${formatLuckyWheelAmount(reward.diamond)} Kim cương`;
        short = `${formatLuckyWheelCompactAmount(reward.diamond)} KC`;
        desc = "Kim cương";
        descVariant = "diamond";
      } else if (rewardTypes > 1) {
        label = buildLuckyWheelRewardText(reward);
        short = buildLuckyWheelShortRewardText(reward);
        desc = "Combo";
        descVariant = "combo";
      }

      return {
        ...segment,
        reward,
        label,
        short,
        desc,
        descVariant
      };
    }

    function getLuckyWheelPrizeDisplayScore(segment) {
      const reward = segment?.reward || {};
      const paypal = Math.max(0, Number(reward.paypal || 0));
      const diamond = Math.max(0, Number(reward.diamond || 0));
      const bonusSpins = Math.max(0, Number(reward.bonusSpins || 0));
      if (paypal > 0) return 300000000 + paypal;
      if (diamond > 0) return 200000000 + diamond;
      if (bonusSpins > 0) return 100000000 + bonusSpins;
      return 0;
    }

    function getLuckyWheelTopupState(selectedSpins = luckyWheelSelectedTopupSpins) {
      const snapshot = syncLuckyWheelSpins();
      const available = Math.max(0, Number(snapshot.available || 0));
      const paypalBalance = Math.max(0, Number(store.paypalBalance || 0));
      const exchangedToday = Math.max(0, Number(store.luckyWheelDailyExchangeSpins || 0));
      const remainingDaily = Math.max(0, LUCKY_WHEEL_TOPUP_MAX_PER_DAY - exchangedToday);
      const freeSlots = Math.max(0, LUCKY_WHEEL_MAX_SPINS - available);
      const maxSelectable = LUCKY_WHEEL_TOPUP_MAX_PER_ACTION;
      const requestedSpins = Math.max(0, Math.floor(Number(selectedSpins || 0)));
      const spins = Math.max(0, Math.min(requestedSpins, LUCKY_WHEEL_TOPUP_MAX_PER_ACTION));
      const paypalCost = spins * LUCKY_WHEEL_TOPUP_PAYPAL_PER_SPIN;
      const hasBalance = spins > 0 && paypalBalance >= paypalCost;
      return {
        snapshot,
        available,
        freeSlots,
        paypalBalance,
        exchangedToday,
        remainingDaily,
        maxSelectable,
        spins,
        paypalCost,
        hasBalance,
        hasSlot: spins > 0 && freeSlots >= spins,
        canExchange: spins > 0 && paypalBalance >= paypalCost && freeSlots >= spins && remainingDaily >= spins
      };
    }

    function closeLuckyWheelTopup() {
      const overlay = document.getElementById("luckyWheelTopupOverlay");
      if (!overlay) return;
      stopLuckyWheelTopupAdjustLoop();
      overlay.hidden = true;
      luckyWheelSelectedTopupSpins = 0;
    }

    function normalizeLuckyWheelTopupSpins(value) {
      const parsed = Math.floor(Number(value || 0));
      if (!Number.isFinite(parsed)) return 0;
      return Math.max(0, Math.min(LUCKY_WHEEL_TOPUP_MAX_PER_ACTION, parsed));
    }

    function setLuckyWheelTopupSpins(value) {
      luckyWheelSelectedTopupSpins = normalizeLuckyWheelTopupSpins(value);
      updateLuckyWheelTopupDialogState();
    }

    function stopLuckyWheelTopupAdjustLoop() {
      if (luckyWheelTopupHoldTimeout) {
        clearTimeout(luckyWheelTopupHoldTimeout);
        luckyWheelTopupHoldTimeout = null;
      }
      if (luckyWheelTopupHoldInterval) {
        clearInterval(luckyWheelTopupHoldInterval);
        luckyWheelTopupHoldInterval = null;
      }
    }

    function startLuckyWheelTopupAdjustLoop(step) {
      stopLuckyWheelTopupAdjustLoop();
      const safeStep = step > 0 ? 1 : -1;
      const tick = () => {
        const nextValue = normalizeLuckyWheelTopupSpins(luckyWheelSelectedTopupSpins + safeStep);
        if (nextValue === luckyWheelSelectedTopupSpins) {
          stopLuckyWheelTopupAdjustLoop();
          return;
        }
        setLuckyWheelTopupSpins(nextValue);
      };
      tick();
      luckyWheelTopupHoldTimeout = window.setTimeout(() => {
        luckyWheelTopupHoldInterval = window.setInterval(tick, 85);
      }, 260);
    }

    function bindLuckyWheelTopupStepButton(button, step) {
      if (!button) return;
      const start = event => {
        if (button.disabled) return;
        event.preventDefault();
        startLuckyWheelTopupAdjustLoop(step);
      };
      const stop = () => stopLuckyWheelTopupAdjustLoop();
      button.addEventListener("mousedown", start);
      button.addEventListener("touchstart", start, { passive: false });
      button.addEventListener("mouseup", stop);
      button.addEventListener("mouseleave", stop);
      button.addEventListener("touchend", stop);
      button.addEventListener("touchcancel", stop);
      button.addEventListener("click", event => event.preventDefault());
      button.addEventListener("keydown", event => {
        if ((event.key === "Enter" || event.key === " ") && !event.repeat) {
          event.preventDefault();
          startLuckyWheelTopupAdjustLoop(step);
        }
      });
      button.addEventListener("keyup", event => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          stopLuckyWheelTopupAdjustLoop();
        }
      });
    }

    function updateLuckyWheelTopupDialogState() {
      const overlay = document.getElementById("luckyWheelTopupOverlay");
      const balanceEl = document.getElementById("luckyWheelTopupBalance");
      const confirmBox = document.getElementById("luckyWheelTopupConfirm");
      const confirmText = document.getElementById("luckyWheelTopupConfirmText");
      const confirmBtn = document.getElementById("luckyWheelTopupConfirmBtn");
      if (!overlay || overlay.hidden || !balanceEl || !confirmBox || !confirmText || !confirmBtn) return;

      const state = getLuckyWheelTopupState(luckyWheelSelectedTopupSpins);
      const input = document.getElementById("luckyWheelTopupInput");
      const minusBtn = document.getElementById("luckyWheelTopupMinus");
      const plusBtn = document.getElementById("luckyWheelTopupPlus");
      const selectedSpinsEl = document.getElementById("luckyWheelTopupSelectedSpins");
      const selectedCostEl = document.getElementById("luckyWheelTopupSelectedCost");
      const exchangedTodayEl = document.getElementById("luckyWheelTopupExchangedToday");
      const remainingDailyEl = document.getElementById("luckyWheelTopupRemainingDaily");
      const resetEl = document.getElementById("luckyWheelTopupResetCountdown");

      balanceEl.textContent = `${formatLuckyWheelAmount(Math.max(0, Number(store.paypalBalance || 0)))} PP`;
      if (input && document.activeElement !== input) {
        input.value = String(state.spins);
      }
      if (minusBtn) minusBtn.disabled = state.spins <= 0;
      if (plusBtn) plusBtn.disabled = state.spins >= LUCKY_WHEEL_TOPUP_MAX_PER_ACTION;
      if (selectedSpinsEl) selectedSpinsEl.textContent = `${formatLuckyWheelAmount(state.spins)} lượt`;
      if (selectedCostEl) selectedCostEl.textContent = `${formatLuckyWheelAmount(state.paypalCost)} PP`;
      if (exchangedTodayEl) exchangedTodayEl.textContent = `${formatLuckyWheelAmount(state.exchangedToday)}/${formatLuckyWheelAmount(LUCKY_WHEEL_TOPUP_MAX_PER_DAY)} lượt`;
      if (remainingDailyEl) remainingDailyEl.textContent = `${formatLuckyWheelAmount(state.remainingDaily)}/${formatLuckyWheelAmount(LUCKY_WHEEL_TOPUP_MAX_PER_DAY)} lượt`;
      if (resetEl) resetEl.textContent = `Reset sau ${formatLuckyWheelCountdown(getLuckyWheelNextDayResetMs())}`;

      confirmBox.hidden = false;
      confirmBtn.disabled = !state.canExchange;
      if (state.spins <= 0) {
        confirmText.innerHTML = `Nhập số lớn hơn <b>0 lượt</b> để mở xác nhận đổi.`;
      } else {
        confirmText.innerHTML = `Bạn có muốn đổi <b>${escapeHtml(formatLuckyWheelAmount(state.paypalCost))} PayPal</b> để nhận <b>${escapeHtml(formatLuckyWheelAmount(state.spins))} lượt quay</b> không?`;
      }

      renderLuckyWheelTopupHistory();
    }

    function renderLuckyWheelTopupDialog() {
      const overlay = document.getElementById("luckyWheelTopupOverlay");
      const balanceEl = document.getElementById("luckyWheelTopupBalance");
      const grid = document.getElementById("luckyWheelTopupGrid");
      const confirmBox = document.getElementById("luckyWheelTopupConfirm");
      const confirmText = document.getElementById("luckyWheelTopupConfirmText");
      const confirmBtn = document.getElementById("luckyWheelTopupConfirmBtn");
      if (!overlay || !balanceEl || !grid || !confirmBox || !confirmText || !confirmBtn) return;

      const state = getLuckyWheelTopupState(luckyWheelSelectedTopupSpins);
      balanceEl.textContent = `${formatLuckyWheelAmount(Math.max(0, Number(store.paypalBalance || 0)))} PP`;

      grid.innerHTML = `
        <div class="spin-topup-slider-card">
          <div class="spin-topup-slider-head">
            <strong>Quy đổi lượt quay</strong>
            <span>2.000 PP / 1 lượt</span>
          </div>
          <div class="spin-topup-slider-box">
            <div class="spin-topup-stepper-shell">
              <div class="spin-topup-stepper">
                <button
                  id="luckyWheelTopupMinus"
                  class="spin-topup-step-btn"
                  type="button"
                  ${state.spins <= 0 ? "disabled" : ""}
                >-</button>
                <label class="spin-topup-step-input-wrap" for="luckyWheelTopupInput">
                  <span class="spin-topup-step-caption">Số lượt muốn đổi</span>
                  <div class="spin-topup-step-input-row">
                    <input
                      id="luckyWheelTopupInput"
                      class="spin-topup-step-input"
                      type="number"
                      min="0"
                      max="${LUCKY_WHEEL_TOPUP_MAX_PER_ACTION}"
                      step="1"
                      value="${Math.max(0, Math.min(state.spins, LUCKY_WHEEL_TOPUP_MAX_PER_ACTION))}"
                      inputmode="numeric"
                    />
                    <span class="spin-topup-step-unit">Lượt</span>
                  </div>
                </label>
                <button
                  id="luckyWheelTopupPlus"
                  class="spin-topup-step-btn"
                  type="button"
                  ${state.spins >= LUCKY_WHEEL_TOPUP_MAX_PER_ACTION ? "disabled" : ""}
                >+</button>
              </div>
            </div>
            <div class="spin-topup-scale">
              <span>50 lượt / lần</span>
            </div>
          </div>
          <div class="spin-topup-slider-value">
            <div>
              <span>Bạn chọn</span>
              <strong id="luckyWheelTopupSelectedSpins">${formatLuckyWheelAmount(state.spins)} lượt</strong>
            </div>
            <div>
              <span>Cần trả</span>
              <strong id="luckyWheelTopupSelectedCost">${formatLuckyWheelAmount(state.paypalCost)} PP</strong>
            </div>
          </div>
          <div class="spin-topup-slider-meta">
            <div>
              <span>Giới hạn/ngày</span>
              <strong id="luckyWheelTopupExchangedToday">${formatLuckyWheelAmount(state.exchangedToday)}/${formatLuckyWheelAmount(LUCKY_WHEEL_TOPUP_MAX_PER_DAY)} lượt</strong>
            </div>
            <div>
              <span>Còn lại trong ngày</span>
              <strong id="luckyWheelTopupRemainingDaily">${formatLuckyWheelAmount(state.remainingDaily)}/${formatLuckyWheelAmount(LUCKY_WHEEL_TOPUP_MAX_PER_DAY)} lượt</strong>
              <small id="luckyWheelTopupResetCountdown">Reset sau ${formatLuckyWheelCountdown(getLuckyWheelNextDayResetMs())}</small>
            </div>
          </div>
        </div>
        <div class="spin-topup-history-box">
          <div class="spin-topup-history-head">
            <strong>Lịch sử đổi lượt</strong>
            <span id="luckyWheelTopupHistoryCount" class="spin-topup-history-count">0 giao dịch</span>
          </div>
          <div id="luckyWheelTopupHistoryList" class="spin-topup-history-list"></div>
        </div>
      `;

      const input = document.getElementById("luckyWheelTopupInput");
      const minusBtn = document.getElementById("luckyWheelTopupMinus");
      const plusBtn = document.getElementById("luckyWheelTopupPlus");
      if (input) {
        const syncInput = event => {
          luckyWheelSelectedTopupSpins = normalizeLuckyWheelTopupSpins(event.target?.value || 0);
          updateLuckyWheelTopupDialogState();
        };
        input.addEventListener("input", syncInput);
        input.addEventListener("change", syncInput);
      }
      bindLuckyWheelTopupStepButton(minusBtn, -1);
      bindLuckyWheelTopupStepButton(plusBtn, 1);
      updateLuckyWheelTopupDialogState();
    }

    function confirmLuckyWheelTopupExchange() {
      const state = getLuckyWheelTopupState(luckyWheelSelectedTopupSpins);
      if (state.spins <= 0) {
        return;
      }
      if (state.remainingDaily <= 0) {
        setLuckyWheelResult(`Bạn đã dùng hết giới hạn đổi <b>${formatLuckyWheelAmount(LUCKY_WHEEL_TOPUP_MAX_PER_DAY)} lượt</b> trong hôm nay.`, "warn");
        return;
      }
      if (!state.hasBalance) {
        setLuckyWheelResult(`Không đủ PayPal để đổi. Bạn cần <b>${formatLuckyWheelAmount(state.paypalCost)} PayPal</b>.`, "warn");
        return;
      }
      if (!state.hasSlot) {
        setLuckyWheelResult("Kho lượt đã đầy, chưa thể đổi thêm lượt.", "warn");
        return;
      }

      store.paypalBalance = Math.max(0, state.paypalBalance - state.paypalCost);
      store.luckyWheelStoredSpins = Math.min(LUCKY_WHEEL_MAX_SPINS, state.available + state.spins);
      store.luckyWheelExchangeDayKey = getLuckyWheelTodayKey();
      store.luckyWheelDailyExchangeSpins = Math.max(0, Number(store.luckyWheelDailyExchangeSpins || 0)) + state.spins;
      if (!Array.isArray(store.luckyWheelTopupHistory)) store.luckyWheelTopupHistory = [];
      const topupAt = getSyncedNowDate();
      store.luckyWheelTopupHistory.unshift({
        at: topupAt.toISOString(),
        spins: state.spins,
        paypalCost: state.paypalCost,
        afterStoredSpins: store.luckyWheelStoredSpins,
        timeText: topupAt.toLocaleString("vi-VN")
      });
      while (store.luckyWheelTopupHistory.length > MAX_LUCKY_WHEEL_TOPUP_HISTORY) {
        store.luckyWheelTopupHistory.pop();
      }
      if (store.luckyWheelStoredSpins >= LUCKY_WHEEL_MAX_SPINS) {
        store.luckyWheelLastRegenAt = getSyncedIsoString();
      }

      saveStore();
      renderCurrencyBar();
      renderPaypalDepositSection();
      renderLuckyWheelPanel();
      closeLuckyWheelTopup();
      setLuckyWheelResult(
        `Đã đổi thành công <b>${formatLuckyWheelAmount(state.paypalCost)} PayPal</b> lấy <b>${formatLuckyWheelAmount(state.spins)} lượt quay</b>.`,
        "ok"
      );
    }

    function getLuckyWheelTodayKey() {
      try {
        return getSyncedNowDate().toLocaleDateString("sv-SE", { timeZone: "Asia/Ho_Chi_Minh" });
      } catch {
        return getSyncedIsoString().slice(0, 10);
      }
    }

    function getLuckyWheelNextDayResetMs() {
      try {
        const nowInTz = new Date(getSyncedNowDate().toLocaleString("en-US", { timeZone: "Asia/Ho_Chi_Minh" }));
        const nextReset = new Date(nowInTz);
        nextReset.setHours(24, 0, 0, 0);
        return Math.max(0, nextReset.getTime() - nowInTz.getTime());
      } catch {
        const now = getSyncedNowDate();
        const nextReset = new Date(now);
        nextReset.setHours(24, 0, 0, 0);
        return Math.max(0, nextReset.getTime() - now.getTime());
      }
    }

    function parseLuckyWheelTimestamp(value) {
      const timestamp = Date.parse(String(value || ""));
      return Number.isFinite(timestamp) ? timestamp : NaN;
    }

    function formatLuckyWheelCountdown(ms) {
      const safeMs = Math.max(0, Math.floor(Number(ms || 0)));
      const totalSeconds = Math.ceil(safeMs / 1000);
      const hours = Math.floor(totalSeconds / 3600);
      const minutes = Math.floor((totalSeconds % 3600) / 60);
      const seconds = totalSeconds % 60;
      return [hours, minutes, seconds].map(part => String(part).padStart(2, "0")).join(":");
    }

    function ensureLuckyWheelState() {
      let changed = false;
      if (!Array.isArray(store.luckyWheelHistory)) store.luckyWheelHistory = [];
      if (!Array.isArray(store.luckyWheelTopupHistory)) store.luckyWheelTopupHistory = [];
      store.luckyWheelSpinCount = Math.max(0, Number(store.luckyWheelSpinCount || 0));
      const todayKey = getLuckyWheelTodayKey();
      store.luckyWheelDailySpinCount = Math.max(0, Number(store.luckyWheelDailySpinCount || 0));
      store.luckyWheelDailyExchangeSpins = Math.max(0, Number(store.luckyWheelDailyExchangeSpins || 0));
      store.luckyWheelExchangeDayKey = String(store.luckyWheelExchangeDayKey || "");
      store.luckyWheelMilestoneDayKey = String(store.luckyWheelMilestoneDayKey || "");
      if (store.luckyWheelExchangeDayKey !== todayKey) {
        store.luckyWheelExchangeDayKey = todayKey;
        store.luckyWheelDailyExchangeSpins = 0;
        changed = true;
      }
      if (store.luckyWheelMilestoneDayKey !== todayKey) {
        store.luckyWheelMilestoneDayKey = todayKey;
        store.luckyWheelDailySpinCount = 0;
        changed = true;
      }
      const parsedStoredSpins = Number(store.luckyWheelStoredSpins);
      if (!Number.isFinite(parsedStoredSpins)) {
        const legacyBonus = Math.max(0, Number(store.luckyWheelBonusSpins || 0));
        const legacyDailyFree = store.luckyWheelLastSpinDay === getLuckyWheelTodayKey() ? 0 : 1;
        const hasLegacySpinData = legacyBonus > 0 || String(store.luckyWheelLastSpinDay || "").trim() !== "";
        store.luckyWheelStoredSpins = hasLegacySpinData
          ? Math.min(LUCKY_WHEEL_MAX_SPINS, Math.max(1, legacyBonus + legacyDailyFree))
          : LUCKY_WHEEL_MAX_SPINS;
        changed = true;
      } else {
        store.luckyWheelStoredSpins = Math.max(0, Math.min(LUCKY_WHEEL_MAX_SPINS, Math.floor(parsedStoredSpins)));
      }
      if (!String(store.luckyWheelLastRegenAt || "").trim()) {
        store.luckyWheelLastRegenAt = getSyncedIsoString();
        changed = true;
      }
      store.luckyWheelBonusSpins = Math.max(0, Number(store.luckyWheelBonusSpins || 0));
      store.luckyWheelLastSpinDay = String(store.luckyWheelLastSpinDay || "");
      if (!store.luckyWheelLastResult || typeof store.luckyWheelLastResult !== "object") {
        store.luckyWheelLastResult = null;
      }
      return changed;
    }

    function buildLuckyWheelRewardText(reward = {}) {
      const parts = [];
      if (Number(reward.diamond || 0) > 0) parts.push(`${formatLuckyWheelAmount(reward.diamond)} Kim cương`);
      if (Number(reward.paypal || 0) > 0) parts.push(`${formatLuckyWheelAmount(reward.paypal)} PayPal`);
      if (Number(reward.bonusSpins || 0) > 0) parts.push(`+${formatLuckyWheelAmount(reward.bonusSpins)} lượt quay`);
      return parts.join(" + ") || "Quà bí mật";
    }

    function syncLuckyWheelSpins() {
      ensureLuckyWheelState();
      let changed = false;
      const now = getSyncedNowMs();
      let storedSpins = Math.max(0, Math.min(LUCKY_WHEEL_MAX_SPINS, Math.floor(Number(store.luckyWheelStoredSpins || 0))));
      let lastRegenAt = parseLuckyWheelTimestamp(store.luckyWheelLastRegenAt);
      if (!Number.isFinite(lastRegenAt)) {
        lastRegenAt = now;
        store.luckyWheelLastRegenAt = new Date(now).toISOString();
        changed = true;
      }

      if (storedSpins < LUCKY_WHEEL_MAX_SPINS) {
        const elapsed = Math.max(0, now - lastRegenAt);
        const gainedSpins = Math.floor(elapsed / LUCKY_WHEEL_REGEN_MS);
        if (gainedSpins > 0) {
          storedSpins = Math.min(LUCKY_WHEEL_MAX_SPINS, storedSpins + gainedSpins);
          lastRegenAt = storedSpins >= LUCKY_WHEEL_MAX_SPINS
            ? now
            : lastRegenAt + (gainedSpins * LUCKY_WHEEL_REGEN_MS);
          changed = true;
        }
      }

      if (storedSpins !== Number(store.luckyWheelStoredSpins || 0)) {
        store.luckyWheelStoredSpins = storedSpins;
        changed = true;
      }
      const nextRegenMs = storedSpins >= LUCKY_WHEEL_MAX_SPINS
        ? 0
        : Math.max(1000, LUCKY_WHEEL_REGEN_MS - Math.max(0, now - lastRegenAt));
      const nextIso = new Date(lastRegenAt).toISOString();
      if (store.luckyWheelLastRegenAt !== nextIso) {
        store.luckyWheelLastRegenAt = nextIso;
        changed = true;
      }

      return {
        available: storedSpins,
        max: LUCKY_WHEEL_MAX_SPINS,
        nextRegenMs,
        changed
      };
    }

    function getLuckyWheelAvailableSpins() {
      return syncLuckyWheelSpins().available;
    }

    function consumeLuckyWheelSpin(amount = 1) {
      const snapshot = syncLuckyWheelSpins();
      const required = Math.max(1, Math.floor(Number(amount || 1)));
      if (snapshot.available < required) {
        return { ok: false, source: "none", nextRegenMs: snapshot.nextRegenMs };
      }
      store.luckyWheelStoredSpins = snapshot.available - required;
      if (snapshot.available >= snapshot.max) {
        store.luckyWheelLastRegenAt = getSyncedIsoString();
      }
      return {
        ok: true,
        source: "regen",
        nextRegenMs: snapshot.available > required ? 0 : LUCKY_WHEEL_REGEN_MS
      };
    }

    function pickLuckyWheelSegment() {
      const total = LUCKY_WHEEL_SEGMENTS.reduce((sum, segment) => sum + Number(segment.weight || 0), 0);
      let randomValue = Math.random() * total;
      for (let index = 0; index < LUCKY_WHEEL_SEGMENTS.length; index++) {
        randomValue -= Number(LUCKY_WHEEL_SEGMENTS[index].weight || 0);
        if (randomValue <= 0) return { index, segment: LUCKY_WHEEL_SEGMENTS[index] };
      }
      return {
        index: LUCKY_WHEEL_SEGMENTS.length - 1,
        segment: LUCKY_WHEEL_SEGMENTS[LUCKY_WHEEL_SEGMENTS.length - 1]
      };
    }

    function setLuckyWheelResult(message, cls = "muted") {
      const el = document.getElementById("spinStatus") || document.getElementById("luckyWheelResult");
      if (!el) return;
      el.className = `${el.id === "spinStatus" ? "sp-status" : "lucky-wheel-result"} ${cls}`.trim();
      el.innerHTML = message;
    }

    function splitLuckyWheelText(text, maxChars = 14, maxLines = 2) {
      const words = String(text || "").trim().split(/\s+/).filter(Boolean);
      if (!words.length) return [];
      const lines = [];
      let current = "";
      let truncated = false;
      for (const word of words) {
        const next = current ? `${current} ${word}` : word;
        if (next.length <= maxChars || !current) {
          current = next;
          continue;
        }
        lines.push(current);
        current = word;
        if (lines.length >= maxLines - 1) {
          truncated = true;
          break;
        }
      }
      if (current && lines.length < maxLines) lines.push(current);
      if (truncated && lines.length) {
        lines[lines.length - 1] = `${lines[lines.length - 1]}...`;
      }
      return lines.slice(0, maxLines);
    }

    function mixLuckyWheelColor(hex, targetHex, amount = 0.5) {
      const normalize = value => {
        const text = String(value || "").replace("#", "").trim();
        const full = text.length === 3 ? text.split("").map(char => char + char).join("") : text;
        const safe = /^[0-9a-fA-F]{6}$/.test(full) ? full : "ffffff";
        return {
          r: parseInt(safe.slice(0, 2), 16),
          g: parseInt(safe.slice(2, 4), 16),
          b: parseInt(safe.slice(4, 6), 16),
        };
      };
      const start = normalize(hex);
      const end = normalize(targetHex);
      const rate = Math.max(0, Math.min(1, Number(amount || 0)));
      const toHex = part => Math.round(part).toString(16).padStart(2, "0");
      return `#${toHex(start.r + ((end.r - start.r) * rate))}${toHex(start.g + ((end.g - start.g) * rate))}${toHex(start.b + ((end.b - start.b) * rate))}`;
    }

    function renderLuckyWheelTicks() {
      const host = document.getElementById("spTicks");
      if (!host) return;
      const size = Math.max(host.clientWidth || 0, host.clientHeight || 0, 360);
      const center = size / 2;
      const radius = Math.max(120, center - (size * 0.058));
      const tickHtml = [];
      for (let index = 0; index < 60; index++) {
        const angle = index * 6;
        const major = index % 5 === 0;
        const tickWidth = major ? 4 : 3;
        const tickHeight = major ? Math.max(14, size * 0.026) : Math.max(10, size * 0.018);
        const rad = ((angle - 90) * Math.PI) / 180;
        const x = center + (Math.cos(rad) * radius);
        const y = center + (Math.sin(rad) * radius);
        tickHtml.push(
          `<div class="sp-tick${major ? " major" : ""}" style="left:${x.toFixed(2)}px;top:${y.toFixed(2)}px;width:${tickWidth}px;height:${tickHeight.toFixed(2)}px;transform:translate(-50%, -50%) rotate(${angle}deg);"></div>`
        );
      }
      host.innerHTML = tickHtml.join("");
    }

    function drawLuckyWheelCanvas() {
      const canvas = document.getElementById("spinCanvas");
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      const displaySegments = LUCKY_WHEEL_SEGMENTS.map(segment => buildLuckyWheelDisplaySegment(segment));

      const rect = canvas.getBoundingClientRect();
      const size = Math.max(320, Math.round(Math.min(rect.width || 440, rect.height || rect.width || 440)));
      const dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
      const pixelSize = Math.round(size * dpr);
      if (canvas.width !== pixelSize || canvas.height !== pixelSize) {
        canvas.width = pixelSize;
        canvas.height = pixelSize;
      }

      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.scale(dpr, dpr);

      const cx = size / 2;
      const cy = size / 2;
      const outerRadius = (size / 2) - 4;
      const step = (Math.PI * 2) / displaySegments.length;
      const startOffset = -Math.PI / 2;
      const separatorWidth = Math.max(3.2, size * 0.008);
      const labelRadius = outerRadius * 0.62;

      ctx.beginPath();
      ctx.arc(cx, cy, outerRadius, 0, Math.PI * 2);
      ctx.fillStyle = "#081427";
      ctx.fill();

      displaySegments.forEach((segment, index) => {
        const startAngle = startOffset + (index * step);
        const endAngle = startAngle + step;
        const fillGradient = ctx.createRadialGradient(cx, cy, outerRadius * 0.14, cx, cy, outerRadius);
        fillGradient.addColorStop(0, mixLuckyWheelColor(segment.color, "#ffffff", 0.28));
        fillGradient.addColorStop(0.46, segment.color);
        fillGradient.addColorStop(1, mixLuckyWheelColor(segment.color, "#071120", 0.18));

        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.arc(cx, cy, outerRadius, startAngle, endAngle);
        ctx.closePath();
        ctx.fillStyle = fillGradient;
        ctx.fill();

        ctx.save();
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.arc(cx, cy, outerRadius, startAngle, endAngle);
        ctx.closePath();
        const gloss = ctx.createLinearGradient(
          cx + Math.cos(startAngle) * outerRadius,
          cy + Math.sin(startAngle) * outerRadius,
          cx + Math.cos(endAngle) * outerRadius,
          cy + Math.sin(endAngle) * outerRadius
        );
        gloss.addColorStop(0, "rgba(255,255,255,.18)");
        gloss.addColorStop(0.4, "rgba(255,255,255,.04)");
        gloss.addColorStop(1, "rgba(6,12,24,.12)");
        ctx.fillStyle = gloss;
        ctx.fill();
        ctx.restore();

        const midAngle = startAngle + (step / 2);
        const x = cx + Math.cos(midAngle) * labelRadius;
        const y = cy + Math.sin(midAngle) * labelRadius;
        const isLeftSide = midAngle > (Math.PI / 2) && midAngle < (Math.PI * 1.5);
        const rewardLines = splitLuckyWheelText(segment.short, segment.short.length >= 8 ? 9 : 10, 2);
        const descLines = segment.desc ? splitLuckyWheelText(segment.desc, 10, 1) : [];
        const rewardFont = Math.round(size * (segment.short.length >= 8 ? 0.042 : 0.048));
        const descFont = Math.round(size * 0.022);
        const rewardOffset = descLines.length ? -rewardFont * 0.34 : 0;

        ctx.save();
        ctx.translate(x, y);
        ctx.rotate(midAngle + Math.PI / 2 + (isLeftSide ? Math.PI : 0));
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillStyle = "#ffffff";
        ctx.shadowColor = "rgba(3,8,18,.45)";
        ctx.shadowBlur = 12;
        ctx.font = `900 ${rewardFont}px "Segoe UI", sans-serif`;
        rewardLines.forEach((lineText, lineIndex) => {
          const rowOffset = rewardOffset + (lineIndex * rewardFont * 0.86);
          ctx.fillText(lineText, 0, rowOffset);
        });
        if (descLines.length) {
          ctx.globalAlpha = 0.96;
          ctx.font = `800 ${descFont}px "Segoe UI", sans-serif`;
          if (segment.descVariant === "paypal") ctx.fillStyle = "#ffe7a3";
          else if (segment.descVariant === "diamond") ctx.fillStyle = "#cbfff1";
          else if (segment.descVariant === "spins") ctx.fillStyle = "#dcecff";
          else ctx.fillStyle = "#f4e8ff";
          descLines.forEach((lineText, lineIndex) => {
            ctx.fillText(lineText, 0, (rewardFont * 0.76) + (lineIndex * descFont * 1.06));
          });
          ctx.globalAlpha = 1;
          ctx.fillStyle = "#ffffff";
        }
        ctx.restore();
      });

      ctx.save();
      ctx.strokeStyle = "rgba(255,255,255,.9)";
      ctx.lineWidth = separatorWidth;
      for (let index = 0; index < displaySegments.length; index++) {
        const angle = startOffset + (index * step);
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(cx + Math.cos(angle) * outerRadius, cy + Math.sin(angle) * outerRadius);
        ctx.stroke();
      }
      ctx.restore();

      ctx.beginPath();
      ctx.arc(cx, cy, outerRadius - 1, 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(255,255,255,.32)";
      ctx.lineWidth = Math.max(4, size * 0.010);
      ctx.stroke();

      const topGloss = ctx.createRadialGradient(
        cx,
        cy - outerRadius * 0.72,
        outerRadius * 0.06,
        cx,
        cy - outerRadius * 0.56,
        outerRadius * 0.86
      );
      topGloss.addColorStop(0, "rgba(255,255,255,.16)");
      topGloss.addColorStop(0.34, "rgba(255,255,255,.04)");
      topGloss.addColorStop(1, "rgba(255,255,255,0)");
      ctx.beginPath();
      ctx.arc(cx, cy, outerRadius * 0.94, 0, Math.PI * 2);
      ctx.fillStyle = topGloss;
      ctx.fill();
    }

    function renderLuckyWheelLabels() {
      const disc = document.getElementById("luckyWheelDisc");
      if (!disc) return;
      disc.style.transform = `rotate(${luckyWheelRotation}deg)`;
      renderLuckyWheelTicks();
      drawLuckyWheelCanvas();
    }

    function renderLuckyWheelPrizeGrid() {
      const grid = document.getElementById("luckyWheelPrizeGrid");
      if (!grid) return;
      const totalWeight = LUCKY_WHEEL_SEGMENTS.reduce((sum, segment) => sum + Number(segment.weight || 0), 0) || 1;
      const displaySegments = LUCKY_WHEEL_SEGMENTS
        .map(segment => buildLuckyWheelDisplaySegment(segment))
        .sort((left, right) => {
        const leftScore = getLuckyWheelPrizeDisplayScore(left);
        const rightScore = getLuckyWheelPrizeDisplayScore(right);
        if (rightScore !== leftScore) return rightScore - leftScore;
        return Number(right.weight || 0) - Number(left.weight || 0);
      });
      grid.innerHTML = displaySegments.map(segment => {
        const percent = (Number(segment.weight || 0) / totalWeight) * 100;
        const rarity = getLuckyWheelRarityMeta(percent);
        return `
        <div class="lucky-wheel-prize-card" style="background: linear-gradient(155deg, ${segment.color}, rgba(11, 18, 31, .92));">
          <div class="lucky-wheel-prize-title">${escapeHtml(segment.label)}</div>
          <div class="lucky-wheel-prize-desc type-${escapeHtml(segment.descVariant || "combo")}">${escapeHtml(segment.desc)}</div>
          <span class="lucky-wheel-prize-weight ${escapeHtml(rarity.className)}">${escapeHtml(rarity.label)}</span>
        </div>
      `;
      }).join("");
    }

    function renderLuckyWheelHistory() {
      ensureLuckyWheelState();
      const list = document.getElementById("luckyWheelHistory");
      const count = document.getElementById("luckyWheelHistoryCount");
      if (!list || !count) return;
      count.textContent = `${store.luckyWheelHistory.length} lượt`;
      if (!store.luckyWheelHistory.length) {
        list.innerHTML = `<div class="lucky-wheel-empty">Chưa có lịch sử quay. Lượt đầu tiên sẽ xuất hiện ở đây.</div>`;
        return;
      }
      list.innerHTML = store.luckyWheelHistory.slice(0, MAX_LUCKY_WHEEL_HISTORY).map(entry => `
        <div class="lucky-wheel-history-item">
          <strong>${escapeHtml(entry.label || "Vòng quay")}</strong>
          <div class="lucky-wheel-history-reward">${escapeHtml(entry.rewardText || "")}</div>
          <div class="lucky-wheel-history-time">
            ${escapeHtml(entry.timeText || "")}
          </div>
        </div>
      `).join("");
    }

    function renderLuckyWheelAutoButton() {
      const autoBtn = document.getElementById("luckyWheelAutoBtn");
      if (!autoBtn) return;
      autoBtn.classList.remove("active");
      autoBtn.textContent = "Mua Thêm Lượt Quay";
    }

    function renderLuckyWheelTopupHistory() {
      ensureLuckyWheelState();
      const list = document.getElementById("luckyWheelTopupHistoryList");
      const count = document.getElementById("luckyWheelTopupHistoryCount");
      if (!list || !count) return;
      const entries = Array.isArray(store.luckyWheelTopupHistory) ? store.luckyWheelTopupHistory : [];
      count.textContent = `${entries.length} giao dịch`;
      if (!entries.length) {
        list.innerHTML = `<div class="spin-topup-history-empty">Chưa có lịch sử đổi lượt. Giao dịch đầu tiên của bạn sẽ hiện tại đây.</div>`;
        return;
      }
      list.innerHTML = entries.slice(0, MAX_LUCKY_WHEEL_TOPUP_HISTORY).map(entry => `
        <div class="spin-topup-history-item">
          <div class="spin-topup-history-top">
            <strong>+${escapeHtml(formatLuckyWheelAmount(entry.spins || 0))} lượt quay</strong>
            <span class="spin-topup-history-cost">-${escapeHtml(formatLuckyWheelAmount(entry.paypalCost || 0))} PP</span>
          </div>
          <div class="spin-topup-history-note">
            Sau đổi: <b>${escapeHtml(formatLuckyWheelAmount(entry.afterStoredSpins || 0))}/${escapeHtml(formatLuckyWheelAmount(LUCKY_WHEEL_MAX_SPINS))}</b> lượt trong kho
          </div>
          <div class="spin-topup-history-time">${escapeHtml(entry.timeText || "")}</div>
        </div>
      `).join("");
    }

    function renderLuckyWheelMultiplierButtons(availableSpins = getLuckyWheelAvailableSpins()) {
      const currentMultiplier = getLuckyWheelSpinMultiplier();
      document.querySelectorAll(".sp-multiplier-btn").forEach(button => {
        const value = Math.max(1, Math.floor(Number(button.dataset.multiplier || 1)));
        button.classList.toggle("active", value === currentMultiplier);
        button.disabled = luckyWheelSpinning || availableSpins < value;
      });
    }

    function setLuckyWheelSpinMultiplier(multiplier) {
      const nextValue = Math.max(1, Math.floor(Number(multiplier || 1)));
      if (![1, 3, 5, 10].includes(nextValue)) return;
      luckyWheelSpinMultiplier = nextValue;
      renderLuckyWheelLabels();
      renderLuckyWheelPrizeGrid();
      renderLuckyWheelMeta();
      setLuckyWheelResult(`Đã chọn chế độ quay <b>x${nextValue}</b>. Mỗi lần quay sẽ tiêu tốn <b>${nextValue}</b> lượt và nhân quà tương ứng.`, "muted");
    }

    function stopLuckyWheelAutoMode(message = "", cls = "muted") {
      luckyWheelAutoMode = false;
      renderLuckyWheelMeta();
      if (message) setLuckyWheelResult(message, cls);
    }

    function openLuckyWheelTopup() {
      luckyWheelAutoMode = false;
      renderLuckyWheelAutoButton();
      renderLuckyWheelMeta();
      luckyWheelSelectedTopupSpins = 0;
      renderLuckyWheelTopupDialog();
      const overlay = document.getElementById("luckyWheelTopupOverlay");
      if (overlay) overlay.hidden = false;
    }

    function renderLuckyWheelEnergy(snapshot) {
      const fill = document.getElementById("spinEnergyFill");
      const count = document.getElementById("spinEnergyCount");
      const next = document.getElementById("spinEnergyNext");
      if (!fill || !count || !next) return;
      const available = Math.max(0, Number(snapshot?.available || 0));
      const max = Math.max(1, Number(snapshot?.max || LUCKY_WHEEL_MAX_SPINS));
      const ratio = Math.max(0, Math.min(1, available / max));
      fill.style.width = `${(ratio * 100).toFixed(2)}%`;
      count.textContent = `${available}/${max}`;
      next.textContent = available >= max
        ? "Đã đầy kho lượt"
        : `+1 lượt sau ${formatLuckyWheelCountdown(snapshot.nextRegenMs)}`;
    }

    function renderLuckyWheelMilestones() {
      const stateChanged = ensureLuckyWheelState();
      if (stateChanged) saveStore();
      const fill = document.getElementById("spinMilestoneFill");
      const markers = document.getElementById("spinMilestoneMarkers");
      const meta = document.getElementById("spinMilestoneMeta");
      const next = document.getElementById("spinMilestoneNext");
      if (!fill || !markers || !meta || !next) return;
      const totalSpins = Math.max(0, Number(store?.luckyWheelDailySpinCount || 0));
      const maxMilestone = LUCKY_WHEEL_GIFT_MILESTONES[LUCKY_WHEEL_GIFT_MILESTONES.length - 1] || 1;
      const ratio = Math.max(0, Math.min(1, totalSpins / maxMilestone));
      fill.style.width = `${(ratio * 100).toFixed(2)}%`;
      fill.style.height = "100%";
      markers.innerHTML = LUCKY_WHEEL_GIFT_MILESTONES.map((value, index) => {
        const progress = (value / maxMilestone) * 100;
        const done = totalSpins >= value;
        return `
          <div class="sp-milestone-marker ${done ? "done" : ""} ${index === LUCKY_WHEEL_GIFT_MILESTONES.length - 1 ? "edge-end" : ""}" style="left:${progress.toFixed(2)}%">
            <span class="sp-milestone-icon">🎁</span>
            <span class="sp-milestone-value">${escapeHtml(String(value))}</span>
          </div>
        `;
      }).join("");
      const nextMilestone = LUCKY_WHEEL_GIFT_MILESTONES.find(value => totalSpins < value);
      meta.textContent = nextMilestone
        ? `Còn ${formatLuckyWheelAmount(nextMilestone - totalSpins)} lượt để mở mốc ${formatLuckyWheelAmount(nextMilestone)}`
        : "Đã chạm toàn bộ mốc hộp quà hôm nay";
      next.textContent = `Reset sau ${formatLuckyWheelCountdown(getLuckyWheelNextDayResetMs())} • 1 ngày reset lại`;
    }

    function maybeTriggerLuckyWheelAutoSpin() {
      if (!luckyWheelAutoMode || luckyWheelSpinning) return;
      const available = getLuckyWheelAvailableSpins();
      const required = getLuckyWheelSpinMultiplier();
      if (available < required) {
        stopLuckyWheelAutoMode(`Không đủ lượt cho chế độ <b>x${required}</b>. Chế độ tự động đã dừng.`, "warn");
        return;
      }
      window.setTimeout(() => {
        if (!luckyWheelAutoMode || luckyWheelSpinning || getLuckyWheelAvailableSpins() < getLuckyWheelSpinMultiplier()) return;
        spinLuckyWheel();
      }, 180);
    }

    function renderLuckyWheelMeta() {
      const snapshot = syncLuckyWheelSpins();
      const spinBtn = document.getElementById("luckyWheelSpinBtn");
      const centerBtn = document.getElementById("luckyWheelCenterBtn");
      const balance = document.getElementById("spBalance");
      renderLuckyWheelAutoButton();
      if (!spinBtn) return;
      renderLuckyWheelEnergy(snapshot);
      renderLuckyWheelMilestones();
      const availableSpins = snapshot.available;
      luckyWheelLastAvailable = availableSpins;
      if (snapshot.changed) saveStore();
      renderLuckyWheelMultiplierButtons(availableSpins);
      if (balance) {
        balance.textContent = `${formatLuckyWheelAmount(store.paypalBalance || 0)} PP • ${formatLuckyWheelAmount(store.diamondBalance || 0)} KC`;
      }
      const required = getLuckyWheelSpinMultiplier();
      if (luckyWheelAutoMode) {
        spinBtn.disabled = false;
        spinBtn.textContent = `⏹ DỪNG x${required}`;
      } else {
        spinBtn.disabled = luckyWheelSpinning || availableSpins < required;
        spinBtn.textContent = luckyWheelSpinning ? `🎰 Đang quay x${required}...` : `🎰 QUAY TỰ ĐỘNG x${required}`;
      }
      if (centerBtn) {
        centerBtn.classList.toggle("is-disabled", luckyWheelSpinning || availableSpins < required);
        centerBtn.setAttribute("aria-disabled", luckyWheelSpinning || availableSpins < required ? "true" : "false");
      }
    }

    function renderLuckyWheelPanel() {
      renderLuckyWheelLabels();
      renderLuckyWheelPrizeGrid();
      renderLuckyWheelHistory();
      renderLuckyWheelMeta();
      if (!document.getElementById("luckyWheelTopupOverlay")?.hidden) {
        updateLuckyWheelTopupDialogState();
      }
      if (!store?.luckyWheelLastResult) {
        setLuckyWheelResult("Chưa quay. Mỗi <b>10 phút</b> hồi 1 lượt, tối đa <b>60/60</b> lượt.", "muted");
        return;
      }
      const last = store.luckyWheelLastResult;
      setLuckyWheelResult(
        `<b>${escapeHtml(last.label || "Vòng quay may mắn")}</b><br>${escapeHtml(last.rewardText || "")}<br><span style="opacity:.78">${escapeHtml(last.timeText || "")}</span>`,
        "ok"
      );
    }

    function closeSpinPopup() {
      if (typeof scrollToAppSection === "function") {
        scrollToAppSection("appHomeAnchor", "homeMenuBtn");
        return;
      }
      window.scrollTo({ top: 0, behavior: "smooth" });
    }

    function toggleLuckyWheelAutoMode() {
      if (luckyWheelAutoMode) {
        stopLuckyWheelAutoMode("Đã tắt <b>quay tự động</b>.", "muted");
        return;
      }
      const available = getLuckyWheelAvailableSpins();
      const required = getLuckyWheelSpinMultiplier();
      if (available < required) {
        renderLuckyWheelMeta();
        setLuckyWheelResult(`Không đủ lượt để bật chế độ <b>x${required}</b>.`, "warn");
        return;
      }
      luckyWheelAutoMode = true;
      renderLuckyWheelMeta();
      setLuckyWheelResult(`Đã bật <b>quay tự động x${required}</b>. Hệ thống sẽ quay cho đến khi không đủ lượt.`, "ok");
      maybeTriggerLuckyWheelAutoSpin();
    }

    function applyLuckyWheelReward(segment, spinSource, multiplier = 1) {
      const snapshot = syncLuckyWheelSpins();
      const safeMultiplier = Math.max(1, Math.floor(Number(multiplier || 1)));
      const displaySegment = buildLuckyWheelDisplaySegment(segment, safeMultiplier);
      const reward = displaySegment.reward || {};
      const diamond = Math.max(0, Number(reward.diamond || 0));
      const paypal = Math.max(0, Number(reward.paypal || 0));
      const bonusSpins = Math.max(0, Number(reward.bonusSpins || 0));
      store.diamondBalance = Math.max(0, Number(store.diamondBalance || 0)) + diamond;
      store.paypalBalance = Math.max(0, Number(store.paypalBalance || 0)) + paypal;
      if (bonusSpins > 0) {
        store.luckyWheelStoredSpins = Math.min(LUCKY_WHEEL_MAX_SPINS, snapshot.available + bonusSpins);
        if (store.luckyWheelStoredSpins >= LUCKY_WHEEL_MAX_SPINS) {
          store.luckyWheelLastRegenAt = getSyncedIsoString();
        }
      }
      store.luckyWheelSpinCount = Math.max(0, Number(store.luckyWheelSpinCount || 0)) + safeMultiplier;
      store.luckyWheelMilestoneDayKey = getLuckyWheelTodayKey();
      store.luckyWheelDailySpinCount = Math.max(0, Number(store.luckyWheelDailySpinCount || 0)) + safeMultiplier;
      const now = getSyncedNowDate();
      const historyEntry = {
        at: now.toISOString(),
        label: displaySegment.label,
        reward: { diamond, paypal, bonusSpins },
        rewardText: buildLuckyWheelRewardText({ diamond, paypal, bonusSpins }),
        source: spinSource,
        multiplier: safeMultiplier,
        timeText: now.toLocaleString("vi-VN"),
      };
      store.luckyWheelLastResult = historyEntry;
      store.luckyWheelHistory.unshift(historyEntry);
      while (store.luckyWheelHistory.length > MAX_LUCKY_WHEEL_HISTORY) {
        store.luckyWheelHistory.pop();
      }
      renderCurrencyBar();
      renderLuckyWheelPanel();
      saveStore();
      setLuckyWheelResult(
        `<b>Chúc mừng!</b><br>Bạn nhận được <b>${escapeHtml(historyEntry.rewardText)}</b>.<br><span style="opacity:.78">${escapeHtml(historyEntry.timeText)}</span>`,
        "ok"
      );
      maybeTriggerLuckyWheelAutoSpin();
    }

    function spinLuckyWheel() {
      if (luckyWheelSpinning) return;
      const multiplier = getLuckyWheelSpinMultiplier();
      const consume = consumeLuckyWheelSpin(multiplier);
      if (!consume.ok) {
        if (luckyWheelAutoMode) {
          stopLuckyWheelAutoMode(`Không đủ lượt cho chế độ <b>x${multiplier}</b>. Còn <b>${formatLuckyWheelCountdown(consume.nextRegenMs)}</b> để hồi thêm lượt.`, "warn");
        } else {
          renderLuckyWheelMeta();
          setLuckyWheelResult(`Không đủ lượt cho chế độ <b>x${multiplier}</b>. Còn <b>${formatLuckyWheelCountdown(consume.nextRegenMs)}</b> để hồi thêm lượt.`, "warn");
        }
        return;
      }
      saveStore();

      const disc = document.getElementById("luckyWheelDisc");
      if (!disc) return;
      const picked = pickLuckyWheelSegment();
      const displaySegment = buildLuckyWheelDisplaySegment(picked.segment, multiplier);
      const segmentAngle = 360 / LUCKY_WHEEL_SEGMENTS.length;
      const segmentCenter = (picked.index * segmentAngle) + (segmentAngle / 2);
      const normalizedCurrent = ((luckyWheelRotation % 360) + 360) % 360;
      const targetNormalized = (360 - segmentCenter) % 360;
      const delta = (targetNormalized - normalizedCurrent + 360) % 360;
      luckyWheelRotation += ((6 + Math.floor(Math.random() * 2)) * 360) + delta;
      luckyWheelSpinning = true;
      renderLuckyWheelMeta();
      setLuckyWheelResult(`Đang quay <b>x${multiplier}</b>... mục tiêu hiện tại là <b>${escapeHtml(displaySegment.label)}</b>.`, "muted");
      disc.style.transform = `rotate(${luckyWheelRotation}deg)`;

      window.setTimeout(() => {
        luckyWheelSpinning = false;
        applyLuckyWheelReward(picked.segment, consume.source, multiplier);
      }, 5300);
    }

    function startLuckyWheelUiTimer() {
      if (luckyWheelUiTimer) clearInterval(luckyWheelUiTimer);
      luckyWheelUiTimer = window.setInterval(() => {
        if (document.hidden) return;
        const topupOverlay = document.getElementById("luckyWheelTopupOverlay");
        const topupOpen = !!topupOverlay && !topupOverlay.hidden;
        const wheelVisible = getCurrentAppPageMode() === "wheel" && isElementActuallyVisible(document.getElementById("luckyWheelSection"));
        if (!wheelVisible && !topupOpen && !luckyWheelAutoMode) return;
        if (luckyWheelSpinning) return;
        const snapshot = syncLuckyWheelSpins();
        if (snapshot.changed || snapshot.available !== luckyWheelLastAvailable) {
          renderLuckyWheelPanel();
          maybeTriggerLuckyWheelAutoSpin();
          return;
        }
        renderLuckyWheelMeta();
        if (topupOpen) {
          updateLuckyWheelTopupDialogState();
        }
        maybeTriggerLuckyWheelAutoSpin();
      }, 1000);
    }

    function resetLuckyWheelHistory() {
      ensureLuckyWheelState();
      store.luckyWheelHistory = [];
      store.luckyWheelLastResult = null;
      renderLuckyWheelPanel();
      saveStore();
    }

    function setSideMenuActiveButton(buttonId) {
      document.querySelectorAll("#sideMenu .side-link").forEach(button => {
        button.classList.toggle("active", button.id === buttonId);
      });
    }

    function setPrimaryContentVisible(visible = true) {
      ["appHomeAnchor", "lotteryMenuPanel", "liveBoardSection", "mainContentGrid"].forEach(sectionId => {
        const section = document.getElementById(sectionId);
        if (!section) return;
        section.hidden = !visible;
      });
    }

    function setAuxiliarySectionsVisible(activeSectionId = "") {
      ["luckyWheelSection", "paypalDepositSection", "dataTableSection"].forEach(sectionId => {
        const section = document.getElementById(sectionId);
        if (!section) return;
        section.hidden = sectionId !== activeSectionId;
      });
    }

    function openAuxiliarySection(sectionId, menuButtonId = "") {
      setAuxiliarySectionsVisible(sectionId);
      scrollToAppSection(sectionId, menuButtonId);
    }

    function navigateToAppPage(mode = "home") {
      const safeMode = APP_PAGE_PATHS[mode] ? mode : "home";
      const targetPath = APP_PAGE_PATHS[safeMode];
      if (getCurrentAppPageMode() === safeMode) {
        applyAppPageLayout();
        closeSideMenu();
        return;
      }
      closeSideMenu();
      if (window.history && typeof window.history.pushState === "function") {
        window.history.pushState({ appPageMode: safeMode }, "", targetPath);
        applyAppPageLayout();
        window.scrollTo({ top: 0, behavior: "auto" });
        return;
      }
      window.location.assign(targetPath);
    }

    function applyAppPageLayout() {
      const mode = getCurrentAppPageMode();
      applyAppPageMetadata();
      document.body.dataset.appPage = mode;
      if (mode === "wheel") {
        setPrimaryContentVisible(false);
        setAuxiliarySectionsVisible("luckyWheelSection");
        setSideMenuActiveButton("luckyWheelMenuBtn");
        renderLuckyWheelPanel();
        return;
      }
      if (mode === "deposit") {
        setPrimaryContentVisible(false);
        setAuxiliarySectionsVisible("paypalDepositSection");
        setSideMenuActiveButton("paypalDepositMenuBtn");
        renderPaypalDepositSection();
        return;
      }
      if (mode === "data") {
        setPrimaryContentVisible(false);
        setAuxiliarySectionsVisible("dataTableSection");
        setSideMenuActiveButton("dataTableMenuBtn");
        renderDataTableShell();
        loadDataTableRows();
        return;
      }
      setPrimaryContentVisible(true);
      setAuxiliarySectionsVisible("");
      setSideMenuActiveButton("homeMenuBtn");
      renderPrizePanel();
      renderLiveResultsBoard();
      renderLiveHistoryOutput();
    }

    function scrollToAppSection(sectionId, menuButtonId = "") {
      const section = document.getElementById(sectionId);
      if (!section) return;
      if (menuButtonId) setSideMenuActiveButton(menuButtonId);
      closeSideMenu();
      section.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    function fillTypeSelect(id) {
      const el = document.getElementById(id);
      if (!el) return;
      el.innerHTML = TYPE_KEYS.map(k => `<option value="${k}">${id === "prizeType" ? (PRIZE_TYPE_SHORT_LABELS[k] || TYPES[k].label) : TYPES[k].label}</option>`).join("");
    }

    function fillLiveHistoryTypeSelect() {
      const el = document.getElementById("liveHistoryType");
      if (!el) return;
      el.innerHTML = LIVE_HISTORY_TYPES.map(item => `<option value="${item.key}">${item.label}</option>`).join("");
    }

    function isKenoLiveHistoryRangeKey(value) {
      const normalized = String(value || "").trim().toLowerCase();
      return Object.prototype.hasOwnProperty.call(KENO_LIVE_HISTORY_COUNT_LABELS, normalized);
    }

    function getLiveHistoryCountOptions(type) {
      return type === "KENO" ? KENO_LIVE_HISTORY_COUNT_OPTIONS : DEFAULT_LIVE_HISTORY_COUNT_OPTIONS;
    }

    function getDefaultLiveHistoryCountKey(type) {
      return "2";
    }

    function getKenoLiveHistoryRangeLabel(countKey) {
      return KENO_LIVE_HISTORY_COUNT_LABELS[String(countKey || "").trim().toLowerCase()] || "Tất cả Kỳ";
    }

    function syncLiveHistoryCountOptions() {
      const type = document.getElementById("liveHistoryType")?.value || LIVE_HISTORY_TYPES[0]?.key || "LOTO_5_35";
      const labelEl = document.getElementById("liveHistoryCountLabel");
      const selectEl = document.getElementById("liveHistoryCount");
      if (!selectEl) return;
      const currentValue = String(selectEl.value || "").trim().toLowerCase();
      const options = getLiveHistoryCountOptions(type);
      selectEl.innerHTML = options.map(item => `<option value="${item.value}">${item.label}</option>`).join("");
      const allowedValues = new Set(options.map(item => item.value));
      selectEl.value = allowedValues.has(currentValue) ? currentValue : getDefaultLiveHistoryCountKey(type);
      if (labelEl) {
        labelEl.textContent = type === "KENO" ? "Số kỳ" : "Số kỳ gần nhất";
      }
    }

    ["prizeType", "pdType", "vipPdType", "dataTableType"].forEach(fillTypeSelect);
    fillLiveHistoryTypeSelect();
    syncLiveHistoryCountOptions();

    function setTypeSelectValue(id, value) {
      const el = document.getElementById(id);
      if (!el) return;
      if (!Array.from(el.options).some(opt => opt.value === value)) return;
      el.value = value;
      el.dispatchEvent(new Event("change", { bubbles: true }));
    }

    function syncLotteryMenuActive(typeKey) {
      document.querySelectorAll(".lottery-menu-btn").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.type === typeKey);
      });
    }

    function applyLotteryMenuType(typeKey) {
      const menuItem = LOTTERY_MENU_TYPES.find(item => item.key === typeKey);
      if (!menuItem) return;

      const note = document.getElementById("lotteryMenuNote");
      syncLotteryMenuActive(typeKey);

      if (menuItem.supported && TYPES[typeKey]) {
        ["rType","pType","vType","prizeType","sType","oType","pdType","vipPdType","lType","dType"].forEach(id => {
          setTypeSelectValue(id, typeKey);
        });
        note.className = "lottery-menu-note";
        note.textContent = `Đã đồng bộ nhanh loại ${menuItem.label} cho các khung chính. Bạn có thể nhập liệu, thống kê và dự đoán ngay.`;
      } else {
        note.className = "lottery-menu-note warn";
        note.textContent = `${menuItem.label} đã xuất hiện trong bảng menu. Hiện đã có bảng live và lịch sử CSV tự động, nhưng logic nhập liệu và tra cứu riêng cho loại này mình chưa nối vào công cụ hiện tại.`;
      }
    }

    function renderLotteryMenu() {
      const host = document.getElementById("lotteryMenuGrid");
      if (!host) return;
      host.innerHTML = LOTTERY_MENU_TYPES.map(item => `
        <button
          type="button"
          class="lottery-menu-btn ${item.supported ? "" : "coming-soon"}"
          data-type="${item.key}"
        >
          <span class="name">${item.label}</span>
          <span class="desc">${item.desc}</span>
          <span class="badge">${item.badge}</span>
        </button>
      `).join("");

      host.querySelectorAll(".lottery-menu-btn").forEach(btn => {
        btn.addEventListener("click", () => applyLotteryMenuType(btn.dataset.type));
      });

      applyLotteryMenuType("LOTO_6_45");
    }

    function closeAllCustomSelects(except = null) {
      document.querySelectorAll(".select-shell.open").forEach(shell => {
        if (except && shell === except) return;
        shell.classList.remove("open");
        shell.classList.remove("open-up");
        const card = shell.closest(".card");
        if (card) card.style.zIndex = "";
      });
    }

    function updateSelectMenuDirection(shell, menu) {
      if (!shell || !menu) return;
      shell.classList.remove("open-up");
      if (shell.dataset.selectId === "pdKenoLevel") return;
      const rect = shell.getBoundingClientRect();
      const viewportH = window.innerHeight || document.documentElement.clientHeight || 0;
      const spaceBelow = viewportH - rect.bottom;
      const spaceAbove = rect.top;
      const desired = Math.min(menu.scrollHeight || 240, 320);
      if (spaceBelow < desired && spaceAbove > spaceBelow) {
        shell.classList.add("open-up");
      }
    }

    function enhanceSelect(selectId) {
      const sel = document.getElementById(selectId);
      if (!sel || sel.dataset.customized === "1") return;
      sel.dataset.customized = "1";
      sel.classList.add("native-hidden-select");

      const shell = document.createElement("div");
      shell.className = "select-shell";
      shell.dataset.selectId = selectId;

      const trigger = document.createElement("button");
      trigger.type = "button";
      trigger.className = "select-trigger";
      trigger.innerHTML = `<span class="select-label"></span><span class="select-caret"></span>`;

      const menu = document.createElement("div");
      menu.className = "select-menu";

      const renderOptions = () => {
        menu.innerHTML = "";
        Array.from(sel.options).forEach(opt => {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "select-option";
          btn.textContent = opt.text;
          btn.dataset.value = opt.value;
          btn.onclick = () => {
            sel.value = opt.value;
            sel.dispatchEvent(new Event("change", { bubbles: true }));
            syncLabelAndActive();
            shell.classList.remove("open");
            shell.classList.remove("open-up");
            const card = shell.closest(".card");
            if (card) card.style.zIndex = "";
          };
          menu.appendChild(btn);
        });
      };

      const syncLabelAndActive = () => {
        renderOptions();
        const txt = sel.options[sel.selectedIndex]?.text || "";
        trigger.querySelector(".select-label").textContent = txt;
        menu.querySelectorAll(".select-option").forEach(btn => {
          btn.classList.toggle("active", btn.dataset.value === sel.value);
        });
      };

      trigger.onclick = () => {
        closeAllCustomSelects(shell);
        shell.classList.toggle("open");
        if (shell.classList.contains("open") && (selectId === "pdKenoLevel" || selectId === "rKenoLevel")) {
          menu.scrollTop = 0;
        }
        if (shell.classList.contains("open")) {
          const card = shell.closest(".card");
          if (card) card.style.zIndex = "1800";
          updateSelectMenuDirection(shell, menu);
        } else {
          shell.classList.remove("open-up");
          const card = shell.closest(".card");
          if (card) card.style.zIndex = "";
        }
      };

      sel.addEventListener("change", syncLabelAndActive);
      sel.__syncCustomSelect = syncLabelAndActive;
      window.addEventListener("resize", () => {
        if (shell.classList.contains("open")) updateSelectMenuDirection(shell, menu);
      });

      sel.insertAdjacentElement("afterend", shell);
      shell.appendChild(trigger);
      shell.appendChild(menu);
      syncLabelAndActive();
    }

    function normalizePredictRecentWindowSelection() {
      const select = document.getElementById("pdRecentWindow");
      if (!select) return;
      const allowed = new Set(["0", "1", "2", "3", "5"]);
      const normalized = String(select.value ?? "").trim().toLowerCase();
      if (!allowed.has(normalized)) {
        select.value = "0";
        select.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }

    function syncPredictBaoOptions() {
      const pdType = String(document.getElementById("pdType")?.value || "").trim().toUpperCase();
      const pdPlayMode = String(document.getElementById("pdPlayMode")?.value || predictPlayModeValue || "normal").trim().toLowerCase();
      const playModeRow = document.getElementById("pdPlayModeRow");
      const baoRow = document.getElementById("pdBaoRow");
      const baoSelect = document.getElementById("pdBaoLevel");
      if (!baoRow || !baoSelect) return;
      const levels = getPredictBaoLevels(pdType);
      if (playModeRow) playModeRow.style.display = levels.length ? "grid" : "none";
      const shouldShow = pdPlayMode === "bao" && levels.length > 0;
      baoRow.style.display = shouldShow ? "grid" : "none";
      if (playModeRow) playModeRow.classList.toggle("has-bao", shouldShow);
      if (!levels.length) {
        baoSelect.innerHTML = "";
        baoSelect.value = "";
        predictBaoLevelValue = "";
        baoSelect.dispatchEvent(new Event("change", { bubbles: true }));
        return;
      }
      const currentValue = String(baoSelect.value || predictBaoLevelValue || levels[0]).trim();
      baoSelect.innerHTML = levels.map(level => `<option value="${level}">Bao ${level}</option>`).join("");
      baoSelect.value = levels.map(String).includes(currentValue) ? currentValue : String(levels[0]);
      predictBaoLevelValue = String(baoSelect.value || "");
      baoSelect.dispatchEvent(new Event("change", { bubbles: true }));
    }

    [
      "prizeType",
      "pdType",
      "pdRecentWindow",
      "pdPlayMode",
      "pdBaoLevel",
      "pdEngine",
      "pdKenoLevel",
      "statsTypeSelect",
      "statsWindowSelect",
      "lottoDashboardGameSelect",
      "chartStatsTypeSelect",
      "chartStatsPresetSelect",
      "chartStatsViewSelect",
      "dataTableType",
      "dataTableLimit",
      "dataTableWeekday",
      "dataTableDay",
      "dataTableMonth",
      "dataTableYear"
    ].forEach(enhanceSelect);
    normalizePredictRecentWindowSelection();
    renderLotteryMenu();
    const initialPredictTypeEl = document.getElementById("pdType");
    if (initialPredictTypeEl && Array.from(initialPredictTypeEl.options).some(option => option.value === "KENO")) {
      initialPredictTypeEl.value = "KENO";
      initialPredictTypeEl.dispatchEvent(new Event("change", { bubbles: true }));
    }

    document.addEventListener("click", e => {
      if (!e.target.closest(".select-shell")) closeAllCustomSelects();
    });
    document.addEventListener("keydown", e => {
      if (e.key === "Escape") closeAllCustomSelects();
    });
    document.getElementById("themeToggleBtn").onclick = () => {
      const next = document.body.classList.contains("light-theme") ? "dark" : "light";
      applyTheme(next);
    };
    applyTheme(localStorage.getItem(THEME_KEY) || "dark");
    applyAppPageMetadata();
    const brandReloadBtn = document.getElementById("brandReloadBtn");
    if (brandReloadBtn) {
      brandReloadBtn.dataset.tooltip = `${APP_SHORT_NAME} là tên viết tắt của ${APP_FULL_NAME}`;
      brandReloadBtn.onclick = () => window.location.reload();
    }
    document.getElementById("notificationBtn").onclick = () => toggleHeaderPopover("notificationBtn", "notificationPanel");
    document.getElementById("settingsBtn").onclick = () => toggleHeaderPopover("settingsBtn", "settingsPanel");
    document.getElementById("notificationMarkReadBtn").onclick = markHeaderNotificationsRead;
    document.getElementById("notificationClearBtn").onclick = clearHeaderNotifications;
    document.getElementById("settingsReloadBtn").onclick = () => window.location.reload();
    document.addEventListener("click", event => {
      if (!event.target.closest(".header-tool-wrap")) closeHeaderPopovers();
    });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape") closeHeaderPopovers();
    });

    function openSideMenu() {
      closeHeaderPopovers();
      document.getElementById("sideMenu").classList.add("show");
      document.getElementById("sideMenuOverlay").classList.add("show");
    }
    function closeSideMenu() {
      document.getElementById("sideMenu").classList.remove("show");
      document.getElementById("sideMenuOverlay").classList.remove("show");
    }
    document.getElementById("menuToggleBtn").onclick = openSideMenu;
    document.getElementById("sideMenuCloseBtn").onclick = closeSideMenu;
    document.getElementById("sideMenuOverlay").onclick = closeSideMenu;
    document.getElementById("homeMenuBtn").onclick = () => {
      navigateToAppPage("home");
    };
    document.getElementById("paypalDepositMenuBtn").onclick = () => {
      navigateToAppPage("deposit");
    };
    document.getElementById("luckyWheelMenuBtn").onclick = () => {
      navigateToAppPage("wheel");
    };
    document.getElementById("dataTableMenuBtn").onclick = () => {
      navigateToAppPage("data");
    };
    {
      const depositAmountEl = document.getElementById("depositAmount");
      if (depositAmountEl) {
        depositAmountEl.addEventListener("input", (event) => {
          renderPaypalRatePreview(event.target?.value || 0);
        });
      }
    }
    document.getElementById("depositCreateBtn").onclick = submitPaypalTopupRequest;
    document.getElementById("depositClearBtn").onclick = () => {
      resetPaypalDepositForm();
      line(document.getElementById("depositMsg"), "Đã làm mới form nạp PayPal.", "muted");
    };
    document.querySelectorAll(".sp-multiplier-btn").forEach(button => {
      button.onclick = () => setLuckyWheelSpinMultiplier(button.dataset.multiplier || 1);
    });
    document.getElementById("luckyWheelSpinBtn").onclick = toggleLuckyWheelAutoMode;
    document.getElementById("luckyWheelCenterBtn").onclick = spinLuckyWheel;
    {
      const luckyWheelCenterBtn = document.getElementById("luckyWheelCenterBtn");
      if (luckyWheelCenterBtn) {
        luckyWheelCenterBtn.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            spinLuckyWheel();
          }
        });
      }
    }
    document.getElementById("luckyWheelAutoBtn").onclick = openLuckyWheelTopup;
    document.getElementById("luckyWheelTopupCloseBtn").onclick = closeLuckyWheelTopup;
    document.getElementById("luckyWheelTopupCancelBtn").onclick = closeLuckyWheelTopup;
    document.getElementById("luckyWheelTopupConfirmBtn").onclick = confirmLuckyWheelTopupExchange;
    {
      const luckyWheelTopupOverlay = document.getElementById("luckyWheelTopupOverlay");
      if (luckyWheelTopupOverlay) {
        luckyWheelTopupOverlay.addEventListener("click", (event) => {
          if (event.target?.id === "luckyWheelTopupOverlay") closeLuckyWheelTopup();
        });
      }
    }
    window.addEventListener("popstate", () => {
      applyAppPageLayout();
    });
    window.addEventListener("resize", () => {
      if (getCurrentAppPageMode() !== "wheel" || !isElementActuallyVisible(document.getElementById("luckyWheelSection"))) return;
      if (luckyWheelResizeFrame) window.cancelAnimationFrame(luckyWheelResizeFrame);
      luckyWheelResizeFrame = window.requestAnimationFrame(() => {
        luckyWheelResizeFrame = 0;
        renderLuckyWheelLabels();
      });
    });
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      if (predictionHistoryPanelOpen) {
        togglePredictionHistoryPanel(false);
        return;
      }
      if (!document.getElementById("luckyWheelTopupOverlay")?.hidden) {
        closeLuckyWheelTopup();
        return;
      }
      closeSideMenu();
    });

    function setAuthMsg(msg, cls = "") {
      line(document.getElementById("authMsg"), msg, cls);
    }

    function setAuthMode(isLogin) {
      document.getElementById("loginForm").style.display = isLogin ? "block" : "none";
      document.getElementById("registerForm").style.display = isLogin ? "none" : "block";
      document.getElementById("showLoginBtn").classList.toggle("inactive", !isLogin);
      document.getElementById("showRegisterBtn").classList.toggle("inactive", isLogin);
      setAuthMsg(isLogin ? "Đăng nhập để tiếp tục." : "Tạo tài khoản mới.");
    }

    async function enterApp(user, role) {
      currentUser = user;
      currentUserRole = role === "admin" ? "admin" : "user";
      await loadStoreFromServer();
      const trainingCfg = saveKenoTrainingConfig({ enabled: false });
      kenoTrainingEnabled = trainingCfg.enabled;
      kenoTrainingLastTriggeredKy = trainingCfg.lastTriggeredKy;
      kenoTrainingLastResolvedKy = trainingCfg.lastResolvedKy;
      syncSideAccountIdentity();
      document.getElementById("authOverlay").style.display = "none";
      document.getElementById("appShell").style.display = "block";
      startLuckyWheelUiTimer();
      updateKenoCsvStatus();
      restoreLiveResultsCache();
      restoreLiveUpdateBadgeCache();
      renderHeaderNotifications();
      clearLegacyLiveHistoryCache();
      clearLiveHistoryState();
      renderPredictionHistoryPanel();
      applyAppPageLayout();
      syncKenoTrainingConfigFromUi();
      renderKenoTrainingToggle();
      if (kenoTrainingEnabled) startKenoTrainingLoop();
      runWhenBrowserIdle(async () => {
        if (!currentUser) return;
        const hasCachedLiveResults = Object.keys(liveResultsState || {}).length > 0;
        if (!hasCachedLiveResults) {
          await syncLiveResults({ silent: true }).catch(() => {});
        }
      }, 800);
    }

    async function logout() {
      try { await api("/api/logout", "POST"); } catch {}
      currentUser = null;
      currentUserRole = "user";
      storeSaveGeneration += 1;
      pendingStoreSave = null;
      lastSavedStoreSnapshotText = "";
      store = emptyStore();
      selectedPaypalTopupPackageId = PAYPAL_TOPUP_PACKAGES[1]?.id || PAYPAL_TOPUP_PACKAGES[0]?.id || "";
      luckyWheelRotation = 0;
      luckyWheelSpinning = false;
      luckyWheelAutoMode = false;
      luckyWheelLastAvailable = null;
      if (luckyWheelUiTimer) {
        clearInterval(luckyWheelUiTimer);
        luckyWheelUiTimer = null;
      }
      stopKenoTrainingLoop();
      kenoTrainingBusy = false;
      setSideMenuActiveButton("homeMenuBtn");
      stopLiveAutoSync();
      stopAnalysisAutoRefresh();
      closeHeaderPopovers();
      closeSideMenu();
      syncSideAccountIdentity();
      renderCurrencyBar();
      document.getElementById("appShell").style.display = "none";
      document.getElementById("authOverlay").style.display = "flex";
      document.getElementById("accountOverlay").style.display = "none";
      setAuthMode(true);
    }

    document.getElementById("showLoginBtn").onclick = () => setAuthMode(true);
    document.getElementById("showRegisterBtn").onclick = () => setAuthMode(false);

    function syncInputModes() {
      const rTypeEl = document.getElementById("rType");
      const rModeEl = document.getElementById("rMode");
      const rBasicBox = document.getElementById("rBasicBox");
      const rQuickBox = document.getElementById("rQuickBox");
      if (rTypeEl && rModeEl && rBasicBox && rQuickBox) {
        if (rTypeEl.value === "KENO" && rModeEl.value !== "quick") {
          rModeEl.value = "quick";
        }
        const rQuick = rModeEl.value === "quick";
        rBasicBox.style.display = rQuick ? "none" : "block";
        rQuickBox.style.display = rQuick ? "block" : "none";
      }

      const pModeEl = document.getElementById("pMode");
      const pBasicBox = document.getElementById("pBasicBox");
      const pQuickBox = document.getElementById("pQuickBox");
      if (pModeEl && pBasicBox && pQuickBox) {
        const pQuick = pModeEl.value === "quick";
        pBasicBox.style.display = pQuick ? "none" : "block";
        pQuickBox.style.display = pQuick ? "block" : "none";
      }
    }
    const rModeEl = document.getElementById("rMode");
    if (rModeEl) rModeEl.addEventListener("change", syncInputModes);
    const pModeEl = document.getElementById("pMode");
    if (pModeEl) pModeEl.addEventListener("change", syncInputModes);
    syncInputModes();

    function enforcePredictRiskModeVisibility(isAiPredict) {
      const riskModeBox = document.getElementById("pdRiskModeBox");
      if (!riskModeBox) return;
      const shouldShow = !!isAiPredict && String(predictEngineValue || "both").trim().toLowerCase() === "both";
      riskModeBox.hidden = !shouldShow;
      riskModeBox.style.display = shouldShow ? "grid" : "none";
    }

    function enforceVipPredictRiskModeVisibility(isAiPredict) {
      const riskModeBox = document.getElementById("vipPdRiskModeBox");
      const controls = document.querySelector("#predictRootVip .predict-vip-controls");
      if (!riskModeBox) return;
      const shouldShow = !!isAiPredict && String(vipPredictEngineValue || "both").trim().toLowerCase() === "both";
      riskModeBox.hidden = !shouldShow;
      riskModeBox.style.display = shouldShow ? "grid" : "none";
      if (controls) controls.classList.toggle("has-risk-mode", shouldShow);
    }

    function enforcePredictEngineVisibility(isKenoPredict, isAiPredict) {
      const pdEngineBox = document.getElementById("pdEngineBox");
      const pdEngineSelect = document.getElementById("pdEngine");
      const pdEngineShell = document.querySelector('.select-shell[data-select-id="pdEngine"]');
      const pdEngineChoice = document.getElementById("pdEngineChoice");
      if (pdEngineBox) {
        pdEngineBox.style.display = isAiPredict ? "grid" : "none";
        pdEngineBox.classList.toggle("keno-engine-mode", !!isKenoPredict);
      }
      if (pdEngineSelect) {
        pdEngineSelect.hidden = !isAiPredict || !isKenoPredict;
        pdEngineSelect.disabled = !isAiPredict || !isKenoPredict;
        pdEngineSelect.style.display = isAiPredict && isKenoPredict ? "block" : "none";
      }
      if (pdEngineShell) {
        pdEngineShell.hidden = !isAiPredict || !isKenoPredict;
        pdEngineShell.style.display = isAiPredict && isKenoPredict ? "" : "none";
      }
      if (pdEngineChoice) {
        pdEngineChoice.hidden = !isAiPredict || !!isKenoPredict;
        pdEngineChoice.style.display = isAiPredict && !isKenoPredict ? "grid" : "none";
      }
      enforcePredictRiskModeVisibility(isAiPredict);
    }

    function enforceVipPredictEngineVisibility(isKenoPredict, isAiPredict) {
      const vipPdEngineBox = document.getElementById("vipPdEngineBox");
      const vipPdEngineSelect = document.getElementById("vipPdEngine");
      const vipPdEngineChoice = document.getElementById("vipPdEngineChoice");
      if (vipPdEngineBox) vipPdEngineBox.style.display = isAiPredict ? "grid" : "none";
      if (vipPdEngineSelect) {
        vipPdEngineSelect.hidden = !isAiPredict || !isKenoPredict;
        vipPdEngineSelect.disabled = !isAiPredict || !isKenoPredict;
        vipPdEngineSelect.style.display = isAiPredict && isKenoPredict ? "block" : "none";
      }
      if (vipPdEngineChoice) {
        vipPdEngineChoice.hidden = !isAiPredict || !!isKenoPredict;
        vipPdEngineChoice.style.display = isAiPredict && !isKenoPredict ? "grid" : "none";
      }
      enforceVipPredictRiskModeVisibility(isAiPredict);
    }

    function getPredictBundleLimit(typeKey, kenoLevel = 0) {
      const normalizedType = String(typeKey || "").trim().toUpperCase();
      if (normalizedType !== "KENO") return PREDICT_MAX_BUNDLES;
      const normalizedLevel = Math.max(1, Math.min(10, Math.floor(Number(kenoLevel) || 1)));
      return Math.max(1, Math.floor(TYPES.KENO.mainMax / normalizedLevel));
    }

    function syncPredictBundleLimit({ clampValue = false, forceMinimum = false } = {}) {
      const input = document.getElementById("pdCount");
      const typeKey = String(document.getElementById("pdType")?.value || "").trim().toUpperCase();
      const kenoLevel = Number(document.getElementById("pdKenoLevel")?.value || 1);
      const limit = getPredictBundleLimit(typeKey, kenoLevel);
      const hint = document.getElementById("pdCountLimit");
      if (hint) hint.textContent = `Tối đa ${limit} bộ`;
      if (!input) return { limit, value: 1 };

      input.max = String(limit);
      input.title = typeKey === "KENO"
        ? `Keno bậc ${Math.max(1, Math.min(10, Math.floor(kenoLevel) || 1))}: tối đa ${limit} bộ`
        : `Tối đa ${limit} bộ`;

      const rawText = String(input.value || "").trim();
      const rawValue = Number(rawText);
      if (rawText && Number.isFinite(rawValue) && clampValue) {
        input.value = String(Math.min(limit, Math.max(1, Math.floor(rawValue))));
      } else if (forceMinimum && (!rawText || !Number.isFinite(rawValue) || rawValue < 1)) {
        input.value = "1";
      }
      return {
        limit,
        value: Math.min(limit, Math.max(1, Math.floor(Number(input.value) || 1))),
      };
    }

    function syncVipPredictBundleLimit({ clampValue = false, forceMinimum = false } = {}) {
      const input = document.getElementById("vipPdCount");
      const typeKey = String(document.getElementById("vipPdType")?.value || vipPredictTypeValue || "").trim().toUpperCase();
      const kenoLevel = Math.max(1, Math.min(10, Number(document.getElementById("vipPdKenoLevel")?.value || vipPredictKenoLevelValue || 5) || 5));
      const limit = typeKey === "KENO"
        ? Math.min(VIP_PREDICT_MAX_BUNDLES, Math.max(1, Math.floor(80 / kenoLevel)))
        : VIP_PREDICT_MAX_BUNDLES;
      const limitLabel = document.getElementById("vipPredictBundleLimitLabel");
      if (limitLabel) limitLabel.textContent = `Tối đa ${limit} bộ`;
      if (!input) return { limit, value: 1 };

      input.max = String(limit);
      input.title = `Tối đa ${limit} bộ VIP`;
      const rawText = String(input.value || "").trim();
      const rawValue = Number(rawText);
      if (rawText && Number.isFinite(rawValue) && clampValue) {
        input.value = String(Math.min(limit, Math.max(1, Math.floor(rawValue))));
      } else if (forceMinimum && (!rawText || !Number.isFinite(rawValue) || rawValue < 1)) {
        input.value = "1";
      }
      return {
        limit,
        value: Math.min(limit, Math.max(1, Math.floor(Number(input.value) || 1))),
      };
    }

    function syncKenoUiHints() {
      const rTypeEl = document.getElementById("rType");
      const pTypeEl = document.getElementById("pType");
      const pdTypeEl = document.getElementById("pdType");
      const rType = rTypeEl?.value || "";
      const pType = pTypeEl?.value || "";
      const pdType = pdTypeEl?.value || "";

      const rMainLabel = document.querySelector("label[for='__none__rmain']") || document.querySelector("#rBasicBox .row label");
      const rDbLabel = document.querySelectorAll("#rBasicBox .row label")[1];
      const rMainInput = document.getElementById("rMain");
      const rDbInput = document.getElementById("rDb");
      const rModeWrap = document.getElementById("rModeWrap");
      const rKenoLevelWrap = document.getElementById("rKenoLevelWrap");
      const rQuickRows = document.getElementById("rQuickRows");
      const rModeControl = document.getElementById("rMode");
      if (rTypeEl && rModeWrap && rKenoLevelWrap && rQuickRows && rModeControl && rMainInput && rDbInput) {
        if (rType === "KENO") {
          rModeControl.value = "quick";
          rModeControl.dispatchEvent(new Event("change", { bubbles: true }));
          rModeWrap.style.display = "none";
          rKenoLevelWrap.style.display = "grid";
          if (rMainLabel) rMainLabel.textContent = "KQ Keno - 10 số đầu (dòng 1)";
          if (rDbLabel) rDbLabel.textContent = "KQ Keno - 10 số cuối (dòng 2)";
          rMainInput.placeholder = "10 15 20 25 30 35 40 45 50 60";
          rDbInput.placeholder = "3 5 7 9 11 13 15 17 19 21";
          rQuickRows.placeholder = "Mỗi dòng đúng 20 số KQ Keno";
        } else {
          rModeWrap.style.display = "grid";
          rKenoLevelWrap.style.display = "none";
          if (rMainLabel) rMainLabel.textContent = "Số chính (nhập nhanh: có thể nhập luôn cả ĐB ở cuối)";
          if (rDbLabel) rDbLabel.textContent = "ĐB (nếu có, có thể để trống khi đã nhập nhanh ở ô trên)";
          rMainInput.placeholder = "5 9 15 17 23 hoặc 5 9 15 17 23 8";
          rDbInput.placeholder = "8";
          rQuickRows.placeholder = "5 9 15 17 23 8\n8 9 15 17 22 7";
        }
      }

      const pLabel = document.querySelector("#pBasicBox .row label");
      const pQuickLabel = document.querySelector("#pQuickBox .row label");
      const pTickets = document.getElementById("pTickets");
      const pQuickRows = document.getElementById("pQuickRows");
      if (pTickets && pQuickRows) {
        if (pType === "KENO") {
          if (pLabel) pLabel.textContent = "Mỗi dòng là 1 vé Keno (hàng ngang), từ 1 đến 10 số";
          if (pQuickLabel) pQuickLabel.textContent = "Nhập nhanh Keno: mỗi dòng 1 vé, từ 1 đến 10 số";
          pTickets.placeholder = "55\n80 55\n3 40 55 80";
          pQuickRows.placeholder = "10 15 20 25 30\n3 40 55 80";
        } else {
          if (pLabel) pLabel.textContent = "Mỗi dòng là 1 vé (vd 5 9 15 17 23 8 nếu loại có ĐB)";
          if (pQuickLabel) pQuickLabel.textContent = "Nhập nhanh: mỗi dòng 1 vé, hàng dưới là vé kế tiếp";
          pTickets.placeholder = "5 9 15 17 23 8\n8 9 15 17 22 7";
          pQuickRows.placeholder = "5 9 12 15 18 12\n5 6 19 8 17 12";
        }
      }

      const isKenoPredict = pdType === "KENO";
      const isAiPredict = AI_PREDICT_TYPES.has(pdType);
      const hasBaoMode = hasPredictBaoMode(pdType);
      const pdPlayMode = document.getElementById("pdPlayMode");
      const pdPlayModeRow = document.getElementById("pdPlayModeRow");
      const pdPlayModeBox = document.getElementById("pdPlayModeBox");
      const pdBaoSelect = document.getElementById("pdBaoLevel");
      const pdTypeCol = document.getElementById("pdTypeCol");
      const pdTypeRow = document.getElementById("pdTypeRow");
      const pdRecentWindowBox = document.getElementById("pdRecentWindowBox");
      const pdSubRow = document.querySelector(".predict-sub-row");
      const pdEngineBox = document.getElementById("pdEngineBox");
      const pdKenoLevelBox = document.getElementById("pdKenoLevelBox");
      const predictOutBox = document.getElementById("predictOut");
      if (pdKenoLevelBox) pdKenoLevelBox.style.display = isKenoPredict ? "grid" : "none";
      enforcePredictEngineVisibility(isKenoPredict, isAiPredict);
      const pdKenoDataBox = document.getElementById("pdKenoDataBox");
      if (pdKenoDataBox) pdKenoDataBox.style.display = isKenoPredict ? "block" : "none";
      const pdCountCol = document.getElementById("pdCountCol");
      if (pdPlayModeRow) pdPlayModeRow.style.display = isAiPredict && hasBaoMode ? "grid" : "none";
      if (pdPlayModeBox) pdPlayModeBox.style.display = isAiPredict && hasBaoMode ? "grid" : "none";
      if (pdPlayMode) {
        if (isKenoPredict || !hasBaoMode) {
          pdPlayMode.value = "normal";
          predictPlayModeValue = "normal";
          pdPlayMode.disabled = true;
          pdPlayMode.title = isKenoPredict ? "Keno hiện chỉ hỗ trợ Vé Thường" : "Loại này hiện chỉ hỗ trợ Vé Thường";
        } else {
          pdPlayMode.disabled = false;
          pdPlayMode.title = "";
          predictPlayModeValue = String(pdPlayMode.value || "normal").trim().toLowerCase() === "bao" ? "bao" : "normal";
        }
      }
      if (pdBaoSelect) {
        pdBaoSelect.disabled = isKenoPredict || !hasBaoMode || predictPlayModeValue !== "bao";
      }
      if (pdRecentWindowBox) pdRecentWindowBox.style.display = isAiPredict ? "none" : "";
      if (pdTypeRow) pdTypeRow.style.display = isAiPredict ? "none" : "grid";
      if (pdTypeRow) pdTypeRow.classList.toggle("keno-mode", isKenoPredict);
      if (pdSubRow) pdSubRow.classList.toggle("keno-mode", isKenoPredict);
      if (predictOutBox) predictOutBox.classList.toggle("keno-predict-out", isKenoPredict);
      if (pdTypeCol) pdTypeCol.style.gridColumn = "";
      if (pdSubRow) {
        if (isKenoPredict) {
          pdSubRow.style.gridTemplateColumns = "repeat(2, minmax(0, 1fr))";
        } else if (isAiPredict) {
          pdSubRow.style.gridTemplateColumns = "repeat(2, minmax(0, 1fr))";
        } else {
          pdSubRow.style.gridTemplateColumns = "repeat(2, minmax(0, 1fr))";
        }
      }
      if (pdCountCol) pdCountCol.style.gridColumn = "";
      if (pdEngineBox) pdEngineBox.style.gridColumn = isKenoPredict ? "" : (isAiPredict ? "1 / -1" : "");
      if (pdKenoLevelBox) pdKenoLevelBox.style.gridColumn = isKenoPredict ? "" : "";
      syncPredictBundleLimit({ clampValue: true });
      if (isKenoPredict) syncKenoTrainingConfigFromUi();
      syncPredictBaoOptions();
      renderKenoTrainingToggle();
      renderPredictEngineChoice();
      renderPredictRiskModeChoice();
    }

    function syncVipPredictBaoOptions() {
      const select = document.getElementById("vipPdBaoLevel");
      const row = document.getElementById("vipPdBaoRow");
      const playModeRow = document.getElementById("vipPdPlayModeRow");
      const typeKey = String(vipPredictTypeValue || document.getElementById("vipPdType")?.value || "").trim().toUpperCase();
      const options = getPredictBaoLevels(typeKey);
      if (!select || !row) return;
      const shouldShow = options.length > 0 && vipPredictPlayModeValue === "bao";
      if (playModeRow) playModeRow.classList.toggle("has-bao", shouldShow);
      if (!shouldShow) {
        select.innerHTML = "";
        vipPredictBaoLevelValue = "";
        row.style.display = "none";
        saveVipPredictState();
        return;
      }
      select.innerHTML = options.map(level => `<option value="${level}">Bao ${level}</option>`).join("");
      if (!options.includes(Number(vipPredictBaoLevelValue))) {
        vipPredictBaoLevelValue = String(options[0] || "");
      }
      select.value = vipPredictBaoLevelValue;
      row.style.display = "grid";
      saveVipPredictState();
    }

    function syncVipUiHints() {
      const pdType = String(document.getElementById("vipPdType")?.value || vipPredictTypeValue || "").trim().toUpperCase();
      vipPredictTypeValue = TYPE_KEYS.includes(pdType) ? pdType : "KENO";
      const isKenoPredict = vipPredictTypeValue === "KENO";
      const isAiPredict = AI_PREDICT_TYPES.has(vipPredictTypeValue);
      const hasBaoMode = hasPredictBaoMode(vipPredictTypeValue);
      const playModeSelect = document.getElementById("vipPdPlayMode");
      const playModeRow = document.getElementById("vipPdPlayModeRow");
      const playModeBox = document.getElementById("vipPdPlayModeBox");
      const baoSelect = document.getElementById("vipPdBaoLevel");
      const subRow = document.querySelector("#predictRootVip .predict-sub-row");
      const kenoLevelBox = document.getElementById("vipPdKenoLevelBox");
      const engineBox = document.getElementById("vipPdEngineBox");
      const controls = document.querySelector("#predictRootVip .predict-vip-controls");
      const shouldShowPlayMode = isAiPredict && hasBaoMode;
      if (playModeRow) playModeRow.style.display = shouldShowPlayMode ? "grid" : "none";
      if (playModeBox) playModeBox.style.display = shouldShowPlayMode ? "grid" : "none";
      if (controls) controls.classList.toggle("is-no-play-mode", !shouldShowPlayMode);
      if (subRow) subRow.classList.toggle("keno-mode", isKenoPredict);
      if (playModeSelect) {
        if (isKenoPredict || !hasBaoMode) {
          playModeSelect.value = "normal";
          vipPredictPlayModeValue = "normal";
          playModeSelect.disabled = true;
        } else {
          playModeSelect.disabled = false;
          playModeSelect.value = vipPredictPlayModeValue;
        }
      }
      if (baoSelect) baoSelect.disabled = isKenoPredict || !hasBaoMode || vipPredictPlayModeValue !== "bao";
      if (subRow) subRow.style.removeProperty("grid-template-columns");
      if (kenoLevelBox) kenoLevelBox.style.display = isKenoPredict ? "grid" : "none";
      if (engineBox) engineBox.style.removeProperty("grid-column");
      enforceVipPredictEngineVisibility(isKenoPredict, isAiPredict);
      syncVipPredictBundleLimit({ clampValue: true, forceMinimum: true });
      syncVipPredictBaoOptions();
      renderVipPredictEngineChoice();
      renderVipPredictRiskModeChoice();
      saveVipPredictState();
    }
    ["pdType"].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.addEventListener("change", syncKenoUiHints);
    });
    ["vipPdType"].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.addEventListener("change", syncVipUiHints);
    });
    document.querySelectorAll("[data-predict-mode-tab]").forEach(button => {
      button.addEventListener("click", () => {
        const nextMode = savePredictPageMode(button.dataset.predictModeTab || PREDICTION_MODE_NORMAL);
        renderPredictModeTabs();
        if (nextMode === PREDICTION_MODE_STATS) {
          renderStatsPanel();
          startStatsPanelRefresh({ force: true, silent: true });
        } else if (nextMode === PREDICTION_MODE_STATS_V2) {
          renderStatsV2Panel();
          loadStatsV2({ force: true, silent: true });
          window.setTimeout(() => {
            document.getElementById("predictRootStatsV2")?.scrollIntoView({ behavior: "smooth", block: "start" });
          }, 40);
        } else if (nextMode === PREDICTION_MODE_CHARTS) {
          renderChartStatsPanel();
          startChartStatsRefresh({ silent: true });
          window.setTimeout(() => {
            document.getElementById("predictRootCharts")?.scrollIntoView({ behavior: "smooth", block: "start" });
          }, 40);
        } else if (nextMode === PREDICTION_MODE_DASHBOARD) {
          renderDashboardPanel();
          startDashboardRefresh({ silent: true });
          window.setTimeout(() => {
            document.getElementById("predictRootDashboard")?.scrollIntoView({ behavior: "smooth", block: "start" });
          }, 40);
        } else if (nextMode === PREDICTION_MODE_ANALYSIS) {
          initAnalysisPanel();
          if (!analysisState.lastPayload) loadAnalysis({ force: true, silent: true });
          startAnalysisAutoRefresh();
          window.setTimeout(() => {
            document.getElementById("predictRootAnalysis")?.scrollIntoView({ behavior: "smooth", block: "start" });
          }, 40);
        }
      });
    });
    document.querySelectorAll("[data-dashboard-activity-view]").forEach(button => {
      button.addEventListener("click", () => {
        const nextView = normalizeDashboardActivityView(button.dataset.dashboardActivityView);
        if (nextView === dashboardActivityViewMode) return;
        dashboardActivityViewMode = nextView;
        saveDashboardUiState();
        renderDashboardPanel();
      });
    });
    document.querySelectorAll("[data-dashboard-distribution-view]").forEach(button => {
      button.addEventListener("click", () => {
        const nextView = normalizeDashboardDistributionView(button.dataset.dashboardDistributionView);
        if (nextView === dashboardDistributionViewMode) return;
        dashboardDistributionViewMode = nextView;
        saveDashboardUiState();
        renderDashboardPanel();
      });
    });
    const lottoDashboardRefreshBtn = document.getElementById("lottoDashboardRefreshBtn");
    if (lottoDashboardRefreshBtn) {
      lottoDashboardRefreshBtn.addEventListener("click", () => {
        startDashboardRefresh({ force: true, silent: false });
      });
    }
    const lottoDashboardGameSelect = document.getElementById("lottoDashboardGameSelect");
    if (lottoDashboardGameSelect) {
      lottoDashboardGameSelect.addEventListener("change", () => {
        const nextGame = normalizeDashboardGame(lottoDashboardGameSelect.value);
        if (nextGame === dashboardSelectedGame) return;
        dashboardSelectedGame = nextGame;
        const allowedViews = getDashboardDistributionOptions(nextGame).map(item => item.value);
        if (!allowedViews.includes(dashboardDistributionViewMode)) {
          dashboardDistributionViewMode = allowedViews[0] || "range";
        }
        saveDashboardUiState();
        renderDashboardPanel();
        startDashboardRefresh({ silent: true });
      });
    }
    const lottoDashboardSettingsBtn = document.getElementById("lottoDashboardSettingsBtn");
    if (lottoDashboardSettingsBtn) {
      lottoDashboardSettingsBtn.addEventListener("click", () => {
        document.getElementById("predictRootCharts")?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }
    const statsTypeSelect = document.getElementById("statsTypeSelect");
    if (statsTypeSelect) {
      statsTypeSelect.addEventListener("change", () => {
        const nextType = normalizeStatsType(statsTypeSelect.value);
        if (nextType === statsSelectedType) return;
        statsSelectedType = nextType;
        saveStatsUiState();
        renderStatsPanel();
        startStatsPanelRefresh({ force: true, silent: true });
      });
    }
    const statsWindowSelect = document.getElementById("statsWindowSelect");
    if (statsWindowSelect) {
      statsWindowSelect.addEventListener("change", () => {
        const nextWindow = normalizeStatsDayWindow(statsWindowSelect.value);
        if (nextWindow === statsSelectedDayWindow) return;
        statsSelectedDayWindow = nextWindow;
        ensureStatsCustomDateDefaults();
        saveStatsUiState();
        renderStatsPanel();
        const currentFeed = getLiveHistoryFeed(statsSelectedType);
        if (!doesLiveHistoryFeedSatisfyCount(statsSelectedType, currentFeed, "all")) {
          startStatsPanelRefresh({ force: true, silent: true });
        }
      });
    }
    const statsDateFromInput = document.getElementById("statsDateFrom");
    if (statsDateFromInput) {
      statsDateFromInput.addEventListener("change", () => {
        statsDateFrom = String(statsDateFromInput.value || "").trim();
        saveStatsUiState();
        renderStatsPanel();
      });
    }
    const statsDateToInput = document.getElementById("statsDateTo");
    if (statsDateToInput) {
      statsDateToInput.addEventListener("change", () => {
        statsDateTo = String(statsDateToInput.value || "").trim();
        saveStatsUiState();
        renderStatsPanel();
      });
    }
    document.addEventListener("change", event => {
      const kenoLevelSelect = event.target.closest("[data-stats-recent-keno-level]");
      if (!kenoLevelSelect) return;
      setStatsRecentKenoLevel(kenoLevelSelect.value);
      saveStatsUiState();
      renderStatsRecentSelectedHostOnly();
    });
    document.addEventListener("click", event => {
      const manualRefreshButton = event.target.closest("[data-stats-manual-refresh]");
      if (manualRefreshButton) {
        event.preventDefault();
        startStatsPanelRefresh({ force: true, silent: true });
        return;
      }
    });
    document.addEventListener("click", event => {
      const recentWindowButton = event.target.closest("[data-stats-recent-window]");
      if (!recentWindowButton) return;
      const nextWindow = normalizeStatsRecentWindow(recentWindowButton.dataset.statsRecentWindow, statsRecentModeValue);
      if (nextWindow === statsRecentWindowValue) return;
      statsRecentWindowValue = nextWindow;
      renderStatsPanel();
    });
    document.addEventListener("click", event => {
      const recentModeButton = event.target.closest("[data-stats-recent-mode]");
      if (!recentModeButton) return;
      const nextMode = normalizeStatsRecentMode(recentModeButton.dataset.statsRecentMode);
      if (nextMode === statsRecentModeValue) return;
      statsRecentModeValue = nextMode;
      statsRecentWindowValue = normalizeStatsRecentWindow(statsRecentWindowValue, statsRecentModeValue);
      renderStatsPanel();
    });
    document.addEventListener("click", event => {
      const displayModeButton = event.target.closest("[data-stats-display-mode]");
      if (!displayModeButton) return;
      const nextMode = normalizeStatsRecentDisplayMode(displayModeButton.dataset.statsDisplayMode);
      if (nextMode === statsRecentDisplayModeValue) return;
      statsRecentDisplayModeValue = nextMode;
      saveStatsUiState();
      renderStatsPanel();
    });
    document.addEventListener("click", event => {
      const recentTypeButton = event.target.closest("[data-stats-recent-type]");
      if (!recentTypeButton) return;
      const nextType = normalizeStatsType(recentTypeButton.dataset.statsRecentType);
      if (nextType === statsSelectedType) return;
      statsSelectedType = nextType;
      statsModernInsightTab = "most";
      statsModernInsightExpanded = false;
      saveStatsUiState();
      renderStatsTypeTabs();
      renderStatsPanel();
      startStatsPanelRefresh({ force: true, silent: true });
    });
    document.addEventListener("click", event => {
      const insightTabButton = event.target.closest("[data-stats-modern-insight-tab]");
      if (insightTabButton) {
        const nextTab = normalizeStatsModernInsightTab(insightTabButton.dataset.statsModernInsightTab);
        if (nextTab === statsModernInsightTab) return;
        statsModernInsightTab = nextTab;
        renderStatsPanel();
        return;
      }
      const insightToggleButton = event.target.closest("[data-stats-modern-insight-toggle]");
      if (!insightToggleButton) return;
      statsModernInsightExpanded = !statsModernInsightExpanded;
      renderStatsPanel();
    });
    document.addEventListener("click", event => {
      const removeButton = event.target.closest("[data-stats-recent-selected-remove]");
      if (removeButton) {
        removeStatsRecentSelectedNumber(
          statsSelectedType,
          removeButton.dataset.statsRecentSelectedRemove,
          removeButton.dataset.statsRecentSelectedSet,
          removeButton.dataset.statsRecentSelectedRole || "main",
        );
        renderStatsRecentSelectedHostOnly();
        return;
      }
      const clearButton = event.target.closest("[data-stats-recent-clear]");
      if (clearButton) {
        clearStatsRecentSelectedNumbers(statsSelectedType);
        renderStatsRecentSelectedHostOnly();
        return;
      }
      const saveButton = event.target.closest("[data-stats-recent-save]");
      if (saveButton) {
        saveStatsRecentSelectedState();
        renderStatsRecentSelectedHostOnly();
        return;
      }
      const activeSetButton = event.target.closest("[data-stats-recent-active-set]");
      if (activeSetButton) {
        setStatsRecentActiveSetIndex(statsSelectedType, activeSetButton.dataset.statsRecentActiveSet);
        saveStatsRecentSelectedState();
        renderStatsRecentSelectedHostOnly();
        return;
      }
      const pickButton = event.target.closest("[data-stats-recent-pick]");
      if (!pickButton) return;
      addStatsRecentSelectedNumber(
        statsSelectedType,
        pickButton.dataset.statsRecentPick,
        pickButton.dataset.statsRecentPickRole || "main",
      );
      renderStatsRecentSelectedHostOnly();
    });
    let statsRecentHelpCloseTimer = null;

    function clearStatsRecentHelpCloseTimer() {
      if (statsRecentHelpCloseTimer) {
        window.clearTimeout(statsRecentHelpCloseTimer);
        statsRecentHelpCloseTimer = null;
      }
    }

    function setStatsRecentHelpOpen(root, open) {
      if (!root) return;
      root.classList.toggle("is-open", !!open);
      const toggle = root.querySelector("[data-stats-recent-help-toggle]");
      if (toggle) toggle.setAttribute("aria-expanded", open ? "true" : "false");
    }

    function closeStatsRecentHelpPopovers(except = null) {
      clearStatsRecentHelpCloseTimer();
      document.querySelectorAll("[data-stats-recent-help].is-open").forEach(node => {
        if (except && node === except) return;
        setStatsRecentHelpOpen(node, false);
      });
    }

    function openStatsRecentHelp(root) {
      clearStatsRecentHelpCloseTimer();
      closeStatsRecentHelpPopovers(root);
      setStatsRecentHelpOpen(root, true);
    }

    function scheduleStatsRecentHelpClose(root) {
      clearStatsRecentHelpCloseTimer();
      statsRecentHelpCloseTimer = window.setTimeout(() => {
        setStatsRecentHelpOpen(root, false);
        statsRecentHelpCloseTimer = null;
      }, 240);
    }

    document.addEventListener("mouseover", event => {
      const root = event.target.closest("[data-stats-recent-help]");
      if (!root) return;
      if (event.relatedTarget && root.contains(event.relatedTarget)) return;
      openStatsRecentHelp(root);
    });
    document.addEventListener("mouseout", event => {
      const root = event.target.closest("[data-stats-recent-help]");
      if (!root) return;
      if (event.relatedTarget && root.contains(event.relatedTarget)) return;
      scheduleStatsRecentHelpClose(root);
    });
    document.addEventListener("click", event => {
      const helpToggle = event.target.closest("[data-stats-recent-help-toggle]");
      const helpClose = event.target.closest("[data-stats-recent-help-close]");
      const helpRoot = event.target.closest("[data-stats-recent-help]");
      if (helpToggle) {
        const root = helpToggle.closest("[data-stats-recent-help]");
        if (!root) return;
        const nextOpen = !root.classList.contains("is-open");
        if (nextOpen) openStatsRecentHelp(root);
        else setStatsRecentHelpOpen(root, false);
        return;
      }
      if (helpClose) {
        const root = helpClose.closest("[data-stats-recent-help]");
        if (root) setStatsRecentHelpOpen(root, false);
        return;
      }
      if (!helpRoot) closeStatsRecentHelpPopovers();
    });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape") {
        closeStatsRecentHelpPopovers();
        return;
      }
      if (event.key !== "Enter" && event.key !== " ") return;
      const pickButton = event.target.closest("[data-stats-recent-pick]");
      const removeButton = event.target.closest("[data-stats-recent-selected-remove]");
      if (!pickButton && !removeButton) return;
      event.preventDefault();
      event.target.click();
    });
    const statsV2TypeSelect = document.getElementById("statsV2TypeSelect");
    if (statsV2TypeSelect) {
      statsV2TypeSelect.addEventListener("change", () => {
        const nextType = normalizeStatsV2Type(statsV2TypeSelect.value);
        if (nextType === statsV2State.type) return;
        statsV2State.type = nextType;
        if (nextType !== "LOTO_5_35") {
          statsV2State.loto535View = "frequency";
          statsV2State.group = "main";
        }
        statsV2State.comboSize = normalizeStatsV2ComboSize(statsV2State.comboSize, nextType);
        clearStatsV2Selection();
        saveStatsV2UiState();
        loadStatsV2({ force: true, silent: true });
      });
    }
    const statsV2PeriodTabs = document.getElementById("statsV2PeriodTabs");
    if (statsV2PeriodTabs) {
      statsV2PeriodTabs.addEventListener("click", event => {
        const button = event.target?.closest("[data-stats-v2-period]");
        if (!button) return;
        const nextPeriod = normalizeStatsV2Period(button.dataset.statsV2Period);
        if (nextPeriod === statsV2State.period) return;
        statsV2State.period = nextPeriod;
        clearStatsV2Selection();
        saveStatsV2UiState();
        loadStatsV2({ force: true, silent: true });
      });
    }
    const statsV2SortSelect = document.getElementById("statsV2SortSelect");
    if (statsV2SortSelect) {
      statsV2SortSelect.addEventListener("change", () => {
        const nextSort = normalizeStatsV2Sort(statsV2SortSelect.value);
        if (nextSort === statsV2State.sort) return;
        statsV2State.sort = nextSort;
        saveStatsV2UiState();
        loadStatsV2({ force: true, silent: true });
      });
    }
    const statsV2ComboTabs = document.getElementById("statsV2ComboTabs");
    if (statsV2ComboTabs) {
      statsV2ComboTabs.addEventListener("click", event => {
        const button = event.target?.closest("[data-stats-v2-combo]");
        if (!button || button.disabled) return;
        const nextCombo = normalizeStatsV2ComboSize(button.dataset.statsV2Combo, statsV2State.type);
        if (nextCombo === statsV2State.comboSize) return;
        statsV2State.comboSize = nextCombo;
        clearStatsV2Selection();
        saveStatsV2UiState();
        loadStatsV2({ force: true, silent: true });
      });
    }
    const statsV2Loto535Tabs = document.getElementById("statsV2Loto535Tabs");
    if (statsV2Loto535Tabs) {
      statsV2Loto535Tabs.addEventListener("click", event => {
        const button = event.target?.closest("[data-stats-v2-loto535-view]");
        if (!button) return;
        const nextView = normalizeStatsV2Loto535View(button.dataset.statsV2Loto535View);
        if (nextView === statsV2State.loto535View) return;
        statsV2State.loto535View = nextView;
        clearStatsV2Selection();
        saveStatsV2UiState();
        renderStatsV2Panel();
        if (!statsV2State.payload) loadStatsV2({ force: true, silent: true });
      });
    }
    const statsV2Out = document.getElementById("statsV2Out");
    if (statsV2Out) {
      statsV2Out.addEventListener("click", event => {
        const groupButton = event.target?.closest("[data-stats-v2-group]");
        if (groupButton) {
          const nextGroup = normalizeStatsV2Group(groupButton.dataset.statsV2Group);
          if (nextGroup !== statsV2State.group) {
            statsV2State.group = nextGroup;
            if (nextGroup === "special") statsV2State.comboSize = 1;
            clearStatsV2Selection();
            saveStatsV2UiState();
            loadStatsV2({ force: true, silent: true });
          }
          return;
        }
        const itemHost = event.target?.closest("[data-stats-v2-item]");
        if (itemHost) toggleStatsV2Selection(itemHost.dataset.statsV2Item);
      });
    }
    const statsV2DateFromInput = document.getElementById("statsV2DateFrom");
    if (statsV2DateFromInput) {
      statsV2DateFromInput.addEventListener("change", () => {
        statsV2State.from = String(statsV2DateFromInput.value || "").trim();
        saveStatsV2UiState();
        if (statsV2State.period === "custom") loadStatsV2({ force: true, silent: true });
      });
    }
    const statsV2DateToInput = document.getElementById("statsV2DateTo");
    if (statsV2DateToInput) {
      statsV2DateToInput.addEventListener("change", () => {
        statsV2State.to = String(statsV2DateToInput.value || "").trim();
        saveStatsV2UiState();
        if (statsV2State.period === "custom") loadStatsV2({ force: true, silent: true });
      });
    }
    const statsV2AutoRefreshInput = document.getElementById("statsV2AutoRefresh");
    if (statsV2AutoRefreshInput) {
      statsV2AutoRefreshInput.addEventListener("change", () => {
        statsV2State.autoRefresh = !!statsV2AutoRefreshInput.checked;
        saveStatsV2UiState();
        syncStatsV2AutoRefreshTimer();
      });
    }
    const statsV2SaveBtn = document.getElementById("statsV2SaveBtn");
    if (statsV2SaveBtn) statsV2SaveBtn.addEventListener("click", () => saveStatsV2Favorite());
    const statsV2BuyBtn = document.getElementById("statsV2BuyBtn");
    if (statsV2BuyBtn) statsV2BuyBtn.addEventListener("click", () => buyStatsV2Selection());
    const analysisTypeSelect = document.getElementById("analysisTypeSelect");
    if (analysisTypeSelect) {
      analysisTypeSelect.addEventListener("change", () => {
        analysisState.type = normalizeAnalysisType(analysisTypeSelect.value);
        saveAnalysisUiState();
        loadAnalysis({ force: true, silent: true });
      });
    }
    const analysisPeriodSelect = document.getElementById("analysisPeriodSelect");
    if (analysisPeriodSelect) {
      analysisPeriodSelect.addEventListener("change", () => {
        analysisState.period = normalizeAnalysisPeriod(analysisPeriodSelect.value);
        saveAnalysisUiState();
        renderAnalysis(analysisState.lastPayload);
        loadAnalysis({ force: true, silent: true });
      });
    }
    const analysisModeSelect = document.getElementById("analysisModeSelect");
    if (analysisModeSelect) {
      analysisModeSelect.addEventListener("change", () => {
        analysisState.mode = normalizeAnalysisMode(analysisModeSelect.value);
        saveAnalysisUiState();
        loadAnalysis({ force: true, silent: true });
      });
    }
    const analysisDateFrom = document.getElementById("analysisDateFrom");
    if (analysisDateFrom) {
      analysisDateFrom.addEventListener("change", () => {
        analysisState.from = String(analysisDateFrom.value || "").trim();
        saveAnalysisUiState();
        if (analysisState.period === "custom") loadAnalysis({ force: true, silent: true });
      });
    }
    const analysisDateTo = document.getElementById("analysisDateTo");
    if (analysisDateTo) {
      analysisDateTo.addEventListener("change", () => {
        analysisState.to = String(analysisDateTo.value || "").trim();
        saveAnalysisUiState();
        if (analysisState.period === "custom") loadAnalysis({ force: true, silent: true });
      });
    }
    [["analysisLimitInput", "limit", 1, 100], ["analysisKInput", "k", 1, 20], ["analysisComboSizeInput", "comboSize", 1, 3]].forEach(([id, key, min, max]) => {
      const input = document.getElementById(id);
      if (!input) return;
      input.addEventListener("change", () => {
        analysisState[key] = clampAnalysisInt(input.value, analysisState[key], min, max);
        saveAnalysisUiState();
        loadAnalysis({ force: true, silent: true });
      });
    });
    const analysisAutoRefresh = document.getElementById("analysisAutoRefresh");
    if (analysisAutoRefresh) {
      analysisAutoRefresh.addEventListener("change", () => {
        analysisState.autoRefresh = !!analysisAutoRefresh.checked;
        saveAnalysisUiState();
        if (analysisState.autoRefresh) startAnalysisAutoRefresh();
        else stopAnalysisAutoRefresh();
      });
    }
    const analysisRefreshBtn = document.getElementById("analysisRefreshBtn");
    if (analysisRefreshBtn) analysisRefreshBtn.addEventListener("click", () => loadAnalysis({ force: true, silent: false }));
    const analysisSaveBtn = document.getElementById("analysisSaveBtn");
    if (analysisSaveBtn) analysisSaveBtn.addEventListener("click", () => saveAnalysisHistory());
    const chartStatsTypeSelect = document.getElementById("chartStatsTypeSelect");
    if (chartStatsTypeSelect) {
      chartStatsTypeSelect.addEventListener("change", () => {
        const nextType = normalizeChartStatsType(chartStatsTypeSelect.value);
        if (nextType === chartStatsSelectedType) return;
        chartStatsSelectedType = nextType;
        chartStatsSelectedPreset = getChartStatsDefaultPreset(nextType);
        chartStatsCustomCountValue = "";
        saveChartStatsUiState();
        renderChartStatsPanel();
        startChartStatsRefresh({ silent: true });
      });
    }
    const chartStatsPresetSelect = document.getElementById("chartStatsPresetSelect");
    if (chartStatsPresetSelect) {
      chartStatsPresetSelect.addEventListener("change", () => {
        const nextPreset = normalizeChartStatsPreset(chartStatsPresetSelect.value, chartStatsSelectedType);
        if (nextPreset === chartStatsSelectedPreset) return;
        const previousPreset = chartStatsSelectedPreset;
        chartStatsSelectedPreset = nextPreset;
        if (nextPreset === "custom" && !chartStatsCustomCountValue && /^\d+$/.test(previousPreset)) {
          chartStatsCustomCountValue = previousPreset;
        }
        if (nextPreset !== "custom") chartStatsCustomCountValue = "";
        saveChartStatsUiState();
        renderChartStatsPanel();
      });
    }
    const chartStatsCustomCountInput = document.getElementById("chartStatsCustomCount");
    if (chartStatsCustomCountInput) {
      chartStatsCustomCountInput.addEventListener("input", () => {
        chartStatsCustomCountValue = normalizeChartStatsCustomCount(chartStatsCustomCountInput.value);
        saveChartStatsUiState();
        renderChartStatsPanel();
      });
      chartStatsCustomCountInput.addEventListener("change", () => {
        chartStatsCustomCountValue = normalizeChartStatsCustomCount(chartStatsCustomCountInput.value);
        saveChartStatsUiState();
        renderChartStatsPanel();
      });
    }
    const chartStatsViewSelect = document.getElementById("chartStatsViewSelect");
    if (chartStatsViewSelect) {
      chartStatsViewSelect.addEventListener("change", () => {
        const nextView = normalizeChartStatsViewMode(chartStatsViewSelect.value);
        if (nextView === chartStatsViewMode) return;
        chartStatsViewMode = nextView;
        saveChartStatsUiState();
        renderChartStatsPanel();
      });
    }
    const predictionHistoryToggleBtn = document.getElementById("predictionHistoryToggleBtn");
    if (predictionHistoryToggleBtn) {
      predictionHistoryToggleBtn.addEventListener("click", () => togglePredictionHistoryPanel());
    }
    const vipPredictionHistoryToggleBtn = document.getElementById("vipPredictionHistoryToggleBtn");
    if (vipPredictionHistoryToggleBtn) {
      vipPredictionHistoryToggleBtn.addEventListener("click", () => toggleVipPredictionHistoryPanel());
    }
    const kenoTrainingToggleBtn = document.getElementById("kenoTrainingToggleBtn");
    if (kenoTrainingToggleBtn) {
      kenoTrainingToggleBtn.addEventListener("click", () => {
        const pdType = String(document.getElementById("pdType")?.value || "").trim().toUpperCase();
        if (pdType !== "KENO") return;
        syncKenoTrainingConfigFromUi();
        setKenoTrainingEnabled(!kenoTrainingEnabled);
      });
    }
    const predictionHistoryCloseBtn = document.getElementById("predictionHistoryCloseBtn");
    if (predictionHistoryCloseBtn) {
      predictionHistoryCloseBtn.addEventListener("click", () => togglePredictionHistoryPanel(false));
    }
    const predictionHistoryOverlay = document.getElementById("predictionHistoryOverlay");
    if (predictionHistoryOverlay) {
      predictionHistoryOverlay.addEventListener("click", event => {
        if (event.target?.id === "predictionHistoryOverlay") {
          togglePredictionHistoryPanel(false);
        }
      });
    }
    const vipPredictionHistoryCloseBtn = document.getElementById("vipPredictionHistoryCloseBtn");
    if (vipPredictionHistoryCloseBtn) {
      vipPredictionHistoryCloseBtn.addEventListener("click", () => toggleVipPredictionHistoryPanel(false));
    }
    const vipPredictionHistoryOverlay = document.getElementById("vipPredictionHistoryOverlay");
    if (vipPredictionHistoryOverlay) {
      vipPredictionHistoryOverlay.addEventListener("click", event => {
        if (event.target?.id === "vipPredictionHistoryOverlay") {
          toggleVipPredictionHistoryPanel(false);
        }
      });
    }
    const predictionHistoryTypeTabs = document.getElementById("predictionHistoryTypeTabs");
    if (predictionHistoryTypeTabs) {
      predictionHistoryTypeTabs.addEventListener("click", (event) => {
        const btn = event.target.closest("[data-prediction-history-type]");
        if (!btn) return;
        predictionHistorySelectedType = normalizePredictionHistoryType(btn.dataset.predictionHistoryType);
        predictionHistorySelectedBaoLevel = "all";
        predictionHistoryCurrentIndex = 0;
        if (predictionHistorySelectedType === "KENO") {
          predictionHistoryLoadingError = "";
        }
        renderPredictionHistoryPanel();
        startPredictionHistoryRefresh(predictionHistorySelectedType, { silent: true });
      });
    }
    const predictionHistoryRangeTabs = document.getElementById("predictionHistoryRangeTabs");
    if (predictionHistoryRangeTabs) {
      predictionHistoryRangeTabs.addEventListener("click", (event) => {
        const btn = event.target.closest("[data-prediction-history-range]");
        if (!btn) return;
        predictionHistorySelectedRange = normalizePredictionHistoryRange(btn.dataset.predictionHistoryRange, predictionHistorySelectedType);
        predictionHistoryCurrentIndex = 0;
        renderPredictionHistoryPanel();
      });
    }
    const predictionHistoryPlayModeTabs = document.getElementById("predictionHistoryPlayModeTabs");
    if (predictionHistoryPlayModeTabs) {
      predictionHistoryPlayModeTabs.addEventListener("click", (event) => {
        const btn = event.target.closest("[data-prediction-history-playmode]");
        if (!btn) return;
        predictionHistorySelectedPlayMode = normalizePredictionHistoryPlayMode(btn.dataset.predictionHistoryPlaymode);
        predictionHistorySelectedBaoLevel = "all";
        predictionHistoryCurrentIndex = 0;
        renderPredictionHistoryPanel();
      });
    }
    const predictionHistoryBaoLevelSelect = document.getElementById("predictionHistoryBaoLevelSelect");
    if (predictionHistoryBaoLevelSelect) {
      predictionHistoryBaoLevelSelect.addEventListener("change", (event) => {
        predictionHistorySelectedBaoLevel = normalizePredictionHistoryBaoLevel(event.target?.value);
        predictionHistoryCurrentIndex = 0;
        renderPredictionHistoryPanel();
      });
    }
    const predictionHistoryPrevBtn = document.getElementById("predictionHistoryPrevBtn");
    if (predictionHistoryPrevBtn) {
      predictionHistoryPrevBtn.addEventListener("click", () => {
        predictionHistoryCurrentIndex = Math.max(0, Number(predictionHistoryCurrentIndex || 0) - 1);
        renderPredictionHistoryPanel();
      });
    }
    const predictionHistoryNextBtn = document.getElementById("predictionHistoryNextBtn");
    if (predictionHistoryNextBtn) {
      predictionHistoryNextBtn.addEventListener("click", () => {
        predictionHistoryCurrentIndex = Math.max(0, Number(predictionHistoryCurrentIndex || 0) + 1);
        renderPredictionHistoryPanel();
      });
    }
    const predictionHistoryRefreshBtn = document.getElementById("predictionHistoryRefreshBtn");
    if (predictionHistoryRefreshBtn) {
      predictionHistoryRefreshBtn.addEventListener("click", () => {
        if (predictionHistoryLoading) return;
        const selectedType = normalizePredictionHistoryType(predictionHistorySelectedType);
        startPredictionHistoryRefresh(selectedType, { silent: false, repairCanonical: true });
      });
    }
    const vipPredictionHistoryTypeTabs = document.getElementById("vipPredictionHistoryTypeTabs");
    if (vipPredictionHistoryTypeTabs) {
      vipPredictionHistoryTypeTabs.addEventListener("click", event => {
        const btn = event.target.closest("[data-vip-prediction-history-type]");
        if (!btn) return;
        vipPredictionHistorySelectedType = normalizePredictionHistoryType(btn.dataset.vipPredictionHistoryType);
        vipPredictionHistorySelectedBaoLevel = "all";
        vipPredictionHistoryCurrentIndex = 0;
        renderVipPredictionHistoryPanel();
        startVipPredictionHistoryRefresh(vipPredictionHistorySelectedType, { silent: true });
      });
    }
    const vipPredictionHistoryRangeTabs = document.getElementById("vipPredictionHistoryRangeTabs");
    if (vipPredictionHistoryRangeTabs) {
      vipPredictionHistoryRangeTabs.addEventListener("click", event => {
        const btn = event.target.closest("[data-vip-prediction-history-range]");
        if (!btn) return;
        vipPredictionHistorySelectedRange = normalizePredictionHistoryRange(btn.dataset.vipPredictionHistoryRange, vipPredictionHistorySelectedType);
        vipPredictionHistoryCurrentIndex = 0;
        renderVipPredictionHistoryPanel();
      });
    }
    const vipPredictionHistoryPlayModeTabs = document.getElementById("vipPredictionHistoryPlayModeTabs");
    if (vipPredictionHistoryPlayModeTabs) {
      vipPredictionHistoryPlayModeTabs.addEventListener("click", event => {
        const btn = event.target.closest("[data-vip-prediction-history-playmode]");
        if (!btn) return;
        vipPredictionHistorySelectedPlayMode = normalizePredictionHistoryPlayMode(btn.dataset.vipPredictionHistoryPlaymode);
        vipPredictionHistorySelectedBaoLevel = "all";
        vipPredictionHistoryCurrentIndex = 0;
        renderVipPredictionHistoryPanel();
      });
    }
    const vipPredictionHistoryBaoLevelSelect = document.getElementById("vipPredictionHistoryBaoLevelSelect");
    if (vipPredictionHistoryBaoLevelSelect) {
      vipPredictionHistoryBaoLevelSelect.addEventListener("change", event => {
        vipPredictionHistorySelectedBaoLevel = normalizePredictionHistoryBaoLevel(event.target?.value);
        vipPredictionHistoryCurrentIndex = 0;
        renderVipPredictionHistoryPanel();
      });
    }
    const vipPredictionHistoryPrevBtn = document.getElementById("vipPredictionHistoryPrevBtn");
    if (vipPredictionHistoryPrevBtn) {
      vipPredictionHistoryPrevBtn.addEventListener("click", () => {
        vipPredictionHistoryCurrentIndex = Math.max(0, Number(vipPredictionHistoryCurrentIndex || 0) - 1);
        renderVipPredictionHistoryPanel();
      });
    }
    const vipPredictionHistoryNextBtn = document.getElementById("vipPredictionHistoryNextBtn");
    if (vipPredictionHistoryNextBtn) {
      vipPredictionHistoryNextBtn.addEventListener("click", () => {
        vipPredictionHistoryCurrentIndex = Math.max(0, Number(vipPredictionHistoryCurrentIndex || 0) + 1);
        renderVipPredictionHistoryPanel();
      });
    }
    const vipPredictionHistoryRefreshBtn = document.getElementById("vipPredictionHistoryRefreshBtn");
    if (vipPredictionHistoryRefreshBtn) {
      vipPredictionHistoryRefreshBtn.addEventListener("click", () => {
        if (vipPredictionHistoryLoading) return;
        startVipPredictionHistoryRefresh(normalizePredictionHistoryType(vipPredictionHistorySelectedType), { silent: false, repairCanonical: true });
      });
    }
    const predictionHistoryList = document.getElementById("predictionHistoryList");
    if (predictionHistoryList) {
      predictionHistoryList.addEventListener("click", async (event) => {
        const toggleBtn = event.target.closest("[data-prediction-history-toggle]");
        if (toggleBtn) {
          const entryKey = String(toggleBtn.dataset.predictionHistoryToggle || "").trim();
          if (!entryKey) return;
          if (predictionHistoryExpandedKeys.has(entryKey)) predictionHistoryExpandedKeys.delete(entryKey);
          else predictionHistoryExpandedKeys.add(entryKey);
          renderPredictionHistoryPanel();
          return;
        }
        const copyBtn = event.target.closest("[data-prediction-history-copy]");
        if (!copyBtn) return;
        const entryIndex = Number(copyBtn.dataset.predictionHistoryCopy);
        if (!Number.isInteger(entryIndex) || entryIndex < 0) return;
        const entries = collectPredictionHistoryEntries(
          predictionHistorySelectedType,
          predictionHistorySelectedRange,
          predictionHistorySelectedPlayMode,
          predictionHistorySelectedBaoLevel,
          PREDICTION_MODE_NORMAL
        );
        const entry = entries[entryIndex];
        if (!entry) return;
        const text = buildPredictionHistoryCopyText(entry);
        if (!text) return;
        const copied = await copyTextToClipboard(text);
        const originalLabel = copyBtn.dataset.label || copyBtn.textContent || "⧉";
        copyBtn.dataset.label = originalLabel;
        copyBtn.classList.toggle("is-copied", !!copied);
        copyBtn.title = copied ? "Đã chép nội dung kỳ này" : "Không chép được";
        copyBtn.setAttribute("aria-label", copied ? "Đã chép nội dung kỳ này" : "Không chép được");
        copyBtn.textContent = copied ? "✓" : "!";
        window.clearTimeout(Number(copyBtn.dataset.resetTimer || 0));
        const timerId = window.setTimeout(() => {
          copyBtn.classList.remove("is-copied");
          copyBtn.textContent = originalLabel;
          copyBtn.title = "Chép nội dung kỳ này";
          copyBtn.setAttribute("aria-label", "Chép nội dung kỳ này");
          delete copyBtn.dataset.resetTimer;
        }, copied ? 1500 : 2000);
        copyBtn.dataset.resetTimer = String(timerId);
      });
    }
    const vipPredictionHistoryList = document.getElementById("vipPredictionHistoryList");
    if (vipPredictionHistoryList) {
      vipPredictionHistoryList.addEventListener("click", async event => {
        const copyBtn = event.target.closest("[data-prediction-history-copy]");
        if (!copyBtn) return;
        const entryIndex = Number(copyBtn.dataset.predictionHistoryCopy);
        if (!Number.isInteger(entryIndex) || entryIndex < 0) return;
      const entries = collectPredictionHistoryEntries(
        vipPredictionHistorySelectedType,
        vipPredictionHistorySelectedRange,
        vipPredictionHistorySelectedPlayMode,
        vipPredictionHistorySelectedBaoLevel,
          PREDICTION_MODE_VIP
        );
        const entry = entries[entryIndex];
        if (!entry) return;
        const text = buildPredictionHistoryCopyText(entry);
        if (!text) return;
        const copied = await copyTextToClipboard(text);
        copyBtn.classList.toggle("is-copied", !!copied);
        copyBtn.textContent = copied ? "✓" : "!";
        window.clearTimeout(Number(copyBtn.dataset.resetTimer || 0));
        const timerId = window.setTimeout(() => {
          copyBtn.classList.remove("is-copied");
          copyBtn.textContent = "⧉";
          delete copyBtn.dataset.resetTimer;
        }, copied ? 1500 : 2000);
        copyBtn.dataset.resetTimer = String(timerId);
      });
    }
    const pdEngineChoice = document.getElementById("pdEngineChoice");
    if (pdEngineChoice) {
      pdEngineChoice.addEventListener("click", event => {
        const btn = event.target.closest("[data-pd-engine]");
        if (!btn) return;
        predictEngineValue = String(btn.dataset.pdEngine || "both").trim().toLowerCase() || "both";
        const select = document.getElementById("pdEngine");
        if (select) select.value = predictEngineValue;
        syncKenoTrainingConfigFromUi();
        syncKenoUiHints();
      });
    }
    const pdEngineSelect = document.getElementById("pdEngine");
    if (pdEngineSelect) {
      pdEngineSelect.addEventListener("change", () => {
        predictEngineValue = String(pdEngineSelect.value || "both").trim().toLowerCase() || "both";
        syncKenoTrainingConfigFromUi();
        syncKenoUiHints();
      });
    }
    const pdRiskModeChoice = document.getElementById("pdRiskModeChoice");
    if (pdRiskModeChoice) {
      pdRiskModeChoice.addEventListener("click", event => {
        const btn = event.target.closest("[data-pd-risk-mode]");
        if (!btn) return;
        savePredictRiskMode(btn.dataset.pdRiskMode || "balanced");
        renderPredictRiskModeChoice();
      });
    }
    const pdPlayModeSelect = document.getElementById("pdPlayMode");
    if (pdPlayModeSelect) {
      pdPlayModeSelect.addEventListener("change", () => {
        const pdType = String(document.getElementById("pdType")?.value || "").trim().toUpperCase();
        const hasBaoMode = hasPredictBaoMode(pdType);
        if (pdType === "KENO" || !hasBaoMode) {
          pdPlayModeSelect.value = "normal";
          predictPlayModeValue = "normal";
        } else {
          predictPlayModeValue = String(pdPlayModeSelect.value || "normal").trim().toLowerCase() === "bao" ? "bao" : "normal";
        }
        maybeAutoSwitchRiskModeForBao(pdType, predictPlayModeValue);
        syncPredictBaoOptions();
      });
    }
    const pdBaoLevelSelect = document.getElementById("pdBaoLevel");
    if (pdBaoLevelSelect) {
      pdBaoLevelSelect.addEventListener("change", () => {
        predictBaoLevelValue = String(pdBaoLevelSelect.value || "").trim();
      });
    }
    const vipPdEngineChoice = document.getElementById("vipPdEngineChoice");
    if (vipPdEngineChoice) {
      vipPdEngineChoice.addEventListener("click", event => {
        const btn = event.target.closest("[data-vip-pd-engine]");
        if (!btn) return;
        vipPredictEngineValue = String(btn.dataset.vipPdEngine || "both").trim().toLowerCase() || "both";
        const select = document.getElementById("vipPdEngine");
        if (select) select.value = vipPredictEngineValue;
        syncVipUiHints();
      });
    }
    const vipPdEngineSelect = document.getElementById("vipPdEngine");
    if (vipPdEngineSelect) {
      vipPdEngineSelect.addEventListener("change", () => {
        vipPredictEngineValue = String(vipPdEngineSelect.value || "both").trim().toLowerCase() || "both";
        syncVipUiHints();
      });
    }
    const vipPdRiskModeChoice = document.getElementById("vipPdRiskModeChoice");
    if (vipPdRiskModeChoice) {
      vipPdRiskModeChoice.addEventListener("click", event => {
        const btn = event.target.closest("[data-vip-pd-risk-mode]");
        if (!btn) return;
        vipPredictRiskModeValue = normalizePredictRiskMode(btn.dataset.vipPdRiskMode || "balanced");
        saveVipPredictState();
        renderVipPredictRiskModeChoice();
      });
    }
    const vipPdPlayModeSelect = document.getElementById("vipPdPlayMode");
    if (vipPdPlayModeSelect) {
      vipPdPlayModeSelect.addEventListener("change", () => {
        const vipType = String(document.getElementById("vipPdType")?.value || "").trim().toUpperCase();
        if (vipType === "KENO" || !hasPredictBaoMode(vipType)) {
          vipPdPlayModeSelect.value = "normal";
          vipPredictPlayModeValue = "normal";
        } else {
          vipPredictPlayModeValue = String(vipPdPlayModeSelect.value || "normal").trim().toLowerCase() === "bao" ? "bao" : "normal";
        }
        maybeAutoSwitchVipRiskModeForBao(vipType, vipPredictPlayModeValue);
        syncVipUiHints();
      });
    }
    const vipPdBaoLevelSelect = document.getElementById("vipPdBaoLevel");
    if (vipPdBaoLevelSelect) {
      vipPdBaoLevelSelect.addEventListener("change", () => {
        vipPredictBaoLevelValue = String(vipPdBaoLevelSelect.value || "").trim();
        saveVipPredictState();
      });
    }
    ["pdCount","pdKenoLevel"].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.addEventListener("change", () => {
        syncPredictBundleLimit({ clampValue: true, forceMinimum: true });
        syncKenoTrainingConfigFromUi();
        renderKenoTrainingToggle();
      });
      if (el) el.addEventListener("input", () => {
        syncPredictBundleLimit({ clampValue: true });
        syncKenoTrainingConfigFromUi();
      });
    });
    const pdCountInput = document.getElementById("pdCount");
    if (pdCountInput) {
      pdCountInput.addEventListener("blur", () => {
        syncPredictBundleLimit({ clampValue: true, forceMinimum: true });
      });
    }
    ["vipPdCount","vipPdKenoLevel"].forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;
      el.addEventListener("change", () => {
        vipPredictCountValue = syncVipPredictBundleLimit({ clampValue: true, forceMinimum: true }).value;
        vipPredictKenoLevelValue = Math.max(1, Math.min(10, Number(document.getElementById("vipPdKenoLevel")?.value || 5) || 5));
        saveVipPredictState();
      });
      el.addEventListener("input", () => {
        vipPredictCountValue = syncVipPredictBundleLimit({ clampValue: true }).value;
        vipPredictKenoLevelValue = Math.max(1, Math.min(10, Number(document.getElementById("vipPdKenoLevel")?.value || 5) || 5));
        saveVipPredictState();
      });
    });
    syncKenoUiHints();
    {
      const initialPdType = document.getElementById("pdType")?.value || "";
      enforcePredictEngineVisibility(initialPdType === "KENO", AI_PREDICT_TYPES.has(initialPdType));
      restoreStatsV2UiState();
      restoreAnalysisUiState();
      renderPredictEngineChoice();
      renderPredictModeTabs();
      renderStatsTypeTabs();
      renderStatsWindowTabs();
      renderKenoTrainingToggle();
      if (predictPageModeValue === PREDICTION_MODE_STATS) {
        renderStatsPanel();
        startStatsPanelRefresh({ force: true, silent: true });
      } else if (predictPageModeValue === PREDICTION_MODE_STATS_V2) {
        renderStatsV2Panel();
        loadStatsV2({ force: true, silent: true });
      } else if (predictPageModeValue === PREDICTION_MODE_CHARTS) {
        renderChartStatsPanel();
        startChartStatsRefresh({ silent: true });
      } else if (predictPageModeValue === PREDICTION_MODE_DASHBOARD) {
        renderDashboardPanel();
        startDashboardRefresh({ silent: true });
      } else if (predictPageModeValue === PREDICTION_MODE_ANALYSIS) {
        renderAnalysis(null);
        loadAnalysis({ force: true, silent: true });
      }
    }
    {
      const vipTypeSelect = document.getElementById("vipPdType");
      if (vipTypeSelect) vipTypeSelect.value = vipPredictTypeValue;
      const vipCountInput = document.getElementById("vipPdCount");
      if (vipCountInput) vipCountInput.value = String(vipPredictCountValue);
      syncVipPredictBundleLimit({ clampValue: true, forceMinimum: true });
      const vipKenoLevelSelect = document.getElementById("vipPdKenoLevel");
      if (vipKenoLevelSelect) vipKenoLevelSelect.value = String(vipPredictKenoLevelValue);
      const vipPlayModeSelect2 = document.getElementById("vipPdPlayMode");
      if (vipPlayModeSelect2) vipPlayModeSelect2.value = vipPredictPlayModeValue;
      syncVipUiHints();
    }
    updateKenoCsvStatus();
    restoreLiveResultsCache();
    restoreLiveUpdateBadgeCache();
    clearLegacyLiveHistoryCache();
    clearLiveHistoryState();
    renderLiveResultsBoard();
    renderLiveHistoryOutput();
    renderPredictionHistoryPanel();
    {
      const liveSyncBtn = document.getElementById("liveSyncBtn");
      if (liveSyncBtn) {
        liveSyncBtn.addEventListener("click", () => {
          syncLiveResults({ repairCanonical: true });
        });
      }
    }
    {
      const liveHistoryBtn = document.getElementById("liveHistoryBtn");
      if (liveHistoryBtn) {
        liveHistoryBtn.addEventListener("click", async () => {
          try {
            await refreshCurrentLiveHistory({ force: true });
          } catch (err) {
            line(document.getElementById("liveHistoryOut"), `Không tải được lịch sử CSV: ${err.message || err}`, "warn");
          }
        });
      }
    }
    {
      const liveHistoryRefreshBtn = document.getElementById("liveHistoryRefreshBtn");
      if (liveHistoryRefreshBtn) {
        liveHistoryRefreshBtn.addEventListener("click", async () => {
          try {
            await refreshRecentLiveHistoryWindow();
          } catch (err) {
            line(document.getElementById("liveHistoryOut"), `Không thể cập nhật 15 ngày gần nhất: ${err.message || err}`, "warn");
          }
        });
      }
    }
    {
      const liveHistoryType = document.getElementById("liveHistoryType");
      if (liveHistoryType) {
        liveHistoryType.addEventListener("change", async () => {
          try {
            syncLiveHistoryCountOptions();
            await refreshCurrentLiveHistory();
          } catch (err) {
            line(document.getElementById("liveHistoryOut"), `Không tải được lịch sử CSV: ${err.message || err}`, "warn");
          }
        });
      }
    }
    {
      const liveHistoryCount = document.getElementById("liveHistoryCount");
      if (liveHistoryCount) {
        liveHistoryCount.addEventListener("change", async () => {
          try {
            await refreshCurrentLiveHistory();
          } catch (err) {
            line(document.getElementById("liveHistoryOut"), `Không tải được lịch sử CSV: ${err.message || err}`, "warn");
          }
        });
      }
    }
    {
      const dataTableType = document.getElementById("dataTableType");
      if (dataTableType) {
        dataTableType.addEventListener("change", async () => {
          dataTableSelectedType = dataTableType.value || "LOTO_5_35";
          await loadDataTableRows();
        });
      }
    }
    {
      const dataTableLimit = document.getElementById("dataTableLimit");
      if (dataTableLimit) {
        dataTableLimit.addEventListener("change", async () => {
          dataTableSelectedLimit = getDataTableLimitValue();
          await loadDataTableRows();
        });
      }
    }
    ["dataTableWeekday", "dataTableDay", "dataTableMonth", "dataTableYear"].forEach(filterId => {
      const filterEl = document.getElementById(filterId);
      if (!filterEl) return;
      filterEl.addEventListener("change", async () => {
        dataTableDateFilters = getDataTableDateFilters();
        await loadDataTableRows();
      });
    });
    {
      const dataTableClearFilterBtn = document.getElementById("dataTableClearFilterBtn");
      if (dataTableClearFilterBtn) {
        dataTableClearFilterBtn.addEventListener("click", async () => {
          resetDataTableDateFilters();
          await loadDataTableRows();
        });
      }
    }
    {
      const dataTableRefreshBtn = document.getElementById("dataTableRefreshBtn");
      if (dataTableRefreshBtn) {
        dataTableRefreshBtn.addEventListener("click", async () => {
          await loadDataTableRows({ force: true });
        });
      }
    }
    {
      const dataTableDownloadBtn = document.getElementById("dataTableDownloadBtn");
      if (dataTableDownloadBtn) {
        dataTableDownloadBtn.addEventListener("click", async () => {
          try {
            await downloadDataTableExcel();
          } catch (err) {
            renderDataTableStatus(`Không tải xuống được Excel: ${err.message || err}`, "warn");
          }
        });
      }
    }
    document.getElementById("registerBtn").onclick = async () => {
      const user = normalizeUser(document.getElementById("regUser").value);
      const pass = document.getElementById("regPass").value;
      const pass2 = document.getElementById("regPass2").value;
      if (user.length < 3) return setAuthMsg("Tên đăng nhập tối thiểu 3 ký tự.", "warn");
      if (pass.length < 4) return setAuthMsg("Mật khẩu tối thiểu 4 ký tự.", "warn");
      if (pass !== pass2) return setAuthMsg("Mật khẩu nhập lại chưa khớp.", "warn");
      showPageLoader();
      try {
        await api("/api/register", "POST", { username: user, password: pass });
        if (document.getElementById("regRemember").checked) {
          saveRememberedCreds(user, pass);
          document.getElementById("rememberCreds").checked = true;
        }
        setAuthMsg("Tạo tài khoản thành công. Hãy đăng nhập.", "ok");
        setAuthMode(true);
        document.getElementById("loginUser").value = user;
        document.getElementById("loginPass").value = pass;
      } catch (e) {
        setAuthMsg(e.message, "warn");
      } finally {
        hidePageLoader(220);
      }
    };

    document.getElementById("loginBtn").onclick = async () => {
      const user = normalizeUser(document.getElementById("loginUser").value);
      const pass = document.getElementById("loginPass").value;
      showPageLoader();
      try {
        const res = await api("/api/login", "POST", { username: user, password: pass });
        if (document.getElementById("rememberCreds").checked) saveRememberedCreds(user, pass);
        else clearRememberedCreds();
        await enterApp(res.username, res.role);
      } catch (e) {
        setAuthMsg(e.message, "warn");
      } finally {
        hidePageLoader(220);
      }
    };

    document.getElementById("recoverAdminBtn").onclick = async () => {
      const nextPass = prompt("Đặt mật khẩu mới cho admin:") || "";
      if (nextPass.length < 4) return setAuthMsg("Mật khẩu mới tối thiểu 4 ký tự.", "warn");
      const nextPass2 = prompt("Nhập lại mật khẩu mới:") || "";
      if (nextPass !== nextPass2) return setAuthMsg("Mật khẩu nhập lại chưa khớp.", "warn");
      showPageLoader();
      try {
        const res = await api("/api/recover-admin", "POST", { password: nextPass });
        document.getElementById("loginUser").value = res.username;
        document.getElementById("loginPass").value = nextPass;
        document.getElementById("rememberCreds").checked = true;
        saveRememberedCreds(res.username, nextPass);
        setAuthMsg(`Đã khôi phục tài khoản ${res.username}. Bạn có thể đăng nhập ngay.`, "ok");
      } catch (e) {
        setAuthMsg(e.message, "warn");
      } finally {
        hidePageLoader(220);
      }
    };

    document.getElementById("logoutBtn").onclick = () => {
      closeSideMenu();
      logout();
    };

    function bindPasswordToggle(btnId, inputId) {
      const btn = document.getElementById(btnId);
      const input = document.getElementById(inputId);
      btn.onclick = () => {
        const hidden = input.type === "password";
        input.type = hidden ? "text" : "password";
        btn.textContent = hidden ? "🙈" : "👁";
      };
    }

    bindPasswordToggle("toggleLoginPass", "loginPass");
    bindPasswordToggle("toggleRegPass", "regPass");
    bindPasswordToggle("toggleRegPass2", "regPass2");

    function updateAccountMsg(msg, cls = "") {
      line(document.getElementById("accountMsg"), msg, cls);
    }

    async function renderAccountRows() {
      const res = await api("/api/admin/users");
      const users = res.users || [];
      const rows = users.map((info) => {
        const u = info.username;
        const editable = accountEditMode;
        const roleOptions = `
          <option value="user" ${info.role === "user" ? "selected" : ""}>Người dùng</option>
          <option value="admin" ${info.role === "admin" ? "selected" : ""}>Admin</option>
        `;
        const accessOptions = `
          <option value="on" ${info.enabled ? "selected" : ""}>Cho phép</option>
          <option value="off" ${!info.enabled ? "selected" : ""}>Khóa</option>
        `;
        return `
          <tr data-user="${u}" data-role="${info.role}" data-enabled="${info.enabled ? "1" : "0"}" data-diamond="${Number(info.diamondBalance || 0)}" data-paypal="${Number(info.paypalBalance || 0)}">
            <td>
              <input class="acc-username" value="${u}" ${editable ? "" : "disabled"} />
              ${u === currentUser ? "<div class='muted'>(đang đăng nhập - không đổi tên tại đây)</div>" : ""}
            </td>
            <td><select class="acc-role" ${editable ? "" : "disabled"}>${roleOptions}</select></td>
            <td><select class="acc-access" ${editable ? "" : "disabled"}>${accessOptions}</select></td>
            <td><input class="acc-diamond" type="number" min="0" value="${Number(info.diamondBalance || 0)}" ${editable ? "" : "disabled"} /></td>
            <td><input class="acc-paypal" type="number" min="0" value="${Number(info.paypalBalance || 0)}" ${editable ? "" : "disabled"} /></td>
            <td>${info.hasData ? "Có dữ liệu" : "Trống"}</td>
            <td>
              <div class="account-actions">
                <button class="btn-ghost btn-reset">Đổi mật khẩu</button>
                <button class="btn-danger-sm btn-delete">Xóa</button>
              </div>
            </td>
          </tr>
        `;
      }).join("");
      document.getElementById("accountRows").innerHTML = rows || `<tr><td colspan="7">Chưa có tài khoản.</td></tr>`;
    }

    async function openAccountManager() {
      if (currentUserRole !== "admin") return;
      accountEditMode = false;
      updateEditModeButton();
      try {
        await renderAccountRows();
      } catch (e) {
        updateAccountMsg(e.message, "warn");
        return;
      }
      updateAccountMsg("Bạn có thể sửa vai trò, khóa/mở truy cập, đổi tên, đổi mật khẩu hoặc xóa tài khoản.");
      document.getElementById("accountOverlay").style.display = "block";
    }

    function closeAccountManager() {
      document.getElementById("accountOverlay").style.display = "none";
      accountEditMode = false;
      updateEditModeButton();
    }

    function updateEditModeButton() {
      const b = document.getElementById("toggleAccountEditBtn");
      b.textContent = accountEditMode ? "Tắt sửa" : "Sửa";
      const s = document.getElementById("saveAccountEditBtn");
      if (s) s.disabled = !accountEditMode;
    }

    document.getElementById("openAccountBtn").onclick = () => {
      closeSideMenu();
      openAccountManager();
    };
    document.getElementById("closeAccountBtn").onclick = closeAccountManager;
    updateEditModeButton();
    document.getElementById("toggleAccountEditBtn").onclick = async () => {
      accountEditMode = !accountEditMode;
      updateEditModeButton();
      await renderAccountRows();
      updateAccountMsg(accountEditMode
        ? "Đang bật chế độ sửa: có thể sửa tên, vai trò, truy cập, tài sản. Riêng tài khoản đang đăng nhập sẽ không đổi tên tại đây."
        : "Đã tắt chế độ sửa.");
    };
    document.getElementById("saveAccountEditBtn").onclick = async () => {
      if (!accountEditMode) return updateAccountMsg("Bấm Sửa trước khi Lưu.", "warn");
      const trs = Array.from(document.querySelectorAll("#accountRows tr[data-user]"));
      if (!trs.length) return;
      let savedCount = 0;
      const errors = [];
      for (const tr of trs) {
        const user = tr.dataset.user;
        const oldRole = tr.dataset.role || "user";
        const oldEnabled = tr.dataset.enabled === "1";
        const oldDiamond = Number(tr.dataset.diamond || 0);
        const oldPaypal = Number(tr.dataset.paypal || 0);
        const newUser = normalizeUser(tr.querySelector(".acc-username").value);
        const newRole = tr.querySelector(".acc-role").value;
        const access = tr.querySelector(".acc-access").value === "on";
        const diamond = Math.max(0, Number(tr.querySelector(".acc-diamond").value || 0));
        const paypal = Math.max(0, Number(tr.querySelector(".acc-paypal").value || 0));
        try {
          if (!newUser || newUser.length < 3) throw new Error(`Tên tài khoản "${user}" không hợp lệ (tối thiểu 3 ký tự).`);
          if (user === currentUser && newUser !== user) throw new Error("Không đổi tên tài khoản đang đăng nhập trong phiên hiện tại.");

          const changedName = newUser !== user;
          const changedUser = newRole !== oldRole || access !== oldEnabled;
          const changedAsset = diamond !== oldDiamond || paypal !== oldPaypal;
          if (!changedName && !changedUser && !changedAsset) continue;

          let targetUser = user;
          if (changedName) {
            await api("/api/admin/rename-user", "POST", { username: user, newUsername: newUser });
            targetUser = newUser;
          }
          if (changedUser) {
            await api("/api/admin/update-user", "POST", { username: targetUser, role: newRole, enabled: access });
          }
          if (changedAsset) {
            await api("/api/admin/update-assets", "POST", { username: targetUser, diamond, paypal });
            if (user === currentUser || targetUser === currentUser) {
              store.diamondBalance = diamond;
              store.paypalBalance = paypal;
              renderCurrencyBar();
            }
          }
          if (user === currentUser) currentUserRole = newRole;
          savedCount++;
        } catch (err) {
          errors.push(`${user}: ${err.message}`);
        }
      }
      await renderAccountRows();
      syncSideAccountIdentity();
      if (errors.length) {
        updateAccountMsg(`Đã lưu ${savedCount} dòng, lỗi ${errors.length} dòng.\n${errors.join("\n")}`, "warn");
      } else {
        updateAccountMsg(`Đã lưu thành công ${savedCount} dòng thay đổi.`, "ok");
      }
    };

    document.getElementById("accountRows").onclick = async (e) => {
      const btn = e.target.closest("button");
      if (!btn) return;
      const tr = e.target.closest("tr");
      if (!tr) return;
      const user = tr.dataset.user;

      if (btn.classList.contains("btn-reset")) {
        if (user === currentUser) return updateAccountMsg("Không đổi mật khẩu cho tài khoản đang đăng nhập tại đây.", "warn");
        const nextPass = prompt(`Nhập mật khẩu mới cho ${user}:`) || "";
        if (nextPass.length < 4) return updateAccountMsg("Mật khẩu mới tối thiểu 4 ký tự.", "warn");
        try {
          await api("/api/admin/reset-password", "POST", { username: user, newPassword: nextPass });
          return updateAccountMsg(`Đã đổi mật khẩu cho ${user}.`, "ok");
        } catch (err) {
          return updateAccountMsg(err.message, "warn");
        }
      }

      if (btn.classList.contains("btn-delete")) {
        if (user === currentUser) return updateAccountMsg("Không thể xóa tài khoản đang đăng nhập.", "warn");
        if (!confirm(`Xóa tài khoản ${user}?`)) return;
        try {
          await api("/api/admin/delete-user", "POST", { username: user });
          await renderAccountRows();
          return updateAccountMsg(`Đã xóa tài khoản ${user}.`, "ok");
        } catch (err) {
          return updateAccountMsg(err.message, "warn");
        }
      }
    };

    function showPageLoader() {
      const loader = document.getElementById("pageLoader");
      if (!loader) return;
      loader.classList.remove("hide");
    }

    function hidePageLoader(delayMs = 0) {
      const loader = document.getElementById("pageLoader");
      if (!loader) return;
      if (delayMs > 0) setTimeout(() => loader.classList.add("hide"), delayMs);
      else loader.classList.add("hide");
    }

    const bootStartAt = Date.now();
    (async () => {
      const rememberedCreds = loadRememberedCreds();
      if (rememberedCreds) {
        document.getElementById("loginUser").value = rememberedCreds.user;
        document.getElementById("loginPass").value = rememberedCreds.pass;
        document.getElementById("rememberCreds").checked = true;
      }
      try {
        const me = await api("/api/me");
        if (me.ok) {
          await enterApp(me.username, me.role);
          return;
        }
      } catch {}
      setAuthMode(true);
    })().finally(() => {
      const elapsed = Date.now() - bootStartAt;
      const wait = Math.max(0, 250 - elapsed);
      hidePageLoader(wait);
    });

    function normalizeKy(ky) {
      ky = (ky || "").trim();
      if (!ky) return null;
      // Allow fast input: 1, 01, 001, 0001, or #1, #01...
      const digits = ky.replace(/[^0-9]/g, "");
      if (!digits) return null;
      const n = Number(digits);
      if (!Number.isInteger(n) || n <= 0) return null;
      return `#${String(n).padStart(4, "0")}`;
    }

    function bindKyInput(id) {
      const el = document.getElementById(id);
      if (!el) return;
      el.addEventListener("input", () => {
        el.value = el.value.replace(/[^0-9#]/g, "");
      });
      el.addEventListener("blur", () => {
        const k = normalizeKy(el.value);
        if (k) el.value = k;
      });
    }

    ["rKy", "pKy", "dKy"].forEach(bindKyInput);

    function parseNums(text) {
      return (text || "").split(/[^0-9]+/).filter(Boolean).map(Number);
    }

    function parseDistinctSortedNums(nums, min, max, minCount, maxCount, label = "Dữ liệu") {
      if (!Array.isArray(nums)) nums = [];
      if (nums.length < minCount || nums.length > maxCount) {
        if (minCount === maxCount) throw new Error(`${label}: cần đúng ${minCount} số.`);
        throw new Error(`${label}: cần từ ${minCount} đến ${maxCount} số.`);
      }
      const set = new Set(nums);
      if (set.size !== nums.length) throw new Error(`${label}: bị trùng số.`);
      for (const n of nums) {
        if (!Number.isInteger(n) || n < min || n > max) throw new Error(`${label}: có số ngoài phạm vi ${min}-${max}.`);
      }
      return [...nums].sort((a, b) => a - b);
    }

    function parseMain(text, type) {
      const t = TYPES[type];
      const nums = parseNums(text);
      if (t.keno) {
        return parseDistinctSortedNums(nums, t.mainMin, t.mainMax, t.resultCount || 20, t.resultCount || 20, "KQ Keno");
      }
      return parseDistinctSortedNums(nums, t.mainMin, t.mainMax, t.mainCount, t.mainCount, "Số chính");
    }

    function parseSpecial(value, type) {
      const t = TYPES[type];
      if (!t.hasSpecial) return null;
      const n = Number(value);
      if (!Number.isInteger(n)) throw new Error("Thiếu hoặc sai số ĐB.");
      if (n < t.specialMin || n > t.specialMax) throw new Error(`ĐB ngoài phạm vi ${t.specialMin}-${t.specialMax}.`);
      return n;
    }

    function formatTicket(ticket, type) {
      const t = TYPES[type];
      const main = (ticket.main || []).map(number => formatPredictNumber(number, type)).join(t?.threeDigit ? " | " : " ");
      if (String(ticket?.playMode || "").trim().toLowerCase() === "bao") {
        const baoLabel = Number(ticket?.baoLevel || (ticket.main || []).length || 0);
        return t.hasSpecial && Number.isInteger(ticket.special)
          ? `Bộ • Bao ${baoLabel}: ${main} | ĐB ${formatPredictNumber(ticket.special, type)}`
          : `Bộ • Bao ${baoLabel}: ${main}`;
      }
      if (t?.threeDigit && Array.isArray(ticket?.displayLines) && ticket.displayLines.length) {
        return ticket.displayLines.join(" | ");
      }
      if (t.keno) {
        if ((ticket.main || []).length === (t.resultCount || 20)) return main;
        return `Bậc ${ticket.main.length}: ${main}`;
      }
      return t.hasSpecial ? `${main} ĐB ${formatPredictNumber(ticket.special, type)}` : main;
    }

    function clonePredictionTicket(ticket) {
      if (!ticket || !Array.isArray(ticket.main)) return null;
      return {
        main: [...ticket.main].sort((a, b) => a - b),
        special: Number.isInteger(ticket.special) ? ticket.special : null,
        playMode: String(ticket.playMode || "").trim().toLowerCase(),
        baoLevel: Number.isInteger(Number(ticket.baoLevel)) ? Number(ticket.baoLevel) : null,
      };
    }

    function ensurePredictionLogBucket(type) {
      if (!store.predictionLogs) {
        store.predictionLogs = Object.fromEntries(PREDICTION_LOG_TYPES.map(key => [key, []]));
      }
      if (PREDICTION_LOG_TYPES.includes(type) && !Array.isArray(store.predictionLogs[type])) {
        store.predictionLogs[type] = [];
      }
      return Array.isArray(store.predictionLogs?.[type]) ? store.predictionLogs[type] : [];
    }

    function pickStorePersistFields(source, keys) {
      if (!source || typeof source !== "object" || !Array.isArray(keys) || !keys.length) return null;
      const next = {};
      keys.forEach(key => {
        if (!Object.prototype.hasOwnProperty.call(source, key)) return;
        const value = source[key];
        if (value == null || value === "") return;
        next[key] = value;
      });
      return Object.keys(next).length ? next : null;
    }

    function compactPredictionLogForStore(entry, type = "") {
      if (!entry || typeof entry !== "object") return null;
      const normalizedRankings = normalizePredictionTopRankings(
        type,
        entry.topMainRanking,
        entry.topSpecialRanking,
        entry.tickets,
      );
      return {
        id: String(entry.id || ""),
        createdAt: String(entry.createdAt || ""),
        predictedKy: normalizeKy(entry.predictedKy),
        targetDrawAt: String(entry.targetDrawAt || ""),
        modelLabel: String(entry.modelLabel || ""),
        engineLabel: String(entry.engineLabel || ""),
        riskMode: normalizePredictRiskMode(entry.riskMode || "balanced"),
        riskModeLabel: String(entry.riskModeLabel || getPredictRiskModeMeta(entry.riskMode || "balanced").label),
        confidence: Number(entry.confidence || 0),
        stabilityScore: Number(entry.stabilityScore || entry.backtest?.stabilityScore || 0),
        recentCount: Number(entry.recentCount || 0),
        drawCount: Number(entry.drawCount || 0),
        historyCount: Number(entry.historyCount || 0),
        bundleCount: Number(entry.bundleCount || 0),
        pickSize: Number(entry.pickSize || 0),
        playMode: String(entry.playMode || "").trim().toLowerCase(),
        baoLevel: Number.isInteger(Number(entry.baoLevel)) ? Number(entry.baoLevel) : null,
        predictionMode: normalizePredictionMode(entry.predictionMode || PREDICTION_MODE_NORMAL),
        vipProfile: String(entry.vipProfile || ""),
        predictionId: String(entry.predictionId || ""),
        predictionStatus: String(entry.predictionStatus || ""),
        dataCutoffDrawId: String(entry.dataCutoffDrawId || ""),
        payloadChecksum: String(entry.payloadChecksum || ""),
        modelVersion: String(entry.modelVersion || ""),
        modelRole: String(entry.modelRole || ""),
        scoreMetrics: entry.scoreMetrics && typeof entry.scoreMetrics === "object" ? entry.scoreMetrics : null,
        tickets: Array.isArray(entry.tickets) ? entry.tickets.map(clonePredictionTicket).filter(Boolean) : [],
        ticketSources: Array.isArray(entry.ticketSources) ? entry.ticketSources.map(item => String(item || "").trim()) : [],
        topMainRanking: normalizedRankings.main,
        topSpecialRanking: normalizedRankings.special,
        metaSelectionMode: String(entry.metaSelectionMode || ""),
        metaPreferredEngine: String(entry.metaPreferredEngine || ""),
        resolved: !!entry.resolved,
        resolvedAt: String(entry.resolvedAt || ""),
        actualKy: String(entry.actualKy || ""),
        resultMissingData: !!entry.resultMissingData,
        resultMissingReason: String(entry.resultMissingReason || ""),
        resultMissingCheckedAt: String(entry.resultMissingCheckedAt || ""),
        actualDraw: entry.actualDraw ? cloneDraw(entry.actualDraw) : null,
        resultSummary: pickStorePersistFields(entry.resultSummary, STORE_PERSIST_RESULT_SUMMARY_KEYS),
      };
    }

    function buildPersistableStoreSnapshot(sourceStore = store) {
      return {
        ...sourceStore,
        predictionLogs: Object.fromEntries(PREDICTION_LOG_TYPES.map(type => {
          const logs = Array.isArray(sourceStore?.predictionLogs?.[type]) ? sourceStore.predictionLogs[type] : [];
          return [type, logs.map(entry => compactPredictionLogForStore(entry, type)).filter(Boolean)];
        })),
      };
    }

    function estimateStorePayloadBytes(text) {
      try {
        return new TextEncoder().encode(String(text || "")).length;
      } catch {
        return String(text || "").length;
      }
    }
    {
      const liveResultGrid = document.getElementById("liveResultGrid");
      if (liveResultGrid) {
        liveResultGrid.addEventListener("click", event => {
          const button = event.target.closest("[data-live-refresh-type]");
          if (!button || button.disabled) return;
          syncSingleLiveResult(button.dataset.liveRefreshType);
        });
      }
    }

    function getNextPredictionKy(type, dataset = null) {
      const resultDataset = dataset || buildPredictionResultDataset(type);
      const lastKy = resultDataset.order?.[resultDataset.order.length - 1];
      const nextValue = kySortValue(lastKy) + 1;
      if (!nextValue) return null;
      return `#${String(nextValue).padStart(4, "0")}`;
    }

    function getPredictEngineMeta(engine) {
      const key = String(engine || "").trim().toLowerCase();
      if (key === "luan_so") {
        return {
          key: "luan_so",
          label: "Luận Số",
          backendEngine: "luan_so",
          available: true,
          description: "",
        };
      }
      if (key === "both") {
        return {
          key: "both",
          label: "Cả 2",
          backendEngine: null,
          available: true,
          description: "",
        };
      }
      return {
        key: "gen_local",
        label: "AI Gen",
        backendEngine: "gen_local",
        available: true,
        description: "",
      };
    }

    function getKenoTrainingResolvedEntry() {
      const logs = ensurePredictionLogBucket("KENO");
      for (let index = logs.length - 1; index >= 0; index--) {
        const entry = logs[index];
        if (!entry || !entry.predictedKy) continue;
        if (entry.actualMain?.length || entry.actualResolvedAt || entry.hitSummary || entry.ticketHitSummary) {
          return entry;
        }
      }
      return null;
    }

    function renderKenoTrainingToggle() {
      const btn = document.getElementById("kenoTrainingToggleBtn");
      const pdType = String(document.getElementById("pdType")?.value || "").trim().toUpperCase();
      if (!btn) return;
      const visible = pdType === "KENO";
      btn.hidden = !visible;
      btn.disabled = !visible;
      btn.classList.toggle("is-on", visible && kenoTrainingEnabled);
      btn.classList.toggle("is-off", !kenoTrainingEnabled);
      btn.textContent = `Huấn Luyện: ${kenoTrainingEnabled ? "Bật" : "Tắt"}`;
      btn.setAttribute("aria-pressed", kenoTrainingEnabled ? "true" : "false");
      btn.title = visible
        ? (kenoTrainingEnabled ? "Đang tự chạy 1 lượt mỗi khi kỳ Keno cũ đã có kết quả" : "Bật auto dự đoán Keno theo cấu hình hiện tại")
        : "";
    }

    function stopKenoTrainingLoop() {
      if (kenoTrainingTimer) {
        window.clearInterval(kenoTrainingTimer);
        kenoTrainingTimer = null;
      }
    }

    async function runKenoTrainingTick() {
      if (!kenoTrainingEnabled || kenoTrainingBusy || currentUser == null) return;
      const pdType = String(document.getElementById("pdType")?.value || "").trim().toUpperCase();
      if (pdType !== "KENO") return;
      kenoTrainingBusy = true;
      try {
        syncKenoTrainingConfigFromUi();
        await refreshKenoPredictionDataForHistory({ silent: true });
        const resolvedEntry = getKenoTrainingResolvedEntry();
        if (!resolvedEntry?.predictedKy) return;
        const resolvedKy = String(resolvedEntry.predictedKy || "").trim();
        if (!resolvedKy || resolvedKy === kenoTrainingLastResolvedKy) return;
        const nextKy = normalizeKy(resolvedEntry.nextKy || "") || getNextPredictionKy("KENO", buildPredictionResultDataset("KENO"));
        if (!nextKy) return;
        const logs = ensurePredictionLogBucket("KENO");
        const hasNextAlready = logs.some(entry => String(entry?.predictedKy || "").trim() === nextKy);
        if (hasNextAlready) {
          const nextCfg = saveKenoTrainingConfig({
            lastResolvedKy: resolvedKy,
            lastTriggeredKy: nextKy,
          });
          kenoTrainingLastResolvedKy = nextCfg.lastResolvedKy;
          kenoTrainingLastTriggeredKy = nextCfg.lastTriggeredKy;
          return;
        }
        const config = syncKenoTrainingConfigFromUi();
        await runPredictFlow({
          type: "KENO",
          count: config.count,
          kenoLevel: config.kenoLevel,
          engineKey: config.engine,
          triggerMode: "keno_training_auto",
          triggerSourceResolvedKy: resolvedKy,
        });
        const nextCfg = saveKenoTrainingConfig({
          lastResolvedKy: resolvedKy,
          lastTriggeredKy: nextKy,
        });
        kenoTrainingLastResolvedKy = nextCfg.lastResolvedKy;
        kenoTrainingLastTriggeredKy = nextCfg.lastTriggeredKy;
        renderKenoTrainingToggle();
      } catch {
      } finally {
        kenoTrainingBusy = false;
      }
    }

    function startKenoTrainingLoop() {
      stopKenoTrainingLoop();
      if (!kenoTrainingEnabled) return;
      kenoTrainingTimer = window.setInterval(() => {
        void runKenoTrainingTick();
      }, 12000);
      void runKenoTrainingTick();
    }

    function setKenoTrainingEnabled(enabled) {
      const nextCfg = saveKenoTrainingConfig({ enabled: !!enabled });
      kenoTrainingEnabled = nextCfg.enabled;
      renderKenoTrainingToggle();
      if (kenoTrainingEnabled) startKenoTrainingLoop();
      else stopKenoTrainingLoop();
    }

