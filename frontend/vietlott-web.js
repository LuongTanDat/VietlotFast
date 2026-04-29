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
    const LIVE_RESULTS_CACHE_KEY = "vietlott_live_results_v1";
    const LIVE_HISTORY_CACHE_KEY = "vietlott_live_history_v1";
    const LIVE_SYNC_TIMING_CACHE_KEY = "vietlott_live_sync_timing_v1";
    const LIVE_UPDATE_BADGE_CACHE_KEY = "vietlott_live_update_badges_v1";
    const MAX_RESULTS_PER_TYPE = 60;
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
    const PREDICT_RISK_MODES = [
      { key: "stable", label: "Ổn Định", summary: "Meta đang ưu tiên giữ nhịp và giảm dao động giữa 2 engine." },
      { key: "balanced", label: "Cân Bằng", summary: "Meta đang giữ cân bằng giữa độ ổn định và cơ hội bùng nhịp." },
      { key: "aggressive", label: "Tấn Công", summary: "Meta đang mở rộng cửa cho tín hiệu nóng và quota co giãn mạnh hơn." },
    ];
    const PREDICTION_MODE_NORMAL = "normal";
    const PREDICTION_MODE_VIP = "vip";
    const PREDICTION_MODE_STATS = "stats";
    const PREDICTION_MODE_CHARTS = "charts";
    const PREDICTION_MODE_DASHBOARD = "dashboard";
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
      LOTO_5_35: Array.from({ length: 12 }, (_, index) => 4 + index),
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
    function hasPredictBaoMode(typeKey) {
      const normalizedType = String(typeKey || "").trim().toUpperCase();
      return Array.isArray(PREDICT_BAO_LEVELS[normalizedType]) && PREDICT_BAO_LEVELS[normalizedType].length > 0;
    }
    const MAX_PREDICTION_LOGS_PER_TYPE = 180;
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
    let accountEditMode = false;
    let kenoCsvFeed = { results: {}, order: [], sourceLabels: [], loadedAt: "" };
    let kenoPredictStatusMeta = { loadedAt: "", detail: "", level: "" };
    let liveResultsState = {};
    let liveUpdateBadgeState = {};
    let liveHistoryState = {};
    let liveHistoryLegacyApiMode = false;
    let liveHistoryRecentRefreshBusy = false;
    let dataTableSelectedType = "LOTO_5_35";
    let dataTableSelectedLimit = "500";
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
    let predictionHistorySelectedRange = "2k";
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
    let vipPredictionHistorySelectedRange = "2k";
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

    function applyAppPageMetadata() {
      const mode = getCurrentAppPageMode();
      if (mode === "wheel") {
        document.title = "Vòng Quay May Mắn | Vietlott Tra Cứu Nhanh Pro";
        return;
      }
      if (mode === "deposit") {
        document.title = "Nạp tiền tài khoản | Vietlott Tra Cứu Nhanh Pro";
        return;
      }
      if (mode === "data") {
        document.title = "Bảng Dữ Liệu | Vietlott Tra Cứu Nhanh Pro";
        return;
      }
      document.title = "Vietlott Tra Cứu Nhanh Pro";
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
      if (normalized === PREDICTION_MODE_CHARTS) return PREDICTION_MODE_CHARTS;
      if (normalized === PREDICTION_MODE_DASHBOARD) return PREDICTION_MODE_DASHBOARD;
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

    function readStatsUiState() {
      try {
        statsSelectedType = normalizeStatsType(localStorage.getItem(STATS_SELECTED_TYPE_KEY) || "KENO");
        statsSelectedDayWindow = normalizeStatsDayWindow(localStorage.getItem(STATS_SELECTED_DAY_WINDOW_KEY) || "30");
        statsDateFrom = String(localStorage.getItem(STATS_DATE_FROM_KEY) || "").trim();
        statsDateTo = String(localStorage.getItem(STATS_DATE_TO_KEY) || "").trim();
      } catch {}
    }

    function saveStatsUiState() {
      try {
        localStorage.setItem(STATS_SELECTED_TYPE_KEY, normalizeStatsType(statsSelectedType));
        localStorage.setItem(STATS_SELECTED_DAY_WINDOW_KEY, normalizeStatsDayWindow(statsSelectedDayWindow));
        localStorage.setItem(STATS_DATE_FROM_KEY, String(statsDateFrom || "").trim());
        localStorage.setItem(STATS_DATE_TO_KEY, String(statsDateTo || "").trim());
      } catch {}
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
        vipPredictCountValue = Number.isInteger(nextCount) && nextCount > 0 ? Math.min(3, nextCount) : 1;
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
      const updatedAt = new Date().toISOString();
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

    function isWithinKenoBadgeWindow(now = new Date()) {
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
          updatedAt: new Date().toISOString(),
        };
      }
      if (key === "KENO") {
        if (isWithinKenoBadgeWindow()) {
          return {
            type: key,
            code: "failure",
            label: "Thất Bại",
            message: errorMessage,
            updatedAt: new Date().toISOString(),
          };
        }
        return {
          type: key,
          code: "outside_hours",
          label: "Thử Lại Trong Khung Giờ 6:00 - 22:00",
          message: errorMessage,
          updatedAt: new Date().toISOString(),
        };
      }
      return {
        type: key,
        code: "retry",
        label: label || "Thử Lại",
        message: errorMessage,
        updatedAt: new Date().toISOString(),
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
          updatedAt: String(progressState.updatedAt || "").trim() || new Date().toISOString(),
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
          updatedAt: String(progressState.updatedAt || "").trim() || new Date().toISOString(),
        };
      } else if (liveState === "pending") {
        nextBadge = {
          type: key,
          code: "pending",
          label: "Chờ cập nhật",
          message: "",
          updatedAt: String(progressState.updatedAt || "").trim() || new Date().toISOString(),
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
      const btn = document.getElementById("themeToggleBtn");
      if (btn) {
        btn.textContent = isLight ? "☀️" : "🌙";
        btn.title = isLight ? "Đang sáng, bấm để chuyển tối" : "Đang tối, bấm để chuyển sáng";
      }
      localStorage.setItem(THEME_KEY, isLight ? "light" : "dark");
    }

    // ---abc--- Store / Session / Persistence ---
    async function loadStoreFromServer() {
      if (!currentUser) {
        store = emptyStore();
        renderCurrencyBar();
        return;
      }
      const res = await api("/api/store");
      const parsed = res.store || {};
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
        base.predictionLogs[t] = Array.isArray(parsed.predictionLogs?.[t]) ? parsed.predictionLogs[t] : [];
      }
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
      reconcileAllPredictionLogs();
      if (getPredictionLogsSignature(store.predictionLogs) !== predictionLogsBeforeReconcile) {
        saveStore();
      }
      renderCurrencyBar();
    }

    function saveStore() {
      if (!currentUser) return;
      if (IS_LOCAL_MODE) {
        setLocalStoreForUser(currentUser, store);
        return;
      }
      api("/api/store", "POST", { store: JSON.stringify(store) })
        .catch(() => {});
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

      const createdAt = new Date();
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
      const topupAt = new Date();
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
        store.luckyWheelLastRegenAt = new Date().toISOString();
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
        return new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Ho_Chi_Minh" });
      } catch {
        return new Date().toISOString().slice(0, 10);
      }
    }

    function getLuckyWheelNextDayResetMs() {
      try {
        const nowInTz = new Date(new Date().toLocaleString("en-US", { timeZone: "Asia/Ho_Chi_Minh" }));
        const nextReset = new Date(nowInTz);
        nextReset.setHours(24, 0, 0, 0);
        return Math.max(0, nextReset.getTime() - nowInTz.getTime());
      } catch {
        const now = new Date();
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
        store.luckyWheelLastRegenAt = new Date().toISOString();
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
      const now = Date.now();
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
        store.luckyWheelLastRegenAt = new Date().toISOString();
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
          store.luckyWheelLastRegenAt = new Date().toISOString();
        }
      }
      store.luckyWheelSpinCount = Math.max(0, Number(store.luckyWheelSpinCount || 0)) + safeMultiplier;
      store.luckyWheelMilestoneDayKey = getLuckyWheelTodayKey();
      store.luckyWheelDailySpinCount = Math.max(0, Number(store.luckyWheelDailySpinCount || 0)) + safeMultiplier;
      const now = new Date();
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
        if (luckyWheelSpinning) return;
        const snapshot = syncLuckyWheelSpins();
        if (snapshot.changed || snapshot.available !== luckyWheelLastAvailable) {
          renderLuckyWheelPanel();
          maybeTriggerLuckyWheelAutoSpin();
          return;
        }
        renderLuckyWheelMeta();
        if (!document.getElementById("luckyWheelTopupOverlay")?.hidden) {
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
      el.innerHTML = TYPE_KEYS.map(k => `<option value="${k}">${TYPES[k].label}</option>`).join("");
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
      const levels = hasPredictBaoMode(pdType) ? PREDICT_BAO_LEVELS[pdType] : [];
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
      "dataTableLimit"
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

    function openSideMenu() {
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
      renderLuckyWheelLabels();
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
      document.getElementById("whoami").textContent = `Tài khoản: ${user} (${currentUserRole})`;
      document.getElementById("openAccountBtn").style.display = currentUserRole === "admin" ? "inline-block" : "none";
      document.getElementById("authOverlay").style.display = "none";
      document.getElementById("appShell").style.display = "block";
      renderPrizePanel();
      renderPaypalDepositSection();
      renderLuckyWheelPanel();
      startLuckyWheelUiTimer();
      restoreKenoCsvFeedCache();
      updateKenoCsvStatus();
      await refreshKenoPredictionDataForHistory({ silent: true });
      restoreLiveResultsCache();
      restoreLiveUpdateBadgeCache();
      clearLegacyLiveHistoryCache();
      clearLiveHistoryState();
      renderLiveResultsBoard();
      renderLiveHistoryOutput();
      renderPredictionHistoryPanel();
      applyAppPageLayout();
      syncKenoTrainingConfigFromUi();
      renderKenoTrainingToggle();
      if (kenoTrainingEnabled) startKenoTrainingLoop();
      syncLiveResults({ silent: true }).catch(() => {});
    }

    async function logout() {
      try { await api("/api/logout", "POST"); } catch {}
      currentUser = null;
      currentUserRole = "user";
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
      if (isKenoPredict) syncKenoTrainingConfigFromUi();
      syncPredictBaoOptions();
      renderKenoTrainingToggle();
      renderPredictEngineChoice();
      renderPredictRiskModeChoice();
    }

    function syncVipPredictBaoOptions() {
      const select = document.getElementById("vipPdBaoLevel");
      const row = document.getElementById("vipPdBaoRow");
      const typeKey = String(vipPredictTypeValue || document.getElementById("vipPdType")?.value || "").trim().toUpperCase();
      const options = hasPredictBaoMode(typeKey) ? PREDICT_BAO_LEVELS[typeKey] : [];
      if (!select || !row) return;
      if (!options.length || vipPredictPlayModeValue !== "bao") {
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
      if (playModeRow) playModeRow.style.display = isAiPredict && hasBaoMode ? "grid" : "none";
      if (playModeBox) playModeBox.style.display = isAiPredict && hasBaoMode ? "grid" : "none";
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
      if (subRow) subRow.style.gridTemplateColumns = "repeat(2, minmax(0, 1fr))";
      if (kenoLevelBox) kenoLevelBox.style.display = isKenoPredict ? "grid" : "none";
      if (engineBox) engineBox.style.gridColumn = isKenoPredict ? "" : (isAiPredict ? "1 / -1" : "");
      enforceVipPredictEngineVisibility(isKenoPredict, isAiPredict);
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
          startStatsPanelRefresh({ silent: true });
        } else if (nextMode === PREDICTION_MODE_CHARTS) {
          startChartStatsRefresh({ silent: true });
          window.setTimeout(() => {
            document.getElementById("predictRootCharts")?.scrollIntoView({ behavior: "smooth", block: "start" });
          }, 40);
        } else if (nextMode === PREDICTION_MODE_DASHBOARD) {
          startDashboardRefresh({ silent: true });
          window.setTimeout(() => {
            document.getElementById("predictRootDashboard")?.scrollIntoView({ behavior: "smooth", block: "start" });
          }, 40);
        }
      });
    });
    document.querySelectorAll("[data-dashboard-activity-view]").forEach(button => {
      button.addEventListener("click", () => {
        const nextView = normalizeDashboardActivityViewMode(button.dataset.dashboardActivityView);
        if (nextView === dashboardActivityViewMode) return;
        dashboardActivityViewMode = nextView;
        saveDashboardUiState();
        renderDashboardPanel();
      });
    });
    document.querySelectorAll("[data-dashboard-distribution-view]").forEach(button => {
      button.addEventListener("click", () => {
        const nextView = normalizeDashboardDistributionViewMode(button.dataset.dashboardDistributionView);
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
        startStatsPanelRefresh({ silent: true });
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
          startStatsPanelRefresh({ silent: true });
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
        predictionHistorySelectedRange = normalizePredictionHistoryRange(btn.dataset.predictionHistoryRange);
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
        startPredictionHistoryRefresh(selectedType, { silent: true });
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
        vipPredictionHistorySelectedRange = normalizePredictionHistoryRange(btn.dataset.vipPredictionHistoryRange);
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
        startVipPredictionHistoryRefresh(normalizePredictionHistoryType(vipPredictionHistorySelectedType), { silent: true });
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
        syncKenoTrainingConfigFromUi();
        renderKenoTrainingToggle();
      });
      if (el) el.addEventListener("input", () => {
        syncKenoTrainingConfigFromUi();
      });
    });
    ["vipPdCount","vipPdKenoLevel"].forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;
      el.addEventListener("change", () => {
        vipPredictCountValue = Math.max(1, Math.min(3, Number(document.getElementById("vipPdCount")?.value || 1) || 1));
        vipPredictKenoLevelValue = Math.max(1, Math.min(10, Number(document.getElementById("vipPdKenoLevel")?.value || 5) || 5));
        saveVipPredictState();
      });
      el.addEventListener("input", () => {
        vipPredictCountValue = Math.max(1, Math.min(3, Number(document.getElementById("vipPdCount")?.value || 1) || 1));
        vipPredictKenoLevelValue = Math.max(1, Math.min(10, Number(document.getElementById("vipPdKenoLevel")?.value || 5) || 5));
        saveVipPredictState();
      });
    });
    syncKenoUiHints();
    {
      const initialPdType = document.getElementById("pdType")?.value || "";
      enforcePredictEngineVisibility(initialPdType === "KENO", AI_PREDICT_TYPES.has(initialPdType));
      renderPredictEngineChoice();
      renderPredictModeTabs();
      renderStatsTypeTabs();
      renderStatsWindowTabs();
      renderStatsPanel();
      renderChartStatsPanel();
      renderDashboardPanel();
      renderKenoTrainingToggle();
      if (predictPageModeValue === PREDICTION_MODE_STATS) {
        startStatsPanelRefresh({ silent: true });
      } else if (predictPageModeValue === PREDICTION_MODE_CHARTS) {
        startChartStatsRefresh({ silent: true });
      } else if (predictPageModeValue === PREDICTION_MODE_DASHBOARD) {
        startDashboardRefresh({ silent: true });
      }
    }
    {
      const vipTypeSelect = document.getElementById("vipPdType");
      if (vipTypeSelect) vipTypeSelect.value = vipPredictTypeValue;
      const vipCountInput = document.getElementById("vipPdCount");
      if (vipCountInput) vipCountInput.value = String(vipPredictCountValue);
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

    document.getElementById("logoutBtn").onclick = () => { logout(); };

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

    document.getElementById("openAccountBtn").onclick = openAccountManager;
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
      document.getElementById("whoami").textContent = `Tài khoản: ${currentUser} (${currentUserRole})`;
      document.getElementById("openAccountBtn").style.display = currentUserRole === "admin" ? "inline-block" : "none";
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
      const wait = Math.max(200, 900 - elapsed);
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

    function mergeUniquePredictionNumbers(primary, secondary = [], limit = 20) {
      const merged = [];
      const seen = new Set();
      const sources = [Array.isArray(primary) ? primary : [], Array.isArray(secondary) ? secondary : []];
      let cursor = 0;
      while (merged.length < limit) {
        let pushed = false;
        for (const source of sources) {
          if (cursor >= source.length) continue;
          const value = Number(source[cursor]);
          if (Number.isInteger(value) && !seen.has(value)) {
            seen.add(value);
            merged.push(value);
            pushed = true;
            if (merged.length >= limit) break;
          }
        }
        cursor += 1;
        if (!pushed && cursor > Math.max(...sources.map(source => source.length), 0)) break;
      }
      return merged;
    }

    function buildBaoPredictionTickets(type, bundleCount, baoLevel, topRanking = [], topSpecialRanking = [], regularTickets = []) {
      const t = TYPES[type];
      const baseLevel = Number(baoLevel || 0);
      if (!t || t.keno || !Number.isInteger(baseLevel) || baseLevel <= t.mainCount) return [];
      const candidatePool = mergeUniquePredictionNumbers(
        topRanking,
        regularTickets.flatMap(ticket => Array.isArray(ticket?.main) ? ticket.main : []),
        Math.min(t.mainMax, Math.max(baseLevel + 10, baseLevel * 3))
      );
      const allCandidates = candidatePool.length >= baseLevel ? candidatePool : range(t.mainMin, t.mainMax);
      const specialPool = Array.isArray(topSpecialRanking) && topSpecialRanking.length
        ? topSpecialRanking.map(Number).filter(Number.isInteger)
        : regularTickets.map(ticket => Number(ticket?.special)).filter(Number.isInteger);
      const tickets = [];
      for (let index = 0; index < bundleCount; index++) {
        const rotated = allCandidates.slice(index).concat(allCandidates.slice(0, index));
        let picked = [];
        for (const value of rotated) {
          const number = Number(value);
          if (!Number.isInteger(number) || picked.includes(number)) continue;
          picked.push(number);
          if (picked.length >= baseLevel) break;
        }
        if (picked.length < baseLevel) {
          for (const number of range(t.mainMin, t.mainMax)) {
            if (!picked.includes(number)) picked.push(number);
            if (picked.length >= baseLevel) break;
          }
        }
        picked = picked.slice(0, baseLevel).sort((a, b) => a - b);
        const special = t.hasSpecial
          ? (Number.isInteger(Number(specialPool[index % Math.max(1, specialPool.length)]))
            ? Number(specialPool[index % Math.max(1, specialPool.length)])
            : (Number.isInteger(Number(regularTickets[index]?.special)) ? Number(regularTickets[index].special) : null))
          : null;
        tickets.push({
          main: picked,
          special,
          playMode: "bao",
          baoLevel: baseLevel,
        });
      }
      return tickets;
    }

    function clampMetaScore(value) {
      return Math.max(0, Math.min(1, Number(value || 0) || 0));
    }

    function formatMetaPercent(value) {
      return `${(clampMetaScore(value) * 100).toFixed(2)}%`;
    }

    function computeAiGenMetaScore(result, type) {
      const backtest = result?.backtest || {};
      const recentRate = Number(backtest?.recentAvgHitRate ?? backtest?.avgHitRate ?? result?.confidence ?? 0);
      const avgRate = Number(backtest?.avgHitRate ?? 0);
      const confidence = Number(result?.confidence ?? 0);
      const agreement = Number(backtest?.agreementScore ?? result?.model?.agreementScore ?? 0);
      const cooldownPenalty = Number(backtest?.cooldownPenalty ?? result?.model?.cooldownPenalty ?? 1);
      const rawScore = (
        recentRate * 0.42 +
        avgRate * 0.18 +
        confidence * 0.24 +
        agreement * 0.16
      ) * Math.max(0.72, Math.min(1.05, cooldownPenalty || 1));
      const score = clampMetaScore(rawScore);
      const reason = backtest?.recentAvgHitRate
        ? `AI Gen đang nhỉnh hơn ở recent backtest ${(Number(backtest.recentAvgHitRate) * 100).toFixed(2)}%`
        : `AI Gen đang được giữ nhờ confidence ${formatMetaPercent(confidence)}`;
      return {
        key: "gen_local",
        label: "AI Gen",
        score,
        reason,
      };
    }

    function getResultRiskMode(result, fallback = "balanced") {
      return normalizePredictRiskMode(result?.riskMode || fallback);
    }

    function getRiskModeQuotaConfig(type, riskMode) {
      const normalized = normalizePredictRiskMode(riskMode);
      const isKeno = type === "KENO";
      if (normalized === "stable") {
        return {
          key: normalized,
          label: "Ổn Định",
          summary: "Meta đang ưu tiên giữ nhịp và giảm dao động giữa 2 engine.",
          tieThreshold: isKeno ? 0.06 : 0.035,
          scoreExponent: 0.95,
          minShare: 0.35,
          maxShare: 0.65,
          preferredBoost: 0.015,
        };
      }
      if (normalized === "aggressive") {
        return {
          key: normalized,
          label: "Tấn Công",
          summary: "Meta đang mở rộng cửa cho tín hiệu nóng và quota co giãn mạnh hơn.",
          tieThreshold: isKeno ? 0.02 : 0.012,
          scoreExponent: 1.32,
          minShare: 0.15,
          maxShare: 0.85,
          preferredBoost: 0.04,
        };
      }
      return {
        key: "balanced",
        label: "Cân Bằng",
        summary: "Meta đang giữ cân bằng giữa độ ổn định và cơ hội bùng nhịp.",
        tieThreshold: isKeno ? 0.04 : 0.02,
        scoreExponent: 1,
        minShare: 0.25,
        maxShare: 0.75,
        preferredBoost: 0.025,
      };
    }

    function getMetaStabilityBias(result) {
      const stabilityScore = Number(result?.stabilityScore ?? result?.backtest?.stabilityScore ?? result?.confidence ?? 0);
      const metaTrust = Number(result?.metaTrust || 0);
      const confidence = Number(result?.confidence || 0);
      const blend = Math.max(0, Math.min(1, (stabilityScore * 0.55) + (metaTrust * 0.3) + (confidence * 0.15)));
      return Number.isFinite(blend) ? blend : 0;
    }

    function computeLuanSoMetaScore(result, type) {
      const signal = result?.signalSummary || {};
      const champion = result?.champion || result?.model || {};
      const confidence = Number(result?.confidence ?? 0);
      const adaptiveScore = Number(champion?.adaptiveScore ?? confidence ?? 0);
      const strongPairs = Number(signal?.strongPairCount ?? champion?.strongPairs ?? 0);
      const watchPairs = Number(signal?.watchPairCount ?? champion?.watchPairs ?? 0);
      const topSupport = Number(champion?.topSupport ?? 0);
      const topPairCount = Number(champion?.topPairCount ?? 0);
      const strongNorm = Math.min(1, strongPairs / (type === "KENO" ? 40 : 24));
      const watchNorm = Math.min(1, watchPairs / (type === "KENO" ? 24 : 12));
      const supportNorm = Math.min(1, topSupport / (type === "KENO" ? 220 : 80));
      const pairNorm = Math.min(1, topPairCount / (type === "KENO" ? 60 : 22));
      const score = clampMetaScore(
        confidence * 0.36 +
        adaptiveScore * 0.28 +
        strongNorm * 0.18 +
        watchNorm * 0.06 +
        supportNorm * 0.07 +
        pairNorm * 0.05
      );
      const reason = `Luận Số đang mạnh ở adaptive score ${formatMetaPercent(adaptiveScore)} và cặp Strong ${strongPairs}`;
      return {
        key: "luan_so",
        label: "Luận Số",
        score,
        reason,
      };
    }

    function buildBothMetaSelection(type, bundleCount, luanSoResult, aiGenResult, riskMode = "balanced") {
      const pools = {
        luan_so: Array.isArray(luanSoResult?.tickets) ? luanSoResult.tickets : [],
        gen_local: Array.isArray(aiGenResult?.tickets) ? aiGenResult.tickets : [],
      };
      const available = {
        luan_so: pools.luan_so.length,
        gen_local: pools.gen_local.length,
      };
      const riskModeMeta = getRiskModeQuotaConfig(type, riskMode);
      const scores = {
        luan_so: available.luan_so ? computeLuanSoMetaScore(luanSoResult, type) : { key: "luan_so", label: "Luận Số", score: 0, reason: "Luận Số không trả đủ dữ liệu." },
        gen_local: available.gen_local ? computeAiGenMetaScore(aiGenResult, type) : { key: "gen_local", label: "AI Gen", score: 0, reason: "AI Gen không trả đủ dữ liệu." },
      };
      const validKeys = Object.keys(available).filter(key => available[key] > 0);
      if (!validKeys.length) {
        return {
          preferredEngine: "",
          scores,
          quota: { luan_so: 0, gen_local: 0 },
          summary: `${riskModeMeta.summary} Không có engine nào trả về bộ số hợp lệ.`,
          reasons: ["Luận Số và AI Gen đều chưa trả được vé hợp lệ."],
          riskMode: riskModeMeta.key,
          riskModeLabel: riskModeMeta.label,
          riskModeSummary: riskModeMeta.summary,
        };
      }
      if (validKeys.length === 1) {
        const onlyKey = validKeys[0];
        return {
          preferredEngine: onlyKey,
          scores,
          quota: {
            luan_so: onlyKey === "luan_so" ? Math.min(bundleCount, available.luan_so) : 0,
            gen_local: onlyKey === "gen_local" ? Math.min(bundleCount, available.gen_local) : 0,
          },
          summary: `${riskModeMeta.summary} ${scores[onlyKey].label} đang gánh toàn bộ lượt vì engine còn lại chưa đủ dữ liệu hoặc lỗi.`,
          reasons: [scores[onlyKey].reason],
          riskMode: riskModeMeta.key,
          riskModeLabel: riskModeMeta.label,
          riskModeSummary: riskModeMeta.summary,
        };
      }
      let luanScore = Math.max(0.0001, scores.luan_so.score || 0);
      let aiScore = Math.max(0.0001, scores.gen_local.score || 0);
      if (riskModeMeta.key === "stable") {
        luanScore *= 0.82 + (getMetaStabilityBias(luanSoResult) * 0.22);
        aiScore *= 0.82 + (getMetaStabilityBias(aiGenResult) * 0.22);
      }
      const weightedLuan = Math.pow(luanScore, riskModeMeta.scoreExponent);
      const weightedAi = Math.pow(aiScore, riskModeMeta.scoreExponent);
      const scoreTotal = weightedLuan + weightedAi;
      const preferredEngine = luanScore >= aiScore ? "luan_so" : "gen_local";
      const scoreGap = Math.abs(luanScore - aiScore);
      const isNearTie = scoreGap < riskModeMeta.tieThreshold;
      let quotaLuan = 0;
      let quotaAi = 0;
      if (bundleCount <= 1) {
        if (preferredEngine === "luan_so") quotaLuan = Math.min(1, available.luan_so);
        else quotaAi = Math.min(1, available.gen_local);
      } else {
        quotaLuan = Math.min(1, available.luan_so);
        quotaAi = Math.min(1, available.gen_local);
        let remaining = Math.max(0, bundleCount - quotaLuan - quotaAi);
        let targetLuan = isNearTie ? 0.5 : (weightedLuan / Math.max(0.0001, scoreTotal));
        targetLuan = Math.max(riskModeMeta.minShare, Math.min(riskModeMeta.maxShare, targetLuan));
        if (!isNearTie) {
          if (preferredEngine === "luan_so") targetLuan = Math.min(riskModeMeta.maxShare, targetLuan + riskModeMeta.preferredBoost);
          else targetLuan = Math.max(riskModeMeta.minShare, targetLuan - riskModeMeta.preferredBoost);
        }
        const desiredLuan = remaining * targetLuan;
        const extraLuanBase = Math.floor(desiredLuan);
        const extraAiBase = remaining - extraLuanBase;
        quotaLuan += Math.min(extraLuanBase, Math.max(0, available.luan_so - quotaLuan));
        quotaAi += Math.min(extraAiBase, Math.max(0, available.gen_local - quotaAi));
        remaining = bundleCount - quotaLuan - quotaAi;
        while (remaining > 0) {
          const luanRoom = available.luan_so - quotaLuan;
          const aiRoom = available.gen_local - quotaAi;
          if (luanRoom <= 0 && aiRoom <= 0) break;
          const firstKey = preferredEngine;
          const secondKey = preferredEngine === "luan_so" ? "gen_local" : "luan_so";
          const tryOrder = isNearTie ? ["luan_so", "gen_local"] : [firstKey, secondKey];
          let assigned = false;
          for (const key of tryOrder) {
            if (key === "luan_so" && luanRoom > 0) {
              quotaLuan += 1;
              assigned = true;
              break;
            }
            if (key === "gen_local" && aiRoom > 0) {
              quotaAi += 1;
              assigned = true;
              break;
            }
          }
          if (!assigned) break;
          remaining -= 1;
        }
      }
      const summary = isNearTie
        ? `${riskModeMeta.summary} Hai engine đang khá sát nhau nên meta giữ phân bổ gần cân bằng.`
        : `${riskModeMeta.summary} ${scores[preferredEngine].label} đang được ưu tiên theo phong độ gần đây.`;
      return {
        preferredEngine,
        scores,
        quota: {
          luan_so: quotaLuan,
          gen_local: quotaAi,
        },
        summary,
        reasons: [
          scores[preferredEngine].reason,
          preferredEngine === "luan_so" ? scores.gen_local.reason : scores.luan_so.reason,
        ].filter(Boolean),
        riskMode: riskModeMeta.key,
        riskModeLabel: riskModeMeta.label,
        riskModeSummary: riskModeMeta.summary,
      };
    }

    function buildSmartInterleavedTickets(bundleCount, ticketPools, metaSelection) {
      const quota = metaSelection?.quota || {};
      const preferred = metaSelection?.preferredEngine === "gen_local" ? "gen_local" : "luan_so";
      const secondary = preferred === "luan_so" ? "gen_local" : "luan_so";
      const remaining = {
        luan_so: Math.max(0, Number(quota.luan_so || 0)),
        gen_local: Math.max(0, Number(quota.gen_local || 0)),
      };
      const indexes = { luan_so: 0, gen_local: 0 };
      const mergedTickets = [];
      const ticketSources = [];
      while (mergedTickets.length < bundleCount) {
        let pushed = false;
        for (const sourceKey of [preferred, secondary]) {
          if ((remaining[sourceKey] || 0) <= 0) continue;
          const nextTicket = ticketPools?.[sourceKey]?.[indexes[sourceKey]++] || null;
          if (!nextTicket) {
            remaining[sourceKey] = 0;
            continue;
          }
          mergedTickets.push(nextTicket);
          ticketSources.push(sourceKey);
          remaining[sourceKey] -= 1;
          pushed = true;
          if (mergedTickets.length >= bundleCount) break;
        }
        if (!pushed) break;
      }
      return { tickets: mergedTickets, ticketSources };
    }

    function mergeBothAiResults(type, bundleCount, luanSoResult, aiGenResult, riskMode = "balanced") {
      const luanPayload = luanSoResult && typeof luanSoResult === "object" ? luanSoResult : {};
      const aiPayload = aiGenResult && typeof aiGenResult === "object" ? aiGenResult : {};
      const metaSelection = buildBothMetaSelection(type, bundleCount, luanSoResult, aiGenResult, riskMode);
      const merged = buildSmartInterleavedTickets(bundleCount, {
        luan_so: Array.isArray(luanPayload?.tickets) ? luanPayload.tickets : [],
        gen_local: Array.isArray(aiPayload?.tickets) ? aiPayload.tickets : [],
      }, metaSelection);
      const luanSignal = luanPayload?.signalSummary || {};
      const preferredLabel = metaSelection?.preferredEngine === "gen_local" ? "AI Gen" : "Luận Số";
      const metaQuota = metaSelection?.quota || { luan_so: 0, gen_local: 0 };
      return {
        ...aiPayload,
        ...luanPayload,
        engine: "both",
        engineLabel: "Cả 2",
        model: {
          key: "both_combo",
          label: "Meta • Luận Số + AI Gen",
          direction: luanSignal?.dominantDirection || "",
          window: Number(luanSignal?.dominantWindow || 0),
        },
        champion: {
          key: "both_combo",
          label: "Meta • Luận Số + AI Gen",
          direction: luanSignal?.dominantDirection || "",
          window: Number(luanSignal?.dominantWindow || 0),
        },
        confidence: Math.max(Number(luanPayload?.confidence || 0), Number(aiPayload?.confidence || 0)),
        historyCount: Math.max(Number(luanPayload?.historyCount || 0), Number(aiPayload?.historyCount || 0)),
        latestKy: String(luanPayload?.latestKy || aiPayload?.latestKy || ""),
        latestDate: String(luanPayload?.latestDate || aiPayload?.latestDate || ""),
        latestTime: String(luanPayload?.latestTime || aiPayload?.latestTime || ""),
        nextKy: String(luanPayload?.nextKy || aiPayload?.nextKy || ""),
        tickets: merged.tickets,
        ticketSources: merged.ticketSources,
        topRanking: mergeUniquePredictionNumbers(luanPayload?.topRanking, aiPayload?.topRanking, 20),
        topSpecialRanking: mergeUniquePredictionNumbers(luanPayload?.topSpecialRanking, aiPayload?.topSpecialRanking, 10),
        notes: [
          metaSelection?.summary || "Chế độ Cả 2 đang phân bổ thông minh giữa Luận Số và AI Gen.",
          metaSelection?.riskModeSummary ? `Chế độ AI: ${metaSelection.riskModeLabel} • ${metaSelection.riskModeSummary}` : "",
          `Meta ưu tiên: ${preferredLabel}.`,
          `Điểm phong độ: Luận Số ${formatMetaPercent(metaSelection?.scores?.luan_so?.score)} • AI Gen ${formatMetaPercent(metaSelection?.scores?.gen_local?.score)}.`,
          `Phân bổ bộ: Luận Số ${Number(metaQuota.luan_so || 0)} bộ • AI Gen ${Number(metaQuota.gen_local || 0)} bộ.`,
          ...(Array.isArray(metaSelection?.reasons) ? metaSelection.reasons.slice(0, 2) : []),
          ...(Array.isArray(luanPayload?.notes) ? luanPayload.notes.slice(0, 1) : []),
          ...(Array.isArray(aiPayload?.notes) ? aiPayload.notes.slice(0, 1) : []),
        ].filter(Boolean),
        signalSummary: luanPayload?.signalSummary || null,
        analysisReport: luanPayload?.analysisReport || null,
        backtest: aiPayload?.backtest || null,
        metaSelectionMode: "smart_interleave",
        metaScores: {
          luan_so: Number(metaSelection?.scores?.luan_so?.score || 0),
          gen_local: Number(metaSelection?.scores?.gen_local?.score || 0),
        },
        metaQuota: {
          luan_so: Number(metaQuota.luan_so || 0),
          gen_local: Number(metaQuota.gen_local || 0),
        },
        metaPreferredEngine: String(metaSelection?.preferredEngine || ""),
        riskMode: String(metaSelection?.riskMode || getResultRiskMode(aiPayload, riskMode)),
        riskModeLabel: String(metaSelection?.riskModeLabel || getPredictRiskModeMeta(riskMode).label),
        riskModeSummary: String(metaSelection?.riskModeSummary || getPredictRiskModeMeta(riskMode).summary),
        metaSummary: [
          metaSelection?.riskModeLabel ? `${metaSelection.riskModeLabel}` : "",
          metaSelection?.summary || "",
          `Ưu tiên ${preferredLabel}`,
          `Luận Số ${Number(metaQuota.luan_so || 0)} bộ • AI Gen ${Number(metaQuota.gen_local || 0)} bộ`,
        ].filter(Boolean).join(" • "),
      };
    }

    function renderPredictEngineChoice() {
      const select = document.getElementById("pdEngine");
      const choiceWrap = document.getElementById("pdEngineChoice");
      if (select) select.value = String(predictEngineValue || "both").trim().toLowerCase() || "both";
      if (!choiceWrap) return;
      const selected = String(predictEngineValue || "both").trim().toLowerCase() || "both";
      choiceWrap.querySelectorAll("[data-pd-engine]").forEach(button => {
        const isActive = String(button.dataset.pdEngine || "").trim().toLowerCase() === selected;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-pressed", isActive ? "true" : "false");
      });
    }

    function renderPredictRiskModeChoice() {
      const choiceWrap = document.getElementById("pdRiskModeChoice");
      if (!choiceWrap) return;
      const selected = normalizePredictRiskMode(predictRiskModeValue);
      choiceWrap.querySelectorAll("[data-pd-risk-mode]").forEach(button => {
        const modeKey = normalizePredictRiskMode(button.dataset.pdRiskMode);
        const isActive = modeKey === selected;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-pressed", isActive ? "true" : "false");
      });
    }

    function renderPredictModeTabs() {
      document.querySelectorAll("[data-predict-mode-tab]").forEach(button => {
        const tabMode = normalizePredictionMode(button.dataset.predictModeTab);
        const isActive = tabMode === predictPageModeValue;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-pressed", isActive ? "true" : "false");
      });
      const normalRoot = document.getElementById("predictRootNormal");
      const vipRoot = document.getElementById("predictRootVip");
      const statsRoot = document.getElementById("predictRootStats");
      const chartsRoot = document.getElementById("predictRootCharts");
      const dashboardRoot = document.getElementById("predictRootDashboard");
      if (normalRoot) normalRoot.hidden = predictPageModeValue !== PREDICTION_MODE_NORMAL;
      if (vipRoot) vipRoot.hidden = predictPageModeValue !== PREDICTION_MODE_VIP;
      if (statsRoot) statsRoot.hidden = predictPageModeValue !== PREDICTION_MODE_STATS;
      if (chartsRoot) chartsRoot.hidden = predictPageModeValue !== PREDICTION_MODE_CHARTS;
      if (dashboardRoot) dashboardRoot.hidden = predictPageModeValue !== PREDICTION_MODE_DASHBOARD;
    }

    function getStatsTypeUiMeta(typeKey) {
      const normalized = normalizeStatsType(typeKey);
      const mapping = {
        LOTO_5_35: { label: "5/35", accentClass: "loto535", fullAccentClass: "stats-insight-accent-loto535", chartColor: "#58d89c" },
        LOTO_6_45: { label: "6/45", accentClass: "loto645", fullAccentClass: "stats-insight-accent-loto645", chartColor: "#63c8ff" },
        LOTO_6_55: { label: "6/55", accentClass: "loto655", fullAccentClass: "stats-insight-accent-loto655", chartColor: "#ffb560" },
        KENO: { label: "Keno", accentClass: "keno", fullAccentClass: "stats-insight-accent-keno", chartColor: "#56dfd7" },
        MAX_3D: { label: "3D", accentClass: "max3d", fullAccentClass: "stats-insight-accent-max3d", chartColor: "#ff8a74" },
        MAX_3D_PRO: { label: "3D Pro", accentClass: "max3dpro", fullAccentClass: "stats-insight-accent-max3dpro", chartColor: "#59dfab" },
      };
      return mapping[normalized] || mapping.KENO;
    }

    function renderStatsTypeTabs() {
      const host = document.getElementById("statsTypeSelect");
      if (!host) return;
      statsSelectedType = normalizeStatsType(statsSelectedType);
      host.innerHTML = STATS_TYPE_OPTIONS.map(item => `<option value="${escapeHtml(item.value)}">${escapeHtml(item.label)}</option>`).join("");
      host.value = STATS_TYPE_OPTIONS.some(item => item.value === statsSelectedType) ? statsSelectedType : STATS_TYPE_OPTIONS[0]?.value || "KENO";
      if (typeof host.__syncCustomSelect === "function") host.__syncCustomSelect();
    }

    function renderStatsWindowTabs() {
      const host = document.getElementById("statsWindowSelect");
      if (!host) return;
      statsSelectedDayWindow = normalizeStatsDayWindow(statsSelectedDayWindow);
      host.innerHTML = STATS_DAY_WINDOWS.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(STATS_DAY_WINDOW_LABELS[value] || value)}</option>`).join("");
      host.value = STATS_DAY_WINDOWS.includes(statsSelectedDayWindow) ? statsSelectedDayWindow : "30";
      if (typeof host.__syncCustomSelect === "function") host.__syncCustomSelect();
      renderStatsCustomDateRange();
    }

    function formatStatsDateInputValue(dateValue) {
      if (!(dateValue instanceof Date) || Number.isNaN(dateValue.getTime())) return "";
      const year = dateValue.getFullYear();
      const month = String(dateValue.getMonth() + 1).padStart(2, "0");
      const day = String(dateValue.getDate()).padStart(2, "0");
      return `${year}-${month}-${day}`;
    }

    function parseStatsDateInputValue(rawValue, endOfDay = false) {
      const normalized = String(rawValue || "").trim();
      if (!normalized) return null;
      const parts = normalized.split("-");
      if (parts.length !== 3) return null;
      const [year, month, day] = parts.map(Number);
      if (!Number.isInteger(year) || !Number.isInteger(month) || !Number.isInteger(day)) return null;
      const dateValue = new Date(year, month - 1, day, endOfDay ? 23 : 0, endOfDay ? 59 : 0, endOfDay ? 59 : 0, endOfDay ? 999 : 0);
      return Number.isNaN(dateValue.getTime()) ? null : dateValue;
    }

    function getStatsLatestFeedDate(type) {
      const entries = buildStatsEntriesForFeed(type, getLiveHistoryFeed(type));
      const latestEntry = entries[entries.length - 1] || null;
      const parsed = parseLiveDate(latestEntry?.draw?.date || "");
      return parsed instanceof Date && !Number.isNaN(parsed.getTime()) ? parsed : new Date();
    }

    function ensureStatsCustomDateDefaults() {
      if (statsSelectedDayWindow !== "custom") return;
      const latestDate = getStatsLatestFeedDate(statsSelectedType);
      if (!statsDateTo) {
        statsDateTo = formatStatsDateInputValue(latestDate);
      }
      if (!statsDateFrom) {
        const startDate = new Date(latestDate.getTime());
        startDate.setDate(startDate.getDate() - 29);
        statsDateFrom = formatStatsDateInputValue(startDate);
      }
    }

    function buildStatsCustomRangeLabel() {
      const fromDate = parseStatsDateInputValue(statsDateFrom);
      const toDate = parseStatsDateInputValue(statsDateTo);
      if (fromDate && toDate) {
        const start = fromDate.getTime() <= toDate.getTime() ? fromDate : toDate;
        const end = fromDate.getTime() <= toDate.getTime() ? toDate : fromDate;
        return `${formatLiveDateFromDate(start)} - ${formatLiveDateFromDate(end)}`;
      }
      if (fromDate) return `Từ ${formatLiveDateFromDate(fromDate)}`;
      if (toDate) return `Đến ${formatLiveDateFromDate(toDate)}`;
      return "Khoảng ngày tùy chọn";
    }

    function renderStatsCustomDateRange() {
      const wrap = document.getElementById("statsCustomDateRange");
      const fromInput = document.getElementById("statsDateFrom");
      const toInput = document.getElementById("statsDateTo");
      if (!wrap || !fromInput || !toInput) return;
      const shouldShow = statsSelectedDayWindow === "custom";
      wrap.hidden = !shouldShow;
      if (shouldShow) ensureStatsCustomDateDefaults();
      fromInput.value = String(statsDateFrom || "");
      toInput.value = String(statsDateTo || "");
    }

    function extractThreeDigitTokensFromLines(lines) {
      const out = [];
      (Array.isArray(lines) ? lines : []).forEach(lineText => {
        const matches = String(lineText || "").match(/\b\d{3}\b/g) || [];
        matches.forEach(token => {
          const numeric = Number(token);
          if (Number.isInteger(numeric) && numeric >= 0 && numeric <= 999) out.push(numeric);
        });
      });
      return out;
    }

    function getStatsDisplayLabel(type, value, isSpecial = false) {
      if (TYPES[type]?.threeDigit) return formatPredictNumber(value, type);
      if (isSpecial && TYPES[type]?.hasSpecial) return formatPredictNumber(value, type);
      return formatPredictNumber(value, type);
    }

    function buildStatsFrequencyItems(type, entries, { special = false } = {}) {
      const counts = new Map();
      const typeConfig = TYPES[type] || {};
      if (!typeConfig?.threeDigit) {
        const seedNumbers = special
          ? (typeConfig?.hasSpecial ? range(typeConfig.specialMin, typeConfig.specialMax) : [])
          : range(typeConfig.mainMin, typeConfig.mainMax);
        seedNumbers.forEach(number => {
          counts.set(Number(number), 0);
        });
      }
      if (TYPES[type]?.threeDigit) {
        entries.forEach(entry => {
          extractThreeDigitTokensFromLines(entry.draw?.displayLines).forEach(number => {
            counts.set(number, Number(counts.get(number) || 0) + 1);
          });
        });
      } else if (special) {
        entries.forEach(entry => {
          const value = entry.draw?.special;
          if (Number.isInteger(Number(value))) {
            const specialValue = Number(value);
            counts.set(specialValue, Number(counts.get(specialValue) || 0) + 1);
          }
        });
      } else {
        entries.forEach(entry => {
          (Array.isArray(entry.draw?.main) ? entry.draw.main : []).forEach(value => {
            const number = Number(value);
            if (Number.isInteger(number)) counts.set(number, Number(counts.get(number) || 0) + 1);
          });
        });
      }
      return [...counts.entries()]
        .map(([value, count]) => ({
          value: Number(value),
          count: Number(count || 0),
          label: getStatsDisplayLabel(type, value, special),
        }))
        .sort((a, b) => b.count - a.count || a.value - b.value);
    }

    function buildStatsEntriesForFeed(type, feed) {
      return (Array.isArray(feed?.order) ? feed.order : [])
        .map(ky => ({ ky, draw: feed?.results?.[ky] }))
        .filter(entry => entry.draw)
        .sort((a, b) => {
          const kyDelta = kySortValue(a.ky) - kySortValue(b.ky);
          if (kyDelta !== 0) return kyDelta;
          const aTime = parseLiveDate(a.draw?.date || "")?.getTime?.() || 0;
          const bTime = parseLiveDate(b.draw?.date || "")?.getTime?.() || 0;
          return aTime - bTime;
        });
    }

    function filterStatsEntriesByDayWindow(entries, windowKey) {
      const normalizedWindow = normalizeStatsDayWindow(windowKey);
      if (normalizedWindow === "custom") {
        const fromRaw = parseStatsDateInputValue(statsDateFrom, false);
        const toRaw = parseStatsDateInputValue(statsDateTo, true);
        if (!fromRaw && !toRaw) return [...entries];
        let start = fromRaw;
        let end = toRaw;
        if (start && end && start.getTime() > end.getTime()) {
          const swappedStart = parseStatsDateInputValue(statsDateTo, false);
          const swappedEnd = parseStatsDateInputValue(statsDateFrom, true);
          start = swappedStart;
          end = swappedEnd;
        }
        return entries.filter(entry => {
          const parsed = parseLiveDate(entry.draw?.date || "");
          if (!(parsed instanceof Date) || Number.isNaN(parsed.getTime())) return false;
          if (start && parsed.getTime() < start.getTime()) return false;
          if (end && parsed.getTime() > end.getTime()) return false;
          return true;
        });
      }
      if (normalizedWindow === "all") return [...entries];
      const dayCount = Math.max(1, Number(normalizedWindow) || 30);
      const cutoff = new Date();
      cutoff.setHours(0, 0, 0, 0);
      cutoff.setDate(cutoff.getDate() - (dayCount - 1));
      return entries.filter(entry => {
        const parsed = parseLiveDate(entry.draw?.date || "");
        return parsed instanceof Date && !Number.isNaN(parsed.getTime()) && parsed.getTime() >= cutoff.getTime();
      });
    }

    function collectStatsHighlightNumberSetFromTickets(tickets) {
      const values = new Set();
      for (const ticket of (Array.isArray(tickets) ? tickets : [])) {
        for (const raw of (Array.isArray(ticket?.main) ? ticket.main : [])) {
          const numeric = Number(raw);
          if (Number.isInteger(numeric)) values.add(numeric);
        }
      }
      return values;
    }

    function collectStatsHighlightSpecialSetFromTickets(tickets) {
      const values = new Set();
      for (const ticket of (Array.isArray(tickets) ? tickets : [])) {
        const numeric = Number(ticket?.special);
        if (Number.isInteger(numeric)) values.add(numeric);
      }
      return values;
    }

    function collectOrderedHighlightNumbers(primaryValues = [], fallbackValues = [], limit = 10) {
      const ordered = [];
      const seen = new Set();
      const safeLimit = Math.max(1, Number(limit || 0) || 10);
      for (const value of [...primaryValues, ...fallbackValues]) {
        const numeric = Number(value);
        if (!Number.isInteger(numeric) || seen.has(numeric)) continue;
        seen.add(numeric);
        ordered.push(numeric);
        if (ordered.length >= safeLimit) break;
      }
      return new Set(ordered);
    }

    function buildStatsLatestActualNumberSet(type, latestEntry) {
      if (!latestEntry?.draw) return new Set();
      if (TYPES[type]?.threeDigit) {
        return new Set(extractThreeDigitTokensFromLines(latestEntry.draw?.displayLines));
      }
      return new Set(
        (Array.isArray(latestEntry.draw?.main) ? latestEntry.draw.main : [])
          .map(value => Number(value))
          .filter(value => Number.isInteger(value))
      );
    }

    function buildStatsLatestActualSpecialSet(type, latestEntry) {
      if (!TYPES[type]?.hasSpecial || !latestEntry?.draw) return new Set();
      const specialValue = Number(latestEntry.draw?.special);
      return Number.isInteger(specialValue) ? new Set([specialValue]) : new Set();
    }

    function getStatsLatestPredictionHighlight(type, latestEntry = null) {
      const logs = ensurePredictionLogBucket(type)
        .filter(entry => Array.isArray(entry?.tickets) && entry.tickets.length);
      if (!logs.length) return { entry: null, numbers: new Set() };
      const targetNextKyValue = (kySortValue(latestEntry?.ky) || 0) + 1;
      const preferredLogs = targetNextKyValue
        ? logs.filter(entry => kySortValue(entry?.predictedKy) === targetNextKyValue)
        : [];
      const candidateLogs = preferredLogs.length ? preferredLogs : logs;
      const sorted = [...candidateLogs].sort((a, b) => {
        const kyDelta = kySortValue(b?.predictedKy) - kySortValue(a?.predictedKy);
        if (kyDelta !== 0) return kyDelta;
        return (Date.parse(String(b?.createdAt || "").trim()) || 0) - (Date.parse(String(a?.createdAt || "").trim()) || 0);
      });
      const entry = sorted[0] || null;
      const highlightLimit = 10;
      const rankedNumbers = Array.isArray(entry?.topMainRanking)
        ? entry.topMainRanking.map(value => Number(value)).filter(value => Number.isInteger(value))
        : [];
      const usageRanking = Object.entries(buildNumberUsageMap(entry?.tickets || [], "main"))
        .map(([value, count]) => ({ value: Number(value), count: Number(count || 0) }))
        .filter(item => Number.isInteger(item.value))
        .sort((a, b) => b.count - a.count || a.value - b.value)
        .map(item => item.value);
      return {
        entry,
        numbers: collectOrderedHighlightNumbers(rankedNumbers, usageRanking, highlightLimit),
      };
    }

    function getStatsLatestSpecialPredictionHighlight(type, latestEntry = null) {
      if (!TYPES[type]?.hasSpecial) return { entry: null, numbers: new Set() };
      const logs = ensurePredictionLogBucket(type)
        .filter(entry => Array.isArray(entry?.tickets) && entry.tickets.length);
      if (!logs.length) return { entry: null, numbers: new Set() };
      const targetNextKyValue = (kySortValue(latestEntry?.ky) || 0) + 1;
      const preferredLogs = targetNextKyValue
        ? logs.filter(entry => kySortValue(entry?.predictedKy) === targetNextKyValue)
        : [];
      const candidateLogs = preferredLogs.length ? preferredLogs : logs;
      const sorted = [...candidateLogs].sort((a, b) => {
        const kyDelta = kySortValue(b?.predictedKy) - kySortValue(a?.predictedKy);
        if (kyDelta !== 0) return kyDelta;
        return (Date.parse(String(b?.createdAt || "").trim()) || 0) - (Date.parse(String(a?.createdAt || "").trim()) || 0);
      });
      const entry = sorted[0] || null;
      const rankedSpecials = Array.isArray(entry?.topSpecialRanking)
        ? entry.topSpecialRanking.map(value => Number(value)).filter(value => Number.isInteger(value))
        : [];
      const usageRanking = Object.entries(buildNumberUsageMap(entry?.tickets || [], "special"))
        .map(([value, count]) => ({ value: Number(value), count: Number(count || 0) }))
        .filter(item => Number.isInteger(item.value))
        .sort((a, b) => b.count - a.count || a.value - b.value)
        .map(item => item.value);
      return {
        entry,
        numbers: collectOrderedHighlightNumbers(rankedSpecials, usageRanking, 4),
      };
    }

    function getStatsLatestMissedPredictionSet(type, latestEntry = null, latestActualSet = null) {
      const normalizedLatestKy = normalizeKy(latestEntry?.ky);
      if (!normalizedLatestKy) return new Set();
      const logs = ensurePredictionLogBucket(type)
        .filter(entry =>
          entry?.resolved &&
          Array.isArray(entry?.tickets) &&
          entry.tickets.length &&
          (normalizeKy(entry?.actualKy) === normalizedLatestKy || normalizeKy(entry?.predictedKy) === normalizedLatestKy)
        )
        .sort((a, b) => {
          const aTime = Date.parse(String(a?.resolvedAt || a?.createdAt || "").trim()) || 0;
          const bTime = Date.parse(String(b?.resolvedAt || b?.createdAt || "").trim()) || 0;
          return bTime - aTime;
        });
      const latestResolved = logs[0];
      if (!latestResolved) return new Set();
      const actualSet = latestActualSet instanceof Set ? latestActualSet : buildStatsLatestActualNumberSet(type, latestEntry);
      const predictedSet = collectStatsHighlightNumberSetFromTickets(latestResolved.tickets);
      const missed = new Set();
      predictedSet.forEach(value => {
        if (!actualSet.has(value)) missed.add(value);
      });
      return missed;
    }

    function getStatsLatestMissedSpecialPredictionSet(type, latestEntry = null, latestActualSpecialSet = null) {
      if (!TYPES[type]?.hasSpecial) return new Set();
      const normalizedLatestKy = normalizeKy(latestEntry?.ky);
      if (!normalizedLatestKy) return new Set();
      const logs = ensurePredictionLogBucket(type)
        .filter(entry =>
          entry?.resolved &&
          Array.isArray(entry?.tickets) &&
          entry.tickets.length &&
          (normalizeKy(entry?.actualKy) === normalizedLatestKy || normalizeKy(entry?.predictedKy) === normalizedLatestKy)
        )
        .sort((a, b) => {
          const aTime = Date.parse(String(a?.resolvedAt || a?.createdAt || "").trim()) || 0;
          const bTime = Date.parse(String(b?.resolvedAt || b?.createdAt || "").trim()) || 0;
          return bTime - aTime;
        });
      const latestResolved = logs[0];
      if (!latestResolved) return new Set();
      const actualSet = latestActualSpecialSet instanceof Set ? latestActualSpecialSet : buildStatsLatestActualSpecialSet(type, latestEntry);
      const rankedSpecials = Array.isArray(latestResolved?.topSpecialRanking)
        ? latestResolved.topSpecialRanking.map(value => Number(value)).filter(value => Number.isInteger(value))
        : [];
      const usageRanking = Object.entries(buildNumberUsageMap(latestResolved?.tickets || [], "special"))
        .map(([value, count]) => ({ value: Number(value), count: Number(count || 0) }))
        .filter(item => Number.isInteger(item.value))
        .sort((a, b) => b.count - a.count || a.value - b.value)
        .map(item => item.value);
      const predictedSet = collectOrderedHighlightNumbers(rankedSpecials, usageRanking, 4);
      const missed = new Set();
      predictedSet.forEach(value => {
        if (!actualSet.has(value)) missed.add(value);
      });
      return missed;
    }

    function getStatsHighlightClass(value, latestActualSet, nextPredictionSet, missedPredictionSet) {
      const numeric = Number(value);
      const isLatestHit = Number.isInteger(numeric) && latestActualSet instanceof Set && latestActualSet.has(numeric);
      const isNextPrediction = Number.isInteger(numeric) && nextPredictionSet instanceof Set && nextPredictionSet.has(numeric);
      const isMissedPrediction = Number.isInteger(numeric) && missedPredictionSet instanceof Set && missedPredictionSet.has(numeric);
      if (isLatestHit && isNextPrediction) return "is-hit-and-prediction";
      if (isLatestHit) return "is-latest-hit";
      if (isNextPrediction) return "is-next-prediction";
      if (isMissedPrediction) return "is-missed-prediction";
      return "";
    }

    function renderStatsTopGrid(type, items, { latestActualSet = null, nextPredictionSet = null, missedPredictionSet = null } = {}) {
      return `<div class="stats-insight-top-grid">${items.map((item, index) => `
        <article class="stats-insight-top-item ${getStatsHighlightClass(item?.value, latestActualSet, nextPredictionSet, missedPredictionSet)}">
          <div class="stats-insight-top-rank">Top ${index + 1}</div>
          <div class="stats-insight-top-number">${escapeHtml(item.label)}</div>
          <div class="stats-insight-top-count">${escapeHtml(`${formatLiveSyncCount(item.count)} lần xuất hiện`)}</div>
        </article>
      `).join("")}</div>`;
    }

    function shouldRenderStatsRankGrid(type) {
      return STATS_SIX_GRID_TYPES.has(type) || type === "KENO";
    }

    function getStatsRankGridClass(type) {
      if (STATS_SIX_GRID_TYPES.has(type)) return "is-six";
      if (type === "KENO") return "is-keno";
      return "";
    }

    function renderStatsRankingGrid(type, items, { latestActualSet = null, nextPredictionSet = null, missedPredictionSet = null, extraClass = "" } = {}) {
      const gridClass = getStatsRankGridClass(type);
      return `<div class="stats-insight-rank-grid ${gridClass} ${extraClass}">${items.map((item, index) => `
        <article class="stats-insight-rank-card ${getStatsHighlightClass(item?.value, latestActualSet, nextPredictionSet, missedPredictionSet)}">
          <div class="stats-insight-rank-card-position">#${index + 1}</div>
          <div class="stats-insight-rank-card-number">${escapeHtml(item.label)}</div>
          <div class="stats-insight-rank-card-count">${escapeHtml(`${formatLiveSyncCount(item.count)} lần`)}</div>
        </article>
      `).join("")}</div>`;
    }

    function renderStatsSpecialCompactGrid(type, items, { latestActualSet = null, nextPredictionSet = null, missedPredictionSet = null } = {}) {
      return `<div class="stats-insight-special-mini-grid">${items.map((item, index) => `
        <article class="stats-insight-rank-card stats-insight-special-mini-card ${getStatsHighlightClass(item?.value, latestActualSet, nextPredictionSet, missedPredictionSet)}">
          <div class="stats-insight-rank-card-position">#${index + 1}</div>
          <div class="stats-insight-rank-card-number">${escapeHtml(getStatsDisplayLabel(type, item?.value, true))}</div>
          <div class="stats-insight-rank-card-count">${escapeHtml(`${formatLiveSyncCount(item?.count || 0)} lần`)}</div>
        </article>
      `).join("")}</div>`;
    }

    function renderStatsRankingList(type, items, { latestActualSet = null, nextPredictionSet = null, missedPredictionSet = null } = {}) {
      return `<div class="stats-insight-rank-list">${items.map((item, index) => `
        <div class="stats-insight-rank-row ${getStatsHighlightClass(item?.value, latestActualSet, nextPredictionSet, missedPredictionSet)}">
          <div class="stats-insight-rank-position">#${index + 1}</div>
          <div class="stats-insight-rank-number">${escapeHtml(item.label)}</div>
          <div class="stats-insight-rank-count">${escapeHtml(`${formatLiveSyncCount(item.count)} lần`)}</div>
        </div>
      `).join("")}</div>`;
    }

    function renderStatsPanel() {
      const out = document.getElementById("statsInsightsOut");
      if (!out) return;
      renderStatsTypeTabs();
      renderStatsWindowTabs();
      const type = normalizeStatsType(statsSelectedType);
      const feed = getLiveHistoryFeed(type);
      const meta = getStatsTypeUiMeta(type);
      if (statsPanelLoading && !feed?.order?.length) {
        out.classList.add("muted");
        out.innerHTML = "Đang tải dữ liệu thống kê từ all_day.csv...";
        return;
      }
      if (statsPanelError) {
        out.classList.add("muted");
        out.innerHTML = escapeHtml(statsPanelError);
        return;
      }
      if (!feed?.order?.length) {
        out.classList.add("muted");
        out.innerHTML = IS_LOCAL_MODE
          ? "Khung thống kê cần mở qua http://localhost:8080 để đọc dữ liệu all_day.csv."
          : "Chưa có dữ liệu thống kê. Hệ thống sẽ tự tải all_day.csv khi bạn mở tab này.";
        return;
      }
      const allEntries = buildStatsEntriesForFeed(type, feed);
      const filteredEntries = filterStatsEntriesByDayWindow(allEntries, statsSelectedDayWindow);
      if (!filteredEntries.length) {
        out.classList.remove("muted");
        out.innerHTML = `<div class="stats-insight-empty">Không có dữ liệu ${escapeHtml(meta.label)} trong phạm vi ${escapeHtml(STATS_DAY_WINDOW_LABELS[statsSelectedDayWindow] || statsSelectedDayWindow)}.</div>`;
        return;
      }
      const mainRanking = buildStatsFrequencyItems(type, filteredEntries);
      const specialRanking = TYPES[type]?.hasSpecial ? buildStatsFrequencyItems(type, filteredEntries, { special: true }) : [];
      const latestEntry = filteredEntries[filteredEntries.length - 1] || null;
      const hotItem = mainRanking[0] || null;
      const latestActualSet = buildStatsLatestActualNumberSet(type, latestEntry);
      const latestActualSpecialSet = buildStatsLatestActualSpecialSet(type, latestEntry);
      const nextPredictionHighlight = getStatsLatestPredictionHighlight(type, latestEntry);
      const nextPredictionSpecialHighlight = getStatsLatestSpecialPredictionHighlight(type, latestEntry);
      const missedPredictionSet = getStatsLatestMissedPredictionSet(type, latestEntry, latestActualSet);
      const missedPredictionSpecialSet = getStatsLatestMissedSpecialPredictionSet(type, latestEntry, latestActualSpecialSet);
      const summaryTitle = TYPES[type]?.threeDigit ? "Bộ nóng nhất" : "Số nóng nhất";
      const topBlockTitle = TYPES[type]?.threeDigit ? "Top 10 Bộ 3 Số Ra Nhiều" : "Top 10 Số Ra Nhiều";
      const fullRankingTitle = STATS_SIX_GRID_TYPES.has(type)
        ? "Xếp hạng đầy đủ"
        : (type === "KENO"
          ? "Xếp hạng đầy đủ dạng lưới"
          : (TYPES[type]?.threeDigit ? "Xếp hạng đầy đủ bộ 3 số" : "Xếp hạng đầy đủ"));
      const fullRankingMetaBase = STATS_SIX_GRID_TYPES.has(type)
        ? (type === "LOTO_5_35"
          ? "Sắp theo nhiều đến ít, đọc theo lưới 5 cột"
          : "Sắp theo nhiều đến ít, đọc theo lưới 6 cột")
        : (type === "KENO"
          ? "Sắp theo nhiều đến ít, đọc theo lưới gọn"
          : "Từ nhiều nhất đến thấp nhất");
      const fullRankingMetaBits = [fullRankingMetaBase];
      if (latestActualSet.size) fullRankingMetaBits.push("Xanh = kỳ vừa rồi");
      if (nextPredictionHighlight.numbers.size) fullRankingMetaBits.push("Vàng = top 10 dự đoán kỳ tiếp theo");
      if (missedPredictionSet.size) fullRankingMetaBits.push("Đỏ = đoán sai kỳ trước");
      if (latestActualSet.size && nextPredictionHighlight.numbers.size) fullRankingMetaBits.push("Xanh-vàng = trùng cả hai");
      const fullRankingMeta = fullRankingMetaBits.join(" • ");
      const latestMeta = latestEntry
        ? `${formatLiveKy(latestEntry.ky) || ""}${latestEntry.draw?.date ? ` • ${latestEntry.draw.date}` : ""}`.replace(/^ • /, "")
        : "Không rõ";
      const rangeLabel = statsSelectedDayWindow === "custom"
        ? buildStatsCustomRangeLabel()
        : (STATS_DAY_WINDOW_LABELS[statsSelectedDayWindow] || statsSelectedDayWindow);
      const hasInlineSpecialRanking = type === "LOTO_5_35" && specialRanking.length > 0;
      const fullRankingBody = shouldRenderStatsRankGrid(type)
        ? renderStatsRankingGrid(type, mainRanking, {
            latestActualSet,
            nextPredictionSet: nextPredictionHighlight.numbers,
            missedPredictionSet,
            extraClass: hasInlineSpecialRanking ? "is-compact-loto535" : "",
          })
        : renderStatsRankingList(type, mainRanking, {
            latestActualSet,
            nextPredictionSet: nextPredictionHighlight.numbers,
            missedPredictionSet,
          });
      out.classList.remove("muted");
      out.innerHTML = `
        <div class="stats-insight-shell-grid ${meta.fullAccentClass}">
          <section class="stats-insight-summary">
            <article class="stats-insight-summary-card is-${meta.accentClass}">
              <div class="stats-insight-summary-head">
                <div class="stats-insight-summary-label">Số kỳ trong phạm vi</div>
                <div class="stats-insight-summary-value">${escapeHtml(formatLiveSyncCount(filteredEntries.length))}</div>
              </div>
              <div class="stats-insight-summary-meta">${escapeHtml(rangeLabel)}</div>
            </article>
            <article class="stats-insight-summary-card is-${meta.accentClass}">
              <div class="stats-insight-summary-head">
                <div class="stats-insight-summary-label">Ngày/Kỳ mới nhất</div>
                <div class="stats-insight-summary-value">${escapeHtml(latestEntry?.draw?.date || "--")}</div>
              </div>
              <div class="stats-insight-summary-meta">${escapeHtml(latestMeta || "--")}</div>
            </article>
            <article class="stats-insight-summary-card is-${meta.accentClass}">
              <div class="stats-insight-summary-head">
                <div class="stats-insight-summary-label">${escapeHtml(summaryTitle)}</div>
                <div class="stats-insight-summary-value">${escapeHtml(hotItem?.label || "--")}</div>
              </div>
              <div class="stats-insight-summary-meta">${escapeHtml(hotItem ? `${formatLiveSyncCount(hotItem.count)} lần xuất hiện` : "Chưa có dữ liệu")}</div>
            </article>
          </section>
          <div class="stats-insight-blocks">
            <section class="stats-insight-block">
              <div class="stats-insight-block-head">
                <div class="stats-insight-block-title">${escapeHtml(topBlockTitle)}</div>
                <div class="stats-insight-block-meta">${escapeHtml(`${rangeLabel} • ${formatLiveSyncCount(mainRanking.length)} mục`)}</div>
              </div>
              ${renderStatsTopGrid(type, mainRanking.slice(0, 10), {
                latestActualSet,
                nextPredictionSet: nextPredictionHighlight.numbers,
                missedPredictionSet,
              })}
            </section>
            ${specialRanking.length && !hasInlineSpecialRanking ? `
              <section class="stats-insight-block">
                <div class="stats-insight-block-head">
                  <div class="stats-insight-block-title">Top ĐB</div>
                  <div class="stats-insight-block-meta">${escapeHtml(rangeLabel)}</div>
                </div>
                ${renderStatsTopGrid(type, specialRanking.slice(0, 10), {
                  latestActualSet: latestActualSpecialSet,
                  nextPredictionSet: nextPredictionSpecialHighlight.numbers,
                  missedPredictionSet: missedPredictionSpecialSet,
                })}
              </section>
            ` : ""}
            <section class="stats-insight-block">
              <div class="stats-insight-block-head">
                <div class="stats-insight-block-title">${escapeHtml(fullRankingTitle)}</div>
                <div class="stats-insight-block-meta">${escapeHtml(fullRankingMeta)}</div>
              </div>
              ${hasInlineSpecialRanking ? `
                <div class="stats-insight-dual-grid">
                  <div class="stats-insight-dual-main">
                    ${fullRankingBody}
                  </div>
                  <aside class="stats-insight-dual-side">
                    <div class="stats-insight-block-head stats-insight-block-head-inline stats-insight-block-head-special">
                      <div class="stats-insight-block-title">XH ĐB</div>
                    </div>
                    ${renderStatsSpecialCompactGrid(type, specialRanking, {
                      latestActualSet: latestActualSpecialSet,
                      nextPredictionSet: nextPredictionSpecialHighlight.numbers,
                      missedPredictionSet: missedPredictionSpecialSet,
                    })}
                  </aside>
                </div>
              ` : fullRankingBody}
            </section>
          </div>
        </div>
      `;
    }

    async function startStatsPanelRefresh({ force = false, silent = true } = {}) {
      const type = normalizeStatsType(statsSelectedType);
      const refreshToken = ++statsPanelRefreshToken;
      statsPanelLoading = true;
      statsPanelError = "";
      renderStatsPanel();
      try {
        await fetchLiveHistory(type, "all", { force, silent });
        if (refreshToken !== statsPanelRefreshToken) return;
        statsPanelLoading = false;
        statsPanelError = "";
      } catch (error) {
        if (refreshToken !== statsPanelRefreshToken) return;
        statsPanelLoading = false;
        statsPanelError = `Không tải được thống kê ${getStatsTypeUiMeta(type).label}: ${String(error?.message || error || "Lỗi không rõ")}`;
      } finally {
        if (refreshToken !== statsPanelRefreshToken) return;
        renderStatsPanel();
      }
    }

    function getChartStatsTypeMeta(typeKey) {
      return getStatsTypeUiMeta(normalizeChartStatsType(typeKey));
    }

    function getChartStatsPresetLabel(value, typeKey = chartStatsSelectedType) {
      const normalized = normalizeChartStatsPreset(value, typeKey);
      return CHART_STATS_PRESET_LABELS[normalized] || `${normalized} kỳ`;
    }

    function getChartStatsGroupConfig(typeKey) {
      return CHART_STATS_GROUPS[normalizeChartStatsType(typeKey)] || CHART_STATS_GROUPS.KENO;
    }

    function getChartStatsNumbersPerDraw(typeKey) {
      return Math.max(1, Number(TYPES[normalizeChartStatsType(typeKey)]?.mainCount || 0));
    }

    function renderChartStatsTypeOptions() {
      const host = document.getElementById("chartStatsTypeSelect");
      if (!host) return;
      chartStatsSelectedType = normalizeChartStatsType(chartStatsSelectedType);
      host.innerHTML = CHART_STATS_TYPE_OPTIONS.map(item => `<option value="${escapeHtml(item.value)}">${escapeHtml(item.label)}</option>`).join("");
      host.value = CHART_STATS_TYPE_OPTIONS.some(item => item.value === chartStatsSelectedType) ? chartStatsSelectedType : "KENO";
      if (typeof host.__syncCustomSelect === "function") host.__syncCustomSelect();
    }

    function renderChartStatsPresetOptions() {
      const host = document.getElementById("chartStatsPresetSelect");
      if (!host) return;
      chartStatsSelectedPreset = normalizeChartStatsPreset(chartStatsSelectedPreset, chartStatsSelectedType);
      host.innerHTML = getChartStatsPresetOptions(chartStatsSelectedType)
        .map(value => `<option value="${escapeHtml(value)}">${escapeHtml(getChartStatsPresetLabel(value, chartStatsSelectedType))}</option>`)
        .join("");
      host.value = chartStatsSelectedPreset;
      if (typeof host.__syncCustomSelect === "function") host.__syncCustomSelect();
    }

    function renderChartStatsViewOptions() {
      const host = document.getElementById("chartStatsViewSelect");
      if (!host) return;
      chartStatsViewMode = normalizeChartStatsViewMode(chartStatsViewMode);
      host.innerHTML = CHART_STATS_VIEW_OPTIONS.map(item => `<option value="${escapeHtml(item.value)}">${escapeHtml(item.label)}</option>`).join("");
      host.value = chartStatsViewMode;
      if (typeof host.__syncCustomSelect === "function") host.__syncCustomSelect();
    }

    function renderChartStatsControls(totalAvailable = 0) {
      ensureChartStatsPresetForType();
      renderChartStatsTypeOptions();
      renderChartStatsPresetOptions();
      renderChartStatsViewOptions();
      const input = document.getElementById("chartStatsCustomCount");
      const note = document.getElementById("chartStatsCountHint");
      if (!input || !note) return;
      input.disabled = chartStatsSelectedPreset !== "custom";
      input.min = "1";
      input.max = totalAvailable > 0 ? String(totalAvailable) : "";
      input.value = chartStatsSelectedPreset === "custom" ? String(chartStatsCustomCountValue || "") : "";
      if (chartStatsSelectedPreset === "custom") {
        note.textContent = totalAvailable > 0
          ? `Nhập từ 1 đến ${formatLiveSyncCount(totalAvailable)} kỳ. Nếu nhập lớn hơn dữ liệu hiện có, hệ thống sẽ tự dùng toàn bộ dữ liệu đang có.`
          : "Nhập số kỳ tùy chỉnh để phân tích.";
      } else if (chartStatsSelectedPreset === "all") {
        note.textContent = totalAvailable > 0
          ? `Đang dùng toàn bộ ${formatLiveSyncCount(totalAvailable)} kỳ hiện có của ${getChartStatsTypeMeta(chartStatsSelectedType).label}.`
          : "Đang dùng toàn bộ dữ liệu hiện có.";
      } else {
        note.textContent = `Preset hiện tại: ${getChartStatsPresetLabel(chartStatsSelectedPreset, chartStatsSelectedType)}. Chuyển sang Tùy chỉnh nếu bạn muốn nhập số kỳ bất kỳ.`;
      }
    }

    function resolveChartStatsRequestedCount(totalAvailable) {
      const available = Math.max(0, Number(totalAvailable || 0));
      const preset = normalizeChartStatsPreset(chartStatsSelectedPreset, chartStatsSelectedType);
      if (preset === "all") {
        return {
          mode: "all",
          requestedCount: available,
          requestedLabel: "All",
          actualUsedCount: available,
          valid: true,
          helperText: `Dùng toàn bộ ${formatLiveSyncCount(available)} kỳ hiện có.`,
        };
      }
      if (preset === "custom") {
        const customCount = Number(chartStatsCustomCountValue || 0);
        if (!Number.isInteger(customCount) || customCount <= 0) {
          return {
            mode: "custom",
            requestedCount: 0,
            requestedLabel: "Tùy chỉnh",
            actualUsedCount: 0,
            valid: false,
            helperText: available > 0
              ? `Nhập số kỳ từ 1 đến ${formatLiveSyncCount(available)} để xem biểu đồ.`
              : "Chưa có dữ liệu để nhập số kỳ.",
          };
        }
        return {
          mode: "custom",
          requestedCount: customCount,
          requestedLabel: String(customCount),
          actualUsedCount: Math.min(customCount, available),
          valid: true,
          helperText: customCount > available
            ? `Yêu cầu ${formatLiveSyncCount(customCount)} kỳ nhưng hiện chỉ có ${formatLiveSyncCount(available)} kỳ, hệ thống sẽ dùng toàn bộ dữ liệu hiện có.`
            : `Đang dùng ${formatLiveSyncCount(Math.min(customCount, available))} kỳ theo số bạn nhập.`,
        };
      }
      const presetCount = Math.max(1, Number(preset) || 1);
      return {
        mode: "preset",
        requestedCount: presetCount,
        requestedLabel: String(presetCount),
        actualUsedCount: Math.min(presetCount, available),
        valid: true,
        helperText: presetCount > available
          ? `Preset yêu cầu ${formatLiveSyncCount(presetCount)} kỳ nhưng dữ liệu hiện có là ${formatLiveSyncCount(available)} kỳ.`
          : `Preset đang dùng ${formatLiveSyncCount(presetCount)} kỳ gần nhất.`,
      };
    }

    function buildChartStatsEntries(typeKey, requestedInfo) {
      const entries = buildStatsEntriesForFeed(typeKey, getLiveHistoryFeed(typeKey));
      const actualUsed = Math.max(0, Number(requestedInfo?.actualUsedCount || 0));
      if (!entries.length || actualUsed <= 0) return [];
      return entries.slice(-actualUsed);
    }

    function computeChartStatsGroupRows(typeKey, entries) {
      const groups = getChartStatsGroupConfig(typeKey).map(item => ({
        ...item,
        count: 0,
      }));
      let totalHits = 0;
      (Array.isArray(entries) ? entries : []).forEach(entry => {
        const numbers = Array.isArray(entry?.draw?.main) ? entry.draw.main.map(Number).filter(Number.isInteger) : [];
        numbers.forEach(number => {
          const group = groups.find(item => number >= item.min && number <= item.max);
          if (!group) return;
          group.count += 1;
          totalHits += 1;
        });
      });
      const maxCount = groups.reduce((max, item) => Math.max(max, item.count), 0) || 1;
      return groups.map(item => ({
        ...item,
        percent: totalHits > 0 ? (item.count / totalHits) * 100 : 0,
        frequencyRatio: maxCount > 0 ? item.count / maxCount : 0,
      }));
    }

    function formatChartStatsPercent(value) {
      return `${Number(value || 0).toFixed(2)}%`;
    }

    function renderChartStatsSummary(meta, requestedInfo, entries, rows) {
      const totalHits = rows.reduce((sum, item) => sum + Number(item.count || 0), 0);
      return `
        <section class="chart-stats-summary ${escapeHtml(meta.fullAccentClass)}">
          <article class="chart-stats-summary-card">
            <div class="chart-stats-summary-label">Loại xổ số</div>
            <div class="chart-stats-summary-value">${escapeHtml(meta.label)}</div>
            <div class="chart-stats-summary-meta">Nhóm số theo cấu hình của ${escapeHtml(meta.label)}</div>
          </article>
          <article class="chart-stats-summary-card">
            <div class="chart-stats-summary-label">Kỳ yêu cầu</div>
            <div class="chart-stats-summary-value">${escapeHtml(requestedInfo.mode === "all" ? "All" : formatLiveSyncCount(requestedInfo.requestedCount))}</div>
            <div class="chart-stats-summary-meta">${escapeHtml(requestedInfo.helperText || "Phân tích theo số kỳ đã chọn")}</div>
          </article>
          <article class="chart-stats-summary-card">
            <div class="chart-stats-summary-label">Kỳ thực dùng</div>
            <div class="chart-stats-summary-value">${escapeHtml(formatLiveSyncCount(requestedInfo.actualUsedCount))}</div>
            <div class="chart-stats-summary-meta">${escapeHtml(`Lấy từ ${formatLiveSyncCount(entries.length)} kỳ gần nhất phù hợp`)}</div>
          </article>
          <article class="chart-stats-summary-card">
            <div class="chart-stats-summary-label">Tổng lượt số đã phân tích</div>
            <div class="chart-stats-summary-value">${escapeHtml(formatLiveSyncCount(totalHits))}</div>
            <div class="chart-stats-summary-meta">${escapeHtml(`${getChartStatsNumbersPerDraw(chartStatsSelectedType)} số / kỳ`)}</div>
          </article>
        </section>
      `;
    }

    function renderChartStatsFrequencyChart(meta, requestedInfo, rows) {
      const titleLabel = requestedInfo.mode === "all" ? "All kỳ" : `${formatLiveSyncCount(requestedInfo.requestedCount)} kỳ`;
      return `
        <section class="chart-stats-block">
          <div class="chart-stats-block-head">
            <div class="chart-stats-block-title">${escapeHtml(`${meta.label} - ${titleLabel} - Tần suất theo nhóm`)}</div>
            <div class="chart-stats-block-meta">${escapeHtml(`Thực dùng ${formatLiveSyncCount(requestedInfo.actualUsedCount)} kỳ`)}</div>
          </div>
          <div class="chart-stats-frequency-chart">
            ${rows.map(item => `
              <article class="chart-stats-frequency-item">
                <div class="chart-stats-frequency-value">${escapeHtml(formatLiveSyncCount(item.count))}</div>
                <div class="chart-stats-frequency-bar-shell">
                  <div class="chart-stats-frequency-bar" style="height:${(Number(item.count || 0) > 0 ? Math.max(6, Number(item.frequencyRatio || 0) * 100) : 0).toFixed(2)}%; --chart-bar-color:${escapeHtml(item.color)}; --chart-bar-opacity:${(0.26 + Math.max(0, Math.min(1, Number(item.frequencyRatio || 0))) * 0.74).toFixed(3)}; --chart-bar-bright:${(0.76 + Math.max(0, Math.min(1, Number(item.frequencyRatio || 0))) * 0.44).toFixed(3)}; --chart-bar-sat:${(0.84 + Math.max(0, Math.min(1, Number(item.frequencyRatio || 0))) * 0.32).toFixed(3)};"></div>
                </div>
                <div class="chart-stats-frequency-label">${escapeHtml(item.label)}</div>
              </article>
            `).join("")}
          </div>
        </section>
      `;
    }

    function renderChartStatsPercentChart(meta, requestedInfo, rows) {
      const titleLabel = requestedInfo.mode === "all" ? "All kỳ" : `${formatLiveSyncCount(requestedInfo.requestedCount)} kỳ`;
      const totalHits = rows.reduce((sum, item) => sum + Number(item.count || 0), 0);
      const radius = 72;
      const stroke = 18;
      const circumference = 2 * Math.PI * radius;
      const activeRows = rows.filter(item => Number(item.count || 0) > 0 && Number(item.percent || 0) > 0);
      if (!activeRows.length || totalHits <= 0) {
        return `
          <section class="chart-stats-block">
            <div class="chart-stats-block-head">
              <div class="chart-stats-block-title">${escapeHtml(`${meta.label} - ${titleLabel} - Tỷ trọng %`)}</div>
              <div class="chart-stats-block-meta">${escapeHtml(`Tổng lượt số ${formatLiveSyncCount(totalHits)}`)}</div>
            </div>
            <div class="chart-stats-donut-empty">Chưa có đủ dữ liệu để dựng donut tỷ trọng %.</div>
          </section>
        `;
      }
      let accumulated = 0;
      const donutSegmentsHtml = activeRows.map(item => {
        const percent = Math.max(0, Number(item.percent || 0));
        const segmentLength = (percent / 100) * circumference;
        const dashOffset = circumference - accumulated;
        accumulated += segmentLength;
        return `<circle
          class="chart-stats-donut-segment"
          cx="90"
          cy="90"
          r="${radius}"
          fill="none"
          stroke="${escapeHtml(item.color)}"
          stroke-width="${stroke}"
          stroke-linecap="round"
          stroke-dasharray="${segmentLength.toFixed(3)} ${(circumference - segmentLength).toFixed(3)}"
          stroke-dashoffset="${dashOffset.toFixed(3)}"
          style="--chart-bar-opacity:${(0.34 + Math.max(0, Math.min(1, percent / 100)) * 0.66).toFixed(3)}; --chart-bar-bright:${(0.84 + Math.max(0, Math.min(1, percent / 100)) * 0.34).toFixed(3)}; --chart-bar-sat:${(0.88 + Math.max(0, Math.min(1, percent / 100)) * 0.26).toFixed(3)};"
        />`;
      }).join("");
      return `
        <section class="chart-stats-block">
          <div class="chart-stats-block-head">
            <div class="chart-stats-block-title">${escapeHtml(`${meta.label} - ${titleLabel} - Tỷ trọng %`)}</div>
            <div class="chart-stats-block-meta">${escapeHtml(`Tổng lượt số ${formatLiveSyncCount(totalHits)}`)}</div>
          </div>
          <div class="chart-stats-donut-layout">
            <div class="chart-stats-donut-wrap">
              <svg class="chart-stats-donut-svg" viewBox="0 0 180 180" aria-hidden="true">
                <circle class="chart-stats-donut-track" cx="90" cy="90" r="${radius}" fill="none" stroke-width="${stroke}"></circle>
                <g class="chart-stats-donut-ring">${donutSegmentsHtml}</g>
              </svg>
              <div class="chart-stats-donut-center">
                <div class="chart-stats-donut-center-value">100%</div>
                <div class="chart-stats-donut-center-label">Tỷ trọng</div>
                <div class="chart-stats-donut-center-meta">${escapeHtml(`${formatLiveSyncCount(activeRows.length)} nhóm`)}</div>
              </div>
            </div>
            <div class="chart-stats-donut-legend">
              ${rows.map(item => `
                <div class="chart-stats-donut-legend-item">
                  <span class="chart-stats-donut-legend-swatch" style="--chart-bar-color:${escapeHtml(item.color)}"></span>
                  <span class="chart-stats-donut-legend-label">${escapeHtml(item.label)}</span>
                  <span class="chart-stats-donut-legend-percent">${escapeHtml(formatChartStatsPercent(item.percent))}</span>
                  <span class="chart-stats-donut-legend-count">${escapeHtml(formatLiveSyncCount(item.count))}</span>
                </div>
              `).join("")}
            </div>
          </div>
        </section>
      `;
    }

    function renderChartStatsTable(rows) {
      return `
        <section class="chart-stats-block">
          <div class="chart-stats-block-head">
            <div class="chart-stats-block-title">Bảng thống kê theo nhóm</div>
            <div class="chart-stats-block-meta">${escapeHtml(`${formatLiveSyncCount(rows.length)} nhóm số`)}</div>
          </div>
          <div class="chart-stats-table-wrap">
            <table class="chart-stats-table">
              <thead>
                <tr>
                  <th>Nhóm số</th>
                  <th>Tần suất</th>
                  <th>Tỷ trọng %</th>
                </tr>
              </thead>
              <tbody>
                ${rows.map(item => `
                  <tr>
                    <td><span class="chart-stats-table-chip" style="--chart-bar-color:${escapeHtml(item.color)};">${escapeHtml(item.label)}</span></td>
                    <td>${escapeHtml(formatLiveSyncCount(item.count))}</td>
                    <td>${escapeHtml(formatChartStatsPercent(item.percent))}</td>
                  </tr>
                `).join("")}
              </tbody>
            </table>
          </div>
        </section>
      `;
    }

    function renderChartStatsPanel() {
      const out = document.getElementById("chartStatsOut");
      if (!out) return;
      const type = normalizeChartStatsType(chartStatsSelectedType);
      const feed = getLiveHistoryFeed(type);
      const meta = getChartStatsTypeMeta(type);
      const allEntries = buildStatsEntriesForFeed(type, feed);
      renderChartStatsControls(allEntries.length);
      if (chartStatsPanelLoading && !feed?.order?.length) {
        out.classList.add("muted");
        out.innerHTML = "Đang tải dữ liệu biểu đồ thống kê từ all_day.csv...";
        return;
      }
      if (chartStatsPanelError) {
        out.classList.add("muted");
        out.innerHTML = escapeHtml(chartStatsPanelError);
        return;
      }
      if (!feed?.order?.length) {
        out.classList.add("muted");
        out.innerHTML = IS_LOCAL_MODE
          ? "Khung biểu đồ thống kê cần mở qua http://localhost:8080 để đọc dữ liệu all_day.csv."
          : "Chưa có dữ liệu biểu đồ thống kê. Hệ thống sẽ tự tải all_day.csv khi bạn mở tab này.";
        return;
      }
      const requestedInfo = resolveChartStatsRequestedCount(allEntries.length);
      if (!requestedInfo.valid) {
        out.classList.add("muted");
        out.innerHTML = escapeHtml(requestedInfo.helperText || "Chưa đủ thông tin để hiển thị biểu đồ.");
        return;
      }
      const entries = buildChartStatsEntries(type, requestedInfo);
      if (!entries.length) {
        out.classList.remove("muted");
        out.innerHTML = `<div class="chart-stats-empty">Không có dữ liệu ${escapeHtml(meta.label)} cho số kỳ đã chọn.</div>`;
        return;
      }
      const rows = computeChartStatsGroupRows(type, entries);
      const chartBlocks = [];
      if (chartStatsViewMode === "all" || chartStatsViewMode === "frequency") {
        chartBlocks.push(renderChartStatsFrequencyChart(meta, requestedInfo, rows));
      }
      if (chartStatsViewMode === "all" || chartStatsViewMode === "percent") {
        chartBlocks.push(renderChartStatsPercentChart(meta, requestedInfo, rows));
      }
      out.classList.remove("muted");
      out.innerHTML = `
        <div class="chart-stats-shell-grid ${escapeHtml(meta.fullAccentClass)}">
          ${renderChartStatsSummary(meta, requestedInfo, entries, rows)}
          <div class="chart-stats-grid">
            ${chartBlocks.join("")}
          </div>
          ${renderChartStatsTable(rows)}
        </div>
      `;
    }

    async function startChartStatsRefresh({ force = false, silent = true } = {}) {
      const type = normalizeChartStatsType(chartStatsSelectedType);
      const refreshToken = ++chartStatsPanelRefreshToken;
      chartStatsPanelLoading = true;
      chartStatsPanelError = "";
      renderChartStatsPanel();
      try {
        await fetchLiveHistory(type, "all", { force, silent });
        if (refreshToken !== chartStatsPanelRefreshToken) return;
        chartStatsPanelLoading = false;
        chartStatsPanelError = "";
      } catch (error) {
        if (refreshToken !== chartStatsPanelRefreshToken) return;
        chartStatsPanelLoading = false;
        chartStatsPanelError = `Không tải được biểu đồ thống kê ${getChartStatsTypeMeta(type).label}: ${String(error?.message || error || "Lỗi không rõ")}`;
      } finally {
        if (refreshToken !== chartStatsPanelRefreshToken) return;
        renderChartStatsPanel();
      }
    }

    function getDashboardTypeMeta(type) {
      const mapping = {
        KENO: { label: "Keno", accent: "#6f66ff" },
        LOTO_5_35: { label: "Lotto 5/35", accent: "#6c63ff" },
        LOTO_6_45: { label: "Mega 6/45", accent: "#4f8cff" },
        LOTO_6_55: { label: "Power 6/55", accent: "#7f63ff" },
      };
      return mapping[type] || mapping.KENO;
    }

    function floorDashboardDate(dateValue) {
      const next = new Date(dateValue instanceof Date ? dateValue.getTime() : Date.now());
      next.setHours(0, 0, 0, 0);
      return next;
    }

    function shiftDashboardDate(dateValue, deltaDays) {
      const next = new Date(dateValue.getTime());
      next.setDate(next.getDate() + Number(deltaDays || 0));
      return next;
    }

    function addDashboardMonths(dateValue, deltaMonths) {
      return new Date(dateValue.getFullYear(), dateValue.getMonth() + Number(deltaMonths || 0), 1);
    }

    function getDashboardWeekStart(dateValue) {
      const next = floorDashboardDate(dateValue);
      const weekday = next.getDay();
      const diff = weekday === 0 ? -6 : 1 - weekday;
      next.setDate(next.getDate() + diff);
      return next;
    }

    function formatDashboardDateKey(dateValue) {
      const year = dateValue.getFullYear();
      const month = String(dateValue.getMonth() + 1).padStart(2, "0");
      const day = String(dateValue.getDate()).padStart(2, "0");
      return `${year}-${month}-${day}`;
    }

    function formatDashboardShortDate(dateValue) {
      const day = String(dateValue.getDate()).padStart(2, "0");
      const month = String(dateValue.getMonth() + 1).padStart(2, "0");
      return `${day}/${month}`;
    }

    function formatDashboardMonthLabel(dateValue) {
      const month = String(dateValue.getMonth() + 1).padStart(2, "0");
      return `${month}/${dateValue.getFullYear()}`;
    }

    function formatDashboardNumber(value, fractionDigits = 1) {
      const numeric = Number(value || 0);
      return new Intl.NumberFormat("vi-VN", {
        minimumFractionDigits: fractionDigits,
        maximumFractionDigits: fractionDigits,
      }).format(Number.isFinite(numeric) ? numeric : 0);
    }

    function formatDashboardInteger(value) {
      return new Intl.NumberFormat("vi-VN").format(Math.max(0, Number(value || 0)));
    }

    function formatDashboardRelativeTime(value) {
      const parsed = value instanceof Date ? value : new Date(String(value || "").trim());
      if (!(parsed instanceof Date) || Number.isNaN(parsed.getTime())) return "chưa rõ";
      const diffMs = Math.max(0, Date.now() - parsed.getTime());
      const diffMinutes = Math.floor(diffMs / 60000);
      if (diffMinutes < 1) return "vừa xong";
      if (diffMinutes < 60) return `${diffMinutes} phút trước`;
      const diffHours = Math.floor(diffMinutes / 60);
      if (diffHours < 24) return `${diffHours} giờ trước`;
      const diffDays = Math.floor(diffHours / 24);
      return `${diffDays} ngày trước`;
    }

    function normalizeDashboardActivityViewMode(value) {
      return normalizeDashboardActivityView(value);
    }

    function normalizeDashboardDistributionViewMode(value) {
      return normalizeDashboardDistributionView(value);
    }

    function buildDashboardEntries() {
      return DASHBOARD_LOTTO_TYPES
        .flatMap(type => {
          const feedEntries = buildStatsEntriesForFeed(type, getLiveHistoryFeed(type));
          return feedEntries
            .map(entry => {
              const parsedDate = parseLiveDate(entry.draw?.date || "");
              if (!(parsedDate instanceof Date) || Number.isNaN(parsedDate.getTime())) return null;
              const mainNumbers = (Array.isArray(entry.draw?.main) ? entry.draw.main : [])
                .map(Number)
                .filter(Number.isInteger);
              return {
                type,
                ky: entry.ky,
                draw: entry.draw,
                date: parsedDate,
                dayStart: floorDashboardDate(parsedDate),
                mainNumbers,
                hitCount: mainNumbers.length,
              };
            })
            .filter(Boolean);
        })
        .sort((a, b) => {
          const dateDelta = a.date.getTime() - b.date.getTime();
          if (dateDelta !== 0) return dateDelta;
          const typeDelta = DASHBOARD_LOTTO_TYPES.indexOf(a.type) - DASHBOARD_LOTTO_TYPES.indexOf(b.type);
          if (typeDelta !== 0) return typeDelta;
          return kySortValue(a.ky) - kySortValue(b.ky);
        });
    }

    function getDashboardLatestDate(entries) {
      const latest = (Array.isArray(entries) ? entries : []).at(-1)?.dayStart;
      return latest instanceof Date && !Number.isNaN(latest.getTime()) ? latest : floorDashboardDate(new Date());
    }

    function filterDashboardEntriesInRange(entries, startDate, endDate) {
      const startTime = startDate.getTime();
      const endTime = endDate.getTime();
      return (Array.isArray(entries) ? entries : []).filter(entry => {
        const currentTime = entry?.dayStart instanceof Date ? entry.dayStart.getTime() : NaN;
        return Number.isFinite(currentTime) && currentTime >= startTime && currentTime <= endTime;
      });
    }

    function computeDashboardWindowMetrics(entries, windowDays, latestDate) {
      const safeWindowDays = Math.max(1, Number(windowDays || 0) || 1);
      const latest = latestDate instanceof Date ? latestDate : getDashboardLatestDate(entries);
      const currentEnd = floorDashboardDate(latest);
      const currentStart = shiftDashboardDate(currentEnd, -(safeWindowDays - 1));
      const previousEnd = shiftDashboardDate(currentStart, -1);
      const previousStart = shiftDashboardDate(previousEnd, -(safeWindowDays - 1));
      const currentEntries = filterDashboardEntriesInRange(entries, currentStart, currentEnd);
      const previousEntries = filterDashboardEntriesInRange(entries, previousStart, previousEnd);
      const currentDraws = currentEntries.length;
      const previousDraws = previousEntries.length;
      const currentHits = currentEntries.reduce((sum, entry) => sum + Number(entry.hitCount || 0), 0);
      const previousHits = previousEntries.reduce((sum, entry) => sum + Number(entry.hitCount || 0), 0);
      const currentSessionsPerDay = currentDraws / safeWindowDays;
      const previousFrequencyPerDay = previousHits / safeWindowDays;
      const currentFrequencyPerDay = currentHits / safeWindowDays;
      const trendRatio = (currentFrequencyPerDay - previousFrequencyPerDay) / Math.max(1, previousFrequencyPerDay || 1);
      let badge = { label: "Ổn định", tone: "stable", detail: "Biên độ gần như giữ nguyên so với giai đoạn trước." };
      if (trendRatio >= 0.08) {
        badge = { label: "Tăng", tone: "up", detail: "Lượng phân tích đang tăng rõ trong giai đoạn này." };
      } else if (trendRatio <= -0.08) {
        badge = { label: "Giảm nhẹ", tone: "down", detail: "Lượng phân tích đang giảm nhẹ so với giai đoạn trước." };
      }
      return {
        currentDraws,
        currentHits,
        currentFrequencyPerDay,
        currentSessionsPerDay,
        previousDraws,
        badge,
      };
    }

    function renderDashboardKpiCard(title, metrics) {
      return `
        <article class="lotto-dashboard-kpi-card">
          <div class="lotto-dashboard-kpi-head">
            <div class="lotto-dashboard-kpi-title">${escapeHtml(title)}</div>
            <span class="lotto-dashboard-badge is-${escapeHtml(metrics.badge.tone)}">${escapeHtml(metrics.badge.label)}</span>
          </div>
          <div class="lotto-dashboard-kpi-metrics">
            <div class="lotto-dashboard-kpi-metric">
              <div class="lotto-dashboard-kpi-metric-label">Số kỳ đã phân tích</div>
              <div class="lotto-dashboard-kpi-metric-value">${escapeHtml(formatDashboardInteger(metrics.currentDraws))}</div>
              <div class="lotto-dashboard-kpi-metric-meta">${escapeHtml(`${formatDashboardInteger(metrics.previousDraws)} kỳ ở giai đoạn trước`)}</div>
            </div>
            <div class="lotto-dashboard-kpi-metric">
              <div class="lotto-dashboard-kpi-metric-label">Tần suất trung bình / ngày</div>
              <div class="lotto-dashboard-kpi-metric-value is-accent">${escapeHtml(formatDashboardNumber(metrics.currentFrequencyPerDay, 1))}</div>
              <div class="lotto-dashboard-kpi-metric-meta">lượt số/ngày</div>
            </div>
            <div class="lotto-dashboard-kpi-metric">
              <div class="lotto-dashboard-kpi-metric-label">Số phiên phân tích / ngày</div>
              <div class="lotto-dashboard-kpi-metric-value is-secondary">${escapeHtml(formatDashboardNumber(metrics.currentSessionsPerDay, 1))}</div>
              <div class="lotto-dashboard-kpi-metric-meta">phiên/ngày</div>
            </div>
          </div>
          <div class="lotto-dashboard-kpi-note">${escapeHtml(metrics.badge.detail)}</div>
        </article>
      `;
    }

    function getDashboardBucketKey(dateValue, mode) {
      if (mode === "month") {
        return `${dateValue.getFullYear()}-${String(dateValue.getMonth() + 1).padStart(2, "0")}`;
      }
      if (mode === "week") {
        return `week-${formatDashboardDateKey(getDashboardWeekStart(dateValue))}`;
      }
      return formatDashboardDateKey(floorDashboardDate(dateValue));
    }

    function getDashboardActivityBuckets(entries, mode) {
      const normalizedMode = normalizeDashboardActivityViewMode(mode);
      const latestDate = getDashboardLatestDate(entries);
      const limit = DASHBOARD_ACTIVITY_BUCKET_LIMITS[normalizedMode] || 12;
      const buckets = [];
      if (normalizedMode === "month") {
        const latestMonth = new Date(latestDate.getFullYear(), latestDate.getMonth(), 1);
        for (let index = limit - 1; index >= 0; index -= 1) {
          const start = addDashboardMonths(latestMonth, -index);
          const end = new Date(start.getFullYear(), start.getMonth() + 1, 0, 23, 59, 59, 999);
          buckets.push({
            key: getDashboardBucketKey(start, normalizedMode),
            label: formatDashboardMonthLabel(start),
            tooltipLabel: `Tháng ${formatDashboardMonthLabel(start)}`,
            start,
            end,
            value: 0,
            drawCount: 0,
          });
        }
      } else if (normalizedMode === "week") {
        const latestWeek = getDashboardWeekStart(latestDate);
        for (let index = limit - 1; index >= 0; index -= 1) {
          const start = shiftDashboardDate(latestWeek, -7 * index);
          const end = new Date(start.getTime());
          end.setDate(end.getDate() + 6);
          end.setHours(23, 59, 59, 999);
          buckets.push({
            key: getDashboardBucketKey(start, normalizedMode),
            label: formatDashboardShortDate(start),
            tooltipLabel: `${formatDashboardShortDate(start)} - ${formatDashboardShortDate(end)}`,
            start,
            end,
            value: 0,
            drawCount: 0,
          });
        }
      } else {
        const latestDay = floorDashboardDate(latestDate);
        for (let index = limit - 1; index >= 0; index -= 1) {
          const start = shiftDashboardDate(latestDay, -index);
          const end = new Date(start.getTime());
          end.setHours(23, 59, 59, 999);
          buckets.push({
            key: getDashboardBucketKey(start, normalizedMode),
            label: formatDashboardShortDate(start),
            tooltipLabel: formatLiveDateFromDate(start),
            start,
            end,
            value: 0,
            drawCount: 0,
          });
        }
      }
      const bucketMap = new Map(buckets.map(item => [item.key, item]));
      (Array.isArray(entries) ? entries : []).forEach(entry => {
        const bucketKey = getDashboardBucketKey(entry.date, normalizedMode);
        const bucket = bucketMap.get(bucketKey);
        if (!bucket) return;
        bucket.value += Number(entry.hitCount || 0);
        bucket.drawCount += 1;
      });
      return buckets;
    }

    function buildDashboardSmoothPath(points) {
      if (!Array.isArray(points) || !points.length) return "";
      if (points.length === 1) return `M ${points[0].x} ${points[0].y}`;
      let d = `M ${points[0].x} ${points[0].y}`;
      for (let index = 0; index < points.length - 1; index += 1) {
        const p0 = points[index - 1] || points[index];
        const p1 = points[index];
        const p2 = points[index + 1];
        const p3 = points[index + 2] || p2;
        const cp1x = p1.x + (p2.x - p0.x) / 6;
        const cp1y = p1.y + (p2.y - p0.y) / 6;
        const cp2x = p2.x - (p3.x - p1.x) / 6;
        const cp2y = p2.y - (p3.y - p1.y) / 6;
        d += ` C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${p2.x} ${p2.y}`;
      }
      return d;
    }

    function buildDashboardAreaPath(points, baseY) {
      if (!Array.isArray(points) || !points.length) return "";
      return `${buildDashboardSmoothPath(points)} L ${points.at(-1).x} ${baseY} L ${points[0].x} ${baseY} Z`;
    }

    function renderDashboardActivityStats(buckets) {
      const totalDraws = buckets.reduce((sum, bucket) => sum + Number(bucket.drawCount || 0), 0);
      const totalAnalyses = buckets.reduce((sum, bucket) => sum + Number(bucket.value || 0), 0);
      const averagePerSession = totalDraws > 0 ? totalAnalyses / totalDraws : 0;
      return `
        <div class="lotto-dashboard-mini-stat">
          <div class="lotto-dashboard-mini-stat-label">Tổng số kỳ</div>
          <div class="lotto-dashboard-mini-stat-value">${escapeHtml(formatDashboardInteger(totalDraws))}</div>
        </div>
        <div class="lotto-dashboard-mini-stat">
          <div class="lotto-dashboard-mini-stat-label">Số lần phân tích</div>
          <div class="lotto-dashboard-mini-stat-value">${escapeHtml(formatDashboardInteger(totalAnalyses))}</div>
        </div>
        <div class="lotto-dashboard-mini-stat">
          <div class="lotto-dashboard-mini-stat-label">Trung bình mỗi phiên</div>
          <div class="lotto-dashboard-mini-stat-value">${escapeHtml(formatDashboardNumber(averagePerSession, 1))}</div>
        </div>
      `;
    }

    function renderDashboardActivityChart(buckets, mode) {
      const normalizedMode = normalizeDashboardActivityViewMode(mode);
      const totalDraws = buckets.reduce((sum, bucket) => sum + Number(bucket.drawCount || 0), 0);
      if (!totalDraws) {
        return `<div class="lotto-dashboard-empty-state">Chưa đủ dữ liệu thật để dựng biểu đồ hoạt động theo ${normalizedMode === "day" ? "ngày" : normalizedMode === "week" ? "tuần" : "tháng"}.</div>`;
      }
      const values = buckets.map(item => Number(item.value || 0));
      const targetValue = values.reduce((sum, value) => sum + value, 0) / Math.max(1, values.length);
      const maxValue = Math.max(1, targetValue, ...values);
      const width = 720;
      const height = 310;
      const paddingX = 28;
      const paddingTop = 16;
      const paddingBottom = 42;
      const chartWidth = width - paddingX * 2;
      const chartHeight = height - paddingTop - paddingBottom;
      const points = buckets.map((bucket, index) => ({
        ...bucket,
        x: paddingX + (buckets.length === 1 ? chartWidth / 2 : (chartWidth / Math.max(1, buckets.length - 1)) * index),
        y: paddingTop + chartHeight - ((Number(bucket.value || 0) / maxValue) * chartHeight),
      }));
      const goalY = paddingTop + chartHeight - ((targetValue / maxValue) * chartHeight);
      const linePath = buildDashboardSmoothPath(points);
      const areaPath = buildDashboardAreaPath(points, paddingTop + chartHeight);
      const gridLines = Array.from({ length: 4 }, (_, index) => {
        const ratio = index / 3;
        const y = paddingTop + chartHeight - ratio * chartHeight;
        const value = maxValue * ratio;
        return { y, value };
      }).reverse();
      return `
        <div class="lotto-dashboard-line-chart-shell">
          <div class="lotto-dashboard-line-chart-wrap">
            <svg class="lotto-dashboard-line-chart" viewBox="0 0 ${width} ${height}" aria-hidden="true">
              <defs>
                <linearGradient id="lottoDashboardAreaFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stop-color="rgba(109, 92, 255, .28)"></stop>
                  <stop offset="100%" stop-color="rgba(109, 92, 255, 0)"></stop>
                </linearGradient>
              </defs>
              ${gridLines.map(line => `
                <g>
                  <line class="lotto-dashboard-grid-line" x1="${paddingX}" y1="${line.y}" x2="${width - paddingX}" y2="${line.y}"></line>
                  <text class="lotto-dashboard-grid-label" x="${paddingX - 8}" y="${line.y + 4}" text-anchor="end">${escapeHtml(formatDashboardInteger(Math.round(line.value)))}</text>
                </g>
              `).join("")}
              <line class="lotto-dashboard-target-line" x1="${paddingX}" y1="${goalY}" x2="${width - paddingX}" y2="${goalY}"></line>
              <path class="lotto-dashboard-line-area" d="${areaPath}"></path>
              <path class="lotto-dashboard-line-path" d="${linePath}"></path>
              ${points.map(point => `
                <circle
                  class="lotto-dashboard-line-point"
                  cx="${point.x}"
                  cy="${point.y}"
                  r="5"
                  data-dashboard-label="${escapeHtml(point.tooltipLabel)}"
                  data-dashboard-value="${escapeHtml(formatDashboardInteger(point.value))}"
                  data-dashboard-meta="${escapeHtml(`${formatDashboardInteger(point.drawCount)} kỳ • ${point.value ? formatDashboardNumber(point.value / Math.max(1, point.drawCount), 1) : "0.0"} số/kỳ`)}"
                ></circle>
              `).join("")}
              ${points.map(point => `<text class="lotto-dashboard-axis-label" x="${point.x}" y="${height - 10}" text-anchor="middle">${escapeHtml(point.label)}</text>`).join("")}
              <text class="lotto-dashboard-target-text" x="${width - paddingX}" y="${goalY - 8}" text-anchor="end">Mục tiêu</text>
            </svg>
            <div class="lotto-dashboard-line-tooltip" hidden></div>
          </div>
        </div>
      `;
    }

    function computeDashboardNumberMetrics(entries) {
      const latestDate = getDashboardLatestDate(entries);
      const recent30Start = shiftDashboardDate(latestDate, -29);
      const recent7Start = shiftDashboardDate(latestDate, -6);
      const recent30Entries = filterDashboardEntriesInRange(entries, recent30Start, latestDate);
      const recent7Entries = filterDashboardEntriesInRange(entries, recent7Start, latestDate);
      const longCountMap = new Map();
      const recent30CountMap = new Map();
      const recent7CountMap = new Map();
      const lastSeenMap = new Map();
      entries.forEach((entry, index) => {
        entry.mainNumbers.forEach(number => {
          longCountMap.set(number, Number(longCountMap.get(number) || 0) + 1);
          lastSeenMap.set(number, index);
        });
      });
      recent30Entries.forEach(entry => {
        entry.mainNumbers.forEach(number => {
          recent30CountMap.set(number, Number(recent30CountMap.get(number) || 0) + 1);
        });
      });
      recent7Entries.forEach(entry => {
        entry.mainNumbers.forEach(number => {
          recent7CountMap.set(number, Number(recent7CountMap.get(number) || 0) + 1);
        });
      });
      const totalLongEntries = Math.max(1, entries.length);
      const totalRecent30Entries = Math.max(1, recent30Entries.length || 1);
      const totalRecent7Entries = Math.max(1, recent7Entries.length || 1);
      const baseRows = range(1, 80).map(number => {
        const longCount = Number(longCountMap.get(number) || 0);
        const recent30Count = Number(recent30CountMap.get(number) || 0);
        const recent7Count = Number(recent7CountMap.get(number) || 0);
        const lastSeenIndex = lastSeenMap.has(number) ? Number(lastSeenMap.get(number)) : -1;
        const delay = lastSeenIndex >= 0 ? Math.max(0, entries.length - 1 - lastSeenIndex) : entries.length;
        const longRate = longCount / totalLongEntries;
        const recent30Rate = recent30Count / totalRecent30Entries;
        return {
          number,
          longCount,
          recent30Count,
          recent7Count,
          delay,
          longRate,
          recent30Rate,
        };
      });
      const maxLong = Math.max(1, ...baseRows.map(row => row.longCount));
      const maxRecent30 = Math.max(1, ...baseRows.map(row => row.recent30Count));
      const maxRecent7 = Math.max(1, ...baseRows.map(row => row.recent7Count));
      const maxDelay = Math.max(1, ...baseRows.map(row => row.delay));
      return baseRows.map(row => {
        const longNorm = row.longCount / maxLong;
        const recent30Norm = row.recent30Count / maxRecent30;
        const recent7Norm = row.recent7Count / maxRecent7;
        const delayNorm = row.delay / maxDelay;
        const stability = 1 - Math.min(1, Math.abs(row.recent30Rate - row.longRate) / Math.max(0.02, row.longRate || 0.02));
        return {
          ...row,
          score: (0.35 * longNorm) + (0.35 * recent30Norm) + (0.15 * recent7Norm) + (0.15 * (1 - delayNorm)),
          confidence: (0.45 * stability) + (0.35 * longNorm) + (0.2 * (1 - delayNorm)),
        };
      });
    }

    function computeDashboardDistributionRows(entries, mode) {
      const normalizedMode = normalizeDashboardDistributionViewMode(mode);
      const metrics = computeDashboardNumberMetrics(entries);
      if (normalizedMode === "numberType") {
        const latestDate = getDashboardLatestDate(entries);
        const recent30Entries = filterDashboardEntriesInRange(entries, shiftDashboardDate(latestDate, -29), latestDate);
        const groups = [
          { key: "low", label: "Số thấp 1-20", min: 1, max: 20, color: DASHBOARD_DISTRIBUTION_COLORS.low, count: 0 },
          { key: "midlow", label: "Số giữa 21-40", min: 21, max: 40, color: DASHBOARD_DISTRIBUTION_COLORS.midlow, count: 0 },
          { key: "midhigh", label: "Số cao 41-60", min: 41, max: 60, color: DASHBOARD_DISTRIBUTION_COLORS.midhigh, count: 0 },
          { key: "high", label: "Số rất cao 61-80", min: 61, max: 80, color: DASHBOARD_DISTRIBUTION_COLORS.high, count: 0 },
        ];
        recent30Entries.forEach(entry => {
          entry.mainNumbers.forEach(number => {
            const group = groups.find(item => number >= item.min && number <= item.max);
            if (group) group.count += 1;
          });
        });
        const total = groups.reduce((sum, item) => sum + item.count, 0) || 1;
        return groups.map(item => ({
          ...item,
          percent: (item.count / total) * 100,
          countLabel: `${formatDashboardInteger(item.count)} lượt`,
          meta: "30 ngày gần nhất",
        }));
      }
      if (normalizedMode === "confidence") {
        const groups = [
          { key: "trusted", label: "Rất tin cậy", color: DASHBOARD_DISTRIBUTION_COLORS.trusted, count: 0 },
          { key: "reliable", label: "Khá tin cậy", color: DASHBOARD_DISTRIBUTION_COLORS.reliable, count: 0 },
          { key: "watching", label: "Đang theo dõi", color: DASHBOARD_DISTRIBUTION_COLORS.watching, count: 0 },
          { key: "volatile", label: "Biến động", color: DASHBOARD_DISTRIBUTION_COLORS.volatile, count: 0 },
          { key: "risky", label: "Rủi ro cao", color: DASHBOARD_DISTRIBUTION_COLORS.risky, count: 0 },
        ];
        metrics.forEach(item => {
          let key = "risky";
          if (item.confidence >= 0.82) key = "trusted";
          else if (item.confidence >= 0.66) key = "reliable";
          else if (item.confidence >= 0.48) key = "watching";
          else if (item.confidence >= 0.3) key = "volatile";
          groups.find(group => group.key === key).count += 1;
        });
        const total = groups.reduce((sum, item) => sum + item.count, 0) || 1;
        return groups.map(item => ({
          ...item,
          percent: (item.count / total) * 100,
          countLabel: `${formatDashboardInteger(item.count)} số`,
          meta: "Recent vs long-term",
        }));
      }
      const groups = [
        { key: "strong", label: "Rất mạnh", color: DASHBOARD_DISTRIBUTION_COLORS.strong, count: 0 },
        { key: "potential", label: "Tiềm năng", color: DASHBOARD_DISTRIBUTION_COLORS.potential, count: 0 },
        { key: "neutral", label: "Trung tính", color: DASHBOARD_DISTRIBUTION_COLORS.neutral, count: 0 },
        { key: "weak", label: "Yếu", color: DASHBOARD_DISTRIBUTION_COLORS.weak, count: 0 },
        { key: "reject", label: "Loại bỏ", color: DASHBOARD_DISTRIBUTION_COLORS.reject, count: 0 },
      ];
      const sorted = [...metrics].sort((a, b) => b.score - a.score || a.number - b.number);
      const totalNumbers = Math.max(1, sorted.length);
      sorted.forEach((item, index) => {
        const ratio = index / totalNumbers;
        let key = "reject";
        if (ratio < 0.15) key = "strong";
        else if (ratio < 0.4) key = "potential";
        else if (ratio < 0.7) key = "neutral";
        else if (ratio < 0.9) key = "weak";
        groups.find(group => group.key === key).count += 1;
      });
      return groups.map(item => ({
        ...item,
        percent: (item.count / totalNumbers) * 100,
        countLabel: `${formatDashboardInteger(item.count)} số`,
        meta: "Scoring nội bộ từ dữ liệu thật",
      }));
    }

    function renderDashboardDistributionPanel(entries, mode) {
      const rows = computeDashboardDistributionRows(entries, mode);
      const total = rows.reduce((sum, row) => sum + Number(row.count || 0), 0);
      const activeRows = rows.filter(row => Number(row.count || 0) > 0);
      if (!activeRows.length || !total) {
        return `<div class="lotto-dashboard-empty-state">Chưa đủ dữ liệu để dựng donut phân bổ cho dashboard.</div>`;
      }
      const radius = 76;
      const stroke = 22;
      const circumference = 2 * Math.PI * radius;
      let accumulated = 0;
      const segments = activeRows.map(row => {
        const segmentLength = (Number(row.percent || 0) / 100) * circumference;
        const dashOffset = circumference - accumulated;
        accumulated += segmentLength;
        return `<circle class="lotto-dashboard-donut-segment" cx="100" cy="100" r="${radius}" fill="none" stroke="${escapeHtml(row.color)}" stroke-width="${stroke}" stroke-linecap="round" stroke-dasharray="${segmentLength.toFixed(3)} ${(circumference - segmentLength).toFixed(3)}" stroke-dashoffset="${dashOffset.toFixed(3)}"></circle>`;
      }).join("");
      return `
        <div class="lotto-dashboard-donut-layout">
          <div class="lotto-dashboard-donut-wrap">
            <svg class="lotto-dashboard-donut-svg" viewBox="0 0 200 200" aria-hidden="true">
              <circle class="lotto-dashboard-donut-track" cx="100" cy="100" r="${radius}" fill="none" stroke-width="${stroke}"></circle>
              <g class="lotto-dashboard-donut-ring">${segments}</g>
            </svg>
            <div class="lotto-dashboard-donut-center">
              <div class="lotto-dashboard-donut-center-value">100%</div>
              <div class="lotto-dashboard-donut-center-label">Tỷ trọng</div>
              <div class="lotto-dashboard-donut-center-meta">${escapeHtml(`${formatDashboardInteger(activeRows.length)} nhóm`)}</div>
            </div>
          </div>
          <div class="lotto-dashboard-donut-legend">
            ${rows.map(row => `
              <div class="lotto-dashboard-donut-legend-item">
                <span class="lotto-dashboard-donut-legend-swatch" style="--dashboard-color:${escapeHtml(row.color)}"></span>
                <div class="lotto-dashboard-donut-legend-copy">
                  <div class="lotto-dashboard-donut-legend-label">${escapeHtml(row.label)}</div>
                  <div class="lotto-dashboard-donut-legend-meta">${escapeHtml(row.meta || "")}</div>
                </div>
                <div class="lotto-dashboard-donut-legend-values">
                  <div class="lotto-dashboard-donut-legend-percent">${escapeHtml(formatChartStatsPercent(row.percent))}</div>
                  <div class="lotto-dashboard-donut-legend-count">${escapeHtml(row.countLabel || `${formatDashboardInteger(row.count)}`)}</div>
                </div>
              </div>
            `).join("")}
          </div>
        </div>
      `;
    }

    function renderDashboardActivityTabs() {
      document.querySelectorAll("[data-dashboard-activity-view]").forEach(button => {
        const viewMode = normalizeDashboardActivityViewMode(button.dataset.dashboardActivityView);
        const isActive = viewMode === dashboardActivityViewMode;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-pressed", isActive ? "true" : "false");
      });
    }

    function renderDashboardDistributionTabs() {
      document.querySelectorAll("[data-dashboard-distribution-view]").forEach(button => {
        const viewMode = normalizeDashboardDistributionViewMode(button.dataset.dashboardDistributionView);
        const isActive = viewMode === dashboardDistributionViewMode;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-pressed", isActive ? "true" : "false");
      });
    }

    function bindDashboardLineTooltip() {
      const wrap = document.querySelector("#lottoDashboardActivityOut .lotto-dashboard-line-chart-wrap");
      const tooltip = wrap?.querySelector(".lotto-dashboard-line-tooltip");
      if (!wrap || !tooltip) return;
      const hide = () => {
        tooltip.hidden = true;
      };
      wrap.querySelectorAll(".lotto-dashboard-line-point").forEach(point => {
        const show = event => {
          const bounds = wrap.getBoundingClientRect();
          const offsetX = Math.max(14, Math.min(bounds.width - 14, event.clientX - bounds.left));
          const offsetY = Math.max(16, event.clientY - bounds.top - 18);
          tooltip.innerHTML = `
            <div class="lotto-dashboard-line-tooltip-label">${escapeHtml(point.dataset.dashboardLabel || "")}</div>
            <div class="lotto-dashboard-line-tooltip-value">${escapeHtml(point.dataset.dashboardValue || "0")}</div>
            <div class="lotto-dashboard-line-tooltip-meta">${escapeHtml(point.dataset.dashboardMeta || "")}</div>
          `;
          tooltip.style.left = `${offsetX}px`;
          tooltip.style.top = `${offsetY}px`;
          tooltip.hidden = false;
        };
        point.addEventListener("mouseenter", show);
        point.addEventListener("mousemove", show);
        point.addEventListener("mouseleave", hide);
      });
      wrap.addEventListener("mouseleave", hide);
    }

    function renderDashboardPanel() {
      const kpisHost = document.getElementById("lottoDashboardKpis");
      const activityStatsHost = document.getElementById("lottoDashboardActivityStats");
      const activityOut = document.getElementById("lottoDashboardActivityOut");
      const distributionOut = document.getElementById("lottoDashboardDistributionOut");
      const updatedAtHost = document.getElementById("lottoDashboardUpdatedAt");
      const statusHost = document.getElementById("lottoDashboardStatus");
      if (!kpisHost || !activityStatsHost || !activityOut || !distributionOut || !updatedAtHost || !statusHost) return;

      renderDashboardActivityTabs();
      renderDashboardDistributionTabs();

      const entries = buildDashboardEntries();
      const loadedTimes = DASHBOARD_LOTTO_TYPES
        .map(type => new Date(String(getLiveHistoryFeed(type)?.loadedAt || "").trim()))
        .filter(dateValue => dateValue instanceof Date && !Number.isNaN(dateValue.getTime()));
      updatedAtHost.textContent = `Cập nhật: ${loadedTimes.length ? formatDashboardRelativeTime(loadedTimes.sort((a, b) => b.getTime() - a.getTime())[0]) : "đang chờ dữ liệu"}`;

      if (dashboardPanelError) {
        statusHost.hidden = false;
        statusHost.className = "lotto-dashboard-status is-warning";
        statusHost.textContent = dashboardPanelError;
      } else {
        statusHost.hidden = true;
        statusHost.className = "lotto-dashboard-status";
        statusHost.textContent = "";
      }

      if (dashboardPanelLoading && !entries.length) {
        kpisHost.innerHTML = `
          <div class="lotto-dashboard-empty-card">Đang gom dữ liệu all_day.csv để dựng KPI 7 ngày và 30 ngày...</div>
          <div class="lotto-dashboard-empty-card">Dashboard đang tải biểu đồ hoạt động và phân bổ số lotto.</div>
        `;
        activityStatsHost.innerHTML = "";
        activityOut.className = "lotto-dashboard-panel-body lotto-dashboard-panel-body-muted";
        activityOut.innerHTML = "Đang tải biểu đồ đường từ dữ liệu thật...";
        distributionOut.className = "lotto-dashboard-panel-body lotto-dashboard-panel-body-muted";
        distributionOut.innerHTML = "Đang tải donut phân bổ số lotto...";
        return;
      }

      if (!entries.length) {
        kpisHost.innerHTML = `<div class="lotto-dashboard-empty-card">Chưa có dữ liệu Keno, 5/35, 6/45 hoặc 6/55 để dựng dashboard lotto.</div>`;
        activityStatsHost.innerHTML = "";
        activityOut.className = "lotto-dashboard-panel-body lotto-dashboard-panel-body-muted";
        activityOut.innerHTML = "Hệ thống cần ít nhất một nguồn all_day.csv đã nạp để vẽ biểu đồ hoạt động.";
        distributionOut.className = "lotto-dashboard-panel-body lotto-dashboard-panel-body-muted";
        distributionOut.innerHTML = "Khi có dữ liệu thật, donut phân bổ sẽ hiển thị ngay tại đây.";
        return;
      }

      const latestDate = getDashboardLatestDate(entries);
      const recent7 = computeDashboardWindowMetrics(entries, 7, latestDate);
      const recent30 = computeDashboardWindowMetrics(entries, 30, latestDate);
      kpisHost.innerHTML = `
        ${renderDashboardKpiCard("7 Ngày Qua", recent7)}
        ${renderDashboardKpiCard("30 Ngày Qua", recent30)}
      `;

      const activityBuckets = getDashboardActivityBuckets(entries, dashboardActivityViewMode);
      activityStatsHost.innerHTML = renderDashboardActivityStats(activityBuckets);
      activityOut.className = "lotto-dashboard-panel-body";
      activityOut.innerHTML = renderDashboardActivityChart(activityBuckets, dashboardActivityViewMode);

      distributionOut.className = "lotto-dashboard-panel-body";
      distributionOut.innerHTML = renderDashboardDistributionPanel(entries, dashboardDistributionViewMode);
      window.setTimeout(bindDashboardLineTooltip, 0);
    }

    async function startDashboardRefresh({ force = false, silent = true } = {}) {
      const refreshToken = ++dashboardPanelRefreshToken;
      dashboardPanelLoading = true;
      dashboardPanelError = "";
      renderDashboardPanel();
      const results = await Promise.allSettled(
        DASHBOARD_LOTTO_TYPES.map(type => fetchLiveHistory(type, "all", { force, silent }))
      );
      if (refreshToken !== dashboardPanelRefreshToken) return;
      dashboardPanelLoading = false;
      const failed = results
        .map((result, index) => ({ result, type: DASHBOARD_LOTTO_TYPES[index] }))
        .filter(item => item.result.status === "rejected")
        .map(item => `${getDashboardTypeMeta(item.type).label}: ${String(item.result.reason?.message || item.result.reason || "Lỗi không rõ")}`);
      dashboardPanelError = failed.length
        ? `Một vài nguồn dashboard chưa tải được: ${failed.join(" • ")}`
        : "";
      renderDashboardPanel();
    }

    function getDashboardTypeMeta(type) {
      const mapping = {
        KENO: { label: "Keno", accent: "#29d2d4", icon: "◎", family: "keno", heroNote: "20 số mỗi kỳ, ưu tiên nhìn dải nóng và nhịp lặp lại gần đây." },
        LOTO_5_35: { label: "Lotto 5/35", accent: "#6d5cff", icon: "◈", family: "ball", heroNote: "Theo dõi riêng 5 số chính và ĐB để nhìn rõ nhịp của game 5/35." },
        LOTO_6_45: { label: "Mega 6/45", accent: "#4f8cff", icon: "◉", family: "ball", heroNote: "Nhìn nhịp 6 bóng chính, nhiệt bóng và chẵn lẻ của Mega 6/45." },
        LOTO_6_55: { label: "Power 6/55", accent: "#ffb44d", icon: "✦", family: "ball", heroNote: "Tập trung vào 6 bóng chính cùng số ĐB để đọc đúng nhịp của Power 6/55." },
        MAX_3D: { label: "Lotto 3D", accent: "#ff7760", icon: "▣", family: "threeDigit", heroNote: "Phân tích riêng đầu, đuôi và nhịp bộ 3 số của 3D." },
        MAX_3D_PRO: { label: "Lotto 3D Pro", accent: "#27c18c", icon: "⬢", family: "threeDigit", heroNote: "Theo dõi bộ 3 số, đầu đuôi và cường độ xuất hiện của 3D Pro." },
      };
      return mapping[normalizeDashboardGame(type)] || mapping.KENO;
    }

    function getDashboardLatestEntry(entries) {
      return Array.isArray(entries) && entries.length ? entries[entries.length - 1] : null;
    }

    function getDashboardLatestDate(entries) {
      const latest = getDashboardLatestEntry(entries)?.dayStart;
      return latest instanceof Date && !Number.isNaN(latest.getTime()) ? latest : floorDashboardDate(new Date());
    }

    function getDashboardFamily(type) {
      return getDashboardTypeMeta(type).family || "ball";
    }

    function getDashboardRangeGroups(type) {
      return CHART_STATS_GROUPS[normalizeDashboardGame(type)] || [];
    }

    function computeDashboardDigitSum(value) {
      return String(Math.max(0, Number(value || 0))).padStart(3, "0").split("").reduce((sum, digit) => sum + Number(digit || 0), 0);
    }

    function computeDashboardEntryActivityValue(type, numbers, draw) {
      const safeNumbers = (Array.isArray(numbers) ? numbers : []).map(Number).filter(Number.isInteger);
      if (getDashboardFamily(type) === "threeDigit") {
        return safeNumbers.reduce((sum, value) => sum + computeDashboardDigitSum(value), 0);
      }
      const specialValue = TYPES[type]?.hasSpecial && Number.isInteger(Number(draw?.special)) ? Number(draw.special) : 0;
      return safeNumbers.reduce((sum, value) => sum + value, 0) + specialValue;
    }

    function buildDashboardEntries() {
      const type = normalizeDashboardGame(dashboardSelectedGame);
      return buildStatsEntriesForFeed(type, getLiveHistoryFeed(type))
        .map(entry => {
          const parsedDate = parseLiveDate(entry.draw?.date || "");
          if (!(parsedDate instanceof Date) || Number.isNaN(parsedDate.getTime())) return null;
          const mainNumbers = TYPES[type]?.threeDigit
            ? [...new Set(extractThreeDigitTokensFromLines(entry.draw?.displayLines))]
            : (Array.isArray(entry.draw?.main) ? entry.draw.main : []).map(Number).filter(Number.isInteger);
          return {
            type,
            ky: entry.ky,
            draw: entry.draw,
            date: parsedDate,
            dayStart: floorDashboardDate(parsedDate),
            mainNumbers,
            hitCount: mainNumbers.length,
            activityValue: computeDashboardEntryActivityValue(type, mainNumbers, entry.draw),
          };
        })
        .filter(Boolean)
        .sort((a, b) => {
          const dateDelta = a.date.getTime() - b.date.getTime();
          if (dateDelta !== 0) return dateDelta;
          return kySortValue(a.ky) - kySortValue(b.ky);
        });
    }

    function getDashboardBucketKey(dateValue, mode) {
      if (mode === "month") {
        return `${dateValue.getFullYear()}-${String(dateValue.getMonth() + 1).padStart(2, "0")}`;
      }
      if (mode === "week") {
        return `week-${formatDashboardDateKey(getDashboardWeekStart(dateValue))}`;
      }
      return formatDashboardDateKey(floorDashboardDate(dateValue));
    }

    function getDashboardActivityBuckets(entries, mode) {
      const normalizedMode = normalizeDashboardActivityViewMode(mode);
      const latestDate = getDashboardLatestDate(entries);
      const limit = DASHBOARD_ACTIVITY_BUCKET_LIMITS[normalizedMode] || 12;
      const buckets = [];
      if (normalizedMode === "month") {
        const latestMonth = new Date(latestDate.getFullYear(), latestDate.getMonth(), 1);
        for (let index = limit - 1; index >= 0; index -= 1) {
          const start = addDashboardMonths(latestMonth, -index);
          const end = new Date(start.getFullYear(), start.getMonth() + 1, 0, 23, 59, 59, 999);
          buckets.push({ key: getDashboardBucketKey(start, normalizedMode), label: formatDashboardMonthLabel(start), tooltipLabel: `Tháng ${formatDashboardMonthLabel(start)}`, start, end, value: 0, drawCount: 0 });
        }
      } else if (normalizedMode === "week") {
        const latestWeek = getDashboardWeekStart(latestDate);
        for (let index = limit - 1; index >= 0; index -= 1) {
          const start = shiftDashboardDate(latestWeek, -7 * index);
          const end = new Date(start.getTime());
          end.setDate(end.getDate() + 6);
          end.setHours(23, 59, 59, 999);
          buckets.push({ key: getDashboardBucketKey(start, normalizedMode), label: formatDashboardShortDate(start), tooltipLabel: `${formatDashboardShortDate(start)} - ${formatDashboardShortDate(end)}`, start, end, value: 0, drawCount: 0 });
        }
      } else {
        const latestDay = floorDashboardDate(latestDate);
        for (let index = limit - 1; index >= 0; index -= 1) {
          const start = shiftDashboardDate(latestDay, -index);
          const end = new Date(start.getTime());
          end.setHours(23, 59, 59, 999);
          buckets.push({ key: getDashboardBucketKey(start, normalizedMode), label: formatDashboardShortDate(start), tooltipLabel: formatLiveDateFromDate(start), start, end, value: 0, drawCount: 0 });
        }
      }
      const bucketMap = new Map(buckets.map(item => [item.key, item]));
      (Array.isArray(entries) ? entries : []).forEach(entry => {
        const bucketKey = getDashboardBucketKey(entry.date, normalizedMode);
        const bucket = bucketMap.get(bucketKey);
        if (!bucket) return;
        bucket.value += Number(entry.activityValue || 0);
        bucket.drawCount += 1;
      });
      return buckets;
    }

    function buildDashboardHeroStatus(type, entries) {
      const latestDate = getDashboardLatestDate(entries);
      const recentWindow = filterDashboardEntriesInRange(entries, shiftDashboardDate(latestDate, -6), latestDate);
      const previousWindow = filterDashboardEntriesInRange(entries, shiftDashboardDate(latestDate, -13), shiftDashboardDate(latestDate, -7));
      const recentValue = recentWindow.reduce((sum, entry) => sum + Number(entry.activityValue || 0), 0);
      const previousValue = previousWindow.reduce((sum, entry) => sum + Number(entry.activityValue || 0), 0);
      const diffRatio = previousValue > 0 ? (recentValue - previousValue) / previousValue : 0;
      if (diffRatio >= 0.08) return { label: "Tăng", tone: "up" };
      if (diffRatio <= -0.08) return { label: "Giảm nhẹ", tone: "down" };
      return { label: "Ổn định", tone: "stable" };
    }

    function renderDashboardHeroNumbers(type, latestEntry) {
      if (!latestEntry?.draw) return `<div class="lotto-dashboard-empty-state">Chưa có kỳ quay mới nhất để hiển thị.</div>`;
      if (getDashboardFamily(type) === "threeDigit") {
        const lines = Array.isArray(latestEntry.draw?.displayLines) && latestEntry.draw.displayLines.length
          ? latestEntry.draw.displayLines
          : latestEntry.mainNumbers.map(number => formatPredictNumber(number, type));
        return `
          <div class="lotto-dashboard-hero-lines">
            ${lines.map(lineText => `<div class="lotto-dashboard-hero-line">${escapeHtml(String(lineText || "").trim())}</div>`).join("")}
          </div>
        `;
      }
      const mainNumbers = (Array.isArray(latestEntry.draw?.main) ? latestEntry.draw.main : latestEntry.mainNumbers)
        .map(number => `<span class="lotto-dashboard-result-ball">${escapeHtml(formatPredictNumber(number, type))}</span>`)
        .join("");
      const specialHtml = TYPES[type]?.hasSpecial && Number.isInteger(Number(latestEntry.draw?.special))
        ? `<span class="lotto-dashboard-result-ball is-special">ĐB ${escapeHtml(formatPredictNumber(Number(latestEntry.draw.special), type))}</span>`
        : "";
      return `
        <div class="lotto-dashboard-result-stack ${type === "KENO" ? "is-keno" : ""}">
          <div class="lotto-dashboard-result-row">${mainNumbers}</div>
          ${specialHtml ? `<div class="lotto-dashboard-result-row is-special-row">${specialHtml}</div>` : ""}
        </div>
      `;
    }

    function renderDashboardHeroCard(type, entries) {
      const meta = getDashboardTypeMeta(type);
      const latestEntry = getDashboardLatestEntry(entries);
      if (!latestEntry) {
        return `<div class="lotto-dashboard-empty-card">Chưa có dữ liệu ${escapeHtml(meta.label)} để dựng overview riêng cho game này.</div>`;
      }
      const badge = buildDashboardHeroStatus(type, entries);
      const formattedDate = latestEntry.date instanceof Date ? formatLiveDateFromDate(latestEntry.date) : "Chưa rõ ngày";
      const hotMain = buildStatsFrequencyItems(type, entries)[0] || null;
      const hotSpecial = TYPES[type]?.hasSpecial ? buildStatsFrequencyItems(type, entries, { special: true })[0] : null;
      const insightLine = hotSpecial
        ? `Nhiệt bóng: ${hotMain ? hotMain.label : "--"} • ĐB nóng: ${hotSpecial ? hotSpecial.label : "--"}`
        : `Nhiệt bóng: ${hotMain ? hotMain.label : "--"} • ${meta.heroNote}`;
      return `
        <article class="lotto-dashboard-hero-shell" style="--dashboard-accent:${escapeHtml(meta.accent)}">
          <div class="lotto-dashboard-hero-copy">
            <div class="lotto-dashboard-hero-kicker">${escapeHtml(meta.label)}</div>
            <h3 class="lotto-dashboard-hero-title">Kỳ quay mới nhất #${escapeHtml(latestEntry.ky || "--")}</h3>
            <div class="lotto-dashboard-hero-meta">${escapeHtml(formattedDate)} • ${escapeHtml(`${formatDashboardInteger(latestEntry.hitCount)} kết quả ghi nhận`)}</div>
            <div class="lotto-dashboard-hero-note">${escapeHtml(insightLine)}</div>
          </div>
          <div class="lotto-dashboard-hero-result">
            <div class="lotto-dashboard-hero-result-panel">
              <div class="lotto-dashboard-hero-result-head">
                <div class="lotto-dashboard-hero-result-label">Bộ số kỳ này</div>
                <span class="lotto-dashboard-badge is-${escapeHtml(badge.tone)}">${escapeHtml(badge.label)}</span>
              </div>
              <div class="lotto-dashboard-hero-result-body">
                ${renderDashboardHeroNumbers(type, latestEntry)}
              </div>
            </div>
          </div>
        </article>
      `;
    }

    function computeDashboardQuickStats(type, entries) {
      const family = getDashboardFamily(type);
      const recentEntries = entries.slice(-Math.min(entries.length, 36));
      if (!recentEntries.length) return [];
      if (family === "threeDigit") {
        const tokenCount = recentEntries.reduce((sum, entry) => sum + entry.mainNumbers.length, 0);
        const tokenValues = recentEntries.flatMap(entry => entry.mainNumbers);
        const tokenFreq = buildStatsFrequencyItems(type, recentEntries);
        const headCounts = Array.from({ length: 10 }, (_, digit) => ({ digit, count: 0 }));
        const tailCounts = Array.from({ length: 10 }, (_, digit) => ({ digit, count: 0 }));
        tokenValues.forEach(value => {
          const head = Math.floor(Number(value) / 100);
          const tail = Number(value) % 10;
          if (headCounts[head]) headCounts[head].count += 1;
          if (tailCounts[tail]) tailCounts[tail].count += 1;
        });
        const hotHead = [...headCounts].sort((a, b) => b.count - a.count || a.digit - b.digit)[0];
        const hotTail = [...tailCounts].sort((a, b) => b.count - a.count || a.digit - b.digit)[0];
        const averageDigitSum = tokenCount ? tokenValues.reduce((sum, value) => sum + computeDashboardDigitSum(value), 0) / tokenCount : 0;
        const averageSpan = recentEntries.length
          ? recentEntries.reduce((sum, entry) => {
              const ordered = [...entry.mainNumbers].sort((a, b) => a - b);
              return sum + (ordered.length > 1 ? (ordered[ordered.length - 1] - ordered[0]) : 0);
            }, 0) / recentEntries.length
          : 0;
        return [
          { label: "Tổng kỳ", value: formatDashboardInteger(recentEntries.length), meta: "kỳ gần nhất đang xét", accent: "neutral" },
          { label: "Tổng bộ", value: formatDashboardInteger(tokenCount), meta: "bộ 3 số ghi nhận", accent: "accent" },
          { label: "Bộ nóng", value: tokenFreq[0]?.label || "--", meta: tokenFreq[0] ? `${formatDashboardInteger(tokenFreq[0].count)} lần` : "chưa có dữ liệu", accent: "accent" },
          { label: "Đầu nóng", value: hotHead ? `${hotHead.digit}` : "--", meta: hotHead ? `${formatDashboardInteger(hotHead.count)} lượt` : "chưa có dữ liệu", accent: "secondary" },
          { label: "Đuôi nóng", value: hotTail ? `${hotTail.digit}` : "--", meta: hotTail ? `${formatDashboardInteger(hotTail.count)} lượt` : "chưa có dữ liệu", accent: "secondary" },
          { label: "Tổng điểm TB", value: formatDashboardNumber(averageDigitSum, 1), meta: `biên độ TB ${formatDashboardNumber(averageSpan, 1)}`, accent: "neutral" },
        ];
      }
      const totalNumbers = recentEntries.reduce((sum, entry) => sum + entry.mainNumbers.length, 0);
      const midpoint = (TYPES[type].mainMin + TYPES[type].mainMax) / 2;
      let oddCount = 0;
      let evenCount = 0;
      let highCount = 0;
      let lowCount = 0;
      recentEntries.forEach(entry => {
        entry.mainNumbers.forEach(number => {
          if (number % 2 === 0) evenCount += 1;
          else oddCount += 1;
          if (number > midpoint) highCount += 1;
          else lowCount += 1;
        });
      });
      const mainRanking = buildStatsFrequencyItems(type, recentEntries);
      const averageSpan = recentEntries.length
        ? recentEntries.reduce((sum, entry) => {
            const ordered = [...entry.mainNumbers].sort((a, b) => a - b);
            return sum + (ordered.length > 1 ? (ordered[ordered.length - 1] - ordered[0]) : 0);
          }, 0) / recentEntries.length
        : 0;
      const averageShift = recentEntries.length > 1
        ? recentEntries.slice(1).reduce((sum, entry, index) => {
            const previous = recentEntries[index];
            return sum + Math.abs(Number(entry.activityValue || 0) - Number(previous.activityValue || 0));
          }, 0) / Math.max(1, recentEntries.length - 1)
        : 0;
      const specialRanking = TYPES[type]?.hasSpecial ? buildStatsFrequencyItems(type, recentEntries, { special: true }) : [];
      if (type === "KENO") {
        const groups = getDashboardRangeGroups(type).map(group => ({ ...group, count: 0 }));
        recentEntries.forEach(entry => {
          entry.mainNumbers.forEach(number => {
            const match = groups.find(group => number >= group.min && number <= group.max);
            if (match) match.count += 1;
          });
        });
        const hotGroup = [...groups].sort((a, b) => b.count - a.count || a.min - b.min)[0];
        const averageRepeat = recentEntries.length > 1
          ? recentEntries.slice(1).reduce((sum, entry, index) => {
              const previousSet = new Set(recentEntries[index].mainNumbers);
              const overlap = entry.mainNumbers.filter(number => previousSet.has(number)).length;
              return sum + overlap;
            }, 0) / Math.max(1, recentEntries.length - 1)
          : 0;
        return [
          { label: "Tổng kỳ", value: formatDashboardInteger(recentEntries.length), meta: "kỳ gần nhất đang xét", accent: "neutral" },
          { label: "Tổng lượt số", value: formatDashboardInteger(totalNumbers), meta: "20 số mỗi kỳ", accent: "accent" },
          { label: "Chẵn / Lẻ", value: `${formatDashboardInteger(evenCount)} / ${formatDashboardInteger(oddCount)}`, meta: "cân bằng nhịp bóng", accent: "neutral" },
          { label: "Tài / Xỉu", value: `${formatDashboardInteger(highCount)} / ${formatDashboardInteger(lowCount)}`, meta: "trên / dưới mốc 40.5", accent: "secondary" },
          { label: "Dải nóng", value: hotGroup?.label || "--", meta: hotGroup ? `${formatDashboardInteger(hotGroup.count)} lượt` : "chưa có dữ liệu", accent: "accent" },
          { label: "Lặp lại TB", value: formatDashboardNumber(averageRepeat, 1), meta: `tịnh tiến ${formatDashboardNumber(averageShift, 1)}`, accent: "secondary" },
        ];
      }
      return [
        { label: "Tổng kỳ", value: formatDashboardInteger(recentEntries.length), meta: "kỳ gần nhất đang xét", accent: "neutral" },
        { label: "TB bóng / kỳ", value: formatDashboardNumber(totalNumbers / Math.max(1, recentEntries.length), 1), meta: `${formatDashboardInteger(totalNumbers)} lượt số`, accent: "accent" },
        { label: "Chẵn / Lẻ", value: `${formatDashboardInteger(evenCount)} / ${formatDashboardInteger(oddCount)}`, meta: "theo toàn bộ bóng trong mẫu", accent: "neutral" },
        { label: "Tài / Xỉu", value: `${formatDashboardInteger(highCount)} / ${formatDashboardInteger(lowCount)}`, meta: `mốc ${formatDashboardNumber(midpoint, 1)}`, accent: "secondary" },
        { label: TYPES[type]?.hasSpecial ? "ĐB nóng" : "Nhiệt bóng", value: (specialRanking[0]?.label || mainRanking[0]?.label || "--"), meta: specialRanking[0] ? `${formatDashboardInteger(specialRanking[0].count)} lần` : (mainRanking[0] ? `${formatDashboardInteger(mainRanking[0].count)} lần` : "chưa có dữ liệu"), accent: "accent" },
        { label: "Khoảng cách TB", value: formatDashboardNumber(averageSpan, 1), meta: `tịnh tiến ${formatDashboardNumber(averageShift, 1)}`, accent: "secondary" },
      ];
    }

    function renderDashboardQuickStats(type, entries) {
      const cards = computeDashboardQuickStats(type, entries);
      if (!cards.length) {
        return `<div class="lotto-dashboard-empty-card">Chưa đủ dữ liệu để dựng quick stats riêng cho ${escapeHtml(getDashboardTypeMeta(type).label)}.</div>`;
      }
      return cards.map(card => `
        <article class="lotto-dashboard-quick-stat is-${escapeHtml(card.accent || "neutral")}">
          <div class="lotto-dashboard-quick-stat-label">${escapeHtml(card.label)}</div>
          <div class="lotto-dashboard-quick-stat-value">${escapeHtml(card.value)}</div>
          <div class="lotto-dashboard-quick-stat-meta">${escapeHtml(card.meta || "")}</div>
        </article>
      `).join("");
    }

    function renderDashboardGameSelect() {
      const host = document.getElementById("lottoDashboardGameSelect");
      if (!host) return;
      host.innerHTML = DASHBOARD_LOTTO_TYPES.map(type => {
        const meta = getDashboardTypeMeta(type);
        return `<option value="${escapeHtml(type)}">${escapeHtml(meta.label)}</option>`;
      }).join("");
      host.value = normalizeDashboardGame(dashboardSelectedGame);
      if (typeof host.__syncCustomSelect === "function") host.__syncCustomSelect();
    }

    function getDashboardDistributionSubtitle(type, mode) {
      const meta = getDashboardTypeMeta(type);
      const normalizedMode = normalizeDashboardDistributionViewMode(mode);
      if (normalizedMode === "range") return `Phân bổ ${meta.label} theo từng dải số đặc trưng của game đang chọn.`;
      if (normalizedMode === "parity") return `Nhìn nhanh chẵn / lẻ để biết nhịp phân bổ của ${meta.label}.`;
      if (normalizedMode === "head") return `Tập trung vào đầu số của các bộ 3 số trong ${meta.label}.`;
      if (normalizedMode === "tail") return `Tập trung vào đuôi số để soi nhịp ra của ${meta.label}.`;
      return `Phân loại theo mức nóng / lạnh từ dữ liệu thật của ${meta.label}.`;
    }

    function buildDashboardTemperatureRows(type, entries) {
      const items = buildStatsFrequencyItems(type, entries);
      const sorted = [...items].sort((a, b) => b.count - a.count || a.value - b.value);
      const total = Math.max(1, sorted.length);
      const groups = [
        { key: "very-hot", label: "Rất nóng", color: "#ff7a63", count: 0 },
        { key: "hot", label: "Nóng", color: "#ffb44d", count: 0 },
        { key: "warm", label: "Trung tính", color: "#7aa8ff", count: 0 },
        { key: "cold", label: "Lạnh", color: "#63d5ff", count: 0 },
        { key: "sleep", label: "Vắng", color: "#d7e2ff", count: 0 },
      ];
      sorted.forEach((item, index) => {
        const ratio = index / total;
        let bucketIndex = 4;
        if (ratio < 0.12) bucketIndex = 0;
        else if (ratio < 0.3) bucketIndex = 1;
        else if (ratio < 0.6) bucketIndex = 2;
        else if (ratio < 0.85) bucketIndex = 3;
        groups[bucketIndex].count += 1;
      });
      return groups.map(group => ({
        ...group,
        percent: (group.count / total) * 100,
        countLabel: `${formatDashboardInteger(group.count)} ${getDashboardFamily(type) === "threeDigit" ? "bộ" : "số"}`,
        meta: "xếp theo tần suất gần nhất",
      }));
    }

    function computeDashboardDistributionRows(type, entries, mode) {
      const normalizedType = normalizeDashboardGame(type);
      const normalizedMode = normalizeDashboardDistributionViewMode(mode);
      if (normalizedMode === "range") {
        const groups = getDashboardRangeGroups(normalizedType).map(group => ({ ...group, count: 0 }));
        entries.forEach(entry => {
          entry.mainNumbers.forEach(number => {
            const match = groups.find(group => number >= group.min && number <= group.max);
            if (match) match.count += 1;
          });
        });
        const total = groups.reduce((sum, item) => sum + item.count, 0) || 1;
        return groups.map(item => ({
          key: item.key,
          label: item.label,
          color: item.color,
          count: item.count,
          percent: (item.count / total) * 100,
          countLabel: `${formatDashboardInteger(item.count)} lượt`,
          meta: getDashboardTypeMeta(normalizedType).label,
        }));
      }
      if (normalizedMode === "parity") {
        const groups = [
          { key: "even", label: "Chẵn", color: "#5a7cff", count: 0 },
          { key: "odd", label: "Lẻ", color: "#57d4a6", count: 0 },
        ];
        entries.forEach(entry => {
          entry.mainNumbers.forEach(number => {
            groups[number % 2 === 0 ? 0 : 1].count += 1;
          });
        });
        const total = groups.reduce((sum, item) => sum + item.count, 0) || 1;
        return groups.map(item => ({
          ...item,
          percent: (item.count / total) * 100,
          countLabel: `${formatDashboardInteger(item.count)} lượt`,
          meta: "theo toàn bộ bóng trong mẫu",
        }));
      }
      if (normalizedMode === "head" || normalizedMode === "tail") {
        const groups = Array.from({ length: 10 }, (_, digit) => ({
          key: String(digit),
          label: normalizedMode === "head" ? `Đầu ${digit}` : `Đuôi ${digit}`,
          color: `hsl(${200 + (digit * 14)}, 78%, 62%)`,
          count: 0,
        }));
        entries.forEach(entry => {
          entry.mainNumbers.forEach(number => {
            const digit = normalizedMode === "head" ? Math.floor(Number(number) / 100) : (Number(number) % 10);
            if (groups[digit]) groups[digit].count += 1;
          });
        });
        const total = groups.reduce((sum, item) => sum + item.count, 0) || 1;
        return groups.map(item => ({
          ...item,
          percent: (item.count / total) * 100,
          countLabel: `${formatDashboardInteger(item.count)} lượt`,
          meta: normalizedMode === "head" ? "theo đầu số" : "theo đuôi số",
        }));
      }
      return buildDashboardTemperatureRows(normalizedType, entries);
    }

    function renderDashboardDistributionPanel(type, entries, mode) {
      const rows = computeDashboardDistributionRows(type, entries, mode);
      const total = rows.reduce((sum, row) => sum + Number(row.count || 0), 0);
      const activeRows = rows.filter(row => Number(row.count || 0) > 0);
      if (!activeRows.length || !total) {
        return `<div class="lotto-dashboard-empty-state">Chưa đủ dữ liệu để dựng phân bổ riêng cho ${escapeHtml(getDashboardTypeMeta(type).label)}.</div>`;
      }
      const radius = 76;
      const stroke = 22;
      const circumference = 2 * Math.PI * radius;
      let accumulated = 0;
      const segments = activeRows.map(row => {
        const segmentLength = (Number(row.percent || 0) / 100) * circumference;
        const dashOffset = circumference - accumulated;
        accumulated += segmentLength;
        return `<circle class="lotto-dashboard-donut-segment" cx="100" cy="100" r="${radius}" fill="none" stroke="${escapeHtml(row.color)}" stroke-width="${stroke}" stroke-linecap="round" stroke-dasharray="${segmentLength.toFixed(3)} ${(circumference - segmentLength).toFixed(3)}" stroke-dashoffset="${dashOffset.toFixed(3)}"></circle>`;
      }).join("");
      const centerLabel = getDashboardDistributionOptions(type).find(option => option.value === normalizeDashboardDistributionViewMode(mode))?.label || "Tỷ trọng";
      return `
        <div class="lotto-dashboard-donut-layout">
          <div class="lotto-dashboard-donut-wrap">
            <svg class="lotto-dashboard-donut-svg" viewBox="0 0 200 200" aria-hidden="true">
              <circle class="lotto-dashboard-donut-track" cx="100" cy="100" r="${radius}" fill="none" stroke-width="${stroke}"></circle>
              <g class="lotto-dashboard-donut-ring">${segments}</g>
            </svg>
            <div class="lotto-dashboard-donut-center">
              <div class="lotto-dashboard-donut-center-value">100%</div>
              <div class="lotto-dashboard-donut-center-label">${escapeHtml(centerLabel)}</div>
              <div class="lotto-dashboard-donut-center-meta">${escapeHtml(`${formatDashboardInteger(activeRows.length)} nhóm`)}</div>
            </div>
          </div>
          <div class="lotto-dashboard-donut-legend">
            ${rows.map(row => `
              <div class="lotto-dashboard-donut-legend-item">
                <span class="lotto-dashboard-donut-legend-swatch" style="--dashboard-color:${escapeHtml(row.color)}"></span>
                <div class="lotto-dashboard-donut-legend-copy">
                  <div class="lotto-dashboard-donut-legend-label">${escapeHtml(row.label)}</div>
                  <div class="lotto-dashboard-donut-legend-meta">${escapeHtml(row.meta || "")}</div>
                </div>
                <div class="lotto-dashboard-donut-legend-values">
                  <div class="lotto-dashboard-donut-legend-percent">${escapeHtml(formatChartStatsPercent(row.percent))}</div>
                  <div class="lotto-dashboard-donut-legend-count">${escapeHtml(row.countLabel || `${formatDashboardInteger(row.count)}`)}</div>
                </div>
              </div>
            `).join("")}
          </div>
        </div>
      `;
    }

    function renderDashboardActivityStats(buckets, type) {
      const totalDraws = buckets.reduce((sum, bucket) => sum + Number(bucket.drawCount || 0), 0);
      const totalValue = buckets.reduce((sum, bucket) => sum + Number(bucket.value || 0), 0);
      const averagePerDraw = totalDraws > 0 ? totalValue / totalDraws : 0;
      const totalLabel = getDashboardFamily(type) === "threeDigit" ? "Tổng điểm bộ" : "Tổng điểm";
      return `
        <div class="lotto-dashboard-mini-stat">
          <div class="lotto-dashboard-mini-stat-label">Tổng số kỳ</div>
          <div class="lotto-dashboard-mini-stat-value">${escapeHtml(formatDashboardInteger(totalDraws))}</div>
        </div>
        <div class="lotto-dashboard-mini-stat">
          <div class="lotto-dashboard-mini-stat-label">${escapeHtml(totalLabel)}</div>
          <div class="lotto-dashboard-mini-stat-value">${escapeHtml(formatDashboardInteger(Math.round(totalValue)))}</div>
        </div>
        <div class="lotto-dashboard-mini-stat">
          <div class="lotto-dashboard-mini-stat-label">Trung bình mỗi kỳ</div>
          <div class="lotto-dashboard-mini-stat-value">${escapeHtml(formatDashboardNumber(averagePerDraw, 1))}</div>
        </div>
      `;
    }

    function renderDashboardActivityChart(buckets, mode, type) {
      const normalizedMode = normalizeDashboardActivityViewMode(mode);
      const totalDraws = buckets.reduce((sum, bucket) => sum + Number(bucket.drawCount || 0), 0);
      if (!totalDraws) {
        return `<div class="lotto-dashboard-empty-state">Chưa đủ dữ liệu ${escapeHtml(getDashboardTypeMeta(type).label)} để dựng biểu đồ hoạt động theo ${normalizedMode === "day" ? "ngày" : normalizedMode === "week" ? "tuần" : "tháng"}.</div>`;
      }
      const values = buckets.map(item => Number(item.value || 0));
      const targetValue = values.reduce((sum, value) => sum + value, 0) / Math.max(1, values.length);
      const maxValue = Math.max(1, targetValue, ...values);
      const width = 720;
      const height = 310;
      const paddingX = 28;
      const paddingTop = 16;
      const paddingBottom = 42;
      const chartWidth = width - paddingX * 2;
      const chartHeight = height - paddingTop - paddingBottom;
      const points = buckets.map((bucket, index) => ({
        ...bucket,
        x: paddingX + (buckets.length === 1 ? chartWidth / 2 : (chartWidth / Math.max(1, buckets.length - 1)) * index),
        y: paddingTop + chartHeight - ((Number(bucket.value || 0) / maxValue) * chartHeight),
      }));
      const goalY = paddingTop + chartHeight - ((targetValue / maxValue) * chartHeight);
      const linePath = buildDashboardSmoothPath(points);
      const areaPath = buildDashboardAreaPath(points, paddingTop + chartHeight);
      const gridLines = Array.from({ length: 4 }, (_, index) => {
        const ratio = index / 3;
        const y = paddingTop + chartHeight - ratio * chartHeight;
        const value = maxValue * ratio;
        return { y, value };
      }).reverse();
      return `
        <div class="lotto-dashboard-line-chart-shell">
          <div class="lotto-dashboard-line-chart-wrap">
            <svg class="lotto-dashboard-line-chart" viewBox="0 0 ${width} ${height}" aria-hidden="true">
              <defs>
                <linearGradient id="lottoDashboardAreaFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stop-color="rgba(109, 92, 255, .24)"></stop>
                  <stop offset="100%" stop-color="rgba(109, 92, 255, 0)"></stop>
                </linearGradient>
              </defs>
              ${gridLines.map(line => `
                <g>
                  <line class="lotto-dashboard-grid-line" x1="${paddingX}" y1="${line.y}" x2="${width - paddingX}" y2="${line.y}"></line>
                  <text class="lotto-dashboard-grid-label" x="${paddingX - 8}" y="${line.y + 4}" text-anchor="end">${escapeHtml(formatDashboardInteger(Math.round(line.value)))}</text>
                </g>
              `).join("")}
              <line class="lotto-dashboard-target-line" x1="${paddingX}" y1="${goalY}" x2="${width - paddingX}" y2="${goalY}"></line>
              <path class="lotto-dashboard-line-area" d="${areaPath}"></path>
              <path class="lotto-dashboard-line-path" d="${linePath}"></path>
              ${points.map(point => `
                <circle
                  class="lotto-dashboard-line-point"
                  cx="${point.x}"
                  cy="${point.y}"
                  r="5"
                  data-dashboard-label="${escapeHtml(point.tooltipLabel)}"
                  data-dashboard-value="${escapeHtml(formatDashboardInteger(Math.round(point.value || 0)))}"
                  data-dashboard-meta="${escapeHtml(`${formatDashboardInteger(point.drawCount)} kỳ • TB ${formatDashboardNumber(point.value / Math.max(1, point.drawCount || 1), 1)}`)}"
                ></circle>
              `).join("")}
              ${points.map(point => `<text class="lotto-dashboard-axis-label" x="${point.x}" y="${height - 10}" text-anchor="middle">${escapeHtml(point.label)}</text>`).join("")}
              <text class="lotto-dashboard-target-text" x="${width - paddingX}" y="${goalY - 8}" text-anchor="end">Mục tiêu</text>
            </svg>
            <div class="lotto-dashboard-line-tooltip" hidden></div>
          </div>
        </div>
      `;
    }

    function renderDashboardActivityTabs() {
      document.querySelectorAll("[data-dashboard-activity-view]").forEach(button => {
        const viewMode = normalizeDashboardActivityViewMode(button.dataset.dashboardActivityView);
        const isActive = viewMode === dashboardActivityViewMode;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-pressed", isActive ? "true" : "false");
      });
    }

    function renderDashboardDistributionTabs() {
      const host = document.getElementById("lottoDashboardDistributionTabs");
      if (!host) return;
      const options = getDashboardDistributionOptions(dashboardSelectedGame);
      host.innerHTML = options.map(option => {
        const isActive = option.value === dashboardDistributionViewMode;
        return `<button type="button" class="lotto-dashboard-tab${isActive ? " is-active" : ""}" data-dashboard-distribution-view="${escapeHtml(option.value)}" aria-pressed="${isActive ? "true" : "false"}">${escapeHtml(option.label)}</button>`;
      }).join("");
      host.querySelectorAll("[data-dashboard-distribution-view]").forEach(button => {
        button.addEventListener("click", () => {
          const nextView = normalizeDashboardDistributionViewMode(button.dataset.dashboardDistributionView);
          if (nextView === dashboardDistributionViewMode) return;
          dashboardDistributionViewMode = nextView;
          saveDashboardUiState();
          renderDashboardPanel();
        });
      });
    }

    function bindDashboardLineTooltip() {
      const wrap = document.querySelector("#lottoDashboardActivityOut .lotto-dashboard-line-chart-wrap");
      const tooltip = wrap?.querySelector(".lotto-dashboard-line-tooltip");
      if (!wrap || !tooltip) return;
      const hide = () => {
        tooltip.hidden = true;
      };
      wrap.querySelectorAll(".lotto-dashboard-line-point").forEach(point => {
        const show = event => {
          const bounds = wrap.getBoundingClientRect();
          const offsetX = Math.max(14, Math.min(bounds.width - 14, event.clientX - bounds.left));
          const offsetY = Math.max(16, event.clientY - bounds.top - 18);
          tooltip.innerHTML = `
            <div class="lotto-dashboard-line-tooltip-label">${escapeHtml(point.dataset.dashboardLabel || "")}</div>
            <div class="lotto-dashboard-line-tooltip-value">${escapeHtml(point.dataset.dashboardValue || "0")}</div>
            <div class="lotto-dashboard-line-tooltip-meta">${escapeHtml(point.dataset.dashboardMeta || "")}</div>
          `;
          tooltip.style.left = `${offsetX}px`;
          tooltip.style.top = `${offsetY}px`;
          tooltip.hidden = false;
        };
        point.addEventListener("mouseenter", show);
        point.addEventListener("mousemove", show);
        point.addEventListener("mouseleave", hide);
      });
      wrap.addEventListener("mouseleave", hide);
    }

    function renderDashboardPanel() {
      const heroHost = document.getElementById("lottoDashboardHero");
      const quickStatsHost = document.getElementById("lottoDashboardQuickStats");
      const activityStatsHost = document.getElementById("lottoDashboardActivityStats");
      const activityOut = document.getElementById("lottoDashboardActivityOut");
      const distributionOut = document.getElementById("lottoDashboardDistributionOut");
      const updatedAtHost = document.getElementById("lottoDashboardUpdatedAt");
      const statusHost = document.getElementById("lottoDashboardStatus");
      const statusBtn = document.getElementById("lottoDashboardStatusBtn");
      const distributionSubtitleHost = document.getElementById("lottoDashboardDistributionSubtitle");
      const activitySubtitleHost = document.getElementById("lottoDashboardActivitySubtitle");
      if (!heroHost || !quickStatsHost || !activityStatsHost || !activityOut || !distributionOut || !updatedAtHost || !statusHost) return;

      renderDashboardGameSelect();
      renderDashboardActivityTabs();
      renderDashboardDistributionTabs();

      const type = normalizeDashboardGame(dashboardSelectedGame);
      const meta = getDashboardTypeMeta(type);
      const entries = buildDashboardEntries();
      const feed = getLiveHistoryFeed(type);
      const loadedAt = new Date(String(feed?.loadedAt || "").trim());
      updatedAtHost.textContent = `Cập nhật: ${loadedAt instanceof Date && !Number.isNaN(loadedAt.getTime()) ? formatDashboardRelativeTime(loadedAt) : "đang chờ dữ liệu"}`;
      if (distributionSubtitleHost) distributionSubtitleHost.textContent = getDashboardDistributionSubtitle(type, dashboardDistributionViewMode);
      if (activitySubtitleHost) {
        activitySubtitleHost.textContent = getDashboardFamily(type) === "threeDigit"
          ? `Theo dõi biến động tổng điểm bộ 3 số của ${meta.label} theo ngày, tuần hoặc tháng.`
          : `Theo dõi biến động tổng điểm kỳ của ${meta.label} theo ngày, tuần hoặc tháng.`;
      }

      if (dashboardPanelError) {
        statusHost.hidden = false;
        statusHost.className = "lotto-dashboard-status is-warning";
        statusHost.textContent = dashboardPanelError;
      } else {
        statusHost.hidden = true;
        statusHost.className = "lotto-dashboard-status";
        statusHost.textContent = "";
      }

      if (statusBtn) {
        statusBtn.className = "lotto-dashboard-icon-btn is-status";
        if (dashboardPanelLoading) {
          statusBtn.classList.add("is-loading");
          statusBtn.textContent = "…";
          statusBtn.title = `Đang tải dữ liệu ${meta.label}`;
        } else if (dashboardPanelError) {
          statusBtn.classList.add("is-danger");
          statusBtn.textContent = "!";
          statusBtn.title = dashboardPanelError;
        } else if (entries.length) {
          statusBtn.classList.add("is-success");
          statusBtn.textContent = "●";
          statusBtn.title = `${meta.label}: ${formatDashboardInteger(entries.length)} kỳ đã nạp`;
        } else {
          statusBtn.classList.add("is-idle");
          statusBtn.textContent = "○";
          statusBtn.title = `${meta.label}: chưa có dữ liệu`;
        }
      }

      if (dashboardPanelLoading && !entries.length) {
        heroHost.innerHTML = `<div class="lotto-dashboard-empty-card">Đang tải overview riêng của ${escapeHtml(meta.label)}...</div>`;
        quickStatsHost.innerHTML = `<div class="lotto-dashboard-empty-card">Đang tính quick stats riêng của ${escapeHtml(meta.label)}...</div>`;
        activityStatsHost.innerHTML = "";
        activityOut.className = "lotto-dashboard-panel-body lotto-dashboard-panel-body-muted";
        activityOut.innerHTML = "Đang tải biểu đồ hoạt động từ dữ liệu thật...";
        distributionOut.className = "lotto-dashboard-panel-body lotto-dashboard-panel-body-muted";
        distributionOut.innerHTML = "Đang dựng phân bổ riêng cho game đang chọn...";
        return;
      }

      if (!entries.length) {
        heroHost.innerHTML = `<div class="lotto-dashboard-empty-card">Chưa có dữ liệu ${escapeHtml(meta.label)} để dựng dashboard riêng cho game này.</div>`;
        quickStatsHost.innerHTML = `<div class="lotto-dashboard-empty-card">Quick stats sẽ xuất hiện khi feed ${escapeHtml(meta.label)} có dữ liệu thật.</div>`;
        activityStatsHost.innerHTML = "";
        activityOut.className = "lotto-dashboard-panel-body lotto-dashboard-panel-body-muted";
        activityOut.innerHTML = `Hệ thống cần ít nhất một nguồn all_day.csv của ${escapeHtml(meta.label)} để vẽ biểu đồ hoạt động.`;
        distributionOut.className = "lotto-dashboard-panel-body lotto-dashboard-panel-body-muted";
        distributionOut.innerHTML = `Khi có dữ liệu thật của ${escapeHtml(meta.label)}, donut phân bổ sẽ hiển thị ngay tại đây.`;
        return;
      }

      heroHost.innerHTML = renderDashboardHeroCard(type, entries);
      quickStatsHost.innerHTML = renderDashboardQuickStats(type, entries);

      const activityBuckets = getDashboardActivityBuckets(entries, dashboardActivityViewMode);
      activityStatsHost.innerHTML = renderDashboardActivityStats(activityBuckets, type);
      activityOut.className = "lotto-dashboard-panel-body";
      activityOut.innerHTML = renderDashboardActivityChart(activityBuckets, dashboardActivityViewMode, type);

      distributionOut.className = "lotto-dashboard-panel-body";
      distributionOut.innerHTML = renderDashboardDistributionPanel(type, entries, dashboardDistributionViewMode);
      window.setTimeout(bindDashboardLineTooltip, 0);
    }

    async function startDashboardRefresh({ force = false, silent = true } = {}) {
      const refreshToken = ++dashboardPanelRefreshToken;
      const type = normalizeDashboardGame(dashboardSelectedGame);
      dashboardPanelLoading = true;
      dashboardPanelError = "";
      renderDashboardPanel();
      try {
        await fetchLiveHistory(type, "all", { force, silent });
        if (refreshToken !== dashboardPanelRefreshToken) return;
        dashboardPanelLoading = false;
        dashboardPanelError = "";
      } catch (error) {
        if (refreshToken !== dashboardPanelRefreshToken) return;
        dashboardPanelLoading = false;
        dashboardPanelError = `Không tải được dashboard ${getDashboardTypeMeta(type).label}: ${String(error?.message || error || "Lỗi không rõ")}`;
      } finally {
        if (refreshToken !== dashboardPanelRefreshToken) return;
        renderDashboardPanel();
      }
    }

    function renderVipPredictEngineChoice() {
      const select = document.getElementById("vipPdEngine");
      const choiceWrap = document.getElementById("vipPdEngineChoice");
      if (select) select.value = String(vipPredictEngineValue || "both").trim().toLowerCase() || "both";
      if (!choiceWrap) return;
      const selected = String(vipPredictEngineValue || "both").trim().toLowerCase() || "both";
      choiceWrap.querySelectorAll("[data-vip-pd-engine]").forEach(button => {
        const isActive = String(button.dataset.vipPdEngine || "").trim().toLowerCase() === selected;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-pressed", isActive ? "true" : "false");
      });
    }

    function renderVipPredictRiskModeChoice() {
      const choiceWrap = document.getElementById("vipPdRiskModeChoice");
      if (!choiceWrap) return;
      const selected = normalizePredictRiskMode(vipPredictRiskModeValue);
      choiceWrap.querySelectorAll("[data-vip-pd-risk-mode]").forEach(button => {
        const modeKey = normalizePredictRiskMode(button.dataset.vipPdRiskMode);
        const isActive = modeKey === selected;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-pressed", isActive ? "true" : "false");
      });
    }

    function maybeAutoSwitchRiskModeForBao(typeKey, playModeValue) {
      const normalizedType = String(typeKey || "").trim().toUpperCase();
      const normalizedPlayMode = String(playModeValue || "").trim().toLowerCase();
      const normalizedEngine = String(predictEngineValue || "both").trim().toLowerCase();
      if (!hasPredictBaoMode(normalizedType) || normalizedPlayMode !== "bao" || normalizedEngine !== "both") {
        return false;
      }
      const currentMode = normalizePredictRiskMode(predictRiskModeValue);
      if (currentMode === "balanced") return false;
      savePredictRiskMode("balanced");
      renderPredictRiskModeChoice();
      const out = document.getElementById("predictOut");
      if (out && (out.classList.contains("muted") || !out.querySelector(".ai-result-shell"))) {
        line(out, "Bao Số đã tự chuyển sang Cân Bằng để giữ nhịp ổn định hơn.", "muted");
      }
      return true;
    }

    function maybeAutoSwitchVipRiskModeForBao(typeKey, playModeValue) {
      const normalizedType = String(typeKey || "").trim().toUpperCase();
      const normalizedPlayMode = String(playModeValue || "").trim().toLowerCase();
      const normalizedEngine = String(vipPredictEngineValue || "both").trim().toLowerCase();
      if (!hasPredictBaoMode(normalizedType) || normalizedPlayMode !== "bao" || normalizedEngine !== "both") {
        return false;
      }
      const currentMode = normalizePredictRiskMode(vipPredictRiskModeValue);
      if (currentMode === "balanced") return false;
      vipPredictRiskModeValue = "balanced";
      saveVipPredictState();
      renderVipPredictRiskModeChoice();
      return true;
    }

    function enforcePredictRiskModeVisibility(isAiPredict) {
      const riskModeBox = document.getElementById("pdRiskModeBox");
      if (!riskModeBox) return;
      const shouldShow = !!isAiPredict && String(predictEngineValue || "both").trim().toLowerCase() === "both";
      riskModeBox.hidden = !shouldShow;
      riskModeBox.style.display = shouldShow ? "grid" : "none";
    }

    function enforceVipPredictRiskModeVisibility(isAiPredict) {
      const riskModeBox = document.getElementById("vipPdRiskModeBox");
      if (!riskModeBox) return;
      const shouldShow = !!isAiPredict && String(vipPredictEngineValue || "both").trim().toLowerCase() === "both";
      riskModeBox.hidden = !shouldShow;
      riskModeBox.style.display = shouldShow ? "grid" : "none";
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

    function getPredictionHitSlotCount(type, tickets = []) {
      const firstTicketSize = Array.isArray(tickets?.[0]?.main) ? tickets[0].main.length : 0;
      const mainCount = firstTicketSize || Number(TYPES[type]?.mainCount || 0);
      return Math.max(0, mainCount + (TYPES[type]?.hasSpecial ? 1 : 0));
    }

    function formatPredictionPercent(value) {
      return `${Number(value || 0).toFixed(2)}%`;
    }

    function buildPredictionTrend(currentRate, previousRate) {
      const current = Number(currentRate || 0);
      const previous = Number(previousRate || 0);
      const delta = current - previous;
      if (delta > 0.0001) {
        return { direction: "up", icon: "↑", delta };
      }
      if (delta < -0.0001) {
        return { direction: "down", icon: "↓", delta };
      }
      return { direction: "same", icon: "→", delta: 0 };
    }

    function formatPredictionTrendText(trend) {
      if (!trend || typeof trend !== "object") return "";
      if (trend.direction === "same") return "→0.00%";
      return `${trend.icon}${formatPredictionPercent(Math.abs(Number(trend.delta || 0)))}`;
    }

    function formatPredictionTrendHtml(trend) {
      if (!trend || typeof trend !== "object") return "";
      const direction = String(trend.direction || "same");
      return `<span class="prediction-trend ${direction}">${escapeHtml(formatPredictionTrendText(trend))}</span>`;
    }

    function buildPredictionRateBuckets(type, details, tickets) {
      const slotCount = getPredictionHitSlotCount(type, tickets);
      const ticketCount = Array.isArray(details) ? details.length : 0;
      const buckets = [];
      for (let hitCount = 1; hitCount <= slotCount; hitCount++) {
        const matchedCount = (details || []).filter(detail => {
          const totalHits = Number(detail?.mainHits || 0) + (detail?.specialHit ? 1 : 0);
          return totalHits === hitCount;
        }).length;
        buckets.push({
          hitCount,
          count: matchedCount,
          rate: ticketCount ? (matchedCount * 100 / ticketCount) : 0,
        });
      }
      return buckets;
    }

    function buildPredictionTopHitSummary(type, entry, draw) {
      const mainRanking = Array.isArray(entry?.topMainRanking) ? entry.topMainRanking.map(Number).filter(Number.isInteger) : [];
      const mainMatched = mainRanking.length ? countMainMatch(mainRanking, draw.main) : 0;
      const topMain = {
        matched: mainMatched,
        total: mainRanking.length,
        rate: mainRanking.length ? (mainMatched * 100 / mainRanking.length) : 0,
      };
      const topSpecial = {
        matched: 0,
        total: 0,
        rate: 0,
      };
      if (TYPES[type]?.hasSpecial) {
        const specialRanking = Array.isArray(entry?.topSpecialRanking) ? entry.topSpecialRanking.map(Number).filter(Number.isInteger) : [];
        const specialMatched = Number.isInteger(draw?.special) && specialRanking.includes(draw.special) ? 1 : 0;
        topSpecial.matched = specialMatched;
        topSpecial.total = specialRanking.length;
        topSpecial.rate = specialRanking.length ? (specialMatched * 100 / specialRanking.length) : 0;
      }
      return { topMain, topSpecial };
    }

    function getPredictionEntrySortMeta(entry) {
      return {
        kyValue: kySortValue(entry?.actualKy || entry?.predictedKy),
        timeValue: Date.parse(entry?.resolvedAt || entry?.createdAt || 0) || 0,
      };
    }

    function enrichPredictionSummary(type, entry, previousSummary = null) {
      if (!entry?.actualDraw || !Array.isArray(entry?.tickets)) return entry?.resultSummary || null;
      const baseSummary = evaluatePredictionTicketsForDraw(type, entry.tickets, entry.actualDraw);
      const hitRateBuckets = buildPredictionRateBuckets(type, baseSummary.details, entry.tickets).map(bucket => {
        const previousBucket = Array.isArray(previousSummary?.hitRateBuckets)
          ? previousSummary.hitRateBuckets.find(item => Number(item?.hitCount || 0) === bucket.hitCount)
          : null;
        return {
          ...bucket,
          trend: buildPredictionTrend(bucket.rate, Number(previousBucket?.rate || 0)),
        };
      });
      const topHitSummary = buildPredictionTopHitSummary(type, entry, entry.actualDraw);
      const previousTopMainRate = Number(previousSummary?.topHitSummary?.topMain?.rate || 0);
      const previousTopSpecialRate = Number(previousSummary?.topHitSummary?.topSpecial?.rate || 0);
      return {
        ...baseSummary,
        hitRateBuckets,
        topHitSummary: {
          topMain: {
            ...topHitSummary.topMain,
            trend: buildPredictionTrend(topHitSummary.topMain.rate, previousTopMainRate),
          },
          topSpecial: {
            ...topHitSummary.topSpecial,
            trend: buildPredictionTrend(topHitSummary.topSpecial.rate, previousTopSpecialRate),
          },
        },
      };
    }

    function refreshResolvedPredictionSummaries(type) {
      if (!PREDICTION_LOG_TYPES.includes(type)) return false;
      const logs = ensurePredictionLogBucket(type);
      const resolvedEntries = logs
        .filter(entry => entry?.resolved && entry?.actualDraw && Array.isArray(entry?.tickets))
        .sort((a, b) => {
          const aMeta = getPredictionEntrySortMeta(a);
          const bMeta = getPredictionEntrySortMeta(b);
          if (aMeta.kyValue !== bMeta.kyValue) return aMeta.kyValue - bMeta.kyValue;
          return aMeta.timeValue - bMeta.timeValue;
        });
      let previousSummary = null;
      let changed = false;
      for (const entry of resolvedEntries) {
        const nextSummary = enrichPredictionSummary(type, entry, previousSummary);
        const before = JSON.stringify(entry.resultSummary || null);
        const after = JSON.stringify(nextSummary || null);
        if (before !== after) {
          entry.resultSummary = nextSummary;
          changed = true;
        }
        previousSummary = nextSummary;
      }
      return changed;
    }

    function evaluatePredictionTicketsForDraw(type, tickets, draw) {
      const threshold = getPredictionHitThreshold(type);
      const details = [];
      let bestMainHits = 0;
      let specialHits = 0;
      let thresholdTicketHits = 0;
      let prizeTicketHits = 0;
      let totalMainHits = 0;
      for (const ticket of (tickets || [])) {
        const cloned = clonePredictionTicket(ticket);
        if (!cloned) continue;
        const isBao = String(cloned.playMode || "").trim().toLowerCase() === "bao";
        const mainHits = countMainMatch(cloned.main, draw.main);
        const specialHit = TYPES[type].hasSpecial && Number.isInteger(cloned.special) && cloned.special === draw.special;
        const prize = isBao ? null : evalPrize(type, cloned, draw);
        if (mainHits > bestMainHits) bestMainHits = mainHits;
        totalMainHits += mainHits;
        if (specialHit) specialHits += 1;
        if (mainHits >= threshold) thresholdTicketHits += 1;
        if (prize) prizeTicketHits += 1;
        details.push({
          main: cloned.main,
          special: cloned.special,
          playMode: cloned.playMode || "",
          baoLevel: cloned.baoLevel,
          mainHits,
          specialHit,
          prizeLabel: prize?.[0] || "",
          prizeValue: prize?.[1] || "",
        });
      }
      return {
        ticketCount: details.length,
        bestMainHits,
        avgMainHits: details.length ? (totalMainHits / details.length) : 0,
        specialHits,
        thresholdTicketHits,
        prizeTicketHits,
        details,
      };
    }

    function resolvePredictionLogsForKy(type, ky, draw) {
      if (!PREDICTION_LOG_TYPES.includes(type)) return;
      const logs = ensurePredictionLogBucket(type);
      const normalizedKy = normalizeKy(ky);
      if (!normalizedKy || !logs.length) return;
      let changed = false;
      for (const entry of logs) {
        if (normalizeKy(entry?.predictedKy) !== normalizedKy) continue;
        if (entry.resolved && entry.actualKy === normalizedKy) continue;
        entry.resolved = true;
        entry.resolvedAt = new Date().toISOString();
        entry.actualKy = normalizedKy;
        entry.actualDraw = cloneDraw(draw);
        entry.resultMissingData = false;
        entry.resultMissingReason = "";
        entry.resultMissingCheckedAt = "";
        changed = true;
      }
      if (changed) {
        refreshResolvedPredictionSummaries(type);
        renderPredictionHistoryPanel();
      }
    }

    function findPredictionResultDraw(dataset, ky) {
      if (!dataset?.results) return null;
      const normalizedKy = normalizeKy(ky);
      if (!normalizedKy) return null;
      const digitKy = normalizedKy.replace(/\D/g, "");
      const directHit = dataset.results[normalizedKy] || dataset.results[digitKy];
      if (directHit) return directHit;
      const targetKyValue = kySortValue(normalizedKy);
      if (!targetKyValue) return null;
      for (const [key, draw] of Object.entries(dataset.results)) {
        if (kySortValue(key) === targetKyValue) return draw;
      }
      return null;
    }

    function getPredictionResultDrawDate(type, dataset, ky) {
      const draw = findPredictionResultDraw(dataset, ky);
      if (!draw) return null;
      const resolved = resolveLiveDrawDateTime(type, draw.date, draw.time);
      return resolved instanceof Date && !Number.isNaN(resolved.getTime()) ? resolved : null;
    }

    function parsePredictionLogDate(value) {
      const parsed = value ? new Date(value) : null;
      return parsed instanceof Date && !Number.isNaN(parsed.getTime()) ? parsed : null;
    }

    function isKenoPredictionLogOverdue(entry, dataset = null, nowValue = new Date()) {
      if (!entry || entry.resolved) return false;
      const resultDataset = dataset || buildPredictionResultDataset("KENO");
      const predictedKy = normalizeKy(entry.predictedKy);
      const predictedKyValue = kySortValue(predictedKy);
      const latestKnownKyValue = kySortValue((resultDataset?.order || []).at(-1));
      if (predictedKyValue && latestKnownKyValue && predictedKyValue <= latestKnownKyValue) {
        return true;
      }
      const predictedDrawDate = predictedKy ? getPredictionResultDrawDate("KENO", resultDataset, predictedKy) : null;
      if (predictedDrawDate && predictedDrawDate.getTime() <= nowValue.getTime()) {
        return true;
      }
      const createdAt = parsePredictionLogDate(entry.createdAt);
      if (!createdAt) return false;
      const fallbackTargetDate = findNextLiveDrawDate("KENO", createdAt);
      return fallbackTargetDate instanceof Date
        && !Number.isNaN(fallbackTargetDate.getTime())
        && fallbackTargetDate.getTime() <= nowValue.getTime();
    }

    function getKenoPredictionHistoryRepairLookbackDays(dataset = null, nowValue = new Date()) {
      const logs = ensurePredictionLogBucket("KENO");
      if (!logs.length) return 0;
      const resultDataset = dataset || buildPredictionResultDataset("KENO");
      let oldestDate = null;
      logs.forEach(entry => {
        if (!isKenoPredictionLogOverdue(entry, resultDataset, nowValue)) return;
        const predictedDrawDate = getPredictionResultDrawDate("KENO", resultDataset, entry.predictedKy);
        const fallbackDate = parsePredictionLogDate(entry.createdAt);
        const candidate = predictedDrawDate || fallbackDate;
        if (!(candidate instanceof Date) || Number.isNaN(candidate.getTime())) return;
        if (!oldestDate || candidate.getTime() < oldestDate.getTime()) oldestDate = candidate;
      });
      if (!(oldestDate instanceof Date) || Number.isNaN(oldestDate.getTime())) return 0;
      const diffDays = Math.ceil((nowValue.getTime() - oldestDate.getTime()) / (24 * 60 * 60 * 1000));
      return Math.min(30, Math.max(3, diffDays + 2));
    }

    function markMissingKenoPredictionResults(dataset = null, nowValue = new Date()) {
      const resultDataset = dataset || buildPredictionResultDataset("KENO");
      const logs = ensurePredictionLogBucket("KENO");
      if (!logs.length) return false;
      let changed = false;
      const checkedAt = nowValue.toISOString();
      logs.forEach(entry => {
        if (!entry) return;
        const shouldMarkMissing = !entry.resolved && isKenoPredictionLogOverdue(entry, resultDataset, nowValue);
        if (shouldMarkMissing) {
          if (!entry.resultMissingData || entry.resultMissingReason !== "canonical_history_missing_result") {
            entry.resultMissingData = true;
            entry.resultMissingReason = "canonical_history_missing_result";
            changed = true;
          }
          if (entry.resultMissingCheckedAt !== checkedAt) {
            entry.resultMissingCheckedAt = checkedAt;
            changed = true;
          }
          return;
        }
        if (entry.resultMissingData || entry.resultMissingReason || entry.resultMissingCheckedAt) {
          entry.resultMissingData = false;
          entry.resultMissingReason = "";
          entry.resultMissingCheckedAt = "";
          changed = true;
        }
      });
      return changed;
    }

    function getPredictionHistoryEntryStatus(entry) {
      if (entry?.resolved) {
        return { className: "resolved", label: "Đã đối chiếu", shortLabel: "Đã đối chiếu" };
      }
      if (entry?.resultMissingData) {
        return { className: "missing", label: "Thiếu dữ liệu KQ", shortLabel: "Thiếu KQ" };
      }
      return { className: "waiting", label: "Chờ kết quả", shortLabel: "Chờ KQ" };
    }

    function findNextKenoKyAfterDate(dataset, afterDate) {
      if (!(afterDate instanceof Date) || Number.isNaN(afterDate.getTime())) return null;
      for (const ky of (dataset?.order || [])) {
        const drawDate = getPredictionResultDrawDate("KENO", dataset, ky);
        if (drawDate && drawDate.getTime() > afterDate.getTime()) {
          return normalizeKy(ky);
        }
      }
      return null;
    }

    function repairStaleKenoPredictionLogs(dataset = null) {
      const resultDataset = dataset || buildPredictionResultDataset("KENO");
      const logs = ensurePredictionLogBucket("KENO");
      if (!logs.length || !(resultDataset?.order || []).length) return false;
      const latestKy = resultDataset.order[resultDataset.order.length - 1];
      const latestKyValue = kySortValue(latestKy);
      let changed = false;

      for (const entry of logs) {
        if (!entry || entry.resolved) continue;
        const predictedKy = normalizeKy(entry.predictedKy);
        const predictedKyValue = kySortValue(predictedKy);
        if (!predictedKy || !predictedKyValue || predictedKyValue > latestKyValue) continue;
        const predictedDrawDate = getPredictionResultDrawDate("KENO", resultDataset, predictedKy);
        const createdAt = entry.createdAt ? new Date(entry.createdAt) : null;
        if (!(createdAt instanceof Date) || Number.isNaN(createdAt.getTime()) || !predictedDrawDate) continue;
        if (createdAt.getTime() <= predictedDrawDate.getTime()) continue;
        const repairedKy = findNextKenoKyAfterDate(resultDataset, createdAt);
        if (!repairedKy || repairedKy === predictedKy) continue;
        if (!findPredictionResultDraw(resultDataset, repairedKy)) continue;
        if (!entry.predictedKyOriginal) entry.predictedKyOriginal = predictedKy;
        entry.predictedKy = repairedKy;
        entry.predictedKyRepaired = repairedKy;
        entry.repairReason = "stale_keno_client_target";
        changed = true;
      }

      return changed;
    }

    function reconcilePredictionLogsForType(type) {
      if (!PREDICTION_LOG_TYPES.includes(type)) return;
      const logs = ensurePredictionLogBucket(type);
      if (!logs.length) return;
      const dataset = buildPredictionResultDataset(type);
      if (type === "KENO") {
        const repaired = repairStaleKenoPredictionLogs(dataset);
        if (repaired) saveStore();
      }
      for (const entry of logs) {
        if (entry?.resolved) continue;
        const predictedKy = normalizeKy(entry?.predictedKy);
        const draw = findPredictionResultDraw(dataset, predictedKy);
        if (!predictedKy || !draw) continue;
        resolvePredictionLogsForKy(type, predictedKy, draw);
      }
      if (type === "KENO" && getLiveHistoryFeed("KENO")?.repairAttempted) {
        const markedMissing = markMissingKenoPredictionResults(dataset);
        if (markedMissing) saveStore();
      }
    }

    function reconcileAllPredictionLogs() {
      for (const type of PREDICTION_LOG_TYPES) reconcilePredictionLogsForType(type);
    }

    function upsertPredictionLog(type, entry) {
      if (!PREDICTION_LOG_TYPES.includes(type) || !entry) return;
      const logs = ensurePredictionLogBucket(type);
      const predictedKy = normalizeKy(entry.predictedKy);
      const next = {
        id: String(entry.id || `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`),
        createdAt: String(entry.createdAt || new Date().toISOString()),
        predictedKy,
        strategyKey: String(entry.strategyKey || ""),
        strategyLabel: String(entry.strategyLabel || ""),
        modelKey: String(entry.modelKey || entry.strategyKey || ""),
        modelLabel: String(entry.modelLabel || entry.strategyLabel || ""),
        engineKey: String(entry.engineKey || ""),
        engineLabel: String(entry.engineLabel || ""),
        riskMode: normalizePredictRiskMode(entry.riskMode || "balanced"),
        riskModeLabel: String(entry.riskModeLabel || getPredictRiskModeMeta(entry.riskMode || "balanced").label),
        riskModeSummary: String(entry.riskModeSummary || getPredictRiskModeMeta(entry.riskMode || "balanced").summary),
        modelVersion: String(entry.modelVersion || ""),
        championKey: String(entry.championKey || ""),
        championLabel: String(entry.championLabel || ""),
        lastTrainedAt: String(entry.lastTrainedAt || ""),
        confidence: Number(entry.confidence || 0),
        stabilityScore: Number(entry.stabilityScore || entry.backtest?.stabilityScore || 0),
        recentCount: Number(entry.recentCount || 0),
        drawCount: Number(entry.drawCount || 0),
        historyFile: String(entry.historyFile || ""),
        historyCount: Number(entry.historyCount || 0),
        bundleCount: Number(entry.bundleCount || 0),
        pickSize: Number(entry.pickSize || 0),
        playMode: String(entry.playMode || "").trim().toLowerCase(),
        baoLevel: Number.isInteger(Number(entry.baoLevel)) ? Number(entry.baoLevel) : null,
        predictionMode: normalizePredictionMode(entry.predictionMode || PREDICTION_MODE_NORMAL),
        vipProfile: String(entry.vipProfile || ""),
        tickets: (entry.tickets || []).map(clonePredictionTicket).filter(Boolean),
        ticketSources: Array.isArray(entry.ticketSources) ? entry.ticketSources.map(item => String(item || "").trim()) : [],
          topMainRanking: Array.isArray(entry.topMainRanking) ? entry.topMainRanking.map(Number) : [],
          topSpecialRanking: Array.isArray(entry.topSpecialRanking) ? entry.topSpecialRanking.map(Number) : [],
          backtest: entry.backtest || null,
          metaSelectionMode: String(entry.metaSelectionMode || ""),
          metaScores: entry.metaScores || null,
          metaQuota: entry.metaQuota || null,
          metaPreferredEngine: String(entry.metaPreferredEngine || ""),
          metaSummary: String(entry.metaSummary || ""),
          resolved: !!entry.resolved,
          resolvedAt: String(entry.resolvedAt || ""),
          actualKy: String(entry.actualKy || ""),
          resultMissingData: !!entry.resultMissingData,
          resultMissingReason: String(entry.resultMissingReason || ""),
          resultMissingCheckedAt: String(entry.resultMissingCheckedAt || ""),
        actualDraw: entry.actualDraw ? cloneDraw(entry.actualDraw) : null,
        resultSummary: entry.resultSummary || null,
      };
      const idx = logs.findIndex(log => String(log?.id || "") === next.id);
      if (idx >= 0) logs[idx] = next;
      else logs.push(next);
      logs.sort((a, b) => {
        const aTime = Date.parse(a?.createdAt || 0) || 0;
        const bTime = Date.parse(b?.createdAt || 0) || 0;
        if (aTime !== bTime) return aTime - bTime;
        return kySortValue(a.predictedKy) - kySortValue(b.predictedKy);
      });
      while (logs.length > MAX_PREDICTION_LOGS_PER_TYPE) logs.shift();
      renderPredictionHistoryPanel();
    }

    function getPredictionEntryPlayModeForMetrics(entry) {
      const directMode = String(entry?.playMode || "").trim().toLowerCase();
      if (directMode === "bao") return "bao";
      const tickets = Array.isArray(entry?.tickets) ? entry.tickets : [];
      return tickets.some(ticket => String(ticket?.playMode || "").trim().toLowerCase() === "bao") ? "bao" : "normal";
    }

    function getPredictionEntryMode(entry) {
      return normalizePredictionMode(entry?.predictionMode || PREDICTION_MODE_NORMAL);
    }

    function getPredictionEntryBaoLevelForMetrics(entry) {
      const directLevel = Number(entry?.baoLevel || 0);
      if (Number.isInteger(directLevel) && directLevel > 0) return directLevel;
      const tickets = Array.isArray(entry?.tickets) ? entry.tickets : [];
      const baoTicket = tickets.find(ticket => String(ticket?.playMode || "").trim().toLowerCase() === "bao");
      if (!baoTicket) return 0;
      const ticketLevel = Number(baoTicket?.baoLevel || (Array.isArray(baoTicket?.main) ? baoTicket.main.length : 0) || 0);
      return Number.isInteger(ticketLevel) && ticketLevel > 0 ? ticketLevel : 0;
    }

    function getPredictionEntryPickSizeForMetrics(type, entry) {
      if (type !== "KENO") return 0;
      const directSize = Number(entry?.pickSize || 0);
      if (Number.isInteger(directSize) && directSize > 0) return directSize;
      const firstTicket = Array.isArray(entry?.tickets) ? entry.tickets.find(ticket => Array.isArray(ticket?.main) && ticket.main.length) : null;
      return firstTicket ? Number(firstTicket.main.length || 0) : 0;
    }

    function findPreviousPredictionLogForMetrics(result) {
      const type = String(result?.type || "").trim().toUpperCase();
      if (!PREDICTION_LOG_TYPES.includes(type)) return null;
      const currentCreatedAtMs = Date.parse(String(result?.createdAt || "").trim());
      if (!Number.isFinite(currentCreatedAtMs)) return null;
      const currentPredictionMode = getPredictionEntryMode(result);
      const currentEngineKey = String(result?.engineKey || result?.engine || "").trim().toLowerCase();
      const currentRiskMode = currentEngineKey === "both" ? getResultRiskMode(result, "balanced") : "";
      const currentPlayMode = getPredictionEntryPlayModeForMetrics(result);
      const currentPickSize = getPredictionEntryPickSizeForMetrics(type, result);
      const currentBaoLevel = currentPlayMode === "bao" ? getPredictionEntryBaoLevelForMetrics(result) : 0;
      const logs = ensurePredictionLogBucket(type);
      const candidates = logs.filter(entry => {
        const entryCreatedAtMs = Date.parse(String(entry?.createdAt || "").trim());
        if (!Number.isFinite(entryCreatedAtMs) || entryCreatedAtMs >= currentCreatedAtMs) return false;
        if (getPredictionEntryMode(entry) !== currentPredictionMode) return false;
        const entryEngineKey = String(entry?.engineKey || "").trim().toLowerCase();
        if (entryEngineKey !== currentEngineKey) return false;
        if (currentEngineKey === "both" && normalizePredictRiskMode(entry?.riskMode || "balanced") !== currentRiskMode) return false;
        const entryPlayMode = getPredictionEntryPlayModeForMetrics(entry);
        if (entryPlayMode !== currentPlayMode) return false;
        if (type === "KENO" && getPredictionEntryPickSizeForMetrics(type, entry) !== currentPickSize) return false;
        if (currentPlayMode === "bao" && getPredictionEntryBaoLevelForMetrics(entry) !== currentBaoLevel) return false;
        return true;
      });
      if (!candidates.length) return null;
      candidates.sort((a, b) => {
        const aTime = Date.parse(String(a?.createdAt || "").trim()) || 0;
        const bTime = Date.parse(String(b?.createdAt || "").trim()) || 0;
        if (aTime !== bTime) return bTime - aTime;
        return kySortValue(b?.predictedKy) - kySortValue(a?.predictedKy);
      });
      return candidates[0] || null;
    }

    function normalizePredictionHistoryType(value) {
      const raw = String(value || "").trim().toUpperCase();
      return PREDICTION_HISTORY_TYPES.some(item => item.value === raw) ? raw : "KENO";
    }

    function getPreferredPredictionHistoryType() {
      const pdType = document.getElementById("pdType");
      return normalizePredictionHistoryType(pdType?.value || predictionHistorySelectedType);
    }

    function renderPredictionHistoryTypeTabs() {
      const tabsEl = document.getElementById("predictionHistoryTypeTabs");
      if (!tabsEl) return;
      const selectedType = normalizePredictionHistoryType(predictionHistorySelectedType);
      predictionHistorySelectedType = selectedType;
      tabsEl.innerHTML = PREDICTION_HISTORY_TYPES.map(item => {
        const isActive = item.value === selectedType;
        return `<button
          type="button"
          class="predict-history-type-tab${isActive ? " is-active" : ""}"
          data-prediction-history-type="${item.value}"
          role="tab"
          aria-selected="${isActive ? "true" : "false"}"
        >${escapeHtml(item.label)}</button>`;
      }).join("");
    }

    function normalizePredictionHistoryRange(value) {
      const normalized = String(value || "").trim().toLowerCase();
      return ["2k", "today", "3d", "7d", "all"].includes(normalized) ? normalized : "2k";
    }

    function renderPredictionHistoryRangeTabs() {
      const tabsEl = document.getElementById("predictionHistoryRangeTabs");
      if (!tabsEl) return;
      const selectedRange = normalizePredictionHistoryRange(predictionHistorySelectedRange);
      predictionHistorySelectedRange = selectedRange;
      const items = [
        { value: "2k", label: "2 Kỳ" },
        { value: "today", label: "Hôm Nay" },
        { value: "3d", label: "3 Ngày" },
        { value: "7d", label: "7 Ngày" },
        { value: "all", label: "Tất Cả" },
      ];
      tabsEl.innerHTML = items.map(item => {
        const isActive = item.value === selectedRange;
        return `<button
          type="button"
          class="predict-history-range-tab${isActive ? " is-active" : ""}"
          data-prediction-history-range="${item.value}"
          role="tab"
          aria-selected="${isActive ? "true" : "false"}"
        >${escapeHtml(item.label)}</button>`;
      }).join("");
    }

    function normalizePredictionHistoryPlayMode(value) {
      const normalized = String(value || "").trim().toLowerCase();
      return normalized === "bao" ? "bao" : "normal";
    }

    function normalizePredictionHistoryBaoLevel(value) {
      if (String(value || "").trim().toLowerCase() === "all") return "all";
      const numericValue = Number(value || 0);
      return Number.isInteger(numericValue) && numericValue > 0 ? String(numericValue) : "all";
    }

    function renderPredictionHistoryPlayModeTabs(typeKey = predictionHistorySelectedType) {
      const tabsEl = document.getElementById("predictionHistoryPlayModeTabs");
      if (!tabsEl) return;
      const normalizedType = normalizePredictionHistoryType(typeKey);
      if (!hasPredictBaoMode(normalizedType)) {
        predictionHistorySelectedPlayMode = "normal";
        tabsEl.hidden = true;
        tabsEl.innerHTML = "";
        renderPredictionHistoryBaoLevelFilter(normalizedType, "normal");
        return;
      }
      tabsEl.hidden = false;
      const selectedPlayMode = normalizePredictionHistoryPlayMode(predictionHistorySelectedPlayMode);
      predictionHistorySelectedPlayMode = selectedPlayMode;
      const items = [
        { value: "normal", label: "Chơi Thường" },
        { value: "bao", label: "Chơi Bao" },
      ];
      tabsEl.innerHTML = items.map(item => {
        const isActive = item.value === selectedPlayMode;
        return `<button
          type="button"
          class="predict-history-playmode-tab${isActive ? " is-active" : ""}"
          data-prediction-history-playmode="${item.value}"
          role="tab"
          aria-selected="${isActive ? "true" : "false"}"
        >${escapeHtml(item.label)}</button>`;
      }).join("");
      renderPredictionHistoryBaoLevelFilter(normalizedType, selectedPlayMode);
    }

    function getPredictionHistoryEntryPlayMode(entry) {
      const directMode = String(entry?.playMode || "").trim().toLowerCase();
      if (directMode === "bao") return "bao";
      const tickets = Array.isArray(entry?.tickets) ? entry.tickets : [];
      return tickets.some(ticket => String(ticket?.playMode || "").trim().toLowerCase() === "bao")
        ? "bao"
        : "normal";
    }

    function getPredictionHistoryEntryBundleCount(entry) {
      const directCount = Number(entry?.bundleCount || 0);
      if (Number.isInteger(directCount) && directCount > 0) return directCount;
      const ticketCount = Array.isArray(entry?.tickets) ? entry.tickets.length : 0;
      return Number.isInteger(ticketCount) && ticketCount > 0 ? ticketCount : 0;
    }

    function getPredictionHistoryBaoLevelOptions(typeKey = predictionHistorySelectedType, predictionMode = PREDICTION_MODE_NORMAL) {
      const normalizedType = normalizePredictionHistoryType(typeKey);
      if (!hasPredictBaoMode(normalizedType)) return [];
      const values = new Set();
      ensurePredictionLogBucket(normalizedType).forEach(entry => {
        if (getPredictionEntryMode(entry) !== normalizePredictionMode(predictionMode)) return;
        if (getPredictionHistoryEntryPlayMode(entry) !== "bao") return;
        const baoLevel = getPredictionEntryBaoLevelForMetrics(entry);
        if (Number.isInteger(baoLevel) && baoLevel > 0) values.add(baoLevel);
      });
      return [...values].sort((a, b) => a - b);
    }

    function renderPredictionHistoryBaoLevelFilter(typeKey = predictionHistorySelectedType, playModeKey = predictionHistorySelectedPlayMode, predictionMode = PREDICTION_MODE_NORMAL) {
      const wrapEl = document.getElementById("predictionHistoryBaoLevelFilterWrap");
      const selectEl = document.getElementById("predictionHistoryBaoLevelSelect");
      if (!wrapEl || !selectEl) return;
      const normalizedType = normalizePredictionHistoryType(typeKey);
      const selectedPlayMode = normalizePredictionHistoryPlayMode(playModeKey);
      const shouldShow = hasPredictBaoMode(normalizedType) && selectedPlayMode === "bao";
      if (!shouldShow) {
        predictionHistorySelectedBaoLevel = "all";
        wrapEl.hidden = true;
        selectEl.innerHTML = `<option value="all">Tất cả bậc</option>`;
        selectEl.value = "all";
        return;
      }
      const options = getPredictionHistoryBaoLevelOptions(normalizedType, predictionMode);
      const normalizedSelectedValue = normalizePredictionHistoryBaoLevel(predictionHistorySelectedBaoLevel);
      const nextSelectedValue = normalizedSelectedValue !== "all" && options.includes(Number(normalizedSelectedValue))
        ? normalizedSelectedValue
        : "all";
      predictionHistorySelectedBaoLevel = nextSelectedValue;
      selectEl.innerHTML = [
        `<option value="all">Tất cả bậc</option>`,
        ...options.map(value => `<option value="${value}">${escapeHtml(`Bao ${value}`)}</option>`),
      ].join("");
      selectEl.value = nextSelectedValue;
      wrapEl.hidden = false;
    }

    function isPredictionHistoryEntryInRange(entry, rangeKey = "all") {
      const selectedRange = normalizePredictionHistoryRange(rangeKey);
      if (selectedRange === "2k") return true;
      if (selectedRange === "all") return true;
      const createdAtMs = Date.parse(String(entry?.createdAt || "").trim());
      if (!Number.isFinite(createdAtMs)) return false;
      const now = new Date();
      const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
      if (selectedRange === "today") {
        return createdAtMs >= startOfToday;
      }
      const rangeDays = selectedRange === "3d" ? 3 : 7;
      return createdAtMs >= (Date.now() - (rangeDays * 24 * 60 * 60 * 1000));
    }

    function formatPredictionHistoryTime(value) {
      const parsed = Date.parse(String(value || "").trim());
      if (!parsed) return "";
      return new Date(parsed).toLocaleString("vi-VN");
    }

    function getPredictionHistoryMainHitSet(entry) {
      return new Set(
        Array.isArray(entry?.actualDraw?.main)
          ? entry.actualDraw.main.map(Number).filter(Number.isInteger)
          : []
      );
    }

    function renderPredictionHistoryNumberToken(number, { isHit = false, isMiss = false, special = false, type = "" } = {}) {
      const classNames = ["predict-hit-number"];
      if (special && isHit) classNames.push("is-special-hit");
      else if (isHit) classNames.push("is-hit");
      else if (isMiss) classNames.push("is-miss");
      return `<span class="${classNames.join(" ")}">${escapeHtml(formatPredictNumber(number, type))}</span>`;
    }

    function renderPredictionHistoryNumberList(numbers, entry, { special = false, perRow = 0, highlight = true } = {}) {
      const values = (numbers || []).map(Number).filter(Number.isInteger);
      if (!values.length) return "";
      const mainHitSet = highlight ? getPredictionHistoryMainHitSet(entry) : new Set();
      const specialHit = highlight ? Number(entry?.actualDraw?.special) : Number.NaN;
      const canHighlight = !!highlight && !!entry?.resolved && !!entry?.actualDraw;
      const tokens = values.map(number => {
        const isHit = special ? number === specialHit : mainHitSet.has(number);
        const isMiss = canHighlight && !isHit;
        return renderPredictionHistoryNumberToken(number, {
          isHit: canHighlight && isHit,
          isMiss,
          special,
          type: entry?.type || "",
        });
      });
      if (!Number.isInteger(perRow) || perRow <= 0 || values.length <= perRow) {
        return `<span class="predict-hit-number-list">${tokens.join("")}</span>`;
      }
      const rows = [];
      for (let index = 0; index < tokens.length; index += perRow) {
        rows.push(`<span class="predict-hit-number-row">${tokens.slice(index, index + perRow).join("")}</span>`);
      }
      return `<span class="predict-hit-number-grid">${rows.join("")}</span>`;
    }

    function formatPredictionHistoryTicketMeta(type, index, entry) {
      const rawSource = String(entry?.ticketSources?.[index] || "").trim().toLowerCase();
      const algorithmLabel = rawSource === "luan_so"
        ? "Luận Số"
        : rawSource === "gen_local"
        ? "AI GEN"
        : String(entry?.championLabel || entry?.modelLabel || entry?.strategyLabel || entry?.engineLabel || "AI Gen").trim();
      if (!algorithmLabel) return "";
      const detail = Array.isArray(entry?.resultSummary?.details) ? entry.resultSummary.details[index] : null;
      if (!entry?.resolved || !detail) {
        const pendingLabel = getPredictionHistoryEntryStatus(entry).shortLabel;
        return `<span class="predict-ticket-meta${entry?.resultMissingData ? " is-missing" : ""}">| ${escapeHtml(algorithmLabel)} - ${escapeHtml(pendingLabel)}</span>`;
      }
      const mainSlotCount = Array.isArray(detail?.main) ? detail.main.length : (Array.isArray(entry?.tickets?.[index]?.main) ? entry.tickets[index].main.length : 0);
      const specialSlotCount = TYPES[type]?.hasSpecial && Number.isInteger(detail?.special) ? 1 : 0;
      const totalSlotCount = Math.max(1, mainSlotCount + specialSlotCount);
      const hitCount = Number(detail?.mainHits || 0) + (detail?.specialHit ? 1 : 0);
      const hitPercent = (hitCount / totalSlotCount) * 100;
      return `<span class="predict-ticket-meta">| ${escapeHtml(algorithmLabel)} - ${escapeHtml(formatPredictionPercent(hitPercent / 100))}</span>`;
    }

    function formatPredictionHistoryTicketLabel(ticket, index) {
      const cloned = clonePredictionTicket(ticket);
      if (!cloned) return `Bộ ${index + 1}`;
      const isBao = String(cloned.playMode || "").trim().toLowerCase() === "bao";
      if (!isBao) return `Bộ ${index + 1}`;
      const baoLevel = cloned.baoLevel || cloned.main.length || "";
      return `Bộ ${index + 1} • Bao ${baoLevel}`.trim();
    }

    function formatPredictionHistoryTicketHtml(type, ticket, index, entry) {
      const cloned = clonePredictionTicket(ticket);
      if (!cloned) return "";
      const label = `<span class="predict-hit-label">${escapeHtml(formatPredictionHistoryTicketLabel(cloned, index))}:</span>`;
      const mainHtml = renderPredictionHistoryNumberList(cloned.main, entry);
      const metaHtml = formatPredictionHistoryTicketMeta(type, index, entry);
      if (type === "KENO") {
        return `${label}${mainHtml}${metaHtml}`;
      }
      if (TYPES[type]?.hasSpecial && Number.isInteger(cloned.special)) {
        return `${label}${mainHtml}<span class="predict-hit-divider">|</span><span class="predict-hit-label">ĐB</span>${renderPredictionHistoryNumberList([cloned.special], entry, { special: true })}${metaHtml}`;
      }
      return `${label}${mainHtml}${metaHtml}`;
    }

    function formatPredictionHistoryRankingLine(label, numbers, entry, { special = false } = {}) {
      const perRow = (entry?.type === "KENO" || TYPES[entry?.type]?.threeDigit) && !special ? 10 : 0;
      const html = renderPredictionHistoryNumberList(numbers, entry, { special, perRow });
      if (!html) return "";
      return `<div class="predict-history-line${perRow ? " predict-history-line-keno" : ""}"><strong>${escapeHtml(label)}:</strong> ${html}</div>`;
    }

    function formatPredictionHistoryPlainNumberRows(numbers, perRow = 0, type = "") {
      const values = (numbers || []).map(Number).filter(Number.isInteger).map(number => formatPredictNumber(number, type));
      if (!values.length) return "";
      if (!Number.isInteger(perRow) || perRow <= 0 || values.length <= perRow) {
        return values.join(" ");
      }
      const rows = [];
      for (let index = 0; index < values.length; index += perRow) {
        rows.push(values.slice(index, index + perRow).join(" "));
      }
      return rows.join("\n");
    }

    function formatPredictionHistoryActualDrawHtml(entry) {
      if (!entry?.resolved || !entry?.actualDraw) return "";
      if (entry.type === "KENO" && Array.isArray(entry.actualDraw.main) && entry.actualDraw.main.length) {
        const html = renderPredictionHistoryNumberList(entry.actualDraw.main, entry, { perRow: 10, highlight: false });
        return html ? `<div class="predict-history-line predict-history-line-keno"><strong>Kết quả thật:</strong> ${html}</div>` : "";
      }
      return `<div class="predict-history-line"><strong>Kết quả thật:</strong> ${escapeHtml(formatLiveHistoryDraw(entry.type, entry.actualDraw))}</div>`;
    }

    function formatPredictionHistoryTicketMetaPlainText(type, index, entry) {
      const rawSource = String(entry?.ticketSources?.[index] || "").trim().toLowerCase();
      const algorithmLabel = rawSource === "luan_so"
        ? "Luận Số"
        : rawSource === "gen_local"
        ? "AI GEN"
        : String(entry?.championLabel || entry?.modelLabel || entry?.strategyLabel || entry?.engineLabel || "AI Gen").trim();
      if (!algorithmLabel) return "";
      const detail = Array.isArray(entry?.resultSummary?.details) ? entry.resultSummary.details[index] : null;
      if (!entry?.resolved || !detail) {
        return ` | ${algorithmLabel} - ${getPredictionHistoryEntryStatus(entry).shortLabel}`;
      }
      const mainSlotCount = Array.isArray(detail?.main) ? detail.main.length : (Array.isArray(entry?.tickets?.[index]?.main) ? entry.tickets[index].main.length : 0);
      const specialSlotCount = TYPES[type]?.hasSpecial && Number.isInteger(detail?.special) ? 1 : 0;
      const totalSlotCount = Math.max(1, mainSlotCount + specialSlotCount);
      const hitCount = Number(detail?.mainHits || 0) + (detail?.specialHit ? 1 : 0);
      const hitPercent = (hitCount / totalSlotCount) * 100;
      return ` | ${algorithmLabel} - ${formatPredictionPercent(hitPercent / 100)}`;
    }

    function formatPredictionHistoryTicketPlainText(type, ticket, index, entry) {
      const cloned = clonePredictionTicket(ticket);
      if (!cloned) return "";
      const mainText = cloned.main.map(number => formatPredictNumber(number, type)).join(TYPES[type]?.threeDigit ? " | " : " ");
      const prefix = formatPredictionHistoryTicketLabel(cloned, index);
      const metaText = formatPredictionHistoryTicketMetaPlainText(type, index, entry);
      if (type === "KENO") {
        return `${prefix}: ${mainText}${metaText}`;
      }
      if (TYPES[type]?.hasSpecial && Number.isInteger(cloned.special)) {
        return `${prefix}: ${mainText} | ĐB ${formatPredictNumber(cloned.special, type)}${metaText}`;
      }
      return `${prefix}: ${mainText}${metaText}`;
    }

    function buildPredictionHistoryCopyText(entry) {
      if (!entry || typeof entry !== "object") return "";
      const titleParts = [entry.typeLabel || TYPES[entry.type]?.label || entry.type || "Không rõ loại"];
      if (entry.predictedKy) titleParts.push(`Kỳ ${formatLiveKy(entry.predictedKy)}`);
      const headerLines = [
        titleParts.join(" • "),
        `Dự đoán: ${titleParts.join(" • ")}`,
        `Thời gian: ${formatPredictionHistoryTime(entry.createdAt) || "Không rõ"}`,
      ];
      const ticketLines = [];
      if (Array.isArray(entry.tickets) && entry.tickets.length) {
        entry.tickets.forEach((ticket, index) => {
          const ticketText = formatPredictionHistoryTicketPlainText(entry.type, ticket, index, entry);
          if (ticketText) ticketLines.push(ticketText);
        });
      }
      const topLines = [];
      if (Array.isArray(entry.topMainRanking) && entry.topMainRanking.length) {
        const topRows = formatPredictionHistoryPlainNumberRows(entry.topMainRanking, 10, entry.type);
        const topParts = topRows.split("\n").filter(Boolean);
        if (topParts.length) {
          topLines.push("Top số:");
          topParts.forEach(part => topLines.push(part));
        }
      }
      if (TYPES[entry.type]?.hasSpecial && Array.isArray(entry.topSpecialRanking) && entry.topSpecialRanking.length) {
        const specialRows = formatPredictionHistoryPlainNumberRows(entry.topSpecialRanking, 10, entry.type);
        const specialParts = specialRows.split("\n").filter(Boolean);
        if (specialParts.length) {
          topLines.push(`Top ĐB: ${specialParts.shift()}`);
          specialParts.forEach(part => topLines.push(part));
        }
      }
      const sections = [
        headerLines.join("\n"),
        ticketLines.join("\n"),
        topLines.join("\n"),
      ].filter(section => String(section || "").trim());
      return sections.join("\n\n");
    }

    async function copyTextToClipboard(text) {
      const value = String(text || "").trim();
      if (!value) return false;
      try {
        if (navigator.clipboard?.writeText) {
          await navigator.clipboard.writeText(value);
          return true;
        }
      } catch {}
      try {
        const textarea = document.createElement("textarea");
        textarea.value = value;
        textarea.setAttribute("readonly", "readonly");
        textarea.style.position = "fixed";
        textarea.style.top = "-9999px";
        textarea.style.left = "-9999px";
        document.body.appendChild(textarea);
        textarea.select();
        textarea.setSelectionRange(0, textarea.value.length);
        const copied = document.execCommand("copy");
        textarea.remove();
        return !!copied;
      } catch {
        return false;
      }
    }

    function formatPredictionHistorySummary(type, entry) {
      const summary = entry?.resultSummary;
      if (!summary || typeof summary !== "object") return "Chưa có dữ liệu đối chiếu.";
      const predictedSize = Array.isArray(entry?.tickets?.[0]?.main)
        ? entry.tickets[0].main.length
        : (TYPES[type]?.mainCount || 0);
      const isBaoMode = getPredictionHistoryEntryPlayMode(entry) === "bao";
      const unitLabel = isBaoMode ? "bộ" : "vé";
      const parts = [];
      if (Number(summary.bestMainHits || 0) > 0) {
        parts.push(`Tốt nhất ${summary.bestMainHits}/${predictedSize} số`);
      }
      if (Number(summary.avgMainHits || 0) > 0) {
        parts.push(`TB ${Number(summary.avgMainHits || 0).toFixed(2)} số/${unitLabel}`);
      }
      if (Number(summary.thresholdTicketHits || 0) > 0) {
        parts.push(`${summary.thresholdTicketHits} ${unitLabel} đạt ngưỡng`);
      }
      if (!isBaoMode && Number(summary.prizeTicketHits || 0) > 0) {
        parts.push(`${summary.prizeTicketHits} vé có giải`);
      }
      if (TYPES[type]?.hasSpecial && Number(summary.specialHits || 0) > 0) {
        parts.push(`${summary.specialHits} ${unitLabel} trúng ĐB`);
      }
      return parts.length ? parts.join(" • ") : "Chưa có số khớp nổi bật.";
    }

    function formatPredictionHistoryHitRateLine(type, entry) {
      const buckets = Array.isArray(entry?.resultSummary?.hitRateBuckets) ? entry.resultSummary.hitRateBuckets : [];
      if (!buckets.length) return "";
      const parts = buckets.map(bucket => {
        const hitLabel = `${bucket.hitCount} số`;
        const rateText = formatPredictionPercent(bucket.rate);
        const trendText = formatPredictionTrendHtml(bucket.trend);
        return `${escapeHtml(hitLabel)} ${escapeHtml(rateText)} ${trendText}`.trim();
      });
      return parts.length ? parts.join(" • ") : "";
    }

    function formatPredictionHistoryTopRateLine(type, entry) {
      const topSummary = entry?.resultSummary?.topHitSummary;
      if (!topSummary || typeof topSummary !== "object") return "";
      const main = topSummary.topMain || {};
      const mainText = main.total
        ? `${escapeHtml(`Top số ${main.matched}/${main.total} = ${formatPredictionPercent(main.rate)}`)} ${formatPredictionTrendHtml(main.trend)}`.trim()
        : "";
      const special = topSummary.topSpecial || {};
      const specialText = TYPES[type]?.hasSpecial && special.total
        ? `${escapeHtml(`Top ĐB ${special.matched}/${special.total} = ${formatPredictionPercent(special.rate)}`)} ${formatPredictionTrendHtml(special.trend)}`.trim()
        : "";
      return [mainText, specialText].filter(Boolean).join(" • ");
    }

    async function refreshKenoPredictionDataForHistory({ silent = true } = {}) {
      const nowValue = new Date();
      const currentDataset = buildPredictionResultDataset("KENO");
      const repairLookbackDays = getKenoPredictionHistoryRepairLookbackDays(currentDataset, nowValue);
      const nextFeed = await fetchLiveHistory("KENO", "all", {
        force: true,
        silent,
        repair: repairLookbackDays > 0,
        recentDays: repairLookbackDays > 0 ? repairLookbackDays : null,
      });
      if (nextFeed?.repairAttempted && Array.isArray(nextFeed.repairErrors) && nextFeed.repairErrors.length) {
        throw new Error(nextFeed.repairErrors.join(" • "));
      }
      const predictionLogsBeforeReconcile = getPredictionLogsSignature(store.predictionLogs?.KENO || []);
      reconcilePredictionLogsForType("KENO");
      if (getPredictionLogsSignature(store.predictionLogs?.KENO || []) !== predictionLogsBeforeReconcile) {
        saveStore();
      }
    }

    async function refreshPredictionHistoryType(type, { silent = true } = {}) {
      const normalizedType = normalizePredictionHistoryType(type);
      if (!PREDICTION_LOG_TYPES.includes(normalizedType)) return;
      if (normalizedType === "KENO") {
        await refreshKenoPredictionDataForHistory({ silent });
        return;
      }
      await fetchLiveHistory(normalizedType, "all", { force: true, silent });
      const before = getPredictionLogsSignature(store.predictionLogs?.[normalizedType] || []);
      reconcilePredictionLogsForType(normalizedType);
      if (getPredictionLogsSignature(store.predictionLogs?.[normalizedType] || []) !== before) {
        saveStore();
      }
    }

    function startPredictionHistoryRefresh(type, { silent = true } = {}) {
      const normalizedType = normalizePredictionHistoryType(type);
      const refreshToken = ++predictionHistoryRefreshToken;
      predictionHistoryLoading = true;
      predictionHistoryLoadingType = normalizedType;
      predictionHistoryLoadingError = "";
      setPredictionHistoryRefreshButtonBusy(true);
      renderPredictionHistoryPanel();
      (async () => {
        try {
          await refreshPredictionHistoryType(normalizedType, { silent });
          if (refreshToken !== predictionHistoryRefreshToken) return;
          predictionHistoryLoading = false;
          predictionHistoryLoadingType = "";
          predictionHistoryLoadingError = "";
        } catch (error) {
          if (refreshToken !== predictionHistoryRefreshToken) return;
          predictionHistoryLoading = false;
          predictionHistoryLoadingType = normalizedType;
          predictionHistoryLoadingError = String(error?.message || error || "Không tải được lịch sử.");
        } finally {
          if (refreshToken !== predictionHistoryRefreshToken) return;
          setPredictionHistoryRefreshButtonBusy(false);
          renderPredictionHistoryPanel();
        }
      })();
    }

    function setPredictionHistoryRefreshButtonBusy(isBusy) {
      const btn = document.getElementById("predictionHistoryRefreshBtn");
      if (!btn) return;
      const originalText = btn.dataset.originalText || String(btn.textContent || "Cập Nhật");
      btn.dataset.originalText = originalText;
      btn.disabled = !!isBusy;
      btn.textContent = isBusy ? "Đang Cập Nhật..." : originalText;
    }

    function collectPredictionHistoryEntries(filterType = "KENO", rangeKey = "all", playModeKey = "normal", baoLevelKey = "all", predictionMode = PREDICTION_MODE_NORMAL) {
      const selectedType = normalizePredictionHistoryType(filterType);
      const selectedRange = normalizePredictionHistoryRange(rangeKey);
      const selectedPredictionMode = normalizePredictionMode(predictionMode);
      const selectedPlayMode = hasPredictBaoMode(selectedType)
        ? normalizePredictionHistoryPlayMode(playModeKey)
        : "normal";
      const selectedBaoLevel = selectedPlayMode === "bao"
        ? normalizePredictionHistoryBaoLevel(baoLevelKey)
        : "all";
      if (!PREDICTION_LOG_TYPES.includes(selectedType)) return [];
      const groupedRows = new Map();
      ensurePredictionLogBucket(selectedType).forEach(entry => {
        const normalizedEntry = {
          type: selectedType,
          typeLabel: TYPES[selectedType]?.label || selectedType,
          ...entry,
        };
        if (getPredictionEntryMode(normalizedEntry) !== selectedPredictionMode) return;
        const entryPlayMode = getPredictionHistoryEntryPlayMode(normalizedEntry);
        if (entryPlayMode !== selectedPlayMode) return;
        const normalizedKy = normalizeKy(normalizedEntry?.predictedKy);
        const dedupeKeyParts = [
          normalizedKy || String(normalizedEntry?.id || normalizedEntry?.createdAt || Math.random()),
          entryPlayMode,
        ];
        if (entryPlayMode === "bao") {
          dedupeKeyParts.push(String(getPredictionEntryBaoLevelForMetrics(normalizedEntry) || 0));
          dedupeKeyParts.push(String(getPredictionHistoryEntryBundleCount(normalizedEntry) || 0));
        }
        const dedupeKey = dedupeKeyParts.join("::");
        const nextTicketCount = Array.isArray(normalizedEntry?.tickets) ? normalizedEntry.tickets.length : 0;
        const current = groupedRows.get(dedupeKey);
        if (!current) {
          groupedRows.set(dedupeKey, normalizedEntry);
          return;
        }
        const currentResolved = !!current?.resolved;
        const nextResolved = !!normalizedEntry?.resolved;
        if (nextResolved && !currentResolved) {
          groupedRows.set(dedupeKey, normalizedEntry);
          return;
        }
        if (currentResolved && !nextResolved) {
          return;
        }
        const currentTicketCount = Array.isArray(current?.tickets) ? current.tickets.length : 0;
        if (nextTicketCount > currentTicketCount) {
          groupedRows.set(dedupeKey, normalizedEntry);
          return;
        }
        if (nextTicketCount < currentTicketCount) {
          return;
        }
        const currentTime = Date.parse(current?.createdAt || 0) || 0;
        const nextTime = Date.parse(normalizedEntry?.createdAt || 0) || 0;
        if (nextTime >= currentTime) groupedRows.set(dedupeKey, normalizedEntry);
      });
      const sortedEntries = [...groupedRows.values()]
        .filter(entry => isPredictionHistoryEntryInRange(entry, selectedRange))
        .filter(entry => selectedBaoLevel === "all" || getPredictionEntryBaoLevelForMetrics(entry) === Number(selectedBaoLevel))
        .sort((a, b) => {
        const aTime = Date.parse(a?.createdAt || 0) || 0;
        const bTime = Date.parse(b?.createdAt || 0) || 0;
        if (aTime !== bTime) return bTime - aTime;
        return kySortValue(b?.predictedKy) - kySortValue(a?.predictedKy);
      });
      return selectedRange === "2k" ? sortedEntries.slice(0, 2) : sortedEntries;
    }

    function getPredictionHistoryEntryKey(entry) {
      if (!entry || typeof entry !== "object") return "";
      return [
        getPredictionEntryMode(entry),
        normalizePredictionHistoryType(entry.type || predictionHistorySelectedType),
        normalizeKy(entry.predictedKy) || "",
        String(entry.createdAt || ""),
      ].join("::");
    }

    function getPredictionHistoryCollapsedTicketLimit(type) {
      if (type === "KENO") return 5;
      return 6;
    }

    function shouldCollapsePredictionHistoryEntry(entry) {
      const ticketCount = Array.isArray(entry?.tickets) ? entry.tickets.length : 0;
      const hasSpecialTop = TYPES[entry?.type]?.hasSpecial && Array.isArray(entry?.topSpecialRanking) && entry.topSpecialRanking.length;
      return ticketCount > getPredictionHistoryCollapsedTicketLimit(entry?.type) || hasSpecialTop || entry?.type === "KENO";
    }

    function syncPredictionHistoryBodyScroll(isOpen = predictionHistoryPanelOpen || vipPredictionHistoryPanelOpen) {
      if (isOpen) {
        document.body.style.overflow = "hidden";
        document.documentElement.style.overflow = "hidden";
        return;
      }
      document.body.style.overflow = "";
      document.documentElement.style.overflow = "";
    }

    function clampPredictionHistoryCurrentIndex(totalEntries = 0) {
      const total = Math.max(0, Number(totalEntries || 0));
      if (!Number.isInteger(predictionHistoryCurrentIndex) || predictionHistoryCurrentIndex < 0) {
        predictionHistoryCurrentIndex = 0;
      }
      if (!total) {
        predictionHistoryCurrentIndex = 0;
        return 0;
      }
      if (predictionHistoryCurrentIndex > total - 1) {
        predictionHistoryCurrentIndex = total - 1;
      }
      return predictionHistoryCurrentIndex;
    }

    function renderPredictionHistoryNavigator(totalEntries = 0) {
      const prevBtn = document.getElementById("predictionHistoryPrevBtn");
      const nextBtn = document.getElementById("predictionHistoryNextBtn");
      const positionEl = document.getElementById("predictionHistoryPosition");
      const total = Math.max(0, Number(totalEntries || 0));
      const currentIndex = clampPredictionHistoryCurrentIndex(total);
      if (positionEl) {
        positionEl.textContent = total ? `${currentIndex + 1} / ${total}` : "0 / 0";
      }
      if (prevBtn) prevBtn.disabled = total <= 1 || currentIndex <= 0;
      if (nextBtn) nextBtn.disabled = total <= 1 || currentIndex >= total - 1;
    }

    function renderPredictionHistoryEntryHtml(entry, entryIndex) {
      const statusMeta = getPredictionHistoryEntryStatus(entry);
      const statusClass = statusMeta.className;
      const statusText = statusMeta.label;
      const countdownState = buildPredictionHistoryCountdownState(entry, new Date());
      const titleParts = [entry.typeLabel];
      if (entry.predictedKy) titleParts.push(`Kỳ ${formatLiveKy(entry.predictedKy)}`);
      const createdAtText = formatPredictionHistoryTime(entry.createdAt) || "Không rõ";
      const engineParts = [
        String(entry.engineLabel || "").trim(),
        String(entry.engineKey || "").trim().toLowerCase() === "both" ? String(entry.riskModeLabel || getPredictRiskModeMeta(entry.riskMode || "balanced").label).trim() : "",
        String(entry.championLabel || entry.modelLabel || "").trim(),
      ].filter(Boolean);
      const topMainRanking = Array.isArray(entry.topMainRanking)
        ? entry.topMainRanking
        : [];
      const topSpecialRanking = Array.isArray(entry.topSpecialRanking)
        ? entry.topSpecialRanking
        : [];
      const infoCards = [
        `<div class="predict-history-info-chip"><span class="predict-history-info-label">Thời gian</span><strong class="predict-history-info-value">${escapeHtml(createdAtText)}</strong></div>`,
        engineParts.length
          ? `<div class="predict-history-info-chip"><span class="predict-history-info-label">AI</span><strong class="predict-history-info-value">${escapeHtml(engineParts.join(" • "))}</strong></div>`
          : "",
      ].filter(Boolean).join("");
      const topMainHtml = topMainRanking.length
        ? renderPredictionHistoryNumberList(topMainRanking, entry, { perRow: entry.type === "KENO" ? 10 : 0 })
        : "";
      const topSpecialHtml = TYPES[entry.type]?.hasSpecial && topSpecialRanking.length
        ? renderPredictionHistoryNumberList(topSpecialRanking, entry, { special: true })
        : "";
      const topBlocks = [
        topMainHtml
          ? `
            <div class="predict-history-stat-card">
              <div class="predict-history-stat-label">Top số</div>
              <div class="predict-history-stat-value">${topMainHtml}</div>
            </div>
          `
          : "",
        topSpecialHtml
          ? `
            <div class="predict-history-stat-card">
              <div class="predict-history-stat-label">Top ĐB</div>
              <div class="predict-history-stat-value">${topSpecialHtml}</div>
            </div>
          `
          : "",
      ].filter(Boolean).join("");
      const topBlockCount = [topMainHtml, topSpecialHtml].filter(Boolean).length;
      const ticketSlice = Array.isArray(entry.tickets)
        ? entry.tickets
        : [];
      const ticketLines = ticketSlice.length
        ? ticketSlice.map((ticket, index) => {
            const html = formatPredictionHistoryTicketHtml(entry.type, ticket, index, entry);
            return html ? `<div class="predict-history-ticket">${html}</div>` : "";
          }).filter(Boolean).join("")
        : "";
      const actualDrawLine = formatPredictionHistoryActualDrawHtml(entry);
      const actualMetaLine = entry.resolved && (entry.actualKy || entry.resolvedAt)
        ? `<div class="predict-history-note">${escapeHtml([entry.actualKy ? `Đã ra ${formatLiveKy(entry.actualKy)}` : "", entry.resolvedAt ? `Đối chiếu lúc ${formatPredictionHistoryTime(entry.resolvedAt)}` : ""].filter(Boolean).join(" • "))}</div>`
        : "";
      const summaryText = entry.resolved ? formatPredictionHistorySummary(entry.type, entry) : "";
      const hitRateText = entry.resolved ? formatPredictionHistoryHitRateLine(entry.type, entry) : "";
      const topRateText = entry.resolved ? formatPredictionHistoryTopRateLine(entry.type, entry) : "";
      const rateLabel = getPredictionHistoryEntryPlayMode(entry) === "bao" ? "Tỷ lệ bộ" : "Tỷ lệ vé";
      const missingNote = !entry.resolved && entry.resultMissingData
        ? `<div class="predict-history-note predict-history-note-warning">Đã rà canonical history nhưng chưa tìm thấy kết quả thật cho kỳ này.</div>`
        : "";
      return `
        <article class="predict-history-item">
          <div class="predict-history-top">
            <div class="predict-history-type">${escapeHtml(titleParts.join(" • "))}</div>
            <div class="predict-history-side">
              <button
                type="button"
                class="predict-history-copy-btn"
                data-prediction-history-copy="${entryIndex}"
                title="Chép nội dung kỳ này"
                aria-label="Chép nội dung kỳ này"
              >⧉</button>
              ${countdownState ? `
                <div class="predict-history-countdown-box">
                  <span class="predict-history-countdown-label">Kỳ tiếp theo</span>
                  <span class="predict-history-countdown-ky">${escapeHtml(countdownState.kyText || "Đang chờ")}</span>
                  <span class="predict-history-countdown-prefix">Còn :</span>
                  <span class="predict-history-countdown-time">${escapeHtml(`${countdownState.countdownText}s`)}</span>
                </div>
              ` : ""}
              <span class="predict-history-status ${statusClass}">${escapeHtml(statusText)}</span>
            </div>
          </div>
          ${infoCards ? `<div class="predict-history-info-row">${infoCards}</div>` : ""}
          ${topBlocks ? `
            <div class="predict-history-section predict-history-top-section">
              <div class="predict-history-top-grid${topBlockCount <= 1 ? " is-single" : ""}">${topBlocks}</div>
            </div>
          ` : ""}
          <div class="predict-history-section predict-history-ticket-section">
            <div class="predict-history-section-title">Bộ số dự đoán</div>
            <div class="predict-history-tickets">${ticketLines || `<div class="predict-history-note">Không có bộ số để hiển thị.</div>`}</div>
            ${missingNote}
          </div>
          ${entry.resolved ? `
            <div class="predict-history-section predict-history-actual">
              <div class="predict-history-section-title">Đối chiếu</div>
              ${actualDrawLine}${actualMetaLine}
            </div>
          ` : ""}
          ${entry.resolved ? `
            <div class="predict-history-section predict-history-summary">
              <div class="predict-history-section-title">Tổng kết</div>
              <div class="predict-history-line"><strong>Tóm tắt:</strong> ${escapeHtml(summaryText)}</div>
              ${hitRateText ? `<div class="predict-history-line"><strong>${escapeHtml(rateLabel)}:</strong> ${hitRateText}</div>` : ""}
              ${topRateText ? `<div class="predict-history-line"><strong>Tỷ lệ top:</strong> ${topRateText}</div>` : ""}
            </div>
          ` : ""}
        </article>
      `;
    }

    // ---abc--- Prediction History / Modal Rendering ---
    function renderPredictionHistoryPanel() {
      const overlay = document.getElementById("predictionHistoryOverlay");
      const panel = document.getElementById("predictionHistoryPanel");
      const list = document.getElementById("predictionHistoryList");
      const countEl = document.getElementById("predictionHistoryCount");
      const toggleBtn = document.getElementById("predictionHistoryToggleBtn");
      if (!overlay || !panel || !list || !countEl) return;
      overlay.hidden = !predictionHistoryPanelOpen;
      syncPredictionHistoryBodyScroll(predictionHistoryPanelOpen || vipPredictionHistoryPanelOpen);
      if (toggleBtn) toggleBtn.classList.toggle("is-active", predictionHistoryPanelOpen);
      predictionHistorySelectedType = normalizePredictionHistoryType(predictionHistorySelectedType);
      predictionHistorySelectedRange = normalizePredictionHistoryRange(predictionHistorySelectedRange);
      predictionHistorySelectedPlayMode = hasPredictBaoMode(predictionHistorySelectedType)
        ? normalizePredictionHistoryPlayMode(predictionHistorySelectedPlayMode)
        : "normal";
      renderPredictionHistoryTypeTabs();
      renderPredictionHistoryRangeTabs();
      renderPredictionHistoryPlayModeTabs(predictionHistorySelectedType);
      renderPredictionHistoryBaoLevelFilter(predictionHistorySelectedType, predictionHistorySelectedPlayMode);
      const selectedType = predictionHistorySelectedType;
      const selectedLabel = PREDICTION_HISTORY_TYPES.find(item => item.value === selectedType)?.label || selectedType;
      const selectedPlayMode = predictionHistorySelectedPlayMode;
      const playModeLabel = selectedPlayMode === "bao" ? "bao số" : "vé thường";
      const isHistoryLoading = predictionHistoryLoading && predictionHistoryLoadingType === selectedType;
      const hasHistoryLoadingError = !isHistoryLoading && predictionHistoryLoadingType === selectedType && !!predictionHistoryLoadingError;
      const loadingNoticeHtml = isHistoryLoading
        ? `<div class="predict-history-empty">Đang tải lịch sử...</div>`
        : "";
      const loadingErrorHtml = hasHistoryLoadingError
        ? `<div class="predict-history-empty">${escapeHtml(predictionHistoryLoadingError)}</div>`
        : "";
      const metricsChanged = refreshResolvedPredictionSummaries(selectedType);
      if (metricsChanged) saveStore();
      const entries = collectPredictionHistoryEntries(
        selectedType,
        predictionHistorySelectedRange,
        selectedPlayMode,
        predictionHistorySelectedBaoLevel,
        PREDICTION_MODE_NORMAL
      );
      const currentIndex = clampPredictionHistoryCurrentIndex(entries.length);
      renderPredictionHistoryNavigator(entries.length);
      countEl.textContent = isHistoryLoading
        ? (entries.length ? `${formatLiveSyncCount(entries.length)} bản ghi • đang tải...` : "Đang tải...")
        : `${formatLiveSyncCount(entries.length)} bản ghi`;
      if (!predictionHistoryPanelOpen) return;
      if (isHistoryLoading && !entries.length) {
        list.innerHTML = loadingNoticeHtml;
        return;
      }
      if (!entries.length) {
        list.innerHTML = loadingErrorHtml || (PREDICTION_LOG_TYPES.includes(selectedType)
          ? `<div class="predict-history-empty">Chưa có lịch sử dự đoán ${escapeHtml(playModeLabel)} cho ${escapeHtml(selectedLabel)}. Sau mỗi lần bấm Dự đoán, bộ số của loại này sẽ tự lưu ở đây.</div>`
          : `<div class="predict-history-empty">Chưa có lịch sử dự đoán cho ${escapeHtml(selectedLabel)}. Loại này chưa có pipeline lưu log dự đoán nên hiện chỉ hiển thị trạng thái rỗng.</div>`);
        return;
      }
      const currentEntry = entries[currentIndex] || null;
      list.innerHTML = `${loadingNoticeHtml}${loadingErrorHtml}${currentEntry ? renderPredictionHistoryEntryHtml(currentEntry, currentIndex) : ""}`;
    }

    function togglePredictionHistoryPanel(forceOpen = null) {
      const nextOpen = typeof forceOpen === "boolean" ? forceOpen : !predictionHistoryPanelOpen;
      if (nextOpen) {
        const overlay = document.getElementById("predictionHistoryOverlay");
        const list = document.getElementById("predictionHistoryList");
        const nextType = getPreferredPredictionHistoryType();
        predictionHistorySelectedType = nextType;
        predictionHistoryCurrentIndex = 0;
        predictionHistoryLoadingError = "";
        predictionHistoryPanelOpen = true;
        if (overlay) overlay.scrollTop = 0;
        if (list) list.scrollTop = 0;
        renderPredictionHistoryPanel();
        startPredictionHistoryRefresh(nextType, { silent: true });
        return;
      }
      predictionHistoryRefreshToken += 1;
      predictionHistoryLoading = false;
      predictionHistoryLoadingType = "";
      predictionHistoryLoadingError = "";
      setPredictionHistoryRefreshButtonBusy(false);
      predictionHistoryPanelOpen = false;
      renderPredictionHistoryPanel();
    }

    function renderVipPredictionHistoryTypeTabs() {
      const tabsEl = document.getElementById("vipPredictionHistoryTypeTabs");
      if (!tabsEl) return;
      const selectedType = normalizePredictionHistoryType(vipPredictionHistorySelectedType);
      vipPredictionHistorySelectedType = selectedType;
      tabsEl.innerHTML = PREDICTION_HISTORY_TYPES.map(item => {
        const isActive = item.value === selectedType;
        return `<button type="button" class="predict-history-type-tab${isActive ? " is-active" : ""}" data-vip-prediction-history-type="${item.value}" role="tab" aria-selected="${isActive ? "true" : "false"}">${escapeHtml(item.label)}</button>`;
      }).join("");
    }

    function renderVipPredictionHistoryRangeTabs() {
      const tabsEl = document.getElementById("vipPredictionHistoryRangeTabs");
      if (!tabsEl) return;
      const selectedRange = normalizePredictionHistoryRange(vipPredictionHistorySelectedRange);
      vipPredictionHistorySelectedRange = selectedRange;
      const items = [
        { value: "2k", label: "2 Kỳ" },
        { value: "today", label: "Hôm Nay" },
        { value: "3d", label: "3 Ngày" },
        { value: "7d", label: "7 Ngày" },
        { value: "all", label: "Tất Cả" },
      ];
      tabsEl.innerHTML = items.map(item => {
        const isActive = item.value === selectedRange;
        return `<button type="button" class="predict-history-range-tab${isActive ? " is-active" : ""}" data-vip-prediction-history-range="${item.value}" role="tab" aria-selected="${isActive ? "true" : "false"}">${escapeHtml(item.label)}</button>`;
      }).join("");
    }

    function renderVipPredictionHistoryPlayModeTabs(typeKey = vipPredictionHistorySelectedType) {
      const tabsEl = document.getElementById("vipPredictionHistoryPlayModeTabs");
      if (!tabsEl) return;
      const normalizedType = normalizePredictionHistoryType(typeKey);
      if (!hasPredictBaoMode(normalizedType)) {
        vipPredictionHistorySelectedPlayMode = "normal";
      }
      const selectedPlayMode = hasPredictBaoMode(normalizedType)
        ? normalizePredictionHistoryPlayMode(vipPredictionHistorySelectedPlayMode)
        : "normal";
      vipPredictionHistorySelectedPlayMode = selectedPlayMode;
      const items = hasPredictBaoMode(normalizedType)
        ? [
            { value: "normal", label: "Chơi Thường" },
            { value: "bao", label: "Chơi Bao" },
          ]
        : [{ value: "normal", label: "Chơi Thường" }];
      tabsEl.innerHTML = items.map(item => {
        const isActive = item.value === selectedPlayMode;
        return `<button type="button" class="predict-history-playmode-tab${isActive ? " is-active" : ""}" data-vip-prediction-history-playmode="${item.value}" role="tab" aria-selected="${isActive ? "true" : "false"}">${escapeHtml(item.label)}</button>`;
      }).join("");
    }

    function renderVipPredictionHistoryBaoLevelFilter(typeKey = vipPredictionHistorySelectedType, playModeKey = vipPredictionHistorySelectedPlayMode) {
      const wrapEl = document.getElementById("vipPredictionHistoryBaoLevelFilterWrap");
      const selectEl = document.getElementById("vipPredictionHistoryBaoLevelSelect");
      if (!wrapEl || !selectEl) return;
      const normalizedType = normalizePredictionHistoryType(typeKey);
      const selectedPlayMode = normalizePredictionHistoryPlayMode(playModeKey);
      const shouldShow = hasPredictBaoMode(normalizedType) && selectedPlayMode === "bao";
      if (!shouldShow) {
        vipPredictionHistorySelectedBaoLevel = "all";
        wrapEl.hidden = true;
        selectEl.innerHTML = `<option value="all">Tất cả bậc</option>`;
        selectEl.value = "all";
        return;
      }
      const options = getPredictionHistoryBaoLevelOptions(normalizedType, PREDICTION_MODE_VIP);
      const normalizedSelectedValue = normalizePredictionHistoryBaoLevel(vipPredictionHistorySelectedBaoLevel);
      const nextSelectedValue = normalizedSelectedValue !== "all" && options.includes(Number(normalizedSelectedValue))
        ? normalizedSelectedValue
        : "all";
      vipPredictionHistorySelectedBaoLevel = nextSelectedValue;
      selectEl.innerHTML = [`<option value="all">Tất cả bậc</option>`, ...options.map(value => `<option value="${value}">${escapeHtml(`Bao ${value}`)}</option>`)].join("");
      selectEl.value = nextSelectedValue;
      wrapEl.hidden = false;
    }

    function clampVipPredictionHistoryCurrentIndex(totalEntries = 0) {
      const total = Math.max(0, Number(totalEntries || 0));
      if (!Number.isInteger(vipPredictionHistoryCurrentIndex) || vipPredictionHistoryCurrentIndex < 0) vipPredictionHistoryCurrentIndex = 0;
      if (!total) {
        vipPredictionHistoryCurrentIndex = 0;
        return 0;
      }
      if (vipPredictionHistoryCurrentIndex > total - 1) vipPredictionHistoryCurrentIndex = total - 1;
      return vipPredictionHistoryCurrentIndex;
    }

    function renderVipPredictionHistoryNavigator(totalEntries = 0) {
      const prevBtn = document.getElementById("vipPredictionHistoryPrevBtn");
      const nextBtn = document.getElementById("vipPredictionHistoryNextBtn");
      const positionEl = document.getElementById("vipPredictionHistoryPosition");
      const total = Math.max(0, Number(totalEntries || 0));
      const currentIndex = clampVipPredictionHistoryCurrentIndex(total);
      if (positionEl) positionEl.textContent = total ? `${currentIndex + 1} / ${total}` : "0 / 0";
      if (prevBtn) prevBtn.disabled = total <= 1 || currentIndex <= 0;
      if (nextBtn) nextBtn.disabled = total <= 1 || currentIndex >= total - 1;
    }

    function renderVipPredictionHistoryPanel() {
      const overlay = document.getElementById("vipPredictionHistoryOverlay");
      const panel = document.getElementById("vipPredictionHistoryPanel");
      const list = document.getElementById("vipPredictionHistoryList");
      const countEl = document.getElementById("vipPredictionHistoryCount");
      const toggleBtn = document.getElementById("vipPredictionHistoryToggleBtn");
      if (!overlay || !panel || !list || !countEl) return;
      overlay.hidden = !vipPredictionHistoryPanelOpen;
      syncPredictionHistoryBodyScroll(vipPredictionHistoryPanelOpen || predictionHistoryPanelOpen);
      if (toggleBtn) toggleBtn.classList.toggle("is-active", vipPredictionHistoryPanelOpen);
      vipPredictionHistorySelectedType = normalizePredictionHistoryType(vipPredictionHistorySelectedType);
      vipPredictionHistorySelectedRange = normalizePredictionHistoryRange(vipPredictionHistorySelectedRange);
      vipPredictionHistorySelectedPlayMode = hasPredictBaoMode(vipPredictionHistorySelectedType)
        ? normalizePredictionHistoryPlayMode(vipPredictionHistorySelectedPlayMode)
        : "normal";
      renderVipPredictionHistoryTypeTabs();
      renderVipPredictionHistoryRangeTabs();
      renderVipPredictionHistoryPlayModeTabs(vipPredictionHistorySelectedType);
      renderVipPredictionHistoryBaoLevelFilter(vipPredictionHistorySelectedType, vipPredictionHistorySelectedPlayMode);
      const selectedType = vipPredictionHistorySelectedType;
      const selectedLabel = PREDICTION_HISTORY_TYPES.find(item => item.value === selectedType)?.label || selectedType;
      const selectedPlayMode = vipPredictionHistorySelectedPlayMode;
      const playModeLabel = selectedPlayMode === "bao" ? "bao số" : "vé thường";
      const isHistoryLoading = vipPredictionHistoryLoading && vipPredictionHistoryLoadingType === selectedType;
      const hasHistoryLoadingError = !isHistoryLoading && vipPredictionHistoryLoadingType === selectedType && !!vipPredictionHistoryLoadingError;
      const loadingNoticeHtml = isHistoryLoading ? `<div class="predict-history-empty">Đang tải lịch sử Vip...</div>` : "";
      const loadingErrorHtml = hasHistoryLoadingError ? `<div class="predict-history-empty">${escapeHtml(vipPredictionHistoryLoadingError)}</div>` : "";
      const metricsChanged = refreshResolvedPredictionSummaries(selectedType);
      if (metricsChanged) saveStore();
      const entries = collectPredictionHistoryEntries(selectedType, vipPredictionHistorySelectedRange, selectedPlayMode, vipPredictionHistorySelectedBaoLevel, PREDICTION_MODE_VIP);
      const currentIndex = clampVipPredictionHistoryCurrentIndex(entries.length);
      renderVipPredictionHistoryNavigator(entries.length);
      countEl.textContent = isHistoryLoading ? (entries.length ? `${formatLiveSyncCount(entries.length)} bản ghi • đang tải...` : "Đang tải...") : `${formatLiveSyncCount(entries.length)} bản ghi`;
      if (!vipPredictionHistoryPanelOpen) return;
      if (isHistoryLoading && !entries.length) {
        list.innerHTML = loadingNoticeHtml;
        return;
      }
      if (!entries.length) {
        list.innerHTML = loadingErrorHtml || `<div class="predict-history-empty">Chưa có lịch sử dự đoán Vip ${escapeHtml(playModeLabel)} cho ${escapeHtml(selectedLabel)}. Sau mỗi lần bấm Dự đoán Vip, bộ số của loại này sẽ tự lưu ở đây.</div>`;
        return;
      }
      const currentEntry = entries[currentIndex] || null;
      list.innerHTML = `${loadingNoticeHtml}${loadingErrorHtml}${currentEntry ? renderPredictionHistoryEntryHtml(currentEntry, currentIndex) : ""}`;
    }

    function setVipPredictionHistoryRefreshButtonBusy(isBusy) {
      const btn = document.getElementById("vipPredictionHistoryRefreshBtn");
      if (!btn) return;
      btn.disabled = !!isBusy;
      btn.classList.toggle("is-busy", !!isBusy);
      btn.textContent = isBusy ? "Đang tải..." : "Cập Nhật";
    }

    async function startVipPredictionHistoryRefresh(typeKey = vipPredictionHistorySelectedType, { silent = true } = {}) {
      const normalizedType = normalizePredictionHistoryType(typeKey);
      if (!PREDICTION_LOG_TYPES.includes(normalizedType)) return;
      const refreshToken = ++vipPredictionHistoryRefreshToken;
      vipPredictionHistoryLoading = true;
      vipPredictionHistoryLoadingType = normalizedType;
      vipPredictionHistoryLoadingError = "";
      setVipPredictionHistoryRefreshButtonBusy(true);
      renderVipPredictionHistoryPanel();
      try {
        await startPredictionHistoryRefresh(normalizedType, { silent: true });
        if (refreshToken !== vipPredictionHistoryRefreshToken) return;
        vipPredictionHistoryLoading = false;
        vipPredictionHistoryLoadingType = "";
        vipPredictionHistoryLoadingError = "";
      } catch (error) {
        if (refreshToken !== vipPredictionHistoryRefreshToken) return;
        vipPredictionHistoryLoading = false;
        vipPredictionHistoryLoadingType = normalizedType;
        vipPredictionHistoryLoadingError = String(error?.message || error || "Không tải được lịch sử Vip.");
      } finally {
        if (refreshToken !== vipPredictionHistoryRefreshToken) return;
        setVipPredictionHistoryRefreshButtonBusy(false);
        renderVipPredictionHistoryPanel();
      }
    }

    function toggleVipPredictionHistoryPanel(forceOpen = null) {
      const nextOpen = typeof forceOpen === "boolean" ? forceOpen : !vipPredictionHistoryPanelOpen;
      if (nextOpen) {
        const overlay = document.getElementById("vipPredictionHistoryOverlay");
        const list = document.getElementById("vipPredictionHistoryList");
        vipPredictionHistorySelectedType = normalizePredictionHistoryType(document.getElementById("vipPdType")?.value || vipPredictionHistorySelectedType);
        vipPredictionHistoryCurrentIndex = 0;
        vipPredictionHistoryLoadingError = "";
        vipPredictionHistoryPanelOpen = true;
        if (overlay) overlay.scrollTop = 0;
        if (list) list.scrollTop = 0;
        renderVipPredictionHistoryPanel();
        startVipPredictionHistoryRefresh(vipPredictionHistorySelectedType, { silent: true });
        return;
      }
      vipPredictionHistoryRefreshToken += 1;
      vipPredictionHistoryLoading = false;
      vipPredictionHistoryLoadingType = "";
      vipPredictionHistoryLoadingError = "";
      setVipPredictionHistoryRefreshButtonBusy(false);
      vipPredictionHistoryPanelOpen = false;
      renderVipPredictionHistoryPanel();
    }

    function putResult(type, ky, draw) {
      if (!store.results[type][ky]) store.resultOrder[type].push(ky);
      store.results[type][ky] = draw;
      while (store.resultOrder[type].length > MAX_RESULTS_PER_TYPE) {
        const old = store.resultOrder[type].shift();
        delete store.results[type][old];
      }
      resolvePredictionLogsForKy(type, ky, draw);
      saveStore();
    }

    function addPick(type, ky, ticket) {
      if (!store.picks[type][ky]) {
        store.picks[type][ky] = [];
        store.pickOrder[type].push(ky);
      }
      store.picks[type][ky].push(ticket);
      while (store.pickOrder[type].length > MAX_PICKS_PER_TYPE) {
        const old = store.pickOrder[type].shift();
        delete store.picks[type][old];
      }
      saveStore();
    }

    function line(el, msg, cls="") {
      el.innerHTML = `<span class="${cls}">${msg}</span>`;
    }

    function kySortValue(ky) {
      return Number(String(ky || "").replace(/\D/g, "")) || 0;
    }

    function emptyKenoCsvFeed() {
      return { results: {}, order: [], sourceLabels: [], loadedAt: "" };
    }

    function cloneDraw(draw) {
      if (!draw || (!Array.isArray(draw.main) && !Array.isArray(draw.displayLines))) return null;
      return {
        ...draw,
        main: Array.isArray(draw.main) ? [...draw.main].sort((a, b) => a - b) : [],
        displayLines: Array.isArray(draw.displayLines) ? draw.displayLines.map(String) : []
      };
    }

    function cloneKenoCsvFeed(feed = kenoCsvFeed) {
      const next = emptyKenoCsvFeed();
      next.sourceLabels = [...(feed.sourceLabels || [])];
      next.loadedAt = feed.loadedAt || "";
      for (const ky of (feed.order || [])) {
        const cloned = cloneDraw(feed.results?.[ky]);
        if (!cloned) continue;
        next.results[ky] = cloned;
      }
      next.order = Object.keys(next.results).sort((a, b) => kySortValue(a) - kySortValue(b));
      return next;
    }

    function emptyLiveHistoryFeed(label = "") {
      return {
        label,
        results: {},
        order: [],
        loadedAt: "",
        countKey: "",
        rangeLabel: "",
        historyNote: "",
        canonicalCount: 0,
        canonicalFile: "",
        allCount: 0,
        todayCount: 0,
        allFile: "",
        todayFile: "",
        latestKy: "",
        latestDate: "",
        latestTime: "",
        repairAttempted: false,
        repairNewRows: 0,
        repairRepairedDates: 0,
        repairRepairedKyGaps: 0,
        repairErrors: [],
      };
    }

    function emptyLiveHistoryState() {
      return Object.fromEntries(
        LIVE_HISTORY_TYPES.map(meta => [meta.key, emptyLiveHistoryFeed(meta.label)])
      );
    }

    function normalizeLiveHistoryKy(ky) {
      const normalized = normalizeKy(String(ky || ""));
      if (normalized) return normalized;
      const formatted = formatLiveKy(ky);
      return formatted || null;
    }

    function normalizeLiveHistoryRepairErrors(items) {
      if (!Array.isArray(items)) return [];
      return items.map(item => {
        if (item && typeof item === "object") {
          const type = String(item.type || "").trim();
          const date = String(item.date || "").trim();
          const message = String(item.message || "").trim();
          return [type, date, message].filter(Boolean).join(" • ");
        }
        return String(item || "").trim();
      }).filter(Boolean);
    }

    function mergeLiveHistoryDraw(feed, ky, draw) {
      const key = normalizeLiveHistoryKy(ky);
      const cloned = cloneDraw(draw);
      if (!key || !cloned) return false;
      const existed = !!feed.results[key];
      feed.results[key] = cloned;
      feed.order = Object.keys(feed.results).sort((a, b) => kySortValue(a) - kySortValue(b));
      return !existed;
    }

    function cloneLiveHistoryFeed(feed = emptyLiveHistoryFeed()) {
      const next = emptyLiveHistoryFeed(feed.label || "");
      next.loadedAt = String(feed.loadedAt || "");
      next.countKey = String(feed.countKey || "");
      next.rangeLabel = String(feed.rangeLabel || "");
      next.historyNote = String(feed.historyNote || "");
      next.canonicalCount = Math.max(0, Number(feed.canonicalCount || feed.allCount || 0));
      next.canonicalFile = String(feed.canonicalFile || feed.allFile || "");
      next.allCount = Math.max(0, Number(feed.allCount || 0));
      next.todayCount = Math.max(0, Number(feed.todayCount || 0));
      next.allFile = String(feed.allFile || "");
      next.todayFile = String(feed.todayFile || "");
      next.latestKy = String(feed.latestKy || "");
      next.latestDate = String(feed.latestDate || "");
      next.latestTime = String(feed.latestTime || "");
      next.repairAttempted = !!feed.repairAttempted;
      next.repairNewRows = Math.max(0, Number(feed.repairNewRows || 0));
      next.repairRepairedDates = Math.max(0, Number(feed.repairRepairedDates || 0));
      next.repairRepairedKyGaps = Math.max(0, Number(feed.repairRepairedKyGaps || 0));
      next.repairErrors = normalizeLiveHistoryRepairErrors(feed.repairErrors);
      for (const ky of (feed.order || [])) {
        const cloned = cloneDraw(feed.results?.[ky]);
        if (!cloned) continue;
        next.results[ky] = cloned;
      }
      next.order = Object.keys(next.results).sort((a, b) => kySortValue(a) - kySortValue(b));
      return next;
    }

    function clearLiveHistoryState() {
      liveHistoryState = emptyLiveHistoryState();
    }

    function setLiveHistoryFeed(type, nextFeed) {
      const meta = LIVE_HISTORY_TYPES.find(item => item.key === type);
      if (!meta) return;
      const nextState = liveHistoryState && typeof liveHistoryState === "object"
        ? { ...liveHistoryState }
        : emptyLiveHistoryState();
      nextState[type] = cloneLiveHistoryFeed({
        ...emptyLiveHistoryFeed(meta.label),
        ...(nextFeed || {}),
      });
      liveHistoryState = nextState;
    }

    function getLiveHistoryFeed(type) {
      return liveHistoryState?.[type] || emptyLiveHistoryFeed(TYPES[type]?.label || type);
    }

    function doesLiveHistoryFeedSatisfyCount(type, feed, countRaw) {
      if (!feed?.order?.length && !String(feed?.historyNote || "").trim()) return false;
      const loadedCountKey = String(feed?.countKey || "").trim().toLowerCase();
      const requestedCountKey = String(countRaw || "").trim().toLowerCase();
      if (type === "KENO" && isKenoLiveHistoryRangeKey(requestedCountKey) && !/^\d+$/.test(requestedCountKey)) {
        return !!loadedCountKey && loadedCountKey === requestedCountKey;
      }
      if (loadedCountKey === "all") return true;
      return !!loadedCountKey && loadedCountKey === requestedCountKey;
    }

    function buildMergedResultDataset(type) {
      const baseResults = store.results[type] || {};
      const baseOrder = store.resultOrder[type] || [];
      if (type === "KENO") {
        return buildPredictionResultDataset(type);
      }

      const externalFeed = getLiveHistoryFeed(type);
      const mergedResults = {};
      const mergeFromSource = (ky, draw) => {
        const key = normalizeLiveHistoryKy(ky);
        const cloned = cloneDraw(draw);
        if (!key || !cloned) return;
        mergedResults[key] = cloned;
      };

      for (const ky of (externalFeed.order || [])) mergeFromSource(ky, externalFeed.results?.[ky]);
      for (const ky of baseOrder) mergeFromSource(ky, baseResults[ky]);

      const order = Object.keys(mergedResults).sort((a, b) => kySortValue(a) - kySortValue(b));
      const parts = [];
      if (externalFeed.order?.length) parts.push(`CSV canonical ${externalFeed.order.length} kỳ`);
      if (baseOrder.length) parts.push(`trong trang ${baseOrder.length} kỳ`);
      return {
        results: mergedResults,
        order,
        sourceText: parts.length
          ? `Nguồn ${TYPES[type].label} đã gộp: ${parts.join(" + ")}. Tổng dùng: ${order.length} kỳ`
          : `Chưa có dữ liệu ${TYPES[type].label}`
      };
    }

    function buildLiveHistoryFeedFromResponse(type, rows, loadedAt = "", countKey = "", responseMeta = {}) {
      const meta = LIVE_HISTORY_TYPES.find(item => item.key === type) || { key: type, label: TYPES[type]?.label || type };
      const next = emptyLiveHistoryFeed(meta.label);
      next.loadedAt = String(loadedAt || "");
      next.countKey = String(countKey || "");
      next.rangeLabel = String(responseMeta?.rangeLabel || "");
      next.historyNote = String(responseMeta?.historyNote || "");
      next.canonicalCount = Math.max(0, Number(responseMeta?.canonicalCount || responseMeta?.allCount || 0));
      next.canonicalFile = String(responseMeta?.canonicalFile || responseMeta?.allFile || "");
      next.allCount = Math.max(0, Number(responseMeta?.allCount || 0));
      next.todayCount = Math.max(0, Number(responseMeta?.todayCount || 0));
      next.allFile = String(responseMeta?.allFile || "");
      next.todayFile = String(responseMeta?.todayFile || "");
      next.latestKy = String(responseMeta?.latestKy || "");
      next.latestDate = String(responseMeta?.latestDate || "");
      next.latestTime = String(responseMeta?.latestTime || "");
      next.repairAttempted = !!responseMeta?.repairAttempted;
      next.repairNewRows = Math.max(0, Number(responseMeta?.repairNewRows || 0));
      next.repairRepairedDates = Math.max(0, Number(responseMeta?.repairRepairedDates || 0));
      next.repairRepairedKyGaps = Math.max(0, Number(responseMeta?.repairRepairedKyGaps || 0));
      next.repairErrors = normalizeLiveHistoryRepairErrors(responseMeta?.repairErrors);
      (Array.isArray(rows) ? rows : []).forEach(row => {
        const main = Array.isArray(row?.main)
          ? row.main.map(Number).filter(Number.isFinite).sort((a, b) => a - b)
          : [];
        const specialValue = row?.special;
        const special = Number.isInteger(Number(specialValue)) ? Number(specialValue) : null;
        mergeLiveHistoryDraw(next, row?.ky, {
          main,
          special,
          displayLines: Array.isArray(row?.displayLines) ? row.displayLines.map(String) : [],
          date: String(row?.date || ""),
          time: String(row?.time || ""),
          sourceUrl: String(row?.sourceUrl || ""),
          sourceDate: String(row?.sourceDate || ""),
          label: String(row?.label || meta.label),
        });
      });
      next.allCount = Math.max(next.allCount, next.order.length);
      next.canonicalCount = Math.max(next.canonicalCount, next.order.length);
      return next;
    }

    function isLiveHistoryRouteMissingError(err) {
      const message = String(err?.message || err || "").trim().toLowerCase();
      return message === "not found" || message.includes("404");
    }

    function isAiPredictRouteMissingError(err) {
      const message = String(err?.message || err || "").trim().toLowerCase();
      return message === "not found" || message.includes("404");
    }

    async function fetchLiveHistoryFromLegacyLiveResults(type, normalizedCount) {
      if (type === "KENO" && isKenoLiveHistoryRangeKey(normalizedCount) && normalizedCount !== "all") {
        throw new Error("Server đang chạy bản cũ và chưa hỗ trợ mốc thời gian Keno trong /api/live-history. Hãy tắt server rồi chạy lại .\\chay_lotto_web.bat.");
      }
      const legacyRes = await api("/api/live-results");
      const historyMap = legacyRes?.history && typeof legacyRes.history === "object"
        ? legacyRes.history
        : {};
      if (!Array.isArray(historyMap?.[type])) {
        throw new Error("Server đang chạy bản cũ và chưa hỗ trợ /api/live-history. Hãy tắt server rồi chạy lại .\\chay_lotto_web.bat.");
      }
      const rows = Array.isArray(historyMap?.[type]) ? historyMap[type] : [];
      const limitedRows = normalizedCount === "all"
        ? rows
        : rows.slice(0, Math.max(1, Number(normalizedCount) || 20));
      const nextFeed = buildLiveHistoryFeedFromResponse(
        type,
        limitedRows,
        String(legacyRes?.fetchedAt || ""),
        normalizedCount,
        {
          allCount: rows.length,
          todayCount: 0,
          allFile: "",
          todayFile: "",
          latestKy: limitedRows?.[0]?.ky || "",
          latestDate: limitedRows?.[0]?.date || "",
          latestTime: limitedRows?.[0]?.time || ""
        }
      );
      setLiveHistoryFeed(type, nextFeed);
      return nextFeed;
    }

    async function fetchLiveHistory(type, countRaw = "2", { force = false, silent = false, repair = false, recentDays = null } = {}) {
      const out = document.getElementById("liveHistoryOut");
      const meta = LIVE_HISTORY_TYPES.find(item => item.key === type);
      if (!meta) throw new Error("Loại lịch sử không hợp lệ.");
      if (IS_LOCAL_MODE) {
        if (!silent && out) {
          line(out, "Lịch sử CSV tự động chỉ hoạt động khi mở qua http://localhost:8080.", "warn");
        }
        return getLiveHistoryFeed(type);
      }

      const normalizedCount = String(countRaw || "2").trim().toLowerCase() || "2";
      const currentFeed = getLiveHistoryFeed(type);
      if (!force && doesLiveHistoryFeedSatisfyCount(type, currentFeed, normalizedCount)) {
        return currentFeed;
      }

      if (!silent && out) {
        line(out, `Đang tải lịch sử CSV ${meta.label} từ all_day.csv...`, "muted");
      }

      let nextFeed;
      try {
        if (liveHistoryLegacyApiMode) {
          nextFeed = await fetchLiveHistoryFromLegacyLiveResults(type, normalizedCount);
        } else {
          const params = new URLSearchParams({ type, count: normalizedCount });
          if (repair) params.set("repair", "1");
          if (Number.isFinite(Number(recentDays)) && Number(recentDays) > 0) {
            params.set("recentDays", String(Math.max(1, Math.floor(Number(recentDays)))));
          }
          const res = await api(`/api/live-history?${params.toString()}`);
          nextFeed = buildLiveHistoryFeedFromResponse(
            type,
            Array.isArray(res?.history) ? res.history : [],
            String(res?.fetchedAt || ""),
            String(res?.count || normalizedCount),
            {
              canonicalCount: res?.canonicalCount,
              canonicalFile: res?.canonicalFile,
              allCount: res?.allCount,
              todayCount: res?.todayCount,
              allFile: res?.allFile,
              todayFile: res?.todayFile,
              latestKy: res?.latestKy,
              latestDate: res?.latestDate,
              latestTime: res?.latestTime,
              rangeLabel: res?.rangeLabel,
              historyNote: res?.historyNote,
              repairAttempted: res?.repairAttempted,
              repairNewRows: res?.repairNewRows,
              repairRepairedDates: res?.repairRepairedDates,
              repairRepairedKyGaps: res?.repairRepairedKyGaps,
              repairErrors: res?.repairErrors,
            }
          );
          setLiveHistoryFeed(type, nextFeed);
        }
      } catch (err) {
        if (!liveHistoryLegacyApiMode && isLiveHistoryRouteMissingError(err)) {
          nextFeed = await fetchLiveHistoryFromLegacyLiveResults(type, normalizedCount);
          liveHistoryLegacyApiMode = true;
        } else {
          throw err;
        }
      }
      if (PREDICTION_LOG_TYPES.includes(type) && String(nextFeed.countKey || "").toLowerCase() === "all") {
        const before = JSON.stringify(store.predictionLogs?.[type] || []);
        reconcilePredictionLogsForType(type);
        if (JSON.stringify(store.predictionLogs?.[type] || []) !== before) {
          saveStore();
        }
      }
      return getLiveHistoryFeed(type);
    }

    async function refreshCurrentLiveHistory({ force = false, silent = false } = {}) {
      const out = document.getElementById("liveHistoryOut");
      const type = document.getElementById("liveHistoryType")?.value || LIVE_HISTORY_TYPES[0]?.key;
      const countRaw = String(document.getElementById("liveHistoryCount")?.value || "2").trim().toLowerCase();
      const feed = await fetchLiveHistory(type, countRaw, { force, silent });
      if (!feed?.order?.length && !String(feed?.historyNote || "").trim()) {
        if (!out) return;
        if (IS_LOCAL_MODE) {
          line(out, "Lịch sử CSV tự động chỉ hoạt động khi mở qua http://localhost:8080.", "warn");
          return;
        }
        line(out, `Chưa có dữ liệu lịch sử CSV cho ${TYPES[type]?.label || type} trong all_day.csv.`, "warn");
        return;
      }
      renderLiveHistoryOutput();
    }

    function setLiveHistoryRefreshButtonBusy(isBusy) {
      const btn = document.getElementById("liveHistoryRefreshBtn");
      if (!btn) return;
      const originalText = btn.dataset.originalText || String(btn.textContent || "Cập nhật 15 ngày");
      btn.dataset.originalText = originalText;
      btn.disabled = !!isBusy;
      btn.textContent = isBusy ? "Đang cập nhật..." : originalText;
    }

    async function refreshRecentLiveHistoryWindow() {
      const out = document.getElementById("liveHistoryOut");
      const type = document.getElementById("liveHistoryType")?.value || LIVE_HISTORY_TYPES[0]?.key || "LOTO_5_35";
      const typeLabel = TYPES[type]?.label || type;
      if (liveHistoryRecentRefreshBusy) return;
      if (IS_LOCAL_MODE) {
        line(out, "Cập nhật lịch sử CSV chỉ hoạt động khi mở qua http://localhost:8080.", "warn");
        return;
      }
      liveHistoryRecentRefreshBusy = true;
      setLiveHistoryRefreshButtonBusy(true);
      line(out, `Đang kiểm tra và cập nhật ${typeLabel} trong ${LIVE_HISTORY_RECENT_REPAIR_DAYS} ngày gần nhất...`, "muted");
      try {
        const params = new URLSearchParams({
          type,
          repair: "1",
          recentDays: String(LIVE_HISTORY_RECENT_REPAIR_DAYS),
        });
        const requestStartedAtMs = Date.now();
        const res = await api(`/api/live-results?${params.toString()}`);
        applyLiveResultsApiResponse(res, { repairCanonical: true, requestStartedAtMs });
        await refreshCurrentLiveHistory({ force: true, silent: true });
        const historyText = String(out?.textContent || "").trim();
        line(
          out,
          `Đã kiểm tra và cập nhật dữ liệu ${typeLabel} trong ${LIVE_HISTORY_RECENT_REPAIR_DAYS} ngày gần nhất.` + (historyText ? `\n\n${historyText}` : ""),
          "ok"
        );
      } finally {
        liveHistoryRecentRefreshBusy = false;
        setLiveHistoryRefreshButtonBusy(false);
      }
    }

    function formatLiveHistoryDraw(type, draw) {
      const displayLines = Array.isArray(draw?.displayLines) ? draw.displayLines.filter(Boolean) : [];
      if (TYPES[type]?.threeDigit && displayLines.length) {
        return displayLines.join(" | ");
      }
      if (TYPES[type] && Array.isArray(draw?.main) && draw.main.length) {
        return formatTicket(draw, type);
      }
      if (displayLines.length) return displayLines.join(" | ");
      if (Array.isArray(draw?.main) && draw.main.length) return draw.main.join(" ");
      return "(không có dữ liệu)";
    }

    function renderLiveHistoryOutput() {
      const out = document.getElementById("liveHistoryOut");
      const type = document.getElementById("liveHistoryType")?.value || LIVE_HISTORY_TYPES[0]?.key;
      const countRaw = String(document.getElementById("liveHistoryCount")?.value || "2").trim().toLowerCase();
      if (!out || !type) return;
      const feed = getLiveHistoryFeed(type);
      if (!feed.order.length && !String(feed.historyNote || "").trim()) {
        return line(out, "Chọn loại rồi bấm Xem lịch sử CSV để tải dữ liệu từ all_day.csv.", "muted");
      }

      const isKenoRangeMode = type === "KENO" && isKenoLiveHistoryRangeKey(countRaw);
      const selectedKeys = isKenoRangeMode || countRaw === "all"
        ? [...feed.order].reverse()
        : [...feed.order].slice(-Math.max(1, Number(countRaw) || 20)).reverse();
      const selectedCount = selectedKeys.length;
      const totalCount = Math.max(feed.order.length, Number(feed.canonicalCount || feed.allCount || 0));
      const lines = [];
      if (isKenoRangeMode) {
        lines.push(`Lịch sử CSV ${feed.label || type}: ${feed.rangeLabel || getKenoLiveHistoryRangeLabel(countRaw)} • ${formatLiveSyncCount(selectedCount)} kỳ.`);
      } else {
        lines.push(`Lịch sử CSV ${feed.label || type}: đang hiển thị ${formatLiveSyncCount(selectedCount)}/${formatLiveSyncCount(totalCount)} kỳ.`);
      }
      const sourceParts = [];
      if (feed.canonicalFile || feed.allFile) {
        sourceParts.push(`Nguồn: ${feed.canonicalFile || feed.allFile}`);
      }
      if (Number(feed.todayCount || 0) > 0) {
        sourceParts.push(`${formatLiveSyncCount(feed.todayCount)} kỳ hôm nay`);
      }
      const latestMetaParts = buildLiveMetaParts(feed.latestKy || "", feed.latestDate || "", feed.latestTime || "");
      if (latestMetaParts.length) {
        sourceParts.push(`mới nhất ${latestMetaParts.join(" • ")}`);
      }
      if (sourceParts.length) {
        lines.push(sourceParts.join(" • "));
      }
      if (feed.loadedAt) {
        lines.push(`Cập nhật cache: ${new Date(feed.loadedAt).toLocaleString("vi-VN")}.`);
      }
      if (feed.historyNote) {
        lines.push(feed.historyNote);
      }
      lines.push("");
      selectedKeys.forEach(ky => {
        const draw = feed.results[ky];
        if (!draw) return;
        const metaParts = buildLiveMetaParts(ky, draw.date, draw.time);
        lines.push(`${feed.label || type} ${metaParts.join(" • ")}: ${formatLiveHistoryDraw(type, draw)}`);
      });
      line(out, lines.join("\n"));
    }

    function formatDataTableWeekday(dateText) {
      const raw = String(dateText || "").trim();
      const match = raw.match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})$/);
      if (!match) return "";
      const day = Number(match[1]);
      const month = Number(match[2]);
      const year = Number(match[3]);
      const date = new Date(year, month - 1, day);
      if (Number.isNaN(date.getTime())) return "";
      return ["Chủ nhật", "Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7"][date.getDay()] || "";
    }

    function normalizeDataTableDisplayLine(lineText) {
      return String(lineText || "").replace(/\s+/g, " ").trim();
    }

    function splitDataTableDisplayLines(draw) {
      const rawLines = Array.isArray(draw?.displayLines) ? draw.displayLines : [];
      return rawLines.map(normalizeDataTableDisplayLine).filter(Boolean);
    }

    function formatDataTableNumbers(type, draw) {
      const displayLines = splitDataTableDisplayLines(draw);
      if (TYPES[type]?.threeDigit && displayLines.length) {
        const specialLines = [];
        const numberLines = [];
        displayLines.forEach(lineText => {
          if (/^đặc\s*biệt\s*:/i.test(lineText)) {
            specialLines.push(lineText.replace(/^đặc\s*biệt\s*:\s*/i, "").trim());
          } else {
            numberLines.push(lineText);
          }
        });
        return {
          numbers: numberLines.join(" | ") || displayLines.join(" | "),
          special: specialLines.join(" | "),
        };
      }

      const main = Array.isArray(draw?.main) ? draw.main.map(Number).filter(Number.isFinite) : [];
      const numbers = main.map(number => formatPredictNumber(number, type)).join(" ");
      const special = TYPES[type]?.hasSpecial && Number.isInteger(Number(draw?.special))
        ? formatPredictNumber(Number(draw.special), type)
        : "";
      return { numbers, special };
    }

    function getDataTableLimitValue() {
      const raw = String(document.getElementById("dataTableLimit")?.value || dataTableSelectedLimit || "500").trim().toLowerCase();
      return raw === "all" ? "all" : String(Math.max(1, Number(raw) || 500));
    }

    function getDataTableHeaders(type) {
      const hasSpecialColumn = !!TYPES[type]?.hasSpecial || !!TYPES[type]?.threeDigit;
      return ["Kỳ", "Thứ", "Ngày", "Giờ", "Số", ...(hasSpecialColumn ? ["ĐB"] : [])];
    }

    function getDataTableSelectedKeys(feed, limitValue = getDataTableLimitValue()) {
      const keys = [...(feed?.order || [])].reverse();
      if (limitValue === "all") return keys;
      return keys.slice(0, Math.max(1, Number(limitValue) || 500));
    }

    function buildDataTableRows(type, feed, limitValue = getDataTableLimitValue()) {
      return getDataTableSelectedKeys(feed, limitValue).map(ky => {
        const draw = feed.results?.[ky] || {};
        const cells = formatDataTableNumbers(type, draw);
        return [
          formatLiveKy(ky),
          formatDataTableWeekday(draw.date),
          draw.date || "",
          draw.time || "",
          cells.numbers || "",
          ...((!!TYPES[type]?.hasSpecial || !!TYPES[type]?.threeDigit) ? [cells.special || ""] : []),
        ];
      });
    }

    function renderDataTableShell() {
      const select = document.getElementById("dataTableType");
      const limitSelect = document.getElementById("dataTableLimit");
      if (select && !select.options.length) {
        select.innerHTML = LIVE_HISTORY_TYPES.map(item => `<option value="${item.key}">${item.label}</option>`).join("");
      }
      if (select && Array.from(select.options).some(option => option.value === dataTableSelectedType)) {
        select.value = dataTableSelectedType;
      }
      if (limitSelect && Array.from(limitSelect.options).some(option => option.value === dataTableSelectedLimit)) {
        limitSelect.value = dataTableSelectedLimit;
      }
      if (select?.__syncCustomSelect) select.__syncCustomSelect();
      if (limitSelect?.__syncCustomSelect) limitSelect.__syncCustomSelect();
    }

    function renderDataTableStatus(message, tone = "muted") {
      const status = document.getElementById("dataTableStatus");
      if (!status) return;
      status.className = `data-table-status ${tone}`;
      status.textContent = message;
    }

    function renderDataTableRows(type, feed) {
      const head = document.getElementById("dataTableHead");
      const body = document.getElementById("dataTableBody");
      if (!head || !body) return;
      const headers = getDataTableHeaders(type);
      head.innerHTML = `<tr>${headers.map(label => `<th>${escapeHtml(label)}</th>`).join("")}</tr>`;

      const rows = buildDataTableRows(type, feed);
      if (!rows.length) {
        body.innerHTML = `<tr><td colspan="${headers.length}" class="data-table-empty">Chưa có dữ liệu để hiển thị.</td></tr>`;
        return;
      }

      body.innerHTML = rows.map(rowCells => {
        return `<tr>${rowCells.map(value => `<td>${escapeHtml(value)}</td>`).join("")}</tr>`;
      }).join("");
    }

    async function loadDataTableRows({ force = false } = {}) {
      const select = document.getElementById("dataTableType");
      const limitSelect = document.getElementById("dataTableLimit");
      const type = select?.value || dataTableSelectedType || "LOTO_5_35";
      if (!TYPES[type] || dataTableLoading) return;
      dataTableSelectedType = type;
      dataTableSelectedLimit = getDataTableLimitValue();
      if (limitSelect?.__syncCustomSelect) limitSelect.__syncCustomSelect();
      if (IS_LOCAL_MODE) {
        renderDataTableStatus("Bảng dữ liệu chỉ tải tự động khi mở qua http://localhost:8080.", "warn");
        renderDataTableRows(type, emptyLiveHistoryFeed(TYPES[type]?.label || type));
        return;
      }
      dataTableLoading = true;
      renderDataTableStatus(`Đang tải ${TYPES[type]?.label || type} từ all_day.csv...`, "muted");
      try {
        const feed = await fetchLiveHistory(type, "all", { force, silent: true });
        renderDataTableRows(type, feed);
        const total = Math.max(feed.order.length, Number(feed.canonicalCount || feed.allCount || 0));
        const shown = buildDataTableRows(type, feed).length;
        const source = feed.canonicalFile || feed.allFile || "all_day.csv";
        renderDataTableStatus(`Đang hiển thị ${formatLiveSyncCount(shown)}/${formatLiveSyncCount(total)} kỳ • Nguồn: ${source}`, "ok");
      } catch (err) {
        renderDataTableStatus(`Không tải được bảng dữ liệu: ${err.message || err}`, "warn");
      } finally {
        dataTableLoading = false;
      }
    }

    async function downloadDataTableExcel() {
      const type = document.getElementById("dataTableType")?.value || dataTableSelectedType || "LOTO_5_35";
      if (!TYPES[type]) return;
      if (IS_LOCAL_MODE) {
        renderDataTableStatus("Tải xuống Excel chỉ hoạt động khi mở qua http://localhost:8080.", "warn");
        return;
      }
      const feed = await fetchLiveHistory(type, "all", { silent: true });
      const headers = getDataTableHeaders(type);
      const rows = buildDataTableRows(type, feed);
      if (!rows.length) {
        renderDataTableStatus("Không có dữ liệu để tải xuống.", "warn");
        return;
      }
      const blob = buildXlsxWorkbookBlob(headers, rows, `Bang Du Lieu ${TYPES[type]?.label || type}`);
      const safeType = String(type || "DATA").toLowerCase();
      const safeLimit = getDataTableLimitValue() === "all" ? "tat_ca" : getDataTableLimitValue();
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = `bang_du_lieu_${safeType}_${safeLimit}.xlsx`;
      document.body.appendChild(link);
      link.click();
      window.setTimeout(() => {
        URL.revokeObjectURL(link.href);
        link.remove();
      }, 0);
      renderDataTableStatus(`Đã tạo file Excel ${rows.length} dòng cho ${TYPES[type]?.label || type}.`, "ok");
    }

    function escapeXml(value) {
      return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&apos;");
    }

    function getExcelColumnName(index) {
      let n = Math.max(1, Number(index) || 1);
      let name = "";
      while (n > 0) {
        const mod = (n - 1) % 26;
        name = String.fromCharCode(65 + mod) + name;
        n = Math.floor((n - 1) / 26);
      }
      return name;
    }

    function buildXlsxSheetXml(headers, rows) {
      const allRows = [headers, ...rows];
      const rowXml = allRows.map((row, rowIndex) => {
        const rowNumber = rowIndex + 1;
        const cells = row.map((value, cellIndex) => {
          const cellRef = `${getExcelColumnName(cellIndex + 1)}${rowNumber}`;
          const text = escapeXml(value);
          return `<c r="${cellRef}" t="inlineStr"><is><t xml:space="preserve">${text}</t></is></c>`;
        }).join("");
        return `<row r="${rowNumber}">${cells}</row>`;
      }).join("");
      const lastCol = getExcelColumnName(Math.max(1, headers.length));
      const lastRow = Math.max(1, allRows.length);
      return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <dimension ref="A1:${lastCol}${lastRow}"/>
  <sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>
  <sheetFormatPr defaultRowHeight="18"/>
  <cols>
    <col min="1" max="4" width="14" customWidth="1"/>
    <col min="5" max="5" width="72" customWidth="1"/>
    <col min="6" max="6" width="24" customWidth="1"/>
  </cols>
  <sheetData>${rowXml}</sheetData>
</worksheet>`;
    }

    function buildXlsxWorkbookBlob(headers, rows, title = "Bang Du Lieu") {
      const now = new Date().toISOString();
      const files = {
        "[Content_Types].xml": `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>`,
        "_rels/.rels": `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>`,
        "docProps/app.xml": `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Vietlott Tra Cuu Nhanh Pro</Application>
</Properties>`,
        "docProps/core.xml": `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>${escapeXml(title)}</dc:title>
  <dc:creator>Vietlott Tra Cuu Nhanh Pro</dc:creator>
  <dcterms:created xsi:type="dcterms:W3CDTF">${now}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">${now}</dcterms:modified>
</cp:coreProperties>`,
        "xl/workbook.xml": `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Bang Du Lieu" sheetId="1" r:id="rId1"/></sheets>
</workbook>`,
        "xl/_rels/workbook.xml.rels": `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>`,
        "xl/styles.xml": `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="1"><font><sz val="11"/><name val="Arial"/></font></fonts>
  <fills count="1"><fill><patternFill patternType="none"/></fill></fills>
  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="1"><xf numFmtId="49" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>
</styleSheet>`,
        "xl/worksheets/sheet1.xml": buildXlsxSheetXml(headers, rows),
      };
      return buildZipBlob(files, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
    }

    function buildCrc32Table() {
      const table = new Uint32Array(256);
      for (let i = 0; i < 256; i++) {
        let value = i;
        for (let bit = 0; bit < 8; bit++) {
          value = (value & 1) ? (0xEDB88320 ^ (value >>> 1)) : (value >>> 1);
        }
        table[i] = value >>> 0;
      }
      return table;
    }

    const ZIP_CRC32_TABLE = buildCrc32Table();

    function crc32(bytes) {
      let crc = 0xFFFFFFFF;
      for (let i = 0; i < bytes.length; i++) {
        crc = ZIP_CRC32_TABLE[(crc ^ bytes[i]) & 0xFF] ^ (crc >>> 8);
      }
      return (crc ^ 0xFFFFFFFF) >>> 0;
    }

    function pushUint16LE(out, value) {
      out.push(value & 0xFF, (value >>> 8) & 0xFF);
    }

    function pushUint32LE(out, value) {
      out.push(value & 0xFF, (value >>> 8) & 0xFF, (value >>> 16) & 0xFF, (value >>> 24) & 0xFF);
    }

    function pushBytes(out, bytes) {
      for (let i = 0; i < bytes.length; i++) out.push(bytes[i]);
    }

    function buildZipBlob(files, mimeType) {
      const encoder = new TextEncoder();
      const localParts = [];
      const centralParts = [];
      let offset = 0;
      let centralSize = 0;
      const dosTime = 0;
      const dosDate = 33;
      Object.entries(files).forEach(([path, content]) => {
        const nameBytes = encoder.encode(path);
        const dataBytes = encoder.encode(String(content || ""));
        const crc = crc32(dataBytes);
        const local = [];
        pushUint32LE(local, 0x04034b50);
        pushUint16LE(local, 20);
        pushUint16LE(local, 0x0800);
        pushUint16LE(local, 0);
        pushUint16LE(local, dosTime);
        pushUint16LE(local, dosDate);
        pushUint32LE(local, crc);
        pushUint32LE(local, dataBytes.length);
        pushUint32LE(local, dataBytes.length);
        pushUint16LE(local, nameBytes.length);
        pushUint16LE(local, 0);
        pushBytes(local, nameBytes);
        pushBytes(local, dataBytes);
        localParts.push(new Uint8Array(local));

        const central = [];
        pushUint32LE(central, 0x02014b50);
        pushUint16LE(central, 20);
        pushUint16LE(central, 20);
        pushUint16LE(central, 0x0800);
        pushUint16LE(central, 0);
        pushUint16LE(central, dosTime);
        pushUint16LE(central, dosDate);
        pushUint32LE(central, crc);
        pushUint32LE(central, dataBytes.length);
        pushUint32LE(central, dataBytes.length);
        pushUint16LE(central, nameBytes.length);
        pushUint16LE(central, 0);
        pushUint16LE(central, 0);
        pushUint16LE(central, 0);
        pushUint16LE(central, 0);
        pushUint32LE(central, 0);
        pushUint32LE(central, offset);
        pushBytes(central, nameBytes);
        centralParts.push(new Uint8Array(central));
        centralSize += central.length;
        offset += local.length;
      });
      const centralOffset = offset;
      const end = [];
      pushUint32LE(end, 0x06054b50);
      pushUint16LE(end, 0);
      pushUint16LE(end, 0);
      pushUint16LE(end, Object.keys(files).length);
      pushUint16LE(end, Object.keys(files).length);
      pushUint32LE(end, centralSize);
      pushUint32LE(end, centralOffset);
      pushUint16LE(end, 0);
      return new Blob([
        ...localParts,
        ...centralParts,
        new Uint8Array(end),
      ], { type: mimeType });
    }

    function mergeKenoDraw(feed, ky, draw) {
      const key = String(ky || "").replace(/\D/g, "");
      const cloned = cloneDraw(draw);
      if (!key || !cloned) return false;
      feed.results[key] = cloned;
      return true;
    }

    function finalizeKenoCsvFeed(feed, loadedAt = new Date().toISOString()) {
      feed.order = Object.keys(feed.results).sort((a, b) => kySortValue(a) - kySortValue(b));
      feed.sourceLabels = [...new Set((feed.sourceLabels || []).filter(Boolean))];
      feed.loadedAt = loadedAt;
      return feed;
    }

    function normalizeHeaderName(value) {
      return String(value || "")
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "");
    }

    function splitCsvRow(lineText) {
      const line = String(lineText || "");
      const cells = [];
      let cur = "";
      let inQuotes = false;
      for (let i = 0; i < line.length; i++) {
        const ch = line[i];
        if (ch === '"') {
          if (inQuotes && line[i + 1] === '"') {
            cur += '"';
            i++;
          } else {
            inQuotes = !inQuotes;
          }
          continue;
        }
        if (ch === "," && !inQuotes) {
          cells.push(cur.trim());
          cur = "";
          continue;
        }
        cur += ch;
      }
      cells.push(cur.trim());
      return cells;
    }

    function parseKenoCsvText(text, sourceLabel = "CSV") {
      const lines = String(text || "")
        .replace(/^\uFEFF/, "")
        .split(/\r?\n/)
        .filter(line => line.trim());
      if (!lines.length) return { rows: [], skipped: 0, sourceLabel };

      let startIndex = 0;
      let kyIndex = 0;
      let dateIndex = 1;
      let timeIndex = 2;
      let numbersIndex = 3;

      const headerCells = splitCsvRow(lines[0]).map(normalizeHeaderName);
      const looksLikeHeader = headerCells.includes("ky") || headerCells.includes("numbers") || headerCells.includes("ngay");
      if (looksLikeHeader) {
        startIndex = 1;
        const idxKy = headerCells.findIndex(name => name === "ky");
        const idxDate = headerCells.findIndex(name => name === "ngay" || name === "date");
        const idxTime = headerCells.findIndex(name => name === "time" || name === "gio");
        const idxNumbers = headerCells.findIndex(name => name === "numbers" || name === "so" || name === "ketqua");
        if (idxKy >= 0) kyIndex = idxKy;
        if (idxDate >= 0) dateIndex = idxDate;
        if (idxTime >= 0) timeIndex = idxTime;
        if (idxNumbers >= 0) numbersIndex = idxNumbers;
      }

      const rows = [];
      let skipped = 0;
      for (let i = startIndex; i < lines.length; i++) {
        const cells = splitCsvRow(lines[i]);
        if (!cells.some(Boolean)) continue;
        const ky = String(cells[kyIndex] || "").replace(/\D/g, "");
        const date = String(cells[dateIndex] || "").trim();
        const time = String(cells[timeIndex] || "").trim();
        try {
          const numbers = parseDistinctSortedNums(
            parseNums(cells[numbersIndex] || ""),
            1,
            80,
            20,
            20,
            `CSV ${sourceLabel} dòng ${i + 1}`
          );
          if (!ky) throw new Error("Thiếu kỳ");
          rows.push({
            ky,
            draw: { main: numbers, special: null, date, time }
          });
        } catch {
          skipped++;
        }
      }
      return { rows, skipped, sourceLabel };
    }

    function saveKenoCsvFeedCache() {
      try {
        localStorage.setItem(LOCAL_KENO_CSV_CACHE_KEY, JSON.stringify({
          results: kenoCsvFeed.results,
          order: kenoCsvFeed.order,
          sourceLabels: kenoCsvFeed.sourceLabels,
          loadedAt: kenoCsvFeed.loadedAt
        }));
      } catch {}
    }

    function restoreKenoCsvFeedCache() {
      try {
        const raw = localStorage.getItem(LOCAL_KENO_CSV_CACHE_KEY);
        if (!raw) {
          kenoCsvFeed = emptyKenoCsvFeed();
          return;
        }
        const parsed = JSON.parse(raw);
        const next = emptyKenoCsvFeed();
        next.sourceLabels = Array.isArray(parsed?.sourceLabels) ? parsed.sourceLabels : [];
        next.loadedAt = String(parsed?.loadedAt || "");
        const resultMap = parsed?.results && typeof parsed.results === "object" ? parsed.results : {};
        for (const [ky, draw] of Object.entries(resultMap)) {
          mergeKenoDraw(next, ky, draw);
        }
        kenoCsvFeed = finalizeKenoCsvFeed(next, next.loadedAt || new Date().toISOString());
      } catch {
        kenoCsvFeed = emptyKenoCsvFeed();
      }
    }

    function setKenoCsvFeed(feed, loadedAt = new Date().toISOString()) {
      kenoCsvFeed = finalizeKenoCsvFeed(feed, loadedAt);
      saveKenoCsvFeedCache();
      updateKenoCsvStatus();
      const predictionLogsBeforeReconcile = getPredictionLogsSignature(store.predictionLogs?.KENO || []);
      reconcilePredictionLogsForType("KENO");
      if (getPredictionLogsSignature(store.predictionLogs?.KENO || []) !== predictionLogsBeforeReconcile) {
        saveStore();
      }
    }

    function updateKenoCsvStatus(extraMessage = "", cls = "") {
      const el = document.getElementById("pdCsvStatus");
      if (!el) return;
      const statusLoadedAt = String(kenoPredictStatusMeta.loadedAt || "");
      const loadedText = statusLoadedAt
        ? new Date(statusLoadedAt).toLocaleString("vi-VN")
        : "";
      const detailMessage = extraMessage || String(kenoPredictStatusMeta.detail || "");

      let message = "";
      let level = cls || String(kenoPredictStatusMeta.level || "");
      if (statusLoadedAt) {
        message = loadedText
          ? `Cập nhật lần cuối: ${loadedText}.`
          : "Đã tự động đồng bộ CSV Keno.";
        if (!level) level = "ok";
      } else {
        message = IS_LOCAL_MODE
          ? "Chưa có CSV Keno trong bộ nhớ. Hãy mở trang qua http://localhost:8080 để web tự đồng bộ dữ liệu dự đoán."
          : "Dữ liệu Keno sẽ tự đồng bộ khi bấm Dự đoán.";
        if (!level) level = "muted";
      }

      if (detailMessage) message += `\n${detailMessage}`;
      line(el, message, level);
    }

    function setKenoPredictStatusMeta(detail = "", level = "", loadedAt = new Date().toISOString()) {
      kenoPredictStatusMeta = {
        loadedAt: String(loadedAt || ""),
        detail: String(detail || ""),
        level: String(level || "")
      };
      updateKenoCsvStatus(detail, level);
    }

    function toKenoNumberTokens(numbers) {
      return (Array.isArray(numbers) ? numbers : [])
        .map(value => Number(value))
        .filter(Number.isFinite)
        .sort((a, b) => a - b)
        .map(value => String(Number(value) || 0).padStart(2, "0"));
    }

    function formatKenoNumberList(numbers) {
      return toKenoNumberTokens(numbers).join(", ");
    }

    function formatKenoNumberRows(numbers, perRow = 10) {
      const tokens = toKenoNumberTokens(numbers);
      const rows = [];
      for (let i = 0; i < tokens.length; i += perRow) {
        rows.push(tokens.slice(i, i + perRow).join(", "));
      }
      return rows;
    }

    // ----- CSV Keno và predictor Keno -----
    // Parse nguồn CSV Keno, chuẩn hóa hiển thị và xử lý nhánh dự đoán Keno riêng.
    function formatKenoPythonPrediction(result) {
      const sync = result?.sync || {};
      const selected = result?.selected || {};
      const selectedModel = selected?.model || {};
      const lastDraw = selected?.last_draw || {};
      const bundles = Array.isArray(selected?.prediction_bundles) ? selected.prediction_bundles : [];
      const lines = [];
      const addLine = (value = "") => {
        const text = String(value || "").trim();
        if (text) lines.push(text);
      };

      if (sync?.sync_error) {
        addLine(`Không thể đồng bộ web, đang dùng dữ liệu local: ${sync.sync_error}`);
      } else if (sync?.latest_date) {
        addLine(`Đã cập nhật web ngày ${sync.latest_date}: +${Number(sync.new_rows || 0)} kỳ mới.`);
      }
      addLine(`Bạn đã chọn: Bậc ${selected.order}`);
      addLine(`Số bộ đã chọn: ${selected.bundle_count}`);
      if (lastDraw.ky) {
        addLine(`Kỳ gần nhất trong dữ liệu: ${lastDraw.ky} - ${lastDraw.ngay || ""} ${lastDraw.time || ""}`.trim());
      }
      if (selected.next_ky) addLine(`Dự đoán kỳ tiếp theo: ${selected.next_ky}`);
      if (Array.isArray(selected.top_numbers) && selected.top_numbers.length) {
        addLine(`Top ${selected.top_numbers.length} số tham khảo:`);
        formatKenoNumberRows(selected.top_numbers, 10).forEach(addLine);
      }
      if (bundles.length) {
        addLine("Các bộ dự đoán:");
        bundles.forEach((bundle, index) => {
          addLine(`Bộ ${index + 1}: ${formatKenoNumberList(bundle)}`);
        });
      }
      if (selected.predicted_ln) addLine(`Dự đoán Lớn/Nhỏ: ${selected.predicted_ln}`);
      if (selected.predicted_cl) addLine(`Dự đoán Chẵn/Lẻ: ${selected.predicted_cl}`);
      if (selected.order && selectedModel.label) {
        addLine(
          `Độ khớp trung bình của bậc ${selected.order}: ${(Number(selectedModel.avg_hit_rate || 0) * 100).toFixed(2)}% ` +
          `(${Number(selectedModel.avg_hits || 0).toFixed(2)} số/kỳ)`
        );
      }
      return lines.map(line => line ? escapeHtml(line) : "").join("<br>");
    }

    // ----- Kết quả AI predict -----
    // Chuẩn hóa payload từ backend AI và render ra phần Tóm tắt AI / Chi tiết dự đoán.
    async function predictWithAiBackend(type, count, kenoLevel = 0, engine = "gen_local", riskMode = "balanced", predictionMode = PREDICTION_MODE_NORMAL) {
      const params = new URLSearchParams();
      params.set("type", type);
      params.set("count", String(count));
      if (type === "KENO") params.set("kenoLevel", String(kenoLevel));
      params.set("engine", String(engine || "gen_local"));
      params.set("riskMode", normalizePredictRiskMode(riskMode));
      params.set("predictionMode", normalizePredictionMode(predictionMode));
      try {
        return await api(`/api/ai-predict?${params.toString()}`);
      } catch (err) {
        if (isAiPredictRouteMissingError(err)) {
          throw new Error("Server đang chạy bản cũ và chưa hỗ trợ /api/ai-predict. Hãy tắt server rồi chạy lại .\\chay_lotto_web.bat.");
        }
        throw err;
      }
    }

    function formatPredictRemaining(ms) {
      const totalSeconds = Math.max(0, Math.ceil((Number(ms) || 0) / 1000));
      const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
      const seconds = String(totalSeconds % 60).padStart(2, "0");
      return `${minutes}:${seconds}`;
    }

    function renderPredictLoadingText(engineKey, engineLabel, elapsedMs = 0) {
      if (engineKey === "both") {
        const remainingMs = Math.max(0, predictBothAvgDurationMs - Math.max(0, elapsedMs));
        return `Đang đồng bộ dữ liệu AI và chạy đồng thời Luận Số + AI Gen... (Thời gian còn lại: ${formatPredictRemaining(remainingMs)})`;
      }
      return `Đang đồng bộ dữ liệu AI và chạy ${engineLabel}...`;
    }

    function startPredictLoading(out, engineKey, engineLabel) {
      if (!out) return;
      if (predictLoadingTimer) {
        window.clearInterval(predictLoadingTimer);
        predictLoadingTimer = null;
      }
      predictLoadingStartAt = Date.now();
      predictLoadingEngineKey = String(engineKey || "");
      line(out, renderPredictLoadingText(engineKey, engineLabel, 0), "muted");
      if (engineKey !== "both") {
        return;
      }
      predictLoadingTimer = window.setInterval(() => {
        const elapsedMs = Date.now() - predictLoadingStartAt;
        line(out, renderPredictLoadingText(engineKey, engineLabel, elapsedMs), "muted");
      }, 500);
    }

    function stopPredictLoading(engineKey, durationMs = 0) {
      if (predictLoadingTimer) {
        window.clearInterval(predictLoadingTimer);
        predictLoadingTimer = null;
      }
      if (engineKey === "both" && Number.isFinite(durationMs) && durationMs > 0) {
        const nextAvg = Math.round((predictBothAvgDurationMs * 0.7) + (durationMs * 0.3));
        predictBothAvgDurationMs = Math.max(5000, Math.min(60000, nextAvg));
      }
      predictLoadingStartAt = 0;
      predictLoadingEngineKey = "";
    }

    function formatAiPredictionText(result) {
      const sync = result?.sync || {};
      const model = result?.model || {};
      const tickets = Array.isArray(result?.tickets) ? result.tickets : [];
      const topRanking = Array.isArray(result?.topRanking) ? result.topRanking : [];
      const topSpecialRanking = Array.isArray(result?.topSpecialRanking) ? result.topSpecialRanking : [];
      const notes = Array.isArray(result?.notes) ? result.notes : [];
      const ticketSources = Array.isArray(result?.ticketSources) ? result.ticketSources : [];
      const backtest = result?.backtest || {};
      const type = String(result?.type || "");
      const engine = String(result?.engine || "gen_local").trim().toLowerCase();
      const selectedEngine = getPredictEngineMeta(engine);
      const engineLabel = String(result?.engineLabel || selectedEngine.label || "AI Gen").trim();
      const riskMode = getResultRiskMode(result, predictRiskModeValue);
      const riskModeMeta = getPredictRiskModeMeta(riskMode);
      const isAiGenEngine = engine === "gen_local" || engine === "both";
      const isLuanSoEngine = engine === "luan_so";
      const adaptiveVipMeta = getAdaptiveVipPredictorMeta(result);
      const isPredictorV2 = adaptiveVipMeta.active;
      const syncReady = sync?.bootstrapComplete !== false || Boolean(sync?.sourceLimited);
      const isReady = result?.ready !== false && (result?.bootstrapComplete !== false || syncReady);
      const getTicketSourceLabel = index => {
        const rawSource = String(ticketSources[index] || "").trim().toLowerCase();
        if (adaptiveVipMeta.active && rawSource === adaptiveVipMeta.key) return adaptiveVipMeta.sourceLabel;
        if (rawSource === "loto_5_35_vip") return "Loto 5/35 Vip";
        if (rawSource === "predictor_v2" || rawSource === "vip_v2") return "Predictor V2";
        if (rawSource === "mega_6_45_vip") return "Mega 6/45 Vip";
        if (rawSource === "power_6_55_vip") return "Power 6/55 Vip";
        if (rawSource === "luan_so") return "Luận Số";
        if (rawSource === "gen_local" || rawSource === "ai_gen" || rawSource === "ai gen") return "AI GEN";
        if (adaptiveVipMeta.active && engine === adaptiveVipMeta.key) return adaptiveVipMeta.sourceLabel;
        if (engine === "loto_5_35_vip") return "Loto 5/35 Vip";
        if (engine === "predictor_v2") return "Predictor V2";
        if (engine === "mega_6_45_vip") return "Mega 6/45 Vip";
        if (engine === "power_6_55_vip") return "Power 6/55 Vip";
        if (engine === "both") return index % 2 === 0 ? "Luận Số" : "AI GEN";
        if (engine === "luan_so") return "Luận Số";
        return "AI GEN";
      };
      const formatCount = value => Number(value || 0).toLocaleString("vi-VN");
      const backtestRate = Number(model.avgHitRate || backtest?.avgHitRate || 0);
      const backtestHits = Number(model.avgHits || backtest?.avgHits || 0);
      const backtestSamples = Number(model.samples || backtest?.samples || 0);
      const playModeLabel = String(result?.playMode || predictPlayModeValue || "normal").trim().toLowerCase() === "bao" ? "Bao Số" : "Vé Thường";
      const compactTop = type === "KENO" ? topRanking.slice(0, 20) : topRanking.slice(0, 8);
      const topSpecialCompact = topSpecialRanking.slice(0, 4);
      const metricCards = [];
      const notesPool = [];
      const parseMetricRate = value => {
        const numeric = Number(value);
        return Number.isFinite(numeric) ? numeric : null;
      };
      const buildMetricDelta = (currentValue, baselineValue) => {
        const current = parseMetricRate(currentValue);
        const baseline = parseMetricRate(baselineValue);
        if (current == null || baseline == null) return null;
        const delta = current - baseline;
        const absDelta = Math.abs(delta);
        const direction = absDelta < 0.00005 ? "flat" : delta > 0 ? "up" : "down";
        const prefix = direction === "flat" ? "±" : delta > 0 ? "+" : "-";
        return {
          value: delta,
          direction,
          text: `${prefix}${(absDelta * 100).toFixed(2)}%`,
        };
      };
      const addMetricCard = (label, value, meta = "", accent = "", delta = null) => {
        const safeLabel = String(label || "").trim();
        const safeValue = String(value || "").trim();
        const safeMeta = String(meta || "").trim();
        if (!safeLabel || !safeValue) return;
        metricCards.push({
          label: safeLabel,
          value: safeValue,
          meta: safeMeta,
          accent: String(accent || "").trim(),
          delta: delta && typeof delta === "object" ? delta : null,
        });
      };
      const addNote = value => {
        const text = String(value || "").trim();
        if (text) notesPool.push(text);
      };
      const formatTopRowsHtml = (numbers, { special = false } = {}) => {
        if (!Array.isArray(numbers) || !numbers.length) return "";
        if (type === "KENO" && !special) {
          return formatKenoNumberRows(numbers, 10)
            .map(row => `<div class="ai-result-top-row">${escapeHtml(row.replace(/,\s*/g, " "))}</div>`)
            .join("");
        }
        if (TYPES[type]?.threeDigit && !special) {
          return formatPredictNumberRows(numbers, type, 10)
            .map(row => `<div class="ai-result-top-row">${escapeHtml(row.replace(/,\s*/g, " "))}</div>`)
            .join("");
        }
        const text = numbers.map(number => formatPredictNumber(number, type)).join(", ");
        return `<div class="ai-result-top-row">${escapeHtml(text)}</div>`;
      };
      const formatTicketNumbersHtml = ticket => {
        const main = Array.isArray(ticket?.main) ? ticket.main : [];
        if (type === "KENO") {
          const rows = formatKenoNumberRows(main, 10);
          return rows.map(row => `<div class="ai-result-ticket-row">${escapeHtml(row.replace(/,\s*/g, " "))}</div>`).join("");
        }
        if (TYPES[type]?.threeDigit && main.length) {
          return `<div class="ai-result-ticket-main">${escapeHtml(main.map(number => formatPredictNumber(number, type)).join(" | "))}</div>`;
        }
        if (TYPES[type]?.threeDigit && main.length > 10) {
          const rows = formatPredictNumberRows(main, type, 10);
          return rows.map(row => `<div class="ai-result-ticket-row">${escapeHtml(row.replace(/,\s*/g, " "))}</div>`).join("");
        }
        return `<div class="ai-result-ticket-main">${escapeHtml(main.map(number => formatPredictNumber(number, type)).join(" "))}</div>`;
      };
      const formatTicketSpecialHtml = ticket => {
        if (type === "KENO") return "";
        if (TYPES[type]?.hasSpecial && Number.isInteger(ticket?.special)) {
          return `<div class="ai-result-ticket-special">ĐB ${escapeHtml(formatPredictNumber(ticket.special, type))}</div>`;
        }
        return "";
      };
      const backtestText = !isReady
        ? "Chưa mở"
        : backtestSamples || backtestRate
        ? `${(backtestRate * 100).toFixed(2)}%`
        : "Chưa đủ mẫu";
      const backtestMeta = !isReady
        ? "Chờ bootstrap full-history hoàn tất"
        : backtestSamples
        ? `${formatCount(backtestSamples)} mẫu • ${backtestHits.toFixed(2)} số/kỳ`
        : "Đang dùng kết quả backtest hiện có";
      const previousComparableEntry = findPreviousPredictionLogForMetrics(result);
      const comparedMetaSuffix = previousComparableEntry ? " • So với lần trước cùng cấu hình" : "";
      const previousBacktestRate = parseMetricRate(previousComparableEntry?.backtest?.avgHitRate);
      const backtestDelta = buildMetricDelta(backtestRate, previousBacktestRate);
      if (model?.label) {
        addMetricCard(
          isAiGenEngine ? "Champion" : "Model thắng",
          model.label,
          [model?.key ? `Key ${model.key}` : "", result?.historyCount ? `${formatCount(result.historyCount)} kỳ train` : "", result?.latestKy ? `Mới nhất ${formatLiveKy(result.latestKy)}` : ""].filter(Boolean).join(" • ")
        );
      } else if (result?.historyCount) {
        addMetricCard("Số kỳ train", formatCount(result.historyCount), result?.latestKy ? `Mới nhất ${formatLiveKy(result.latestKy)}` : "");
      }
      addMetricCard("Độ khớp backtest", backtestText, `${backtestMeta}${comparedMetaSuffix}`, "", backtestDelta);
      if (isAiGenEngine) {
        const confidence = Number(result?.confidence || 0);
        const stabilityScore = parseMetricRate(result?.stabilityScore ?? backtest?.stabilityScore);
        const stabilityValue = stabilityScore != null ? stabilityScore : confidence;
        const previousStabilityValue = parseMetricRate(
          previousComparableEntry?.stabilityScore ??
          previousComparableEntry?.backtest?.stabilityScore ??
          previousComparableEntry?.confidence
        );
        const stabilityDelta = buildMetricDelta(stabilityValue, previousStabilityValue);
        addMetricCard(
          "Độ ổn định",
          `${(stabilityValue * 100).toFixed(2)}%`,
          `Tự điều chỉnh theo dữ liệu mới${comparedMetaSuffix}`,
          "",
          stabilityDelta
        );
      }
      if (engine === "both" && result?.metaSelectionMode === "smart_interleave") {
        const preferredEngineLabel = String(result?.metaPreferredEngine || "").trim().toLowerCase() === "gen_local" ? "AI Gen" : "Luận Số";
        addMetricCard("Meta ưu tiên", preferredEngineLabel, result?.metaSummary || "Đang tự cân đối theo phong độ gần đây", "preferred");
      }
      // predictor_v2 integration start
      if (isPredictorV2) {
        const qualityScore = Number(result?.qualityScore ?? result?.quality_score ?? 0);
        const trackingState = result?.tracking_state || {};
        const deepEnabled = Boolean(result?.deep_enabled);
        const deepStatus = String(result?.deep_status || "").trim() || "fallback_heuristic_only";
        const deepStatusLine = String(result?.deep_status_line || "").trim();
        const prioritizedCount = Array.isArray(trackingState?.prioritized_special)
          ? trackingState.prioritized_special.length
          : Array.isArray(trackingState?.prioritized_bonus)
          ? trackingState.prioritized_bonus.length
          : 0;
        const prioritizedLabel = type === "LOTO_6_55" ? "Special" : "Bonus";
        const slotMeta = [String(result?.target_date || "").trim(), String(result?.target_slot || "").trim()].filter(Boolean).join(" • ") || "-";
        if (qualityScore > 0) {
          addMetricCard(
            "Chất lượng vé",
            `${qualityScore.toFixed(2)}/100`,
            `${String(result?.regimeLabel || result?.regime || "Neutral")} • ${slotMeta}`,
            "preferred"
          );
        }
        addMetricCard(
          "Deep Status",
          deepEnabled ? "ACTIVE" : deepStatus.toUpperCase(),
          deepStatusLine || (deepEnabled ? "CNN/RNN deep scoring is active." : "Heuristic-only fallback is active.")
        );
        addMetricCard(
          "Bộ nhớ giữ nhịp",
          `${Array.isArray(trackingState?.kept_numbers) ? trackingState.kept_numbers.length : 0} giữ • ${Array.isArray(trackingState?.temporary_excluded_numbers) ? trackingState.temporary_excluded_numbers.length : 0} cooldown`,
          `Hot ${Array.isArray(trackingState?.true_hot_numbers) ? trackingState.true_hot_numbers.length : 0} • ${prioritizedLabel} ${prioritizedCount}`
        );
      }
      // predictor_v2 integration end
      if (isLuanSoEngine && result?.signalSummary) {
        const signal = result.signalSummary || {};
          const directionLabel = signal.dominantDirection === "backward"
            ? "Backward"
            : signal.dominantDirection === "forward"
            ? "Forward"
            : "Chưa rõ";
        addMetricCard(
          "Tín hiệu chính",
          `${directionLabel} • W=${Number(signal.dominantWindow || 0) || "-"}`,
          `${Number(signal.strongPairCount || 0)} Strong • ${Number(signal.watchPairCount || 0)} Watchlist`
        );
      }

      if (!isReady) {
        addNote(
          !syncReady
            ? "Dữ liệu lịch sử chưa sẵn sàng. Predictor sẽ mở lại khi bootstrap hoàn tất."
            : "Predictor đang tạm khóa cho tới khi dữ liệu canonical sẵn sàng."
        );
        (isPredictorV2 ? notes.slice(0, 3) : notes.slice(0, 1)).forEach(addNote);
      } else {
        if (type === "KENO" && (result?.predictedLn || result?.predictedCl)) {
          const quickFlags = [result?.predictedLn, result?.predictedCl].filter(Boolean).join(" • ");
          if (quickFlags) addNote(`Dự đoán nhanh: ${quickFlags}`);
        }
        if (isPredictorV2 && (result?.target_slot || result?.target_date)) {
          const targetMeta = [String(result?.target_date || "").trim(), String(result?.target_slot || "").trim()].filter(Boolean).join(" • ");
          addNote(`Khung Vip mục tiêu: ${targetMeta}`);
        }
        (isPredictorV2 ? notes.slice(0, 3) : notes.slice(0, 1)).forEach(addNote);
      }
      const heroBadges = [
        engineLabel,
        playModeLabel,
        engine === "both" ? riskModeMeta.label : "",
        result?.nextKy ? `Kỳ ${result.nextKy}` : "",
        String(result?.playMode || predictPlayModeValue || "normal").trim().toLowerCase() === "bao" && (result?.baoLevel || predictBaoLevelValue) ? `Bao ${result?.baoLevel || predictBaoLevelValue}` : "",
        type === "KENO" && result?.pickSize ? `Bậc ${result.pickSize}` : "",
      ].filter(Boolean);
      const headerNote = result?.lastTrainedAt
        ? `Học gần nhất: ${String(result.lastTrainedAt).replace("T", " ")}`
        : "";
      const ticketCardsHtml = isReady && tickets.length
        ? tickets.map((ticket, index) => {
            const isBaoTicket = String(ticket?.playMode || "").trim().toLowerCase() === "bao";
            const isThreeDigitTicket = !!TYPES[type]?.threeDigit;
            const ticketLabel = isBaoTicket
              ? `Bộ ${index + 1} • Bao ${ticket?.baoLevel || (ticket?.main || []).length || ""}`.trim()
              : `Bộ ${index + 1}`;
            const sourceLabel = engine === "both" ? getTicketSourceLabel(index) : engineLabel;
            if (isThreeDigitTicket) {
              return `
                <article class="ai-result-ticket-card ai-result-ticket-card-inline">
                  <div class="ai-result-ticket-inline-main">
                    <div class="ai-result-ticket-label">${escapeHtml(ticketLabel)}</div>
                    <div class="ai-result-ticket-body">
                      ${formatTicketNumbersHtml(ticket)}
                      ${formatTicketSpecialHtml(ticket)}
                    </div>
                  </div>
                  <div class="ai-result-ticket-source">${escapeHtml(sourceLabel)}</div>
                </article>
              `;
            }
            return `
              <article class="ai-result-ticket-card">
                <div class="ai-result-ticket-head">
                  <div class="ai-result-ticket-label">${escapeHtml(ticketLabel)}</div>
                  <div class="ai-result-ticket-source">${escapeHtml(sourceLabel)}</div>
                </div>
                <div class="ai-result-ticket-body">
                  ${formatTicketNumbersHtml(ticket)}
                  ${formatTicketSpecialHtml(ticket)}
                </div>
              </article>
            `;
          }).join("")
        : `<div class="ai-result-empty">${escapeHtml(notesPool[0] || "Dữ liệu dự đoán chưa sẵn sàng.")}</div>`;
      const topSectionHtml = (compactTop.length || topSpecialCompact.length)
        ? `<section class="ai-result-block ai-result-top-block">
            <div class="ai-result-block-head">
              <div class="ai-result-block-title">Top số ưu tiên</div>
              <div class="ai-result-block-meta">${escapeHtml(type === "KENO" ? "Top 20" : `Top ${compactTop.length}`)}</div>
            </div>
            ${compactTop.length ? `
              <div class="ai-result-top-item">
                <div class="ai-result-top-label">Top số</div>
                <div class="ai-result-top-body">${formatTopRowsHtml(compactTop)}</div>
              </div>
            ` : ""}
            ${topSpecialCompact.length ? `
              <div class="ai-result-top-item">
                <div class="ai-result-top-label">Top ĐB</div>
                <div class="ai-result-top-body">${formatTopRowsHtml(topSpecialCompact, { special: true })}</div>
              </div>
            ` : ""}
          </section>`
        : "";
      const notesHtml = notesPool.length
        ? `<section class="ai-result-block">
            <div class="ai-result-block-head">
              <div class="ai-result-block-title">Ghi chú</div>
              <div class="ai-result-block-meta">AI</div>
            </div>
            <div class="ai-result-notes">${notesPool.map(note => `<div class="ai-result-note-line">${escapeHtml(note)}</div>`).join("")}</div>
          </section>`
        : "";
      const heroHeaderItems = [
        ...heroBadges.map(badge => {
          const isRiskBadge = engine === "both" && badge === riskModeMeta.label;
          const riskClass = isRiskBadge ? ` ai-result-badge-risk is-${riskMode}` : "";
          return `<span class="ai-result-badge${riskClass}">${escapeHtml(badge)}</span>`;
        }),
        headerNote ? `<span class="ai-result-badge ai-result-badge-note">${escapeHtml(headerNote)}</span>` : "",
      ].filter(Boolean).join("");
      return `<div class="ai-result-shell">
        ${heroHeaderItems ? `
          <section class="ai-result-hero ai-result-hero-compact">
            <div class="ai-result-badges">${heroHeaderItems}</div>
          </section>
        ` : ""}
        ${metricCards.length ? `
          <section class="ai-result-metrics">
            ${metricCards.map(card => `
              <article class="ai-result-metric${card.accent ? ` is-${card.accent}` : ""}">
                <div class="ai-result-metric-label">${escapeHtml(card.label)}</div>
                <div class="ai-result-metric-main">
                  <div class="ai-result-metric-value">${escapeHtml(card.value)}</div>
                  ${card.delta ? `<div class="ai-result-metric-delta is-${escapeHtml(card.delta.direction || "flat")}">${escapeHtml(card.delta.text || "")}</div>` : ""}
                </div>
                ${card.meta ? `<div class="ai-result-metric-meta">${escapeHtml(card.meta)}</div>` : ""}
              </article>
            `).join("")}
          </section>
        ` : ""}
        <section class="ai-result-block ai-result-ticket-block">
          <div class="ai-result-block-head">
            <div class="ai-result-block-title">Chi tiết dự đoán</div>
            <div class="ai-result-block-meta">${escapeHtml(isReady ? `${tickets.length || 0} bộ số` : "Trạng thái dữ liệu")}</div>
          </div>
          <div class="ai-result-ticket-grid">${ticketCardsHtml}</div>
        </section>
        ${topSectionHtml}
        ${notesHtml}
      </div>`;
    }

    function renderPredictOutput(result = predictLastDisplayResult) {
      const out = document.getElementById("predictOut");
      if (!out) return;
      predictLastDisplayResult = result || predictLastDisplayResult || null;
      if (!predictLastDisplayResult) return;
      out.classList.remove("muted");
      out.innerHTML = formatAiPredictionText(predictLastDisplayResult);
    }

    function getAdaptiveVipPredictorMeta(result = {}) {
      const version = String(result?.predictorVersion || "").trim().toLowerCase();
      if (version === "loto_5_35_vip_v1") {
        return {
          active: true,
          key: "loto_5_35_vip",
          label: String(result?.engineLabel || "Loto 5/35 Vip Adaptive").trim() || "Loto 5/35 Vip Adaptive",
          sourceLabel: "Loto 5/35 Vip",
        };
      }
      if (version === "predictor_v2") {
        return {
          active: true,
          key: "predictor_v2",
          label: String(result?.engineLabel || "Predictor V2 Vip").trim() || "Predictor V2 Vip",
          sourceLabel: "Predictor V2",
        };
      }
      if (version === "mega_6_45_vip_v1") {
        return {
          active: true,
          key: "mega_6_45_vip",
          label: String(result?.engineLabel || "Mega 6/45 Vip Adaptive").trim() || "Mega 6/45 Vip Adaptive",
          sourceLabel: "Mega 6/45 Vip",
        };
      }
      if (version === "power_6_55_vip_v1") {
        return {
          active: true,
          key: "power_6_55_vip",
          label: String(result?.engineLabel || "Power 6/55 Vip Adaptive").trim() || "Power 6/55 Vip Adaptive",
          sourceLabel: "Power 6/55 Vip",
        };
      }
      return {
        active: false,
        key: "",
        label: "",
        sourceLabel: "",
      };
    }

    function getPredictVipTicketSourceLabel(result, index) {
      const ticketSources = Array.isArray(result?.ticketSources) ? result.ticketSources : [];
      const rawSource = String(ticketSources[index] || "").trim().toLowerCase();
      const engine = String(result?.engine || "gen_local").trim().toLowerCase();
      const adaptiveVipMeta = getAdaptiveVipPredictorMeta(result);
      if (adaptiveVipMeta.active && rawSource === adaptiveVipMeta.key) return adaptiveVipMeta.sourceLabel;
      if (rawSource === "loto_5_35_vip") return "Loto 5/35 Vip";
      if (rawSource === "predictor_v2" || rawSource === "vip_v2") return "Predictor V2";
      if (rawSource === "mega_6_45_vip") return "Mega 6/45 Vip";
      if (rawSource === "power_6_55_vip") return "Power 6/55 Vip";
      if (rawSource === "luan_so") return "Luận Số";
      if (rawSource === "gen_local" || rawSource === "ai_gen" || rawSource === "ai gen") return "AI GEN";
      if (adaptiveVipMeta.active && engine === adaptiveVipMeta.key) return adaptiveVipMeta.sourceLabel;
      if (engine === "loto_5_35_vip") return "Loto 5/35 Vip";
      if (engine === "predictor_v2") return "Predictor V2";
      if (engine === "mega_6_45_vip") return "Mega 6/45 Vip";
      if (engine === "power_6_55_vip") return "Power 6/55 Vip";
      if (engine === "both") return index % 2 === 0 ? "Luận Số" : "AI GEN";
      if (engine === "luan_so") return "Luận Số";
      return "AI GEN";
    }

    function formatPredictVipTicketLabel(type, ticket, index) {
      const isBaoTicket = String(ticket?.playMode || "").trim().toLowerCase() === "bao";
      if (isBaoTicket) {
        const baoLevel = Number(ticket?.baoLevel || (Array.isArray(ticket?.main) ? ticket.main.length : 0) || 0);
        return `Bộ ${index + 1} • Bao ${baoLevel || ""}`.trim();
      }
      if (type === "KENO" && Number.isInteger(Number(ticket?.main?.length || 0))) {
        return `Bộ ${index + 1} • Bậc ${Number(ticket.main.length || 0)}`;
      }
      return `Bộ ${index + 1}`;
    }

    function formatPredictVipTopRows(numbers, type, perRow = 10) {
      const values = Array.isArray(numbers) ? numbers.map(Number).filter(Number.isInteger) : [];
      if (!values.length) return "";
      if (type === "KENO") {
        return formatKenoNumberRows(values, perRow)
          .map(row => `<div class="predict-vip-top-row">${escapeHtml(row.replace(/,\s*/g, " "))}</div>`)
          .join("");
      }
      if (TYPES[type]?.threeDigit) {
        return formatPredictNumberRows(values, type, perRow)
          .map(row => `<div class="predict-vip-top-row">${escapeHtml(row.replace(/,\s*/g, " "))}</div>`)
          .join("");
      }
      return `<div class="predict-vip-top-row">${escapeHtml(values.map(number => formatPredictNumber(number, type)).join(" "))}</div>`;
    }

    function renderPredictVipTicketNumbers(ticket, type) {
      const main = Array.isArray(ticket?.main) ? ticket.main.map(Number).filter(Number.isInteger) : [];
      const tokens = main.map(number => `<span class="predict-vip-number">${escapeHtml(formatPredictNumber(number, type))}</span>`);
      if (TYPES[type]?.hasSpecial && Number.isInteger(ticket?.special)) {
        tokens.push(`<span class="predict-vip-number is-special">ĐB ${escapeHtml(formatPredictNumber(ticket.special, type))}</span>`);
      }
      return `<div class="predict-vip-number-list">${tokens.join("")}</div>`;
    }

    function buildPredictVipTicketAnalyses(result) {
      const type = String(result?.type || "").trim().toUpperCase();
      const tickets = Array.isArray(result?.tickets) ? result.tickets : [];
      const topRanking = Array.isArray(result?.topRanking) ? result.topRanking.map(Number).filter(Number.isInteger) : [];
      const topSpecialRanking = Array.isArray(result?.topSpecialRanking) ? result.topSpecialRanking.map(Number).filter(Number.isInteger) : [];
      const topMainIndex = new Map(topRanking.map((number, index) => [number, index]));
      const topSpecialIndex = new Map(topSpecialRanking.map((number, index) => [number, index]));
      const preferredEngine = String(result?.metaPreferredEngine || "").trim().toLowerCase();
      return tickets.map((ticket, index) => {
        const main = Array.isArray(ticket?.main) ? ticket.main.map(Number).filter(Number.isInteger) : [];
        const sourceLabel = getPredictVipTicketSourceLabel(result, index);
        const sourceKey = sourceLabel === "Luận Số" ? "luan_so" : "gen_local";
        const topCoverage = main.reduce((sum, number) => sum + (topMainIndex.has(number) ? 1 : 0), 0);
        const topWeight = main.reduce((sum, number) => {
          if (!topMainIndex.has(number)) return sum;
          return sum + Math.max(1, topRanking.length - topMainIndex.get(number));
        }, 0);
        const specialWeight = Number.isInteger(ticket?.special) && topSpecialIndex.has(Number(ticket.special))
          ? Math.max(1, topSpecialRanking.length - topSpecialIndex.get(Number(ticket.special)))
          : 0;
        const sourceBonus = preferredEngine && preferredEngine === sourceKey ? 6 : 0;
        const score = topWeight + (topCoverage * 4) + (specialWeight * 3) + sourceBonus;
        return {
          ticket,
          index,
          label: formatPredictVipTicketLabel(type, ticket, index),
          sourceLabel,
          sourceKey,
          topCoverage,
          score,
        };
      }).sort((a, b) => {
        if (b.score !== a.score) return b.score - a.score;
        if (b.topCoverage !== a.topCoverage) return b.topCoverage - a.topCoverage;
        return a.index - b.index;
      });
    }

    function getPredictVipHedgePair(analyses) {
      const primary = analyses[0] || null;
      if (!primary) return { primary: null, risky: null };
      const primarySet = new Set(Array.isArray(primary.ticket?.main) ? primary.ticket.main.map(Number) : []);
      const risky = analyses.slice(1).map(item => {
        const main = Array.isArray(item.ticket?.main) ? item.ticket.main.map(Number) : [];
        const overlap = main.reduce((sum, number) => sum + (primarySet.has(number) ? 1 : 0), 0);
        const diversity = Math.max(0, main.length - overlap);
        const hedgeScore = (item.score * 0.68) + (diversity * 5) + (item.sourceKey !== primary.sourceKey ? 2 : 0);
        return { ...item, hedgeScore };
      }).sort((a, b) => {
        if (b.hedgeScore !== a.hedgeScore) return b.hedgeScore - a.hedgeScore;
        return b.score - a.score;
      })[0] || null;
      return { primary, risky };
    }

    function renderPredictVipTicketCard(item, type, title) {
      if (!item) return "";
      return `
        <article class="predict-vip-card-item">
          <div class="predict-vip-card-head">
            <div class="predict-vip-card-title">${escapeHtml(title || item.label || `Bộ ${item.index + 1}`)}</div>
            <div class="predict-vip-card-source">${escapeHtml(item.sourceLabel || "AI")}</div>
          </div>
          ${renderPredictVipTicketNumbers(item.ticket, type)}
          <div class="predict-vip-note">${escapeHtml(`${item.label} • Độ phủ top ${item.topCoverage}/${Array.isArray(item.ticket?.main) ? item.ticket.main.length : 0}`)}</div>
        </article>
      `;
    }

    function formatPredictVipOutput(result = vipPredictLastDisplayResult) {
      const type = String(result?.type || "").trim().toUpperCase();
      if (!result || !AI_PREDICT_TYPES.has(type)) {
        return "Chọn cấu hình Vip rồi bấm Dự đoán Vip để xem bộ ưu tiên chính và thống kê riêng.";
      }
      return formatAiPredictionText(result);
    }

    function renderPredictVipOutput(result = vipPredictLastDisplayResult) {
      const out = document.getElementById("predictVipOut");
      if (!out) return;
      vipPredictLastDisplayResult = result || vipPredictLastDisplayResult || null;
      const hasResult = !!vipPredictLastDisplayResult;
      out.classList.toggle("muted", !hasResult);
      out.innerHTML = formatPredictVipOutput(vipPredictLastDisplayResult);
    }

    function escapeHtml(value) {
      return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }

    function formatLiveKy(ky) {
      const digits = String(ky || "").replace(/\D/g, "");
      return digits ? `#${digits}` : "";
    }

    function parseLiveDate(value) {
      const text = String(value || "").trim();
      const match = text.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
      if (!match) return null;
      const day = Number(match[1]);
      const month = Number(match[2]);
      const year = Number(match[3]);
      const parsed = new Date(year, month - 1, day);
      if (
        !Number.isFinite(day) ||
        !Number.isFinite(month) ||
        !Number.isFinite(year) ||
        parsed.getFullYear() !== year ||
        parsed.getMonth() !== month - 1 ||
        parsed.getDate() !== day
      ) {
        return null;
      }
      return parsed;
    }

    function formatLiveWeekday(dateText) {
      const parsed = parseLiveDate(dateText);
      if (!parsed) return "";
      const day = parsed.getDay();
      return day === 0 ? "Chủ nhật" : `Thứ ${day + 1}`;
    }

    function formatLiveWeekdayFromDate(dateValue) {
      if (!(dateValue instanceof Date) || Number.isNaN(dateValue.getTime())) return "";
      const day = dateValue.getDay();
      return day === 0 ? "Chủ nhật" : `Thứ ${day + 1}`;
    }

    function formatLiveDateFromDate(dateValue) {
      if (!(dateValue instanceof Date) || Number.isNaN(dateValue.getTime())) return "";
      const day = String(dateValue.getDate()).padStart(2, "0");
      const month = String(dateValue.getMonth() + 1).padStart(2, "0");
      const year = dateValue.getFullYear();
      return `${day}/${month}/${year}`;
    }

    function parseScheduleTimeToMinutes(value) {
      const match = String(value || "").trim().match(/^(\d{1,2}):(\d{2})$/);
      if (!match) return null;
      const hours = Number(match[1]);
      const minutes = Number(match[2]);
      if (!Number.isFinite(hours) || !Number.isFinite(minutes) || hours < 0 || hours > 23 || minutes < 0 || minutes > 59) {
        return null;
      }
      return hours * 60 + minutes;
    }

    function buildScheduleDate(baseDate, minutesFromMidnight) {
      if (!(baseDate instanceof Date) || Number.isNaN(baseDate.getTime()) || !Number.isFinite(minutesFromMidnight)) return null;
      const candidate = new Date(baseDate.getFullYear(), baseDate.getMonth(), baseDate.getDate(), 0, 0, 0, 0);
      candidate.setMinutes(minutesFromMidnight);
      return candidate;
    }

    function formatDrawCountdown(totalMs) {
      const safeMs = Math.max(0, Number(totalMs || 0));
      const totalSeconds = Math.floor(safeMs / 1000);
      const hours = Math.floor(totalSeconds / 3600);
      const minutes = Math.floor((totalSeconds % 3600) / 60);
      const seconds = totalSeconds % 60;
      return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
    }

    function computeNextLiveKy(ky) {
      const digits = String(ky || "").replace(/\D/g, "");
      if (!digits) return "";
      const nextValue = Number(digits) + 1;
      if (!Number.isFinite(nextValue) || nextValue <= 0) return "";
      return formatLiveKy(String(nextValue));
    }

    function findNextLiveDrawDate(type, nowValue = new Date()) {
      const schedule = LIVE_DRAW_SCHEDULES[String(type || "").trim().toUpperCase()];
      const now = nowValue instanceof Date ? new Date(nowValue.getTime()) : new Date();
      if (!schedule || Number.isNaN(now.getTime())) return null;

      if (schedule.kind === "interval") {
        for (let offset = 0; offset <= 7; offset += 1) {
          const day = new Date(now.getFullYear(), now.getMonth(), now.getDate() + offset, 0, 0, 0, 0);
          for (let minutes = schedule.startMinutes; minutes <= schedule.endMinutes; minutes += schedule.stepMinutes) {
            const candidate = buildScheduleDate(day, minutes);
            if (candidate && candidate.getTime() > now.getTime()) return candidate;
          }
        }
        return null;
      }

      if (schedule.kind === "daily") {
        const slots = (schedule.slots || [])
          .map(parseScheduleTimeToMinutes)
          .filter(value => Number.isFinite(value))
          .sort((a, b) => a - b);
        for (let offset = 0; offset <= 2; offset += 1) {
          const day = new Date(now.getFullYear(), now.getMonth(), now.getDate() + offset, 0, 0, 0, 0);
          for (const minutes of slots) {
            const candidate = buildScheduleDate(day, minutes);
            if (candidate && candidate.getTime() > now.getTime()) return candidate;
          }
        }
        return null;
      }

      if (schedule.kind === "weekly") {
        const timeMinutes = parseScheduleTimeToMinutes(schedule.time);
        if (!Number.isFinite(timeMinutes)) return null;
        for (let offset = 0; offset <= 14; offset += 1) {
          const day = new Date(now.getFullYear(), now.getMonth(), now.getDate() + offset, 0, 0, 0, 0);
          if (!Array.isArray(schedule.weekdays) || !schedule.weekdays.includes(day.getDay())) continue;
          const candidate = buildScheduleDate(day, timeMinutes);
          if (candidate && candidate.getTime() > now.getTime()) return candidate;
        }
      }

      return null;
    }

    function buildUpcomingLiveMetaParts(type, item = null, nowValue = new Date()) {
      const nextDrawDate = findNextLiveDrawDate(type, nowValue);
      if (!nextDrawDate) return buildLiveMetaParts(item?.ky, item?.date, item?.time);
      const nextKyText = computeNextLiveKy(item?.ky);
      const parts = [];
      if (nextKyText) parts.push(`Kỳ ${nextKyText}`);
      const weekdayText = formatLiveWeekdayFromDate(nextDrawDate);
      if (weekdayText) parts.push(weekdayText);
      const dateText = formatLiveDateFromDate(nextDrawDate);
      if (dateText) parts.push(dateText);
      const timeText = `${String(nextDrawDate.getHours()).padStart(2, "0")}:${String(nextDrawDate.getMinutes()).padStart(2, "0")}`;
      if (timeText) parts.push(timeText);
      parts.push(formatDrawCountdown(nextDrawDate.getTime() - nowValue.getTime()));
      return parts.filter(Boolean);
    }

    function resolveLiveDrawDateTime(type, dateText, timeText) {
      const parsedDate = parseLiveDate(dateText);
      if (!parsedDate) return null;
      const parsedMinutes = parseScheduleTimeToMinutes(timeText);
      if (Number.isFinite(parsedMinutes)) return buildScheduleDate(parsedDate, parsedMinutes);
      const schedule = LIVE_DRAW_SCHEDULES[String(type || "").trim().toUpperCase()];
      if (!schedule) return parsedDate;
      if (schedule.kind === "weekly") {
        const fixedMinutes = parseScheduleTimeToMinutes(schedule.time);
        if (Number.isFinite(fixedMinutes)) return buildScheduleDate(parsedDate, fixedMinutes);
      }
      return parsedDate;
    }

    function getNthUpcomingDrawDate(type, baseDate, stepCount = 1) {
      let cursor = baseDate instanceof Date ? new Date(baseDate.getTime()) : new Date();
      let candidate = null;
      const safeSteps = Math.max(1, Number(stepCount || 1));
      for (let index = 0; index < safeSteps; index += 1) {
        candidate = findNextLiveDrawDate(type, new Date(cursor.getTime() + 1000));
        if (!candidate) return null;
        cursor = candidate;
      }
      return candidate;
    }

    function buildPredictionHistoryCountdownState(entry, nowValue = new Date()) {
      if (!entry || entry.resolved || entry.resultMissingData) return null;
      const type = String(entry.type || "").trim().toUpperCase();
      if (!type || !LIVE_DRAW_SCHEDULES[type]) return null;
      const predictedKyText = formatLiveKy(entry.predictedKy);
      const liveItem = liveResultsState?.[type] || null;
      const latestKyValue = Number(String(liveItem?.ky || "").replace(/\D/g, "")) || 0;
      const targetKyValue = Number(String(entry.predictedKy || "").replace(/\D/g, "")) || 0;
      const latestDrawDate = resolveLiveDrawDateTime(type, liveItem?.date, liveItem?.time);
      let targetDate = null;

      if (targetKyValue > 0 && latestKyValue > 0 && targetKyValue > latestKyValue && latestDrawDate) {
        targetDate = getNthUpcomingDrawDate(type, latestDrawDate, targetKyValue - latestKyValue);
      }

      if (!targetDate) {
        const createdDate = entry.createdAt ? new Date(entry.createdAt) : null;
        if (createdDate instanceof Date && !Number.isNaN(createdDate.getTime())) {
          targetDate = findNextLiveDrawDate(type, createdDate);
        }
      }

      if (!targetDate) {
        targetDate = findNextLiveDrawDate(type, nowValue);
      }

      if (!targetDate) return null;
      return {
        kyText: predictedKyText || computeNextLiveKy(liveItem?.ky),
        countdownText: formatDrawCountdown(targetDate.getTime() - nowValue.getTime()),
      };
    }

    function buildLiveMetaParts(ky, dateText, timeText) {
      const parts = [];
      const kyText = formatLiveKy(ky);
      const weekdayText = formatLiveWeekday(dateText);
      if (kyText) parts.push(`Kỳ ${kyText}`);
      if (weekdayText) parts.push(weekdayText);
      if (dateText) parts.push(String(dateText).trim());
      if (timeText) parts.push(String(timeText).trim());
      return parts.filter(Boolean);
    }

    function readLiveResultsCache() {
      return readJsonLocal(LIVE_RESULTS_CACHE_KEY, {});
    }

    function saveLiveResultsCache() {
      writeJsonLocal(LIVE_RESULTS_CACHE_KEY, {
        fetchedAt: liveResultsFetchedAt,
        results: liveResultsState
      });
    }

    function restoreLiveResultsCache() {
      const cached = readLiveResultsCache();
      liveResultsFetchedAt = String(cached?.fetchedAt || "");
      liveResultsState = cached?.results && typeof cached.results === "object" ? cached.results : {};
      startLiveDrawCountdown();
    }

    function normalizeLiveSyncTimingSamples(values) {
      if (!Array.isArray(values)) return [];
      return values
        .map(value => Math.round(Number(value || 0)))
        .filter(value => Number.isFinite(value) && value > 0)
        .slice(-5);
    }

    function readLiveSyncTimingCache() {
      const cached = readJsonLocal(LIVE_SYNC_TIMING_CACHE_KEY, {});
      return {
        manual_repair: normalizeLiveSyncTimingSamples(cached?.manual_repair),
        quick_live: normalizeLiveSyncTimingSamples(cached?.quick_live),
      };
    }

    function saveLiveSyncTimingCache(cache) {
      writeJsonLocal(LIVE_SYNC_TIMING_CACHE_KEY, {
        manual_repair: normalizeLiveSyncTimingSamples(cache?.manual_repair),
        quick_live: normalizeLiveSyncTimingSamples(cache?.quick_live),
      });
    }

    function getLiveSyncTimingBucket(repairCanonical) {
      return repairCanonical ? "manual_repair" : "quick_live";
    }

    function getLiveSyncFallbackSeconds(repairCanonical) {
      return repairCanonical ? 90 : 15;
    }

    function estimateLiveSyncSeconds(repairCanonical) {
      const bucket = getLiveSyncTimingBucket(repairCanonical);
      const samples = readLiveSyncTimingCache()[bucket] || [];
      if (!samples.length) return getLiveSyncFallbackSeconds(repairCanonical);
      const sorted = [...samples].sort((a, b) => a - b);
      const middle = Math.floor(sorted.length / 2);
      if (sorted.length % 2 === 1) return Math.max(1, sorted[middle]);
      return Math.max(1, Math.round((sorted[middle - 1] + sorted[middle]) / 2));
    }

    function rememberLiveSyncDuration(repairCanonical, durationMs) {
      const durationSeconds = Math.max(1, Math.round(Number(durationMs || 0) / 1000));
      if (!Number.isFinite(durationSeconds) || durationSeconds <= 0) return;
      const bucket = getLiveSyncTimingBucket(repairCanonical);
      const cache = readLiveSyncTimingCache();
      const samples = [...(cache[bucket] || []), durationSeconds].slice(-5);
      cache[bucket] = samples;
      saveLiveSyncTimingCache(cache);
    }

    function isLiveResultStored(item) {
      if (!item || !item.importable || !TYPES[item.key]) return false;
      const ky = formatLiveKy(item.ky);
      if (!ky) return false;
      const current = store.results[item.key]?.[ky];
      if (!current) return false;
      const currentMain = Array.isArray(current.main) ? [...current.main].sort((a, b) => a - b) : [];
      const nextMain = Array.isArray(item.main) ? [...item.main].map(Number).sort((a, b) => a - b) : [];
      const currentSpecial = current.special ?? null;
      const nextSpecial = Number.isInteger(Number(item.special)) ? Number(item.special) : null;
      return JSON.stringify(currentMain) === JSON.stringify(nextMain) && currentSpecial === nextSpecial;
    }

    function importLiveResult(item) {
      if (!item || !item.importable || !TYPES[item.key]) return false;
      const ky = formatLiveKy(item.ky);
      const main = Array.isArray(item.main) ? item.main.map(Number).filter(Number.isFinite).sort((a, b) => a - b) : [];
      if (!ky || !main.length) return false;
      const special = Number.isInteger(Number(item.special)) ? Number(item.special) : null;
      const current = store.results[item.key]?.[ky];
      if (current) {
        const currentMain = Array.isArray(current.main) ? [...current.main].sort((a, b) => a - b) : [];
        if (JSON.stringify(currentMain) === JSON.stringify(main) && (current.special ?? null) === special) {
          return false;
        }
      }
      putResult(item.key, ky, { main, special });
      return true;
    }

    function applyLiveResultsToStore(results) {
      const importedKeys = new Set();
      for (const item of (results || [])) {
        if (importLiveResult(item)) importedKeys.add(item.key);
      }
      return importedKeys;
    }

    function updateLiveAutoButton() {
      const btn = document.getElementById("liveAutoBtn");
      if (!btn) return;
      const running = !!liveAutoTimer;
      btn.textContent = running ? "Tắt tự động" : "Bật tự động";
      btn.classList.toggle("secondary", !running);
    }

    function renderLiveCardMainLines(typeKey, item) {
      if (typeKey === "KENO" && Array.isArray(item?.main) && item.main.length) {
        const sorted = [...item.main].map(Number).filter(Number.isFinite).sort((a, b) => a - b);
        const rows = [];
        for (let index = 0; index < sorted.length; index += 10) {
          rows.push(sorted.slice(index, index + 10));
        }
        return rows
          .filter(row => row.length)
          .map(row => `<div class="live-card-line primary keno-row">${escapeHtml(row.map(formatPredictNumber).join(" "))}</div>`)
          .join("");
      }
      return (item?.displayLines || [])
        .map((lineText, index) => `<div class="live-card-line ${index === 0 ? "primary" : ""}">${escapeHtml(lineText)}</div>`)
        .join("");
    }

    // ----- Giao diện live results và lịch sử CSV -----
    // Render bảng 6 loại vé, status Cập Nhật và nội dung Lịch Sử CSV theo canonical all_day.
    function renderLiveResultsBoard() {
      const host = document.getElementById("liveResultGrid");
      if (!host) return;
      const nowValue = new Date();
      host.innerHTML = LIVE_RESULT_TYPES.map(meta => {
        const badge = getLiveUpdateBadge(meta.key);
        const badgeClass = `live-card-badge ${liveUpdateBadgeClass(badge.code)}`.trim();
        const badgeText = badge.label || "Chờ cập nhật";
        const item = liveResultsState?.[meta.key];
        if (!item) {
          const pendingMetaParts = buildUpcomingLiveMetaParts(meta.key, null, nowValue);
          return `
            <article class="live-card pending">
              <div class="live-card-top">
                <span class="live-card-chip">Live</span>
                <span class="${badgeClass}" title="${escapeHtml(badge.message || badgeText)}">${escapeHtml(badgeText)}</span>
              </div>
              <h3 class="live-card-title">${escapeHtml(meta.label)}</h3>
              ${pendingMetaParts.length ? `<div class="live-card-meta">${escapeHtml(pendingMetaParts.join(" • "))}</div>` : ""}
              <div class="live-card-empty">Chưa có kết quả live cho loại này.</div>
            </article>
          `;
        }
        const metaParts = buildUpcomingLiveMetaParts(meta.key, item, nowValue);
        const lines = renderLiveCardMainLines(meta.key, item);
        let sourceHost = "";
        try {
          sourceHost = item.sourceUrl ? new URL(item.sourceUrl).hostname : "";
        } catch {
          sourceHost = "";
        }
        const footParts = [item.sourceDate ? `Nguồn ngày ${item.sourceDate}` : "", sourceHost].filter(Boolean);
        return `
          <article class="live-card" data-live-type="${meta.key}">
            <div class="live-card-top">
              <span class="live-card-chip">Live</span>
              <span class="${badgeClass}" title="${escapeHtml(badge.message || badgeText)}">${escapeHtml(badgeText)}</span>
            </div>
            <h3 class="live-card-title">${escapeHtml(meta.label)}</h3>
            <div class="live-card-meta">${escapeHtml(metaParts.join(" • "))}</div>
            <div class="live-card-main">${lines}</div>
            <div class="live-card-foot">${escapeHtml(footParts.join(" • "))}</div>
          </article>
        `;
      }).join("");
    }

    function setLiveStatus(message, cls = "") {
      const el = document.getElementById("liveSyncStatus");
      if (!el) return;
      line(el, message, cls);
    }

    let liveSyncCountdownTimer = null;
    let liveResultsProgressPollTimer = null;
    let liveResultsProgressSeenRunning = false;
    var liveDrawCountdownTimer = null;

    // ---abc--- Live Results / Countdown ---
    function startLiveDrawCountdown() {
      if (liveDrawCountdownTimer) return;
      liveDrawCountdownTimer = window.setInterval(() => {
        renderLiveResultsBoard();
        if (predictLastDisplayResult) renderPredictOutput();
        if (vipPredictLastDisplayResult) renderPredictVipOutput();
        if (predictionHistoryPanelOpen) renderPredictionHistoryPanel();
        if (vipPredictionHistoryPanelOpen) renderVipPredictionHistoryPanel();
      }, 1000);
    }

    function formatCountdownSeconds(totalSeconds) {
      const safeSeconds = Math.max(0, Number(totalSeconds || 0));
      const minutes = Math.floor(safeSeconds / 60);
      const seconds = safeSeconds % 60;
      return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
    }

    function stopLiveSyncCountdown() {
      if (liveSyncCountdownTimer) {
        clearInterval(liveSyncCountdownTimer);
        liveSyncCountdownTimer = null;
      }
    }

    function startLiveSyncCountdown({ repairCanonical = false, estimatedSeconds = null, note = "" } = {}) {
      stopLiveSyncCountdown();
      const numericEstimate = Number(estimatedSeconds);
      let remainingSeconds = Math.max(
        1,
        Math.round(Number.isFinite(numericEstimate) && numericEstimate > 0
          ? numericEstimate
          : getLiveSyncFallbackSeconds(repairCanonical))
      );
      let waitingForFinish = false;
      const prefix = repairCanonical ? "Đang cập nhật 6 loại từ MinhChinh" : "Đang cập nhật 6 loại";
      const noteSuffix = note ? `\n${note}` : "";
      setLiveStatus(`${prefix} • Ước tính còn ${formatCountdownSeconds(remainingSeconds)}.${noteSuffix}`, "muted");
      liveSyncCountdownTimer = setInterval(() => {
        if (remainingSeconds > 0) {
          remainingSeconds = Math.max(0, remainingSeconds - 1);
          setLiveStatus(`${prefix} • Ước tính còn ${formatCountdownSeconds(remainingSeconds)}.${noteSuffix}`, "muted");
          return;
        }
        if (!waitingForFinish) {
          waitingForFinish = true;
          setLiveStatus(`${prefix} • Đang hoàn tất xử lý, vui lòng chờ thêm...${noteSuffix}`, "muted");
          return;
        }
        stopLiveSyncCountdown();
      }, 1000);
    }

    function getLiveResultsCompatibilityFallbackNote() {
      return "Đang dùng chế độ tương thích do phiên cũ chưa hỗ trợ cập nhật nền.";
    }

    function isLiveResultsCompatibilityError(err, { allowNotFound = false } = {}) {
      const status = Number(err?.status || 0);
      if (status === 405) return true;
      if (allowNotFound && status === 404) return true;
      const message = String(err?.message || "").trim().toLowerCase();
      if (message.includes("method not allowed")) return true;
      if (allowNotFound && message.includes("not found")) return true;
      return false;
    }

    function stopLiveResultsProgressPolling(resetButton = true) {
      if (liveResultsProgressPollTimer) {
        clearInterval(liveResultsProgressPollTimer);
        liveResultsProgressPollTimer = null;
      }
      liveResultsProgressSeenRunning = false;
      if (resetButton && typeof liveResultsProgressButtonReset === "function") {
        liveResultsProgressButtonReset();
      }
      if (resetButton) {
        liveResultsProgressButtonReset = null;
      }
    }

    function setLiveSyncButtonBusy(isBusy, originalText = "Cập Nhật") {
      const liveSyncBtn = document.getElementById("liveSyncBtn");
      if (!liveSyncBtn) return;
      if (isBusy) {
        liveSyncBtn.disabled = true;
        liveSyncBtn.textContent = "Đang Cập Nhật...";
        liveResultsProgressButtonReset = () => {
          const button = document.getElementById("liveSyncBtn");
          if (!button) return;
          button.disabled = false;
          button.textContent = originalText;
        };
        return;
      }
      liveSyncBtn.disabled = false;
      liveSyncBtn.textContent = originalText;
      liveResultsProgressButtonReset = null;
    }

    function getLiveResultsProgressStatus(progress, { repairCanonical = false } = {}) {
      const prefix = repairCanonical ? "Đang cập nhật 6 loại từ MinhChinh" : "Đang cập nhật 6 loại";
      const warnings = Array.isArray(progress?.warnings) ? progress.warnings.filter(Boolean) : [];
      const errors = Array.isArray(progress?.errors) ? progress.errors.filter(Boolean) : [];
      if (progress?.running) {
        const etaSeconds = Number(progress?.etaSeconds);
        if (Number.isFinite(etaSeconds) && etaSeconds > 0) {
          return { message: `${prefix} • Ước tính còn ${formatCountdownSeconds(etaSeconds)}.`, cls: "muted" };
        }
        if (Number(progress?.completedSteps || 0) > 0) {
          return { message: `${prefix} • Đang hoàn tất xử lý, vui lòng chờ thêm...`, cls: "muted" };
        }
        return { message: `${prefix} • Đang tính thời gian còn lại...`, cls: "muted" };
      }
      if (errors.length) return { message: errors.join(" | "), cls: "warn" };
      if (warnings.length) return { message: warnings.join(" | "), cls: "warn" };
      if (progress?.done) {
        return { message: repairCanonical ? "Hoàn Tất Cập Nhật." : "Đã Cập Nhật", cls: "ok" };
      }
      return { message: `${prefix} • Đang tính thời gian còn lại...`, cls: "muted" };
    }

    function mergeLiveResultIntoState(item) {
      const key = String(item?.key || "").trim().toUpperCase();
      if (!key || !TYPES[key]) return false;
      const previous = liveResultsState?.[key];
      const nextItem = { ...item };
      const samePayload = !!previous && getLiveResultSignature(previous) === getLiveResultSignature(nextItem);
      liveResultsState = {
        ...(liveResultsState && typeof liveResultsState === "object" ? liveResultsState : {}),
        [key]: nextItem,
      };
      const imported = applyLiveResultsToStore([nextItem]);
      nextItem.imported = imported.has(key) || isLiveResultStored(nextItem);
      if (!samePayload || imported.has(key)) {
        liveResultsFetchedAt = new Date().toISOString();
        saveLiveResultsCache();
        startLiveDrawCountdown();
        renderLiveResultsBoard();
      }
      return !samePayload || imported.has(key);
    }

    async function refreshLiveHistoryForProgressType(type, updatedAt) {
      if (!type || liveResultsProgressHistoryRefreshBusy) return;
      const currentType = document.getElementById("liveHistoryType")?.value || "";
      if (String(currentType || "").toUpperCase() !== String(type || "").toUpperCase()) return;
      const refreshKey = `${type}:${updatedAt || ""}`;
      if (liveResultsProgressHistoryRefreshCursor[type] === refreshKey) return;
      liveResultsProgressHistoryRefreshCursor[type] = refreshKey;
      liveResultsProgressHistoryRefreshBusy = true;
      try {
        await refreshCurrentLiveHistory({ force: true, silent: true });
      } catch {
      } finally {
        liveResultsProgressHistoryRefreshBusy = false;
      }
    }

    async function applyLiveResultsProgressSnapshot(progress) {
      const typeStates = progress?.typeStates && typeof progress.typeStates === "object"
        ? progress.typeStates
        : {};
      let changed = false;
      let badgeChanged = false;
      for (const [type, state] of Object.entries(typeStates)) {
        if (!state || typeof state !== "object") continue;
        badgeChanged = applyLiveUpdateBadgeFromProgressState(type, state, { render: false }) || badgeChanged;
        const updatedAt = String(state.updatedAt || "");
        const cursorKey = String(type || "").toUpperCase();
        if (!updatedAt || liveResultsProgressTypeCursor[cursorKey] === updatedAt) continue;
        liveResultsProgressTypeCursor[cursorKey] = updatedAt;
        if (state.liveResult && typeof state.liveResult === "object") {
          changed = mergeLiveResultIntoState(state.liveResult) || changed;
        }
        await refreshLiveHistoryForProgressType(cursorKey, updatedAt);
      }
      if (changed || badgeChanged) {
        if (badgeChanged && !changed) renderLiveResultsBoard();
        renderLiveHistoryOutput();
      }
    }

    function applyLiveResultsApiResponse(res, { repairCanonical = false, requestStartedAtMs = Date.now() } = {}) {
      const durationMs = Number.isFinite(Number(res.durationMs))
        ? Number(res.durationMs)
        : Math.max(1, Date.now() - requestStartedAtMs);
      rememberLiveSyncDuration(repairCanonical, durationMs);
      const resultMap = {};
      for (const item of (res.results || [])) {
        resultMap[item.key] = item;
      }
      liveResultsState = resultMap;
      liveResultsFetchedAt = String(res.fetchedAt || "");
      const importedKeys = applyLiveResultsToStore(res.results || []);
      Object.values(liveResultsState).forEach(item => {
        item.imported = importedKeys.has(item.key) || isLiveResultStored(item);
      });
      saveLiveResultsCache();
      startLiveDrawCountdown();
      if (repairCanonical) {
        applyManualLiveUpdateBadgesFromApiResponse(res, { render: false });
      }
      renderLiveResultsBoard();

      const statusParts = [];
      if ((res.errors || []).length) {
        const errorText = res.errors.map(err => {
          if (String(err.key || "").toUpperCase() === "KENO" && String(err.message || "").trim() === "Hoạt động từ 6:00 đến 22:00") {
            return "KENO : Hoạt động từ 6:00 đến 22:00";
          }
          return `${err.key}: ${err.message}`;
        }).join(" | ");
        statusParts.push(errorText);
      }
      const canonicalBackfillErrors = Array.isArray(res.canonicalBackfill?.errors) ? res.canonicalBackfill.errors : [];
      if (canonicalBackfillErrors.length) {
        const backfillErrorText = canonicalBackfillErrors
          .map(err => `${err.type}${err.date ? ` ${err.date}` : ""}: ${err.message}`)
          .join(" | ");
        if (backfillErrorText) statusParts.push(`Lỗi khi bù all_day.csv: ${backfillErrorText}`);
      }
      if (!statusParts.length) {
        statusParts.push(repairCanonical ? "Hoàn Tất Cập Nhật." : "Đã Cập Nhật");
      }
      setLiveStatus(statusParts.join("\n"), ((res.errors || []).length || canonicalBackfillErrors.length) ? "warn" : "ok");
    }

    async function runLegacyRepairCanonicalSync({ silent = false, manageButton = false, originalButtonText = "Cập Nhật" } = {}) {
      const requestStartedAtMs = Date.now();
      const compatibilityNote = getLiveResultsCompatibilityFallbackNote();
      if (!silent) {
        if (manageButton) setLiveSyncButtonBusy(true, originalButtonText);
        startLiveSyncCountdown({
          repairCanonical: true,
          estimatedSeconds: estimateLiveSyncSeconds(true),
          note: compatibilityNote,
        });
      }
      try {
        const res = await api("/api/live-results?repair=1");
        applyLiveResultsApiResponse(res, { repairCanonical: true, requestStartedAtMs });
        return res;
      } catch (err) {
        markAllLiveUpdateBadgesFailed(err?.message || "Cập nhật thất bại", { render: true });
        setLiveStatus(`Không thể cập nhật live và bù all_day.csv: ${err.message}`, "warn");
        throw err;
      } finally {
        stopLiveSyncCountdown();
        if (!silent && manageButton) {
          setLiveSyncButtonBusy(false, originalButtonText);
        }
      }
    }

    async function pollLiveResultsProgress({ repairCanonical = false } = {}) {
      try {
        const progress = await api("/api/live-results-progress");
        await applyLiveResultsProgressSnapshot(progress);
        if (progress?.running) {
          liveResultsProgressSeenRunning = true;
        }
        if (!liveResultsProgressSeenRunning && !progress?.running) {
          const prefix = repairCanonical ? "Đang cập nhật 6 loại từ MinhChinh" : "Đang cập nhật 6 loại";
          setLiveStatus(`${prefix} • Đang tính thời gian còn lại...`, "muted");
          return;
        }
        const status = getLiveResultsProgressStatus(progress, { repairCanonical });
        setLiveStatus(status.message, status.cls);
        if (!progress?.running && progress?.done) {
          stopLiveResultsProgressPolling();
        }
      } catch (err) {
        if (repairCanonical && !liveResultsLegacyFallbackRunning && isLiveResultsCompatibilityError(err, { allowNotFound: true })) {
          liveResultsLegacyFallbackRunning = true;
          stopLiveResultsProgressPolling(false);
          try {
            await runLegacyRepairCanonicalSync({ silent: false, manageButton: true });
          } catch {
          } finally {
            liveResultsLegacyFallbackRunning = false;
          }
        }
      }
    }

    function startLiveResultsProgressPolling({ repairCanonical = false, initialProgress = null } = {}) {
      stopLiveResultsProgressPolling(false);
      liveResultsProgressTypeCursor = {};
      if (initialProgress) {
        void applyLiveResultsProgressSnapshot(initialProgress);
      }
      if (initialProgress) {
        if (initialProgress?.running) {
          liveResultsProgressSeenRunning = true;
        }
        const status = getLiveResultsProgressStatus(initialProgress, { repairCanonical });
        setLiveStatus(status.message, status.cls);
      } else {
        const prefix = repairCanonical ? "Đang cập nhật 6 loại từ MinhChinh" : "Đang cập nhật 6 loại";
        setLiveStatus(`${prefix} • Đang tính thời gian còn lại...`, "muted");
      }
      pollLiveResultsProgress({ repairCanonical });
      liveResultsProgressPollTimer = setInterval(() => {
        pollLiveResultsProgress({ repairCanonical });
      }, 1000);
    }

    function formatLiveSyncCount(value) {
      const numeric = Math.max(0, Number(value || 0));
      return numeric.toLocaleString("vi-VN");
    }

    async function syncLiveResults({ silent = false, repairCanonical = false } = {}) {
      const liveSyncBtn = document.getElementById("liveSyncBtn");
      const originalButtonText = liveSyncBtn ? String(liveSyncBtn.textContent || "Cập Nhật") : "";
      const requestStartedAtMs = Date.now();
      let keepProgressPolling = false;
      if (IS_LOCAL_MODE) {
        renderLiveResultsBoard();
        if (!silent) {
          setLiveStatus("Đồng bộ live chỉ hoạt động khi mở trang qua http://localhost:8080 để server gọi Python scraper.", "warn");
        }
        return;
      }

      if (!silent) {
        if (repairCanonical) setLiveSyncButtonBusy(true, originalButtonText);
        else if (liveSyncBtn) {
          liveSyncBtn.disabled = true;
          liveSyncBtn.textContent = "Đang cập nhật...";
        }
        if (repairCanonical) {
          resetLiveUpdateBadgesForManualRun({ render: true });
          setLiveStatus("Đang cập nhật 6 loại từ MinhChinh • Đang tính thời gian còn lại...", "muted");
        } else {
          startLiveSyncCountdown({ repairCanonical, estimatedSeconds: estimateLiveSyncSeconds(repairCanonical) });
        }
      }
      try {
        if (repairCanonical) {
          try {
            const res = await api("/api/live-results-start", "POST");
            startLiveResultsProgressPolling({ repairCanonical: true, initialProgress: res.progress || null });
            keepProgressPolling = true;
            return;
          } catch (startErr) {
            if (isLiveResultsCompatibilityError(startErr, { allowNotFound: true })) {
              await runLegacyRepairCanonicalSync({ silent });
              return;
            }
            throw startErr;
          }
        }
        const res = await api("/api/live-results");
        applyLiveResultsApiResponse(res, { repairCanonical, requestStartedAtMs });
      } catch (err) {
        if (repairCanonical && Number(err?.status || 0) === 409) {
          const progress = err?.payload?.progress;
          startLiveResultsProgressPolling({ repairCanonical: true, initialProgress: progress });
          keepProgressPolling = true;
          return;
        }
        if (repairCanonical) {
          markAllLiveUpdateBadgesFailed(err?.message || "Cập nhật thất bại", { render: true });
        } else {
          renderLiveResultsBoard();
        }
        setLiveStatus(
          repairCanonical
            ? `Không thể cập nhật live và bù all_day.csv: ${err.message}`
            : `Không thể đồng bộ live: ${err.message}`,
          "warn"
        );
      } finally {
        stopLiveSyncCountdown();
        if (repairCanonical && !keepProgressPolling) {
          stopLiveResultsProgressPolling();
        }
        if (!silent && liveSyncBtn && !keepProgressPolling) {
          liveSyncBtn.disabled = false;
          liveSyncBtn.textContent = originalButtonText;
        }
      }
    }

    function startLiveAutoSync() {
      const seconds = Number(document.getElementById("liveSyncInterval")?.value || 120);
      const delay = Number.isFinite(seconds) && seconds > 0 ? seconds * 1000 : 120000;
      if (liveAutoTimer) clearInterval(liveAutoTimer);
      liveAutoTimer = setInterval(() => {
        syncLiveResults({ silent: true });
      }, delay);
      updateLiveAutoButton();
    }

    function stopLiveAutoSync() {
      if (liveAutoTimer) clearInterval(liveAutoTimer);
      liveAutoTimer = null;
      updateLiveAutoButton();
    }

    function buildPredictionResultDataset(type) {
      const baseResults = store.results[type] || {};
      const baseOrder = store.resultOrder[type] || [];
      if (type !== "KENO") {
        return buildMergedResultDataset(type);
      }

      const canonicalFeed = getLiveHistoryFeed("KENO");
      const mergedResults = {};
      const mergeFromStore = (ky, draw) => {
        const key = String(ky || "").replace(/\D/g, "");
        const cloned = cloneDraw(draw);
        if (!key || !cloned) return;
        mergedResults[key] = cloned;
      };

      for (const ky of baseOrder) mergeFromStore(ky, baseResults[ky]);
      for (const ky of (kenoCsvFeed.order || [])) mergeFromStore(ky, kenoCsvFeed.results[ky]);
      for (const ky of (canonicalFeed.order || [])) mergeFromStore(ky, canonicalFeed.results?.[ky]);

      const order = Object.keys(mergedResults).sort((a, b) => kySortValue(a) - kySortValue(b));
      const parts = [];
      if (canonicalFeed.order.length) parts.push(`canonical ${canonicalFeed.order.length} kỳ`);
      if (baseOrder.length) parts.push(`trong trang ${baseOrder.length} kỳ`);
      if (kenoCsvFeed.order.length) parts.push(`CSV ${kenoCsvFeed.order.length} kỳ`);
      return {
        results: mergedResults,
        order,
        sourceText: parts.length
          ? `Nguồn Keno đã gộp: ${parts.join(" + ")}. Tổng dùng để dự đoán: ${order.length} kỳ`
          : "Chưa có dữ liệu Keno"
      };
    }

    async function mergeKenoCsvTexts(items) {
      const next = cloneKenoCsvFeed();
      let validRows = 0;
      let skippedRows = 0;
      const loadedSources = [];

      for (const item of items) {
        const parsed = parseKenoCsvText(item.text, item.label);
        if (parsed.rows.length) {
          loadedSources.push(`${item.label} (${parsed.rows.length} kỳ)`);
          next.sourceLabels.push(item.label);
          parsed.rows.forEach(row => {
            if (mergeKenoDraw(next, row.ky, row.draw)) validRows++;
          });
        }
        skippedRows += parsed.skipped;
      }

      setKenoCsvFeed(next);
      return { validRows, skippedRows, loadedSources, totalRows: kenoCsvFeed.order.length };
    }

    async function loadDefaultKenoCsvSources({ silent = false } = {}) {
      if (IS_LOCAL_MODE) {
        if (!silent) {
          updateKenoCsvStatus(
            "Hãy mở trang qua http://localhost:8080 để web tự đồng bộ CSV Keno. Khi chạy qua server, mục này không cần tải file thủ công nữa.",
            "warn"
          );
        }
        return { validRows: 0, skippedRows: 0, loadedSources: [] };
      }

      const res = await api("/api/keno-predict-data");
      const csvFileName = String(res.csvFileName || "keno_all_day.csv");
      const csvText = String(res.csvText || "");
      if (!csvText.trim()) {
        if (!silent) {
          updateKenoCsvStatus("Server đã trả về trạng thái sync nhưng chưa có nội dung CSV Keno.", "warn");
        }
        return { validRows: 0, skippedRows: 0, loadedSources: [] };
      }

      const parsed = parseKenoCsvText(csvText, csvFileName);
      const next = emptyKenoCsvFeed();
      next.sourceLabels = [csvFileName];
      parsed.rows.forEach(row => {
        mergeKenoDraw(next, row.ky, row.draw);
      });
      setKenoCsvFeed(next);

      const status = res.status || {};
      const notes = [];
      if (status.latest_date) {
        notes.push(`Đã cập nhật web ngày ${status.latest_date}: +${Number(status.new_rows || 0)} kỳ mới.`);
      }
      if (status.sync_error) {
        notes.push(`Không lấy thêm được từ web, đang dùng dữ liệu local: ${status.sync_error}`);
      }
      setKenoPredictStatusMeta(notes.join("\n"), status.sync_error ? "warn" : "ok");
      return {
        validRows: parsed.rows.length,
        skippedRows: parsed.skipped,
        loadedSources: [csvFileName],
        totalRows: parsed.rows.length,
        syncStatus: status,
      };
    }

    async function predictKenoWithPython(order, bundles) {
      if (IS_LOCAL_MODE) {
        throw new Error("Hãy mở trang qua http://localhost:8080 để dùng thuật toán Keno từ Test/L1.py.");
      }

      const params = new URLSearchParams({
        order: String(order),
        bundles: String(bundles),
      });
      const res = await api(`/api/keno-predict?${params.toString()}`);
      const sync = res?.sync || {};
      const detail = sync?.sync_error
        ? `Không thể đồng bộ web, đang dùng dữ liệu local: ${sync.sync_error}`
        : sync?.latest_date
          ? `Đã cập nhật web ngày ${sync.latest_date}: +${Number(sync.new_rows || 0)} kỳ mới.`
          : "";
      setKenoPredictStatusMeta(detail, sync?.sync_error ? "warn" : "ok", res?.generated_at || new Date().toISOString());
      return res;
    }

    function ensureDataReady(type, outEl, featureLabel) {
      const resultDataset = buildPredictionResultDataset(type);
      const hasResult = (resultDataset.order || []).length > 0;
      const hasPick = (store.pickOrder[type] || []).length > 0;
      if (hasResult && hasPick) return true;
      const miss = [];
      if (!hasResult) miss.push("dữ liệu kết quả");
      if (!hasPick) miss.push("Nhập số đã chọn (mục 2)");
      line(
        outEl,
        `${featureLabel}: cần nhập đủ dữ liệu trước khi dùng.\nThiếu: ${miss.join(" và ")}.`,
        "warn"
      );
      return false;
    }

    function countPickTickets(type) {
      let total = 0;
      for (const ky of (store.pickOrder[type] || [])) {
        total += (store.picks[type]?.[ky] || []).length;
      }
      return total;
    }

    function ensurePickMin(type, outEl, featureLabel, minTickets = 3) {
      const total = countPickTickets(type);
      if (total >= minTickets) return true;
      line(
        outEl,
        `${featureLabel}: cần dữ liệu Nhập số đã chọn (mục 2) tối thiểu ${minTickets} cặp/vé.\nHiện có: ${total}.`,
        "warn"
      );
      return false;
    }

    function getDeleteTargetMeta(target) {
      return target === "results"
        ? { orderKey: "resultOrder", dataKey: "results", uiLabel: "Kết Quả", needText: "Kết Quả" }
        : { orderKey: "pickOrder", dataKey: "picks", uiLabel: "Số Nhập", needText: "Số Chọn" };
    }

    function ensureDeleteTargetReady(type, target, outEl) {
      const meta = getDeleteTargetMeta(target);
      const hasData = (store[meta.orderKey]?.[type] || []).length > 0;
      if (hasData) return true;
      line(outEl, `${meta.uiLabel === "Kết Quả" ? "Xóa Kết Quả" : "Xóa Số Nhập"}: Vui lòng điền ${meta.needText} trước khi xóa.`, "warn");
      return false;
    }

    async function ensureResultOnly(type, outEl, featureLabel) {
      if (!TYPES[type]?.keno && !IS_LOCAL_MODE) {
        try {
          await fetchLiveHistory(type, "all", { silent: true });
        } catch {}
      }
      const resultDataset = buildPredictionResultDataset(type);
      const hasResult = (resultDataset.order || []).length > 0;
      if (hasResult) return true;
      line(
        outEl,
        `${featureLabel}: cần dữ liệu kết quả trước khi dùng.`,
        "warn"
      );
      return false;
    }

    const saveResultBtn = document.getElementById("saveResultBtn");
    if (saveResultBtn) {
      saveResultBtn.onclick = () => {
        const type = document.getElementById("rType").value;
        const ky = normalizeKy(document.getElementById("rKy").value);
        const mode = document.getElementById("rMode").value;
        const out = document.getElementById("rMsg");
        try {
          if (!ky) throw new Error("Kỳ không hợp lệ. Nhập 1, 01, 001, 0001 hoặc #0001.");
          const t = TYPES[type];
          if (mode === "quick") {
            const rawRows = document.getElementById("rQuickRows").value;
            const rows = rawRows.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
            if (!rows.length) throw new Error("Bạn chưa nhập dòng dữ liệu nhanh.");
            const need = t.keno ? (t.resultCount || 20) : (t.mainCount + (t.hasSpecial ? 1 : 0));
            const start = Number(ky.replace("#", ""));
            let saved = 0;
            for (let i = 0; i < rows.length; i++) {
              const nums = parseNums(rows[i]);
              if (nums.length !== need) throw new Error(`Dòng ${i + 1} cần đúng ${need} số.`);
              let main = [];
              let special = null;
              if (t.keno) {
                main = parseDistinctSortedNums(nums, t.mainMin, t.mainMax, t.resultCount || 20, t.resultCount || 20, `KQ Keno dòng ${i + 1}`);
              } else {
                main = parseMain(nums.slice(0, t.mainCount).join(" "), type);
                special = t.hasSpecial ? parseSpecial(String(nums[t.mainCount]), type) : null;
              }
              const kySeq = `#${String(start + i).padStart(4, "0")}`;
              putResult(type, kySeq, { main, special });
              saved++;
            }
            line(out, `Đã lưu nhanh ${saved} kỳ từ ${ky} cho ${TYPES[type].label}.`, "ok");
          } else {
            const rawMain = document.getElementById("rMain").value;
            const rawDb = document.getElementById("rDb").value;
            let main = [];
            let special = null;
            if (t.keno) {
              const line1 = parseNums(rawMain);
              const line2 = parseNums(rawDb);
              if (line1.length !== 10 || line2.length !== 10) {
                throw new Error("KQ Keno (chế độ cơ bản) cần đúng 2 dòng, mỗi dòng 10 số.");
              }
              const nums = [...line1, ...line2];
              main = parseDistinctSortedNums(nums, t.mainMin, t.mainMax, t.resultCount || 20, t.resultCount || 20, "KQ Keno");
            } else {
              const nums = parseNums(rawMain);
              if (t.hasSpecial && !String(rawDb || "").trim() && nums.length === t.mainCount + 1) {
                main = parseMain(nums.slice(0, t.mainCount).join(" "), type);
                special = parseSpecial(String(nums[t.mainCount]), type);
              } else {
                main = parseMain(rawMain, type);
                special = parseSpecial(rawDb, type);
              }
            }
            putResult(type, ky, { main, special });
            line(out, `Đã lưu KQ ${TYPES[type].label} Kỳ ${ky}: ${formatTicket({main, special}, type)}`, "ok");
          }
        } catch (e) {
          line(out, e.message, "warn");
        }
      };
    }

    const savePickBtn = document.getElementById("savePickBtn");
    if (savePickBtn) savePickBtn.onclick = () => {
      const type = document.getElementById("pType").value;
      const ky = normalizeKy(document.getElementById("pKy").value);
      const mode = document.getElementById("pMode").value;
      const raw = mode === "quick" ? document.getElementById("pQuickRows").value : document.getElementById("pTickets").value;
      const out = document.getElementById("pMsg");
      try {
        if (!ky) throw new Error("Kỳ không hợp lệ. Nhập 1, 01, 001, 0001 hoặc #0001.");
        const t = TYPES[type];
        const need = t.mainCount + (t.hasSpecial ? 1 : 0);
        let lines = raw.split(/\r?\n/).map(s=>s.trim()).filter(Boolean);

        // Fast input for picks:
        // - If pasted as a single long line and count is multiple of ticket size,
        //   auto-split into multiple ticket lines.
        if (lines.length === 1) {
          const allNums = parseNums(lines[0]);
          if (!t.keno && allNums.length > need && allNums.length % need === 0) {
            const auto = [];
            for (let i = 0; i < allNums.length; i += need) {
              auto.push(allNums.slice(i, i + need).join(" "));
            }
            lines = auto;
          }
        }

        if (!lines.length) throw new Error("Bạn chưa nhập vé.");
        let ok = 0;
        for (const ln of lines) {
          const nums = parseNums(ln);
          let main = [];
          let special = null;
          if (t.keno) {
            main = parseDistinctSortedNums(nums, t.mainMin, t.mainMax, t.pickMinCount || 1, t.pickMaxCount || 10, `Vé Keno "${ln}"`);
          } else {
            if (nums.length !== need) throw new Error(`Vé "${ln}" sai số lượng số.`);
            main = parseDistinctSortedNums(nums.slice(0, t.mainCount), t.mainMin, t.mainMax, t.mainCount, t.mainCount, `Vé "${ln}"`);
            special = t.hasSpecial ? nums[t.mainCount] : null;
            if (t.hasSpecial && (special < t.specialMin || special > t.specialMax)) {
              throw new Error(`Vé "${ln}" có ĐB ngoài phạm vi ${t.specialMin}-${t.specialMax}.`);
            }
          }
          addPick(type, ky, { main, special });
          ok++;
        }
        line(out, `Đã lưu ${ok} vé cho ${TYPES[type].label} Kỳ ${ky}.`, "ok");
      } catch (e) {
        line(out, e.message, "warn");
      }
    };

    const pTicketsEl = document.getElementById("pTickets");
    if (pTicketsEl) {
      pTicketsEl.addEventListener("input", () => {
        let v = pTicketsEl.value;
        v = v.replace(/\\n/g, "\n");
        v = v.replace(/[;|]+/g, "\n");
        v = v.replace(/[^\d \r\n\t]/g, " ");
        v = v.replace(/[ \t]+/g, " ");
        v = v.replace(/ *\n */g, "\n");
        pTicketsEl.value = v;
      });
    }
    const pQuickEl = document.getElementById("pQuickRows");
    if (pQuickEl) {
      pQuickEl.addEventListener("input", () => {
        let v = pQuickEl.value;
        v = v.replace(/\\n/g, "\n");
        v = v.replace(/[;|]+/g, "\n");
        v = v.replace(/[^\d \r\n\t]/g, " ");
        v = v.replace(/[ \t]+/g, " ");
        v = v.replace(/ *\n */g, "\n");
        pQuickEl.value = v;
      });
    }

    const viewBtn = document.getElementById("viewBtn");
    if (viewBtn) viewBtn.onclick = () => {
      const type = document.getElementById("vType").value;
      const mode = document.getElementById("vMode").value;
      const out = document.getElementById("viewOut");
      if (mode === "result") {
        const dataset = buildPredictionResultDataset(type);
        const keys = dataset.order || [];
        if (!keys.length) {
          return line(out, "Hiển thị Bảng Kết Quả: cần có dữ liệu kết quả trước khi dùng.", "warn");
        }
        const rows = [];
        if (dataset.sourceText) rows.push(dataset.sourceText, "");
        keys.forEach(ky => {
          const draw = dataset.results?.[ky];
          if (!draw) return;
          rows.push(`${TYPES[type].label} Kỳ ${ky} - ${formatTicket(draw, type)}`);
        });
        line(out, rows.join("\n"));
      } else {
        const keys = store.pickOrder[type];
        if (!keys.length) {
          return line(out, "Hiển thị Bảng số đã chọn: cần nhập dữ liệu số đã chọn ở mục 2 trước khi dùng.", "warn");
        }
        const lines = [];
        for (const ky of keys) {
          const arr = store.picks[type][ky] || [];
          if (!arr.length) continue;
          for (const ticket of arr) {
            lines.push(`${TYPES[type].label} Kỳ ${ky} - ${formatTicket(ticket, type)}`);
          }
        }
        line(out, lines.join("\n"));
      }
    };

    function ball(cls) {
      return `<span class="ball ${cls}">O</span>`;
    }
    function mainBalls(total, hit) {
      return `${Array.from({ length: hit }, () => ball("ball-main-hit")).join("")}${Array.from({ length: total - hit }, () => ball("ball-main-miss")).join("")}`;
    }
    function specialBall(hit) {
      return ball(hit ? "ball-special-hit" : "ball-special-miss");
    }
    function formatPrizeCurrency(value) {
      return `${Math.max(0, Number(value || 0)).toLocaleString("vi-VN")} VNĐ`;
    }
    function combinationCount(n, k) {
      const safeN = Math.max(0, Number(n || 0));
      const safeK = Math.max(0, Number(k || 0));
      if (!Number.isFinite(safeN) || !Number.isFinite(safeK) || safeK > safeN) return 0;
      if (safeK === 0 || safeK === safeN) return 1;
      const choose = Math.min(safeK, safeN - safeK);
      let out = 1;
      for (let i = 1; i <= choose; i++) {
        out = (out * (safeN - choose + i)) / i;
      }
      return Math.round(out);
    }
    function buildPrizeSection(title, subtitle, content) {
      return `
        <section class="prize-section">
          <div class="prize-section-head">
            <h3 class="prize-section-title">${escapeHtml(title)}</h3>
            <div class="prize-section-subtitle">${subtitle}</div>
          </div>
          ${content}
        </section>
      `;
    }
    function buildBaoGuarantee(type, n) {
      if (type === "LOTO_5_35") {
        return `Nếu cả 5 số chính trúng đều nằm trong tập ${n} số đã bao, sẽ có ít nhất 1 vé con trúng đủ 5 số chính. Số đặc biệt vẫn cần khớp riêng theo từng vé.`;
      }
      if (type === "LOTO_6_55") {
        return `Nếu cả 6 số chính trúng đều nằm trong tập ${n} số đã bao, sẽ có ít nhất 1 vé con trúng đủ 6 số chính. Jackpot 2 vẫn phụ thuộc thêm số đặc biệt.`;
      }
      return `Nếu cả 6 số trúng đều nằm trong tập ${n} số đã bao, sẽ có ít nhất 1 vé con trúng đủ 6 số.`;
    }
    function buildBaoNote(type) {
      if (type === "LOTO_5_35") {
        return `<b>Ghi chú Bao Vé:</b> Tính theo bao số chính, giá vé cơ bản 10.000 VNĐ/vé con. Riêng số đặc biệt của Lotto 5/35 không được “bao” trong bảng này và vẫn phải khớp theo từng vé phát sinh.`;
      }
      if (type === "LOTO_6_55") {
        return `<b>Ghi chú Bao Vé:</b> Tính theo bao 6 số chính, giá vé cơ bản 10.000 VNĐ/vé con. Jackpot 2 của Power 6/55 vẫn phụ thuộc thêm số đặc biệt trên từng vé con.`;
      }
      return `<b>Ghi chú Bao Vé:</b> Bao vé giúp tăng độ phủ tổ hợp, không làm tăng xác suất nền của việc chọn đúng tập số mạnh. Chi phí tính theo toàn bộ vé con phát sinh ở mức 10.000 VNĐ/vé.`;
    }
    function getBaoBrochureTheme(type) {
      if (type === "LOTO_5_35") return "theme-lotto";
      if (type === "LOTO_6_55") return "theme-power";
      return "theme-mega";
    }
    function getBaoBrochureData(type) {
      const data = {
        LOTO_5_35: [
          { level: 4, sub: "Bao 4 (310K/1 lần dự thưởng)", rows: [
            ["5 số chính + ĐB", "ĐỘC ĐẮC + 150 TRIỆU"],
            ["5 số chính", "25 TRIỆU ĐỒNG"],
            ["4 số chính + ĐB", "12,9 TRIỆU ĐỒNG"],
            ["4 số chính", "1,87 TRIỆU ĐỒNG"],
            ["3 số chính + ĐB", "580.000"],
            ["3 số chính", "90.000"],
            ["2 số chính + ĐB", "310.000"]
          ]},
          { level: 6, sub: "Bao 6 (60K/1 lần dự thưởng)", rows: [
            ["5 số chính + ĐB", "ĐỘC ĐẮC + 25 TRIỆU"],
            ["5 số chính", "12,5 TRIỆU ĐỒNG"],
            ["4 số chính + ĐB", "10,4 TRIỆU ĐỒNG"],
            ["4 số chính", "1,12 TRIỆU ĐỒNG"],
            ["3 số chính + ĐB", "330.000"],
            ["3 số chính", "90.000"],
            ["2 số chính + ĐB", "60.000"]
          ]},
          { level: 7, sub: "Bao 7 (210K/1 lần dự thưởng)", rows: [
            ["5 số chính + ĐB", "ĐỘC ĐẮC + 51 TRIỆU"],
            ["5 số chính", "15,3 TRIỆU ĐỒNG"],
            ["4 số chính + ĐB", "16,26 TRIỆU ĐỒNG"],
            ["4 số chính", "1,86 TRIỆU ĐỒNG"],
            ["3 số chính + ĐB", "750.000"],
            ["3 số chính", "180.000"],
            ["2 số chính + ĐB", "210.000"]
          ]},
          { level: 8, sub: "Bao 8 (560K/1 lần dự thưởng)", rows: [
            ["5 số chính + ĐB", "ĐỘC ĐẮC + 78,1 TRIỆU"],
            ["5 số chính", "18,4 TRIỆU ĐỒNG"],
            ["4 số chính + ĐB", "22,68 TRIỆU ĐỒNG"],
            ["4 số chính", "2,72 TRIỆU ĐỒNG"],
            ["3 số chính + ĐB", "1,46 TRIỆU ĐỒNG"],
            ["3 số chính", "300.000"],
            ["2 số chính + ĐB", "560.000"]
          ]},
          { level: 9, sub: "Bao 9 (1.260K/1 lần dự thưởng)", rows: [
            ["5 số chính + ĐB", "ĐỘC ĐẮC + 106,45 TRIỆU"],
            ["5 số chính", "21,8 TRIỆU ĐỒNG"],
            ["4 số chính + ĐB", "29,81 TRIỆU ĐỒNG"],
            ["4 số chính", "3,7 TRIỆU ĐỒNG"],
            ["3 số chính + ĐB", "2,61 TRIỆU ĐỒNG"],
            ["3 số chính", "450.000"],
            ["2 số chính + ĐB", "1,26 TRIỆU ĐỒNG"]
          ]},
          { level: 10, sub: "Bao 10 (2.520K/1 lần dự thưởng)", rows: [
            ["5 số chính + ĐB", "ĐỘC ĐẮC + 136,26 TRIỆU"],
            ["5 số chính", "25,5 TRIỆU ĐỒNG"],
            ["4 số chính + ĐB", "37,86 TRIỆU ĐỒNG"],
            ["4 số chính", "4,8 TRIỆU ĐỒNG"],
            ["3 số chính + ĐB", "4,41 TRIỆU ĐỒNG"],
            ["3 số chính", "630.000"],
            ["2 số chính + ĐB", "2,52 TRIỆU ĐỒNG"]
          ]},
          { level: 11, sub: "Bao 11 (4.620K/1 lần dự thưởng)", rows: [
            ["5 số chính + ĐB", "ĐỘC ĐẮC + 167,81 TRIỆU"],
            ["5 số chính", "29,5 TRIỆU ĐỒNG"],
            ["4 số chính + ĐB", "47,11 TRIỆU ĐỒNG"],
            ["4 số chính", "6,02 TRIỆU ĐỒNG"],
            ["3 số chính + ĐB", "7,14 TRIỆU ĐỒNG"],
            ["3 số chính", "840.000"],
            ["2 số chính + ĐB", "4,62 TRIỆU ĐỒNG"]
          ]},
          { level: 12, sub: "Bao 12 (7.920K/1 lần dự thưởng)", rows: [
            ["5 số chính + ĐB", "ĐỘC ĐẮC + 201,46 TRIỆU"],
            ["5 số chính", "33,8 TRIỆU ĐỒNG"],
            ["4 số chính + ĐB", "57,92 TRIỆU ĐỒNG"],
            ["4 số chính", "7,36 TRIỆU ĐỒNG"],
            ["3 số chính + ĐB", "11,16 TRIỆU ĐỒNG"],
            ["3 số chính", "1,08 TRIỆU ĐỒNG"],
            ["2 số chính + ĐB", "7,92 TRIỆU ĐỒNG"]
          ]},
          { level: 13, sub: "Bao 13 (12.870K/1 lần dự thưởng)", rows: [
            ["5 số chính + ĐB", "ĐỘC ĐẮC + 237,66 TRIỆU"],
            ["5 số chính", "38,4 TRIỆU ĐỒNG"],
            ["4 số chính + ĐB", "70,74 TRIỆU ĐỒNG"],
            ["4 số chính", "8,82 TRIỆU ĐỒNG"],
            ["3 số chính + ĐB", "16,92 TRIỆU ĐỒNG"],
            ["3 số chính", "1,35 TRIỆU ĐỒNG"],
            ["2 số chính + ĐB", "12,87 TRIỆU ĐỒNG"]
          ]},
          { level: 14, sub: "Bao 14 (20.020K/1 lần dự thưởng)", rows: [
            ["5 số chính + ĐB", "ĐỘC ĐẮC + 276,96 TRIỆU"],
            ["5 số chính", "43,3 TRIỆU ĐỒNG"],
            ["4 số chính + ĐB", "86,12 TRIỆU ĐỒNG"],
            ["4 số chính", "10,4 TRIỆU ĐỒNG"],
            ["3 số chính + ĐB", "24,97 TRIỆU ĐỒNG"],
            ["3 số chính", "1,65 TRIỆU ĐỒNG"],
            ["2 số chính + ĐB", "20,02 TRIỆU ĐỒNG"]
          ]},
          { level: 15, sub: "Bao 15 (30.030K/1 lần dự thưởng)", rows: [
            ["5 số chính + ĐB", "ĐỘC ĐẮC + 320,02 TRIỆU"],
            ["5 số chính", "48,5 TRIỆU ĐỒNG"],
            ["4 số chính + ĐB", "104,72 TRIỆU ĐỒNG"],
            ["4 số chính", "12,1 TRIỆU ĐỒNG"],
            ["3 số chính + ĐB", "35,97 TRIỆU ĐỒNG"],
            ["3 số chính", "1,98 TRIỆU ĐỒNG"],
            ["2 số chính + ĐB", "30,03 TRIỆU ĐỒNG"]
          ]}
        ],
        LOTO_6_45: [
          { level: 5, sub: "Chọn 5 số (400.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 2 số", "120.000"],
            ["Trúng 3 số", "2.010.000"],
            ["Trúng 4 số", "31.400.000"],
            ["Trúng 5 số", "JACKPOT + 390 TRIỆU"]
          ]},
          { level: 7, sub: "Chọn 7 số (70.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "120.000"],
            ["Trúng 4 số", "1.020.000"],
            ["Trúng 5 số", "21.500.000"],
            ["Trúng 6 số", "JACKPOT + 60 TRIỆU"]
          ]},
          { level: 8, sub: "Chọn 8 số (280.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "300.000"],
            ["Trúng 4 số", "2.280.000"],
            ["Trúng 5 số", "34.800.000"],
            ["Trúng 6 số", "JACKPOT + 124,5 TRIỆU"]
          ]},
          { level: 9, sub: "Chọn 9 số (840.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "600.000"],
            ["Trúng 4 số", "4.200.000"],
            ["Trúng 5 số", "50.200.000"],
            ["Trúng 6 số", "JACKPOT + 194,1 TRIỆU"]
          ]},
          { level: 10, sub: "Chọn 10 số (2.100.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "1.050.000"],
            ["Trúng 4 số", "6.900.000"],
            ["Trúng 5 số", "68.000.000"],
            ["Trúng 6 số", "JACKPOT + 269,4 TRIỆU"]
          ]},
          { level: 11, sub: "Chọn 11 số (4.620.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "1.680.000"],
            ["Trúng 4 số", "10.500.000"],
            ["Trúng 5 số", "88.500.000"],
            ["Trúng 6 số", "JACKPOT + 351 TRIỆU"]
          ]},
          { level: 12, sub: "Chọn 12 số (9.240.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "2.520.000"],
            ["Trúng 4 số", "15.120.000"],
            ["Trúng 5 số", "112.000.000"],
            ["Trúng 6 số", "JACKPOT + 439,5 TRIỆU"]
          ]},
          { level: 13, sub: "Chọn 13 số (17.160.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "3.600.000"],
            ["Trúng 4 số", "20.880.000"],
            ["Trúng 5 số", "138.800.000"],
            ["Trúng 6 số", "JACKPOT + 535,5 TRIỆU"]
          ]},
          { level: 14, sub: "Chọn 14 số (30.030.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "4.950.000"],
            ["Trúng 4 số", "27.900.000"],
            ["Trúng 5 số", "169.200.000"],
            ["Trúng 6 số", "JACKPOT + 639,6 TRIỆU"]
          ]},
          { level: 15, sub: "Chọn 15 số (50.050.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "6.600.000"],
            ["Trúng 4 số", "36.300.000"],
            ["Trúng 5 số", "203.500.000"],
            ["Trúng 6 số", "JACKPOT + 752,4 TRIỆU"]
          ]},
          { level: 18, sub: "Chọn 18 số (185.640.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "13.650.000"],
            ["Trúng 4 số", "70.980.000"],
            ["Trúng 5 số", "332.800.000"],
            ["Trúng 6 số", "JACKPOT + 1,149 TỶ"]
          ]}
        ],
        LOTO_6_55: [
          { level: 5, sub: "Chọn 5 số (500.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 2 số", "200.000"],
            ["Trúng 3 số", "3.850.000"],
            ["Trúng 4 số", "104.000.000"],
            ["Trúng 4 số + số đặc biệt", "(JACKPOT2 X 2) + 24 TRIỆU"],
            ["Trúng 5 số", "JACKPOT1 + JACKPOT2 + 1,92 TỶ"]
          ]},
          { level: 7, sub: "Chọn 7 số (70.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "200.000"],
            ["Trúng 4 số", "1.700.000"],
            ["Trúng 5 số", "82.500.000"],
            ["Trúng 5 số + số đặc biệt", "JACKPOT2 + 42,5 TRIỆU"],
            ["Trúng 6 số", "JACKPOT1 + 240 TRIỆU"],
            ["Trúng 6 số + số đặc biệt", "JACKPOT1 + (JACKPOT2 X 6)"]
          ]},
          { level: 8, sub: "Chọn 8 số (280.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "500.000"],
            ["Trúng 4 số", "3.800.000"],
            ["Trúng 5 số", "128.000.000"],
            ["Trúng 5 số + số đặc biệt", "JACKPOT2 + 88 TRIỆU"],
            ["Trúng 6 số", "JACKPOT1 + 487,5 TRIỆU"],
            ["Trúng 6 số + số đặc biệt", "JACKPOT1 + (JACKPOT2 X 6) + 247,5 TRIỆU"]
          ]},
          { level: 9, sub: "Chọn 9 số (840.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "1.000.000"],
            ["Trúng 4 số", "7.000.000"],
            ["Trúng 5 số", "177.000.000"],
            ["Trúng 5 số + số đặc biệt", "JACKPOT2 + 137 TRIỆU"],
            ["Trúng 6 số", "JACKPOT1 + 743,5 TRIỆU"],
            ["Trúng 6 số + số đặc biệt", "JACKPOT1 + (JACKPOT2 X 6) + 503,5 TRIỆU"]
          ]},
          { level: 10, sub: "Chọn 10 số (2.100.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "1.750.000"],
            ["Trúng 4 số", "11.500.000"],
            ["Trúng 5 số", "230.000.000"],
            ["Trúng 5 số + số đặc biệt", "JACKPOT2 + 190 TRIỆU"],
            ["Trúng 6 số", "JACKPOT1 + 1,009 TỶ"],
            ["Trúng 6 số + số đặc biệt", "JACKPOT1 + (JACKPOT2 X 6) + 769 TRIỆU"]
          ]},
          { level: 11, sub: "Chọn 11 số (4.620.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "2.800.000"],
            ["Trúng 4 số", "17.500.000"],
            ["Trúng 5 số", "287.500.000"],
            ["Trúng 5 số + số đặc biệt", "JACKPOT2 + 247,5 TRIỆU"],
            ["Trúng 6 số", "JACKPOT1 + 1,285 TỶ"],
            ["Trúng 6 số + số đặc biệt", "JACKPOT1 + (JACKPOT2 X 6) + 1,045 TỶ"]
          ]},
          { level: 12, sub: "Chọn 12 số (9.240.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "4.200.000"],
            ["Trúng 4 số", "25.200.000"],
            ["Trúng 5 số", "350.000.000"],
            ["Trúng 5 số + số đặc biệt", "JACKPOT2 + 310 TRIỆU"],
            ["Trúng 6 số", "JACKPOT1 + 1,575 TỶ"],
            ["Trúng 6 số + số đặc biệt", "JACKPOT1 + (JACKPOT2 X 6) + 1,335 TỶ"]
          ]},
          { level: 13, sub: "Chọn 13 số (17.160.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "6.000.000"],
            ["Trúng 4 số", "34.800.000"],
            ["Trúng 5 số", "418.000.000"],
            ["Trúng 5 số + số đặc biệt", "JACKPOT2 + 378 TRIỆU"],
            ["Trúng 6 số", "JACKPOT1 + 1,8725 TỶ"],
            ["Trúng 6 số + số đặc biệt", "JACKPOT1 + (JACKPOT2 X 6) + 1,6325 TỶ"]
          ]},
          { level: 14, sub: "Chọn 14 số (30.030.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "8.250.000"],
            ["Trúng 4 số", "46.500.000"],
            ["Trúng 5 số", "492.000.000"],
            ["Trúng 5 số + số đặc biệt", "JACKPOT2 + 452 TRIỆU"],
            ["Trúng 6 số", "JACKPOT1 + 2,186 TỶ"],
            ["Trúng 6 số + số đặc biệt", "JACKPOT1 + (JACKPOT2 X 6) + 1,946 TỶ"]
          ]},
          { level: 15, sub: "Chọn 15 số (50.050.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "11.000.000"],
            ["Trúng 4 số", "60.500.000"],
            ["Trúng 5 số", "572.500.000"],
            ["Trúng 5 số + số đặc biệt", "JACKPOT2 + 532,5 TRIỆU"],
            ["Trúng 6 số", "JACKPOT1 + 2,514 TỶ"],
            ["Trúng 6 số + số đặc biệt", "JACKPOT1 + (JACKPOT2 X 6) + 2,274 TỶ"]
          ]},
          { level: 18, sub: "Chọn 18 số (185.640.000 VNĐ/1 lần dự thưởng)", rows: [
            ["Trúng 3 số", "22.750.000"],
            ["Trúng 4 số", "118.300.000"],
            ["Trúng 5 số", "858.000.000"],
            ["Trúng 5 số + số đặc biệt", "JACKPOT2 + 818 TRIỆU"],
            ["Trúng 6 số", "JACKPOT1 + 3,595 TỶ"],
            ["Trúng 6 số + số đặc biệt", "JACKPOT1 + (JACKPOT2 X 6) + 3,355 TỶ"]
          ]}
        ]
      };
      return data[type] || [];
    }
    function renderBaoPrizeTable(type) {
      const brochureCards = getBaoBrochureData(type);
      if (!brochureCards.length) return "";
      const themeClass = getBaoBrochureTheme(type);
      const cards = brochureCards.map(card => `
        <article class="bao-prize-brochure ${themeClass}">
          <div class="bao-prize-brochure-title">BAO ${escapeHtml(card.level)}</div>
          <div class="bao-prize-brochure-sub">${escapeHtml(card.sub)}</div>
          <table class="bao-prize-mini">
            <tbody>
              ${card.rows.map(row => `
                <tr>
                  <td>${escapeHtml(row[0])}</td>
                  <td>${escapeHtml(row[1])}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </article>
      `);
      return buildPrizeSection(
        "Phần 2: Bao Vé",
        escapeHtml(type === "LOTO_5_35" ? "Hiển thị theo brochure Lotto 5/35" : (type === "LOTO_6_55" ? "Hiển thị theo brochure Power 6/55" : "Hiển thị theo brochure Mega 6/45")),
        `
          <div class="bao-prize-grid">${cards.join("")}</div>
          <div class="prize-note">${buildBaoNote(type)}</div>
        `
      );
    }
    // ---abc--- Prize Panel / Brochure Rendering ---
    function renderPrizeTable(type) {
      if (type === "KENO") {
        const cols = [10, 9, 8, 7, 6, 5, 4, 3, 2, 1];
        const rows = [10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0];
        const head = cols.map(c => `<th>${c}</th>`).join("");
        const body = rows.map(r => {
          const tds = cols.map(c => {
            const v = KENO_PAYOUT[c]?.[r];
            return `<td class="${v ? "" : "empty"}">${v || "·"}</td>`;
          }).join("");
          return `<tr><th scope="row">${r}</th>${tds}</tr>`;
        }).join("");
        return `
          <div class="keno-prize-board">
            <div class="keno-prize-topbar">
              <div class="keno-prize-title">Bảng thưởng Keno</div>
              <div class="keno-prize-subtitle">Cột: số bạn chơi • Hàng: số bạn trúng</div>
            </div>
            <div class="keno-prize-layout">
              <div class="keno-prize-scroller">
                <table class="prize-table keno-prize-table">
                  <thead>
                    <tr>
                      <th class="corner">Trúng / Chơi</th>
                      ${head}
                    </tr>
                  </thead>
                  <tbody>${body}</tbody>
                </table>
              </div>
            </div>
            <div class="keno-prize-foot">
              <div class="keno-prize-note"><b>Cao nhất:</b> Bậc 10 trùng 10 số = 2 tỷ.</div>
              <div class="keno-prize-note"><b>*</b> Bậc 8-10 có giới hạn/chia thưởng theo quy định.</div>
            </div>
          </div>
        `;
      }
      if (TYPES[type]?.threeDigit) {
        if (type === "MAX_3D") {
          return `
            <div class="prize-sections">
              ${buildPrizeSection(
                "Phần Thưởng Max 3D",
                "Cơ cấu thưởng chính thức của Max 3D",
                `
                  <div class="prize-table-wrap">
                    <table class="prize-table">
                      <thead>
                        <tr>
                          <th>Giải thưởng</th>
                          <th>Kết quả</th>
                          <th>Giá trị giải thưởng (VNĐ)</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr><td>Giải Đặc Biệt</td><td>Trùng bất kỳ 1 trong 2 bộ ba số quay thưởng giải Đặc biệt theo đúng thứ tự các số</td><td>1.000.000</td></tr>
                        <tr><td>Giải Nhất</td><td>Trùng bất kỳ 1 trong 4 bộ ba số quay thưởng giải Nhất theo đúng thứ tự các số</td><td>350.000</td></tr>
                        <tr><td>Giải Nhì</td><td>Trùng bất kỳ 1 trong 6 bộ ba số quay thưởng giải Nhì theo đúng thứ tự các số</td><td>210.000</td></tr>
                        <tr><td>Giải Ba</td><td>Trùng bất kỳ 1 trong 8 bộ ba số quay thưởng giải Ba theo đúng thứ tự các số</td><td>100.000</td></tr>
                      </tbody>
                    </table>
                  </div>
                  <div class="prize-note"><b>Ghi chú:</b> Mỗi kỳ quay số mở thưởng chọn ra 20 bộ ba số trúng giải, gồm 2 giải Đặc biệt, 4 giải Nhất, 6 giải Nhì và 8 giải Ba. Nếu một bộ số trúng nhiều giải thì được lĩnh tổng các giải trúng.</div>
                `
              )}
            </div>
          `;
        }
        if (type === "MAX_3D_PRO") {
          return `
            <div class="prize-sections">
              ${buildPrizeSection(
                "Phần Thưởng Max 3D Pro",
                "Cơ cấu thưởng chính thức của Max 3D Pro",
                `
                  <div class="prize-table-wrap">
                    <table class="prize-table">
                      <thead>
                        <tr>
                          <th>Giải thưởng</th>
                          <th>Kết quả</th>
                          <th>Giá trị giải thưởng (VNĐ)</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr><td>Giải Đặc Biệt</td><td>Trùng hai bộ ba số quay thưởng giải Đặc biệt theo đúng thứ tự quay</td><td>2.000.000.000</td></tr>
                        <tr><td>Giải phụ Đặc Biệt</td><td>Trùng hai bộ ba số quay thưởng giải Đặc biệt theo ngược thứ tự quay</td><td>400.000.000</td></tr>
                        <tr><td>Giải Nhất</td><td>Trùng bất kỳ 2 trong 4 bộ ba số quay thưởng giải Nhất</td><td>30.000.000</td></tr>
                        <tr><td>Giải Nhì</td><td>Trùng bất kỳ 2 trong 6 bộ ba số quay thưởng giải Nhì</td><td>10.000.000</td></tr>
                        <tr><td>Giải Ba</td><td>Trùng bất kỳ 2 trong 8 bộ ba số quay thưởng giải Ba</td><td>4.000.000</td></tr>
                        <tr><td>Giải Tư</td><td>Trùng bất kỳ 2 bộ ba số quay thưởng của giải Đặc biệt, Nhất, Nhì hoặc Ba</td><td>1.000.000</td></tr>
                        <tr><td>Giải Năm</td><td>Trùng 1 bộ ba số quay thưởng giải Đặc biệt bất kỳ</td><td>100.000</td></tr>
                        <tr><td>Giải Sáu</td><td>Trùng 1 bộ ba số quay thưởng giải Nhất, Nhì hoặc Ba bất kỳ</td><td>40.000</td></tr>
                      </tbody>
                    </table>
                  </div>
                  <div class="prize-note"><b>Ghi chú:</b> Mỗi kỳ quay số mở thưởng chọn ra 20 bộ ba số trúng giải, gồm 2 bộ Đặc biệt, 4 bộ Nhất, 6 bộ Nhì và 8 bộ Ba. Nếu chọn hai bộ ba số giống nhau, giá trị giải từ Nhất đến Sáu được nhân đôi; riêng Đặc biệt/phụ Đặc biệt tính theo tổng giá trị hai giải tương ứng.</div>
                `
              )}
            </div>
          `;
        }
        return `
          <div class="prize-sections">
            ${buildPrizeSection(
              "Phần Thưởng Vietlott 3D",
              `Cơ cấu thưởng của ${escapeHtml(TYPES[type]?.label || type)}`,
              `<div class="prize-note"><b>Ghi chú:</b> Chưa có bảng thưởng riêng cho loại này trong panel hiện tại.</div>`
            )}
          </div>
        `;
      }
      if (type === "LOTO_5_35") {
        const regularSection = buildPrizeSection(
          "Phần 1: Vé Thường",
          "Cơ cấu thưởng chuẩn của Lotto 5/35",
          `
            <div class="prize-table-wrap">
              <table class="prize-table">
                <thead>
                  <tr>
                    <th rowspan="2">Giải thưởng</th>
                    <th colspan="2" class="group">Kết quả</th>
                    <th rowspan="2">Giá trị giải thưởng (VNĐ)</th>
                  </tr>
                  <tr>
                    <th>Các số chính</th>
                    <th>Số đặc biệt</th>
                  </tr>
                </thead>
                <tbody>
                  <tr><td>Giải Độc Đắc</td><td>${mainBalls(5, 5)}</td><td>${specialBall(true)}</td><td>(Tối thiểu 6 tỷ và tích lũy)</td></tr>
                  <tr><td>Giải Nhất</td><td>${mainBalls(5, 5)}</td><td>${specialBall(false)}</td><td>10.000.000 *</td></tr>
                  <tr><td>Giải Nhì</td><td>${mainBalls(5, 4)}</td><td>${specialBall(true)}</td><td>5.000.000 *</td></tr>
                  <tr><td>Giải Ba</td><td>${mainBalls(5, 4)}</td><td>${specialBall(false)}</td><td>500.000 *</td></tr>
                  <tr><td>Giải Tư</td><td>${mainBalls(5, 3)}</td><td>${specialBall(true)}</td><td>100.000 *</td></tr>
                  <tr><td>Giải Năm</td><td>${mainBalls(5, 3)}</td><td>${specialBall(false)}</td><td>30.000 *</td></tr>
                  <tr>
                    <td>Giải Khuyến Khích</td>
                    <td class="prize-lines">
                      <div>${mainBalls(5, 2)}</div>
                      <div>${mainBalls(5, 1)}</div>
                      <div>${mainBalls(5, 0)}</div>
                    </td>
                    <td class="prize-lines">
                      <div>${specialBall(true)}</div>
                      <div>${specialBall(true)}</div>
                      <div>${specialBall(true)}</div>
                    </td>
                    <td>10.000 *</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div class="prize-note"><b>Ghi chú:</b> ${ball("ball-main-hit")} bóng đỏ: số chính trúng | ${ball("ball-special-hit")} bóng vàng: số đặc biệt trúng | ${ball("ball-main-miss")} bóng đen/xám: số không trúng.<br><b> Các số không theo thứ tự. </b></div>
          `
        );
        return `<div class="prize-sections">${regularSection}${renderBaoPrizeTable(type)}</div>`;
      }
      if (type === "LOTO_6_45") {
        const regularSection = buildPrizeSection(
          "Phần 1: Vé Thường",
          "Cơ cấu thưởng chuẩn của Mega 6/45",
          `
            <div class="prize-table-wrap">
              <table class="prize-table">
                <thead>
                  <tr>
                    <th>Giải thưởng</th>
                    <th>Kết quả</th>
                    <th>Giá trị giải thưởng (VNĐ)</th>
                  </tr>
                </thead>
                <tbody>
                  <tr><td>Giải Đặc biệt</td><td>${mainBalls(6, 6)}</td><td>(Tối thiểu 12 tỷ và tích lũy)</td></tr>
                  <tr><td>Giải Nhất</td><td>${mainBalls(6, 5)}</td><td>10.000.000</td></tr>
                  <tr><td>Giải Nhì</td><td>${mainBalls(6, 4)}</td><td>300.000</td></tr>
                  <tr><td>Giải Ba</td><td>${mainBalls(6, 3)}</td><td>30.000</td></tr>
                </tbody>
              </table>
            </div>
            <div class="prize-note"><b>Ghi chú:</b> ${ball("ball-main-hit")} bóng đỏ: số trúng | ${ball("ball-main-miss")} bóng đen/xám: số không trúng.<br><b> Các số không theo thứ tự. </b></div>
          `
        );
        return `<div class="prize-sections">${regularSection}${renderBaoPrizeTable(type)}</div>`;
      }
      const regularSection = buildPrizeSection(
        "Phần 1: Vé Thường",
        "Cơ cấu thưởng chuẩn của Power 6/55",
        `
          <div class="prize-table-wrap">
            <table class="prize-table">
              <thead>
                <tr>
                  <th>Giải thưởng</th>
                  <th>Kết quả</th>
                  <th>Giá trị giải thưởng (VNĐ)</th>
                </tr>
              </thead>
              <tbody>
                <tr><td>Giải Jackpot 1</td><td>${mainBalls(6, 6)}</td><td>(Tối thiểu 30 tỷ và tích lũy)</td></tr>
                <tr><td>Giải Jackpot 2</td><td>${mainBalls(6, 5)} + ${specialBall(true)}</td><td>(Tối thiểu 3 tỷ và tích lũy)</td></tr>
                <tr><td>Giải Nhất</td><td>${mainBalls(6, 5)}</td><td>40.000.000</td></tr>
                <tr><td>Giải Nhì</td><td>${mainBalls(6, 4)}</td><td>500.000</td></tr>
                <tr><td>Giải Ba</td><td>${mainBalls(6, 3)}</td><td>50.000</td></tr>
              </tbody>
            </table>
          </div>
          <div class="prize-note"><b>Ghi chú:</b> ${ball("ball-main-hit")} bóng đỏ: số chính trúng | ${ball("ball-special-hit")} bóng vàng: số đặc biệt trúng (Jackpot 2) | ${ball("ball-main-miss")} bóng đen/xám: số không trúng.<br><b> Các số không theo thứ tự. </b></div>
        `
      );
      return `<div class="prize-sections">${regularSection}${renderBaoPrizeTable(type)}</div>`;
    }
    function renderPrizePanel() {
      const type = document.getElementById("prizeType").value;
      const out = document.getElementById("prizeOut");
      out.className = "result-box prize-box";
      out.innerHTML = renderPrizeTable(type);
    }
    document.getElementById("showPrizeBtn").onclick = () => renderPrizePanel();
    document.getElementById("prizeType").onchange = () => renderPrizePanel();

    function range(min, max) {
      const out = [];
      for (let i = min; i <= max; i++) out.push(i);
      return out;
    }

    function countFreqFromPicks(type) {
      const t = TYPES[type];
      const freqMain = Object.fromEntries(range(t.mainMin, t.mainMax).map(n => [n, 0]));
      const freqSpecial = t.hasSpecial ? Object.fromEntries(range(t.specialMin, t.specialMax).map(n => [n, 0])) : null;
      for (const ky of store.pickOrder[type]) {
        for (const ticket of (store.picks[type][ky] || [])) {
          for (const n of ticket.main) freqMain[n]++;
          if (t.hasSpecial && Number.isInteger(ticket.special)) freqSpecial[ticket.special]++;
        }
      }
      return { freqMain, freqSpecial };
    }

    function countFreqFromResults(type, dataset = null) {
      const t = TYPES[type];
      const resultOrder = dataset?.order || store.resultOrder[type] || [];
      const resultMap = dataset?.results || store.results[type] || {};
      const freqMain = Object.fromEntries(range(t.mainMin, t.mainMax).map(n => [n, 0]));
      const freqSpecial = t.hasSpecial ? Object.fromEntries(range(t.specialMin, t.specialMax).map(n => [n, 0])) : null;
      for (const ky of resultOrder) {
        const draw = resultMap[ky];
        if (!draw) continue;
        for (const n of draw.main) freqMain[n]++;
        if (t.hasSpecial && Number.isInteger(draw.special)) freqSpecial[draw.special]++;
      }
      return { freqMain, freqSpecial };
    }

    function sortPairs(freqObj) {
      return Object.entries(freqObj)
        .map(([num, count]) => ({ num: Number(num), count }))
        .sort((a, b) => b.count - a.count || a.num - b.num);
    }

    function unhitList(freqObj) {
      return Object.entries(freqObj).filter(([, c]) => c === 0).map(([n]) => Number(n));
    }

    const statsPickBtn = document.getElementById("statsPickBtn");
    if (statsPickBtn) statsPickBtn.onclick = () => {
      const type = document.getElementById("sType").value;
      const mode = document.getElementById("sMode").value;
      const out = document.getElementById("statsPickOut");
      if (!ensurePickMin(type, out, "In Số (chưa chọn / chọn nhiều nhất)", 3)) return;
      const t = TYPES[type];
      const { freqMain, freqSpecial } = countFreqFromPicks(type);
      const unpickedMain = unhitList(freqMain);
      const rankedMain = sortPairs(freqMain);
      let text = "";
      if (mode === "1") text = `6 số chưa được chọn: ${unpickedMain.slice(0, 6).join(", ") || "(rỗng)"}`;
      else if (mode === "2") text = `Tất cả số chưa được chọn (${unpickedMain.length} số): ${unpickedMain.join(", ") || "(rỗng)"}`;
      else if (mode === "3") text = `Top 6 số chọn nhiều nhất: ${rankedMain.slice(0, 6).map(p => `${p.num}(${p.count})`).join(", ")}`;
      else text = `Tất cả số chọn nhiều nhất (${rankedMain.length} số): ${rankedMain.map(p => `${p.num}(${p.count})`).join(", ")}`;

      if (t.hasSpecial) {
        const unpickedDb = unhitList(freqSpecial);
        const rankedDb = sortPairs(freqSpecial);
        text += `\n\nĐB chưa được chọn: ${unpickedDb.join(", ") || "(rỗng)"}`;
        text += `\nSố ĐB chọn nhiều nhất: ${rankedDb.map(p => `${p.num}(${p.count})`).join(", ") || "(rỗng)"}`;
      }
      line(out, text);
    };

    const statsOutBtn = document.getElementById("statsOutBtn");
    if (statsOutBtn) statsOutBtn.onclick = async () => {
      const type = document.getElementById("oType").value;
      const mode = document.getElementById("oMode").value;
      const out = document.getElementById("statsOutOut");
      if (!await ensureResultOnly(type, out, "In kết quả (chưa trúng / trúng nhiều nhất)")) return;
      const t = TYPES[type];
      const dataset = buildPredictionResultDataset(type);
      const { freqMain, freqSpecial } = countFreqFromResults(type, dataset);
      const unhitMain = unhitList(freqMain);
      const rankedMain = sortPairs(freqMain);
      let text = `(${dataset.sourceText || "Dựa vào tất cả dữ liệu KQ hiện có"})\n\n`;
      if (mode === "1") text += `6 số chưa trúng: ${unhitMain.slice(0, 6).join(", ") || "(rỗng)"}`;
      else if (mode === "2") text += `Tất cả số chưa trúng (${unhitMain.length} số): ${unhitMain.join(", ") || "(rỗng)"}`;
      else if (mode === "3") text += `Top 6 số trúng nhiều nhất: ${rankedMain.slice(0, 6).map(p => `${p.num}(${p.count})`).join(", ")}`;
      else text += `Tất cả số trúng nhiều nhất (${rankedMain.length} số): ${rankedMain.map(p => `${p.num}(${p.count})`).join(", ")}`;

      if (t.hasSpecial) {
        const rankedDb = sortPairs(freqSpecial);
        if (type === "LOTO_5_35") {
          const unhitDb = unhitList(freqSpecial);
          text += `\n\nĐB chưa trúng: ${unhitDb.join(", ") || "(rỗng)"}`;
        }
        text += `\nSố ĐB trúng nhiều nhất: ${rankedDb.map(p => `${p.num}(${p.count})`).join(", ") || "(rỗng)"}`;
      }
      line(out, text);
    };

    function pickRandomDistinct(nums, count) {
      const arr = [...nums];
      const out = [];
      while (arr.length && out.length < count) {
        const i = Math.floor(Math.random() * arr.length);
        out.push(arr[i]);
        arr.splice(i, 1);
      }
      return out;
    }

    function buildCandidateScores(type, candidates, freqMap, recentSet = new Set(), isSpecial = false) {
      const t = TYPES[type];
      const min = isSpecial ? t.specialMin : t.mainMin;
      const max = isSpecial ? t.specialMax : t.mainMax;
      const safeCandidates = Array.isArray(candidates) ? candidates.filter(Number.isFinite) : [];
      const maxFreq = Math.max(1, ...safeCandidates.map(number => Number(freqMap?.[number] || 0)));
      const scores = {};

      safeCandidates.forEach(number => {
        const freqNorm = clamp01(Number(freqMap?.[number] || 0) / maxFreq);
        const coldNorm = 1 - freqNorm;
        const pos = (number - min) / Math.max(1, (max - min));
        const centerNorm = 1 - Math.abs((pos * 2) - 1);
        const recentPenalty = recentSet?.has(number) ? 0.42 : 0;
        const score = (freqNorm * 0.52) + (coldNorm * 0.28) + (centerNorm * 0.20) - recentPenalty;
        scores[number] = Math.max(0.02, Number(score.toFixed(6)));
      });

      return scores;
    }

    function pickWeightedDistinctByScore(candidates, scoreMap, count, options = {}) {
      const minDistance = Math.max(0, Number(options?.minDistance || 0));
      const targetCount = Math.max(0, Math.floor(Number(count || 0)));
      const pool = Array.from(new Set((Array.isArray(candidates) ? candidates : []).filter(Number.isFinite)));
      const picked = [];

      while (pool.length && picked.length < targetCount) {
        let eligible = pool.filter(number =>
          !picked.includes(number) &&
          (minDistance <= 0 || picked.every(existing => Math.abs(existing - number) >= minDistance))
        );
        if (!eligible.length) {
          eligible = pool.filter(number => !picked.includes(number));
        }
        if (!eligible.length) break;

        const weighted = eligible.map(number => ({
          number,
          weight: Math.max(0.001, Number(scoreMap?.[number] || 0.001))
        }));
        const totalWeight = weighted.reduce((sum, entry) => sum + entry.weight, 0);
        let randomValue = Math.random() * Math.max(totalWeight, 0.001);
        let chosen = weighted[weighted.length - 1]?.number;

        for (const entry of weighted) {
          randomValue -= entry.weight;
          if (randomValue <= 0) {
            chosen = entry.number;
            break;
          }
        }

        if (!Number.isFinite(chosen)) break;
        picked.push(chosen);
        const index = pool.indexOf(chosen);
        if (index >= 0) pool.splice(index, 1);
      }

      return picked;
    }

    function getSortedResultDraws(type, dataset = null) {
      const resultOrder = dataset?.order || store.resultOrder[type] || [];
      const resultMap = dataset?.results || store.results[type] || {};
      const keys = [...resultOrder].sort((a, b) => kySortValue(a) - kySortValue(b));
      return keys
        .map(ky => ({ ky, draw: resultMap[ky] }))
        .filter(x => x.draw);
    }

    function clamp01(v) {
      return Math.max(0, Math.min(1, v));
    }

    function parsePredictRecentWindowValue(rawValue) {
      const normalized = String(rawValue ?? "").trim().toLowerCase();
      const parsed = Number(normalized || "0");
      return Number.isInteger(parsed) ? parsed : NaN;
    }

    function isPredictRecentWindowDisabled(recentCount) {
      return recentCount === 0;
    }

    function getRecentResultExclusionsFromEntries(type, entries, recentCount) {
      const t = TYPES[type];
      if (isPredictRecentWindowDisabled(recentCount)) {
        return { mode: "none", keys: [], mainSet: new Set(), specialSet: new Set() };
      }
      const n = Math.max(0, recentCount);
      const recentEntries = n === 0 ? [] : entries.slice(-n);
      const keys = recentEntries.map(entry => entry.ky);
      const mainSet = new Set();
      const specialSet = new Set();
      for (const entry of recentEntries) {
        for (const number of (entry.draw?.main || [])) mainSet.add(number);
        if (t.hasSpecial && Number.isInteger(entry.draw?.special)) specialSet.add(entry.draw.special);
      }
      return { mode: "count", keys, mainSet, specialSet };
    }

    function getRecentResultExclusions(type, recentCount, dataset = null) {
      const entries = getSortedResultDraws(type, dataset);
      return getRecentResultExclusionsFromEntries(type, entries, recentCount);
    }

    function buildPairKey(a, b) {
      return a < b ? `${a}-${b}` : `${b}-${a}`;
    }

    function buildPredictionStatsFromEntries(type, entries) {
      const t = TYPES[type];
      const mainNumbers = range(t.mainMin, t.mainMax);
      const specialNumbers = t.hasSpecial ? range(t.specialMin, t.specialMax) : [];
      const recentShortEntries = entries.slice(-12);
      const recentLongEntries = entries.slice(-24);
      const stats = {
        drawCount: entries.length,
        mainFreqAll: Object.fromEntries(mainNumbers.map(n => [n, 0])),
        mainFreqRecentShort: Object.fromEntries(mainNumbers.map(n => [n, 0])),
        mainFreqRecentLong: Object.fromEntries(mainNumbers.map(n => [n, 0])),
        mainLastSeen: Object.fromEntries(mainNumbers.map(n => [n, -1])),
        specialFreqAll: t.hasSpecial ? Object.fromEntries(specialNumbers.map(n => [n, 0])) : null,
        specialFreqRecentShort: t.hasSpecial ? Object.fromEntries(specialNumbers.map(n => [n, 0])) : null,
        specialFreqRecentLong: t.hasSpecial ? Object.fromEntries(specialNumbers.map(n => [n, 0])) : null,
        specialLastSeen: t.hasSpecial ? Object.fromEntries(specialNumbers.map(n => [n, -1])) : null,
        pairCounts: new Map(),
        maxPairCount: 1,
      };

      entries.forEach((entry, idx) => {
        const main = [...(entry.draw?.main || [])].sort((a, b) => a - b);
        main.forEach(number => {
          stats.mainFreqAll[number] += 1;
          stats.mainLastSeen[number] = idx;
        });
        for (let i = 0; i < main.length; i++) {
          for (let j = i + 1; j < main.length; j++) {
            const key = buildPairKey(main[i], main[j]);
            const nextCount = Number(stats.pairCounts.get(key) || 0) + 1;
            stats.pairCounts.set(key, nextCount);
            if (nextCount > stats.maxPairCount) stats.maxPairCount = nextCount;
          }
        }
        if (t.hasSpecial && Number.isInteger(entry.draw?.special)) {
          stats.specialFreqAll[entry.draw.special] += 1;
          stats.specialLastSeen[entry.draw.special] = idx;
        }
      });

      recentShortEntries.forEach(entry => {
        for (const number of (entry.draw?.main || [])) stats.mainFreqRecentShort[number] += 1;
        if (t.hasSpecial && Number.isInteger(entry.draw?.special)) stats.specialFreqRecentShort[entry.draw.special] += 1;
      });

      recentLongEntries.forEach(entry => {
        for (const number of (entry.draw?.main || [])) stats.mainFreqRecentLong[number] += 1;
        if (t.hasSpecial && Number.isInteger(entry.draw?.special)) stats.specialFreqRecentLong[entry.draw.special] += 1;
      });

      return stats;
    }

    function getLotteryPredictionStrategies(type) {
      const specialHeavy = type === "LOTO_5_35";
      return [
        {
          key: "balanced",
          label: "Cân bằng có độ trễ",
          main: { global: 0.15, recentShort: 0.12, recentLong: 0.18, overdue: 0.24, cold: 0.08, pair: 0.11, center: 0.04, structure: 0.08, recentPenalty: 0.34, usagePenalty: 0.18 },
          special: { global: 0.20, recentShort: 0.16, recentLong: 0.22, overdue: 0.18, cold: 0.10, pair: 0, center: 0.06, structure: 0, recentPenalty: specialHeavy ? 0.38 : 0.26, usagePenalty: 0.12 },
        },
        {
          key: "momentum",
          label: "Động lực gần",
          main: { global: 0.20, recentShort: 0.26, recentLong: 0.20, overdue: 0.08, cold: 0.03, pair: 0.12, center: 0.03, structure: 0.08, recentPenalty: 0.20, usagePenalty: 0.18 },
          special: { global: 0.22, recentShort: 0.24, recentLong: 0.22, overdue: 0.08, cold: 0.04, pair: 0, center: 0.05, structure: 0, recentPenalty: specialHeavy ? 0.24 : 0.16, usagePenalty: 0.12 },
        },
        {
          key: "overdue",
          label: "Độ trễ kiểm soát",
          main: { global: 0.07, recentShort: 0.06, recentLong: 0.10, overdue: 0.39, cold: 0.18, pair: 0.10, center: 0.02, structure: 0.08, recentPenalty: 0.42, usagePenalty: 0.20 },
          special: { global: 0.08, recentShort: 0.10, recentLong: 0.14, overdue: 0.34, cold: 0.20, pair: 0, center: 0.05, structure: 0, recentPenalty: specialHeavy ? 0.34 : 0.20, usagePenalty: 0.12 },
        },
        {
          key: "pairs",
          label: "Tần suất và cặp số",
          main: { global: 0.24, recentShort: 0.14, recentLong: 0.18, overdue: 0.08, cold: 0.04, pair: 0.18, center: 0.03, structure: 0.07, recentPenalty: 0.18, usagePenalty: 0.16 },
          special: { global: 0.26, recentShort: 0.18, recentLong: 0.22, overdue: 0.10, cold: 0.05, pair: 0, center: 0.05, structure: 0, recentPenalty: specialHeavy ? 0.24 : 0.16, usagePenalty: 0.12 },
        }
      ];
    }

    function buildNumberUsageMap(tickets, kind = "main") {
      const usage = {};
      for (const ticket of tickets) {
        if (kind === "special") {
          if (Number.isInteger(ticket?.special)) usage[ticket.special] = Number(usage[ticket.special] || 0) + 1;
          continue;
        }
        for (const number of (ticket?.main || [])) {
          usage[number] = Number(usage[number] || 0) + 1;
        }
      }
      return usage;
    }

    function buildStructureBalanceScore(type, selectedNumbers) {
      if (!selectedNumbers.length) return 0.5;
      const t = TYPES[type];
      const ordered = [...selectedNumbers].sort((a, b) => a - b);
      const midpoint = (t.mainMin + t.mainMax) / 2;
      const oddCount = ordered.filter(number => number % 2 !== 0).length;
      const lowCount = ordered.filter(number => number <= midpoint).length;
      const oddTarget = ordered.length / 2;
      const lowTarget = ordered.length / 2;
      const oddScore = 1 - Math.abs(oddCount - oddTarget) / Math.max(1, ordered.length);
      const lowScore = 1 - Math.abs(lowCount - lowTarget) / Math.max(1, ordered.length);
      const spread = ordered.length >= 2
        ? (ordered[ordered.length - 1] - ordered[0]) / Math.max(1, (t.mainMax - t.mainMin))
        : 0.45;
      const spreadScore = ordered.length >= 2 ? clamp01(spread * 1.15) : 0.45;
      return (oddScore * 0.38) + (lowScore * 0.38) + (spreadScore * 0.24);
    }

    function buildPredictionContext(type, historyEntries, strategy, recentCount) {
      const t = TYPES[type];
      const stats = buildPredictionStatsFromEntries(type, historyEntries);
      const recent = getRecentResultExclusionsFromEntries(type, historyEntries, recentCount);
      const allMainCandidates = range(t.mainMin, t.mainMax);
      const allSpecialCandidates = t.hasSpecial ? range(t.specialMin, t.specialMax) : [];
      const filteredMainCandidates = allMainCandidates.filter(number => !recent.mainSet.has(number));
      const filteredSpecialCandidates = allSpecialCandidates.filter(number => !recent.specialSet.has(number));
      return {
        type,
        t,
        strategy,
        stats,
        recent,
        historyEntries,
        mainCandidates: filteredMainCandidates.length >= t.mainCount ? filteredMainCandidates : allMainCandidates,
        specialCandidates: t.hasSpecial ? (filteredSpecialCandidates.length ? filteredSpecialCandidates : allSpecialCandidates) : [],
      };
    }

    function scorePredictionCandidate(context, candidate, options = {}) {
      const isSpecial = !!options.isSpecial;
      const selected = options.selected || [];
      const usageMap = options.usageMap || {};
      const usageCount = Number(usageMap[candidate] || 0);
      const bundleIndex = Number(options.bundleIndex || 0);
      const weights = isSpecial ? context.strategy.special : context.strategy.main;
      const min = isSpecial ? context.t.specialMin : context.t.mainMin;
      const max = isSpecial ? context.t.specialMax : context.t.mainMax;
      const freqAll = isSpecial ? context.stats.specialFreqAll : context.stats.mainFreqAll;
      const freqRecentShort = isSpecial ? context.stats.specialFreqRecentShort : context.stats.mainFreqRecentShort;
      const freqRecentLong = isSpecial ? context.stats.specialFreqRecentLong : context.stats.mainFreqRecentLong;
      const lastSeen = isSpecial ? context.stats.specialLastSeen : context.stats.mainLastSeen;
      const recentSet = isSpecial ? context.recent.specialSet : context.recent.mainSet;
      const candidates = isSpecial ? context.specialCandidates : context.mainCandidates;
      const maxAll = Math.max(1, ...candidates.map(number => Number(freqAll?.[number] || 0)));
      const maxRecentShort = Math.max(1, ...candidates.map(number => Number(freqRecentShort?.[number] || 0)));
      const maxRecentLong = Math.max(1, ...candidates.map(number => Number(freqRecentLong?.[number] || 0)));
      const globalFreqNorm = clamp01(Number(freqAll?.[candidate] || 0) / maxAll);
      const recentShortNorm = clamp01(Number(freqRecentShort?.[candidate] || 0) / maxRecentShort);
      const recentLongNorm = clamp01(Number(freqRecentLong?.[candidate] || 0) / maxRecentLong);
      const coldNorm = 1 - globalFreqNorm;
      const gap = Number(lastSeen?.[candidate] ?? -1) < 0
        ? context.stats.drawCount
        : Math.max(0, context.stats.drawCount - 1 - Number(lastSeen[candidate] || 0));
      const overdueNorm = context.stats.drawCount <= 1 ? 0.5 : clamp01(gap / context.stats.drawCount);
      const pos = (candidate - min) / Math.max(1, (max - min));
      const centerNorm = 1 - Math.abs((pos * 2) - 1);
      let pairNorm = 0;
      if (!isSpecial && selected.length) {
        const pairScore = selected.reduce((sum, picked) => sum + Number(context.stats.pairCounts.get(buildPairKey(picked, candidate)) || 0), 0);
        pairNorm = clamp01((pairScore / selected.length) / Math.max(1, context.stats.maxPairCount));
      }
      const structureNorm = !isSpecial ? buildStructureBalanceScore(context.type, [...selected, candidate]) : 0;
      const recentPenalty = recentSet.has(candidate) ? 1 : 0;

      return (
        (weights.global * globalFreqNorm) +
        (weights.recentShort * recentShortNorm) +
        (weights.recentLong * recentLongNorm) +
        (weights.overdue * overdueNorm) +
        (weights.cold * coldNorm) +
        (weights.pair * pairNorm) +
        (weights.center * centerNorm) +
        (weights.structure * structureNorm) -
        (weights.recentPenalty * recentPenalty) -
        (weights.usagePenalty * usageCount) -
        (bundleIndex * usageCount * 0.015)
      );
    }

    function rankPredictionCandidates(context, options = {}) {
      const isSpecial = !!options.isSpecial;
      const candidates = isSpecial ? context.specialCandidates : context.mainCandidates;
      const selected = options.selected || [];
      const usageMap = options.usageMap || {};
      const bundleIndex = Number(options.bundleIndex || 0);
      return candidates
        .map(number => ({
          number,
          score: scorePredictionCandidate(context, number, { isSpecial, selected, usageMap, bundleIndex })
        }))
        .sort((a, b) => b.score - a.score || a.number - b.number);
    }

    function buildOptimizedPredictionTicket(context, existingTickets = []) {
      const mainUsage = buildNumberUsageMap(existingTickets, "main");
      const main = [];
      while (main.length < context.t.mainCount) {
        const ranked = rankPredictionCandidates(context, {
          selected: main,
          usageMap: mainUsage,
          bundleIndex: existingTickets.length,
        });
        const chosen = ranked.find(item => !main.includes(item.number));
        if (!chosen) break;
        main.push(chosen.number);
      }
      main.sort((a, b) => a - b);

      let special = null;
      if (context.t.hasSpecial) {
        const specialUsage = buildNumberUsageMap(existingTickets, "special");
        const rankedSpecial = rankPredictionCandidates(context, {
          isSpecial: true,
          usageMap: specialUsage,
          bundleIndex: existingTickets.length,
        });
        special = rankedSpecial[0]?.number ?? context.t.specialMin;
      }

      return { main, special };
    }

    function getPredictionHitThreshold(type) {
      if (TYPES[type]?.threeDigit) return 1;
      return type === "LOTO_5_35" ? 3 : 3;
    }

    function getResolvedPredictionLogStats(type) {
      if (!PREDICTION_LOG_TYPES.includes(type)) return { byStrategy: {}, recentResolved: [] };
      const logs = ensurePredictionLogBucket(type)
        .filter(entry => entry?.resolved && entry?.resultSummary && entry?.strategyKey)
        .sort((a, b) => Date.parse(a.resolvedAt || a.createdAt || 0) - Date.parse(b.resolvedAt || b.createdAt || 0));
      const recentResolved = logs.slice(-24);
      const byStrategy = {};
      for (const entry of recentResolved) {
        const key = String(entry.strategyKey || "");
        if (!key) continue;
        if (!byStrategy[key]) {
          byStrategy[key] = {
            strategyKey: key,
            strategyLabel: String(entry.strategyLabel || key),
            count: 0,
            bestMainHitsTotal: 0,
            avgMainHitsTotal: 0,
            thresholdLogHits: 0,
            prizeLogHits: 0,
            specialLogHits: 0,
            lastResolvedAt: "",
          };
        }
        const target = byStrategy[key];
        target.count += 1;
        target.bestMainHitsTotal += Number(entry.resultSummary.bestMainHits || 0);
        target.avgMainHitsTotal += Number(entry.resultSummary.avgMainHits || 0);
        if (Number(entry.resultSummary.thresholdTicketHits || 0) > 0) target.thresholdLogHits += 1;
        if (Number(entry.resultSummary.prizeTicketHits || 0) > 0) target.prizeLogHits += 1;
        if (Number(entry.resultSummary.specialHits || 0) > 0) target.specialLogHits += 1;
        target.lastResolvedAt = entry.resolvedAt || entry.createdAt || target.lastResolvedAt;
      }
      for (const value of Object.values(byStrategy)) {
        value.avgBestMainHits = value.count ? (value.bestMainHitsTotal / value.count) : 0;
        value.avgMainHits = value.count ? (value.avgMainHitsTotal / value.count) : 0;
        value.thresholdRate = value.count ? (value.thresholdLogHits / value.count) : 0;
        value.prizeRate = value.count ? (value.prizeLogHits / value.count) : 0;
        value.specialRate = value.count ? (value.specialLogHits / value.count) : 0;
        value.composite = value.avgBestMainHits + (value.thresholdRate * 0.72) + (value.prizeRate * 0.95) + (value.specialRate * 0.24);
      }
      return { byStrategy, recentResolved };
    }

    function evaluatePredictionStrategy(type, dataset, strategy, recentCount) {
      const t = TYPES[type];
      const draws = getSortedResultDraws(type, dataset);
      const minHistory = Math.max(18, t.mainCount * 4);
      const startIndex = Math.max(minHistory, draws.length - 36);
      let tested = 0;
      let totalMainHits = 0;
      let totalSpecialHits = 0;
      let thresholdHits = 0;
      let prizeHits = 0;

      for (let index = startIndex; index < draws.length; index++) {
        const historyEntries = draws.slice(0, index);
        if (historyEntries.length < minHistory) continue;
        const context = buildPredictionContext(type, historyEntries, strategy, recentCount);
        const ticket = buildOptimizedPredictionTicket(context, []);
        if ((ticket.main || []).length !== t.mainCount) continue;
        const actual = draws[index].draw;
        const mainHits = countMainMatch(ticket.main, actual.main);
        const specialHit = t.hasSpecial && Number.isInteger(ticket.special) && ticket.special === actual.special ? 1 : 0;
        const prize = evalPrize(type, ticket, actual);
        tested += 1;
        totalMainHits += mainHits;
        totalSpecialHits += specialHit;
        if (mainHits >= getPredictionHitThreshold(type)) thresholdHits += 1;
        if (prize) prizeHits += 1;
      }

      if (!tested) {
        return {
          strategy,
          tested: 0,
          avgMainHits: 0,
          avgMainHitRate: 0,
          specialHitRate: 0,
          thresholdHitRate: 0,
          prizeHitRate: 0,
          composite: 0,
        };
      }

      const avgMainHits = totalMainHits / tested;
      const thresholdHitRate = thresholdHits / tested;
      const specialHitRate = t.hasSpecial ? totalSpecialHits / tested : 0;
      const prizeHitRate = prizeHits / tested;
      const composite = avgMainHits + (thresholdHitRate * 0.72) + (prizeHitRate * 0.90) + (specialHitRate * 0.26);

      return {
        strategy,
        tested,
        avgMainHits,
        avgMainHitRate: avgMainHits / t.mainCount,
        specialHitRate,
        thresholdHitRate,
        prizeHitRate,
        composite,
      };
    }

    function optimizeLotteryPrediction(type, dataset, bundleCount, recentCount) {
      const draws = getSortedResultDraws(type, dataset);
      const strategies = getLotteryPredictionStrategies(type);
      const liveLogStats = getResolvedPredictionLogStats(type);
      const evaluations = strategies
        .map(strategy => {
          const base = evaluatePredictionStrategy(type, dataset, strategy, recentCount);
          const live = liveLogStats.byStrategy[strategy.key] || null;
          const liveWeight = live ? Math.min(0.65, live.count / 12) : 0;
          return {
            ...base,
            live,
            blendedComposite: base.composite + ((live?.composite || 0) * liveWeight),
          };
        })
        .sort((a, b) => b.blendedComposite - a.blendedComposite || b.prizeHitRate - a.prizeHitRate || b.avgMainHits - a.avgMainHits);
      const best = evaluations[0] || { strategy: strategies[0], tested: 0, avgMainHits: 0, thresholdHitRate: 0, prizeHitRate: 0, specialHitRate: 0 };
      const context = buildPredictionContext(type, draws, best.strategy, recentCount);
      const topMainRanking = rankPredictionCandidates(context).slice(0, Math.min(12, context.mainCandidates.length)).map(item => item.number);
      const topSpecialRanking = context.t.hasSpecial
        ? rankPredictionCandidates(context, { isSpecial: true }).slice(0, Math.min(6, context.specialCandidates.length)).map(item => item.number)
        : [];
      const tickets = [];
      for (let index = 0; index < bundleCount; index++) {
        let ticket = buildOptimizedPredictionTicket(context, tickets);
        let retry = 0;
        while (
          retry < 5 &&
          tickets.some(existing =>
            String(existing?.main || []) === String(ticket?.main || []) &&
            Number(existing?.special ?? -1) === Number(ticket?.special ?? -1)
          )
        ) {
          ticket = buildOptimizedPredictionTicket(context, [...tickets, ticket]);
          retry += 1;
        }
        tickets.push(ticket);
      }
      return {
        best,
        evaluations,
        tickets,
        topMainRanking,
        topSpecialRanking,
        recentKeys: context.recent.keys,
        drawCount: draws.length,
        lastEntry: draws[draws.length - 1] || null,
        liveLogStats,
      };
    }

    function formatPredictNumber(number, type = "") {
      const normalizedType = String(type || "").trim().toUpperCase();
      const width = TYPES[normalizedType]?.threeDigit ? 3 : 2;
      return String(Number(number) || 0).padStart(width, "0");
    }

    function formatPredictNumberList(numbers, type = "") {
      return (numbers || []).map(number => formatPredictNumber(number, type)).join(", ");
    }

    function formatPredictNumberRows(numbers, type = "", perRow = 10) {
      const tokens = (Array.isArray(numbers) ? numbers : [])
        .map(value => Number(value))
        .filter(Number.isFinite)
        .map(value => formatPredictNumber(value, type));
      const rows = [];
      for (let index = 0; index < tokens.length; index += perRow) {
        rows.push(tokens.slice(index, index + perRow).join(", "));
      }
      return rows;
    }

    function formatOptimizedPredictionText(type, optimized, recentCount, sourceText) {
      const t = TYPES[type];
      const lines = [];
      if (sourceText) lines.push(sourceText);
      if (isPredictRecentWindowDisabled(recentCount)) {
        lines.push(
          `Dự đoán tối ưu bằng backtest ${optimized.best.tested || 0} kỳ, không loại số theo kỳ gần nhất.`
        );
      } else {
        lines.push(
          `Dự đoán tối ưu bằng backtest ${optimized.best.tested || 0} kỳ, loại bỏ số xuất hiện trong ${Math.min(recentCount, optimized.recentKeys.length)} kỳ gần nhất (${optimized.recentKeys.length ? optimized.recentKeys.join(", ") : "chưa có kỳ"}).`
        );
      }
      lines.push(`Chiến lược tốt nhất: ${optimized.best.strategy.label}`);
      lines.push(
        `Backtest: TB trùng ${optimized.best.avgMainHits.toFixed(2)} số/kỳ | Tỷ lệ đạt ${getPredictionHitThreshold(type)}+ số: ${(optimized.best.thresholdHitRate * 100).toFixed(2)}% | Tỷ lệ có giải: ${(optimized.best.prizeHitRate * 100).toFixed(2)}%`
      );
      if (optimized.best.live?.count) {
        lines.push(
          `Log thực tế gần đây: ${optimized.best.live.count} kỳ đã chấm | TB tốt nhất ${optimized.best.live.avgBestMainHits.toFixed(2)} số/kỳ | Tỷ lệ có giải ${(optimized.best.live.prizeRate * 100).toFixed(2)}%`
        );
      }
      lines.push(`Top ${optimized.topMainRanking.length} số ưu tiên: ${formatPredictNumberList(optimized.topMainRanking, type)}`);
      if (t.hasSpecial) {
        lines.push(`Top ${optimized.topSpecialRanking.length} số ĐB ưu tiên: ${formatPredictNumberList(optimized.topSpecialRanking, type)}`);
      }
      optimized.tickets.forEach((ticket, index) => {
        if (t.hasSpecial) {
          if (type === "LOTO_5_35") lines.push(`Kết quả dự đoán #${index + 1}: 6 số (5+1): ${formatPredictNumberList(ticket.main, type)} | ĐB ${formatPredictNumber(ticket.special, type)}`);
          else lines.push(`Kết quả dự đoán #${index + 1}: ${formatPredictNumberList(ticket.main, type)} | ĐB ${formatPredictNumber(ticket.special, type)}`);
        } else {
          lines.push(`Kết quả dự đoán #${index + 1}: ${formatPredictNumberList(ticket.main, type)}`);
        }
      });
      return lines.join("\n\n");
    }

    async function runPredictFlow({
      type,
      count,
      kenoLevel = 0,
      engineKey = null,
      triggerMode = "manual",
      triggerSourceResolvedKy = "",
    } = {}) {
      const out = document.getElementById("predictOut");
      const t = TYPES[type];
      if (predictFlowBusy) {
        if (triggerMode === "manual") line(out, "Hệ thống đang chạy một lượt dự đoán khác, bạn đợi xong rồi thử lại nhé.", "warn");
        return null;
      }
      if (!t) {
        line(out, "Loại dự đoán không hợp lệ.", "warn");
        return null;
      }
      predictFlowBusy = true;
      try {
      normalizePredictRecentWindowSelection();
      const recentCount = parsePredictRecentWindowValue(document.getElementById("pdRecentWindow").value);
      const c = Number(count || 0);
      const activePlayMode = String(predictPlayModeValue || "normal").trim().toLowerCase() === "bao" ? "bao" : "normal";
      const activeBaoLevel = Number(predictBaoLevelValue || 0);
      const aiEngine = String(engineKey || predictEngineValue || "both").trim().toLowerCase() || "both";
      const activeRiskMode = aiEngine === "both" ? normalizePredictRiskMode(predictRiskModeValue) : "balanced";
      const activeRiskModeMeta = getPredictRiskModeMeta(activeRiskMode);
      const engineMeta = getPredictEngineMeta(aiEngine);
      if (!Number.isInteger(c) || c <= 0) {
        line(out, "Số bộ dự đoán không hợp lệ.", "warn");
        return null;
      }
      const normalizedKenoLevel = t.keno ? Number(kenoLevel || 0) : 0;
      const predictCountPerTicket = t.keno ? normalizedKenoLevel : t.mainCount;
      if (AI_PREDICT_TYPES.has(type)) {
        if (t.keno && (!Number.isInteger(normalizedKenoLevel) || normalizedKenoLevel < 1 || normalizedKenoLevel > 10)) {
          out.classList.remove("muted");
          line(out, "Bậc Keno không hợp lệ (1-10).", "warn");
          return null;
        }
        if (!engineMeta.available) {
          out.classList.remove("muted");
          line(out, engineMeta.description || "Engine này chưa sẵn sàng.", "warn");
          return null;
        }
        out.classList.add("muted");
        startPredictLoading(out, engineMeta.key, engineMeta.label);
        const predictStartedAt = Date.now();
        try {
          let result;
          if (engineMeta.key === "both") {
            const [luanSoSettled, aiGenSettled] = await Promise.allSettled([
              predictWithAiBackend(type, c, normalizedKenoLevel, "luan_so", activeRiskMode, PREDICTION_MODE_NORMAL),
              predictWithAiBackend(type, c, normalizedKenoLevel, "gen_local", activeRiskMode, PREDICTION_MODE_NORMAL),
            ]);
            const luanSoResult = luanSoSettled?.status === "fulfilled" ? luanSoSettled.value : null;
            const aiGenResult = aiGenSettled?.status === "fulfilled" ? aiGenSettled.value : null;
            if (!luanSoResult && !aiGenResult) {
              const luanMessage = luanSoSettled?.reason?.message || "Luận Số lỗi";
              const aiMessage = aiGenSettled?.reason?.message || "AI Gen lỗi";
              throw new Error(`${luanMessage} | ${aiMessage}`);
            }
            result = mergeBothAiResults(type, c, luanSoResult, aiGenResult, activeRiskMode);
          } else {
            result = await predictWithAiBackend(type, c, normalizedKenoLevel, engineMeta.backendEngine || "gen_local", activeRiskMode, PREDICTION_MODE_NORMAL);
          }
          if (activePlayMode === "bao" && !t.keno) {
            const baoTickets = buildBaoPredictionTickets(
              type,
              c,
              activeBaoLevel,
              Array.isArray(result?.topRanking) ? result.topRanking : [],
              Array.isArray(result?.topSpecialRanking) ? result.topSpecialRanking : [],
              Array.isArray(result?.tickets) ? result.tickets : []
            );
            if (baoTickets.length) {
              result = {
                ...result,
                tickets: baoTickets,
              };
            }
          }
          const predictionCreatedAt = new Date().toISOString();
          const displayResult = {
            ...result,
            createdAt: predictionCreatedAt,
            engine: engineMeta.key,
            engineKey: engineMeta.key,
            engineLabel: engineMeta.label,
            riskMode: activeRiskMode,
            riskModeLabel: activeRiskModeMeta.label,
            riskModeSummary: activeRiskModeMeta.summary,
            playMode: activePlayMode,
            baoLevel: activePlayMode === "bao" ? activeBaoLevel : null,
            pickSize: t.keno ? normalizedKenoLevel : 0,
            predictionMode: PREDICTION_MODE_NORMAL,
            vipProfile: "",
          };
          if (result?.ready !== false && PREDICTION_LOG_TYPES.includes(type)) {
            if (type === "KENO" && (result?.sync || result?.latestKy || result?.nextKy)) {
              await refreshKenoPredictionDataForHistory({ silent: true });
            }
            const predictionDataset = buildPredictionResultDataset(type);
            const predictedKy = normalizeKy(result?.nextKy) || getNextPredictionKy(type, predictionDataset);
            if (predictedKy) {
              upsertPredictionLog(type, {
                createdAt: predictionCreatedAt,
                predictedKy,
                strategyKey: result?.model?.key || "",
                strategyLabel: result?.model?.label || "",
                modelKey: result?.model?.key || "",
                modelLabel: result?.model?.label || "",
                engineKey: engineMeta.key,
                engineLabel: engineMeta.label,
                riskMode: activeRiskMode,
                riskModeLabel: activeRiskModeMeta.label,
                riskModeSummary: activeRiskModeMeta.summary,
                modelVersion: result?.modelVersion || "",
                championKey: result?.champion?.key || result?.model?.key || "",
                championLabel: result?.champion?.label || result?.model?.label || "",
                lastTrainedAt: result?.lastTrainedAt || "",
                confidence: Number(result?.confidence || 0),
                recentCount: 0,
                drawCount: Number(result?.historyCount || 0),
                historyFile: String(result?.historyFile || ""),
                historyCount: Number(result?.historyCount || 0),
                bundleCount: Array.isArray(result?.tickets) ? result.tickets.length : c,
                tickets: Array.isArray(result?.tickets) ? result.tickets : [],
                ticketSources: Array.isArray(result?.ticketSources) ? result.ticketSources : [],
                topMainRanking: Array.isArray(result?.topRanking) ? result.topRanking : [],
                topSpecialRanking: Array.isArray(result?.topSpecialRanking) ? result.topSpecialRanking : [],
                backtest: result?.backtest || null,
                metaSelectionMode: String(result?.metaSelectionMode || ""),
                metaScores: result?.metaScores || null,
                metaQuota: result?.metaQuota || null,
                metaPreferredEngine: String(result?.metaPreferredEngine || ""),
                metaSummary: String(result?.metaSummary || ""),
                triggerMode: String(triggerMode || "manual"),
                triggerSourceResolvedKy: String(triggerSourceResolvedKy || ""),
                playMode: activePlayMode,
                baoLevel: activePlayMode === "bao" ? activeBaoLevel : null,
                pickSize: t.keno ? normalizedKenoLevel : 0,
                stabilityScore: Number((result?.stabilityScore ?? result?.backtest?.stabilityScore) || 0),
                predictionMode: PREDICTION_MODE_NORMAL,
                vipProfile: "",
              });
              saveStore();
            }
          }
          stopPredictLoading(engineMeta.key, Date.now() - predictStartedAt);
          renderPredictOutput(displayResult);
          return displayResult;
        } catch (err) {
          stopPredictLoading(engineMeta.key, Date.now() - predictStartedAt);
          predictLastDisplayResult = null;
          out.classList.remove("muted");
          line(out, `Không thể dự đoán bằng AI backend: ${err.message}`, "warn");
          return null;
        }
      }
      predictLastDisplayResult = null;
      if (![0, 1, 2, 3, 5].includes(recentCount)) return line(out, "Số kỳ gần nhất không hợp lệ.", "warn");
      if (!t.keno) {
        if (!await ensureResultOnly(type, out, "Dự Đoán Số Kỳ Tới")) return null;
      }
      if (!t.keno && !store.resultOrder[type].length) return line(out, "Chưa có KQ để dự đoán.", "warn");
      if (t.keno && (!Number.isInteger(normalizedKenoLevel) || normalizedKenoLevel < 1 || normalizedKenoLevel > 10)) {
        return line(out, "Bậc Keno không hợp lệ (1-10).", "warn");
      }
      if (t.keno && !store.resultOrder[type].length) {
        const all = range(t.mainMin, t.mainMax);
        const lines = [`Dự đoán Keno bậc ${predictCountPerTicket}: không loại theo KQ, sinh ngẫu nhiên trong dải ${t.mainMin}-${t.mainMax}.`];
        for (let i = 1; i <= c; i++) {
          const main = pickRandomDistinct(all, predictCountPerTicket).sort((a,b)=>a-b);
          lines.push(`Kết quả dự đoán #${i} (Keno bậc ${predictCountPerTicket}):\n${main.join(", ")}`);
        }
        return line(out, lines.join("\n\n"));
      }
      const { freqMain, freqSpecial } = countFreqFromResults(type);
      const { keys: recentKeys, mainSet: recentMainSet, specialSet: recentSpecialSet } = getRecentResultExclusions(type, recentCount);
      const allMainCandidates = range(t.mainMin, t.mainMax);
      const filteredMainCandidates = allMainCandidates.filter(n => !recentMainSet.has(n));
      const usableMainCandidates = filteredMainCandidates.length >= predictCountPerTicket ? filteredMainCandidates : allMainCandidates;
      const mainScores = buildCandidateScores(type, usableMainCandidates, freqMain, recentMainSet, false);

      const lines = [];
      if (isPredictRecentWindowDisabled(recentCount)) {
        lines.push("Dự đoán dựa trên KQ đã nhập, không loại số theo kỳ gần nhất.");
      } else {
        lines.push(`Dự đoán dựa trên KQ đã nhập + loại bỏ số xuất hiện trong ${Math.min(recentCount, recentKeys.length)} kỳ gần nhất (${recentKeys.length ? recentKeys.join(", ") : "chưa có kỳ"}).`);
      }
      if (activePlayMode === "bao" && !t.keno && activeBaoLevel > t.mainCount) {
        const topMainCandidates = usableMainCandidates.slice(0, Math.max(activeBaoLevel + 8, activeBaoLevel * 2));
        const topSpecialCandidates = t.hasSpecial
          ? range(t.specialMin, t.specialMax).filter(n => !recentSpecialSet.has(n)).slice(0, 6)
          : [];
        const baoTickets = buildBaoPredictionTickets(type, c, activeBaoLevel, topMainCandidates, topSpecialCandidates, []);
        baoTickets.forEach((ticket, index) => {
          if (t.hasSpecial && Number.isInteger(ticket.special)) {
            lines.push(`Bộ ${index + 1} • Bao ${ticket.baoLevel}: ${ticket.main.join(", ")} | ĐB ${ticket.special}`);
          } else {
            lines.push(`Bộ ${index + 1} • Bao ${ticket.baoLevel}: ${ticket.main.join(", ")}`);
          }
        });
        line(out, lines.join("\n\n"));
        return baoTickets;
      }
      for (let i = 1; i <= c; i++) {
        let main = pickWeightedDistinctByScore(usableMainCandidates, mainScores, predictCountPerTicket, { minDistance: 2 });
        main = main.slice(0, predictCountPerTicket).sort((a,b)=>a-b);

        if (t.hasSpecial) {
          const allDbCandidates = range(t.specialMin, t.specialMax);
          const filteredDbCandidates = allDbCandidates.filter(n => !recentSpecialSet.has(n));
          const usableDbCandidates = filteredDbCandidates.length ? filteredDbCandidates : allDbCandidates;
          const dbScores = buildCandidateScores(type, usableDbCandidates, freqSpecial, recentSpecialSet, true);
          const [dbPicked] = pickWeightedDistinctByScore(usableDbCandidates, dbScores, 1);
          const db = dbPicked || t.specialMin;
          if (type === "LOTO_5_35") lines.push(`Kết quả dự đoán #${i}: 6 số (5+1): ${main.join(", ")} | ĐB ${db}`);
          else lines.push(`Kết quả dự đoán #${i}: ${main.join(", ")} | ĐB ${db}`);
        } else {
          if (t.keno) lines.push(`Kết quả dự đoán #${i} (Keno bậc ${predictCountPerTicket}):\n${main.join(", ")}`);
          else lines.push(`Kết quả dự đoán #${i}: ${main.join(", ")}`);
        }
      }
      line(out, lines.join("\n\n"));
      if (t.keno) {
        line(out, "Đang đồng bộ và chạy thuật toán Keno...", "muted");
        try {
          const result = await predictKenoWithPython(normalizedKenoLevel, c);
          return line(out, formatKenoPythonPrediction(result));
        } catch (err) {
          predictLastDisplayResult = null;
          return line(out, `Không thể dự đoán Keno từ Test/L1.py: ${err.message}`, "warn");
        }
      }

      const predictionDataset = buildPredictionResultDataset(type);
      if (!predictionDataset.order.length) {
        return line(out, "Chưa có KQ để dự đoán.", "warn");
      }
      const optimized = optimizeLotteryPrediction(type, predictionDataset, c, recentCount);
      const predictedKy = getNextPredictionKy(type, predictionDataset);
      if (predictedKy) {
        upsertPredictionLog(type, {
          predictedKy,
          strategyKey: optimized.best.strategy.key,
          strategyLabel: optimized.best.strategy.label,
          recentCount,
          drawCount: optimized.drawCount,
          bundleCount: optimized.tickets.length,
          tickets: optimized.tickets,
          topMainRanking: optimized.topMainRanking,
          topSpecialRanking: optimized.topSpecialRanking,
          triggerMode: String(triggerMode || "manual"),
          triggerSourceResolvedKy: String(triggerSourceResolvedKy || ""),
        });
        saveStore();
      }
      line(out, formatOptimizedPredictionText(type, optimized, recentCount, predictionDataset.sourceText));
      return optimized;
      } finally {
        predictFlowBusy = false;
      }
    }

    function applyVipPredictionProfile(result, requestedBundleCount = 1) {
      const type = String(result?.type || "").trim().toUpperCase();
      if (!AI_PREDICT_TYPES.has(type)) return result;
      // predictor_v2 integration start
      const adaptiveVipMeta = getAdaptiveVipPredictorMeta(result);
      if (adaptiveVipMeta.active) {
        return {
          ...result,
          predictionMode: PREDICTION_MODE_VIP,
          vipProfile: String(result?.vipProfile || `${adaptiveVipMeta.key}_adaptive`).trim() || `${adaptiveVipMeta.key}_adaptive`,
          vipSummary: String(result?.vipSummary || `${adaptiveVipMeta.label} đang giữ 1 bộ chính và ${Math.max(0, (Array.isArray(result?.tickets) ? result.tickets.length : 0) - 1)} bộ phụ.`),
          notes: [
            String(result?.vipSummary || ""),
            ...(Array.isArray(result?.notes) ? result.notes : []),
          ].filter(Boolean),
        };
      }
      // predictor_v2 integration end
      const nextCount = Math.max(1, Math.min(3, Number(requestedBundleCount || 1) || 1));
      const analyses = buildPredictVipTicketAnalyses(result);
      const selected = analyses.slice(0, Math.min(nextCount, analyses.length));
      const selectedIndexes = new Set(selected.map(item => item.index));
      const preferredMainTop = type === "KENO" ? 20 : (TYPES[type]?.threeDigit ? 12 : 12);
      const preferredSpecialTop = TYPES[type]?.hasSpecial ? 6 : 0;
      return {
        ...result,
        predictionMode: PREDICTION_MODE_VIP,
        vipProfile: "strict_select",
        vipSummary: `Vip đang lọc gắt ${selected.length} bộ ưu tiên chính từ ${Array.isArray(result?.tickets) ? result.tickets.length : 0} bộ gốc.`,
        tickets: selected.map(item => item.ticket),
        ticketSources: Array.isArray(result?.ticketSources)
          ? result.ticketSources.filter((_, index) => selectedIndexes.has(index))
          : [],
        topRanking: Array.isArray(result?.topRanking) ? result.topRanking.slice(0, preferredMainTop) : [],
        topSpecialRanking: Array.isArray(result?.topSpecialRanking) ? result.topSpecialRanking.slice(0, preferredSpecialTop) : [],
        notes: [
          `Vip profile • strict_select • ${selected.length} bộ ưu tiên`,
          String(result?.vipSummary || ""),
          ...(Array.isArray(result?.notes) ? result.notes : []),
        ].filter(Boolean),
      };
    }

    async function runVipPredictFlow() {
      const type = String(document.getElementById("vipPdType")?.value || vipPredictTypeValue || "").trim().toUpperCase();
      const out = document.getElementById("predictVipOut");
      const t = TYPES[type];
      if (!t || !AI_PREDICT_TYPES.has(type)) {
        if (out) line(out, "Loại Vip không hợp lệ.", "warn");
        return null;
      }
      const count = Math.max(1, Math.min(3, Number(document.getElementById("vipPdCount")?.value || vipPredictCountValue || 1) || 1));
      const kenoLevel = t.keno ? Math.max(1, Math.min(10, Number(document.getElementById("vipPdKenoLevel")?.value || vipPredictKenoLevelValue || 5) || 5)) : 0;
      vipPredictTypeValue = type;
      vipPredictCountValue = count;
      vipPredictKenoLevelValue = kenoLevel || vipPredictKenoLevelValue;
      saveVipPredictState();
      if (predictFlowBusy) {
        if (out) line(out, "Hệ thống đang chạy một lượt dự đoán khác, bạn đợi xong rồi thử lại nhé.", "warn");
        return null;
      }
      predictFlowBusy = true;
      try {
        const engineMeta = getPredictEngineMeta(vipPredictEngineValue);
        const activeRiskMode = engineMeta.key === "both" ? normalizePredictRiskMode(vipPredictRiskModeValue) : "balanced";
        if (!engineMeta.available) {
          if (out) line(out, engineMeta.description || "Engine Vip chưa sẵn sàng.", "warn");
          return null;
        }
        if (out) {
          out.classList.add("muted");
          line(out, "Đang tổng hợp bộ Vip theo profile chọn lọc cao...", "muted");
        }
        const startedAt = Date.now();
        let result;
        // predictor_v2 integration start
        const useAdaptiveVipPredictor = type === "LOTO_5_35" || type === "LOTO_6_45" || type === "LOTO_6_55";
        if (useAdaptiveVipPredictor) {
          result = await predictWithAiBackend(type, count, kenoLevel, engineMeta.backendEngine || "gen_local", activeRiskMode, PREDICTION_MODE_VIP);
        } else if (engineMeta.key === "both") {
          const [luanSoSettled, aiGenSettled] = await Promise.allSettled([
            predictWithAiBackend(type, count, kenoLevel, "luan_so", activeRiskMode, PREDICTION_MODE_VIP),
            predictWithAiBackend(type, count, kenoLevel, "gen_local", activeRiskMode, PREDICTION_MODE_VIP),
          ]);
          const luanSoResult = luanSoSettled?.status === "fulfilled" ? luanSoSettled.value : null;
          const aiGenResult = aiGenSettled?.status === "fulfilled" ? aiGenSettled.value : null;
          if (!luanSoResult && !aiGenResult) {
            throw new Error(`${luanSoSettled?.reason?.message || "Luận Số lỗi"} | ${aiGenSettled?.reason?.message || "AI Gen lỗi"}`);
          }
          result = mergeBothAiResults(type, count, luanSoResult, aiGenResult, activeRiskMode);
        } else {
          result = await predictWithAiBackend(type, count, kenoLevel, engineMeta.backendEngine || "gen_local", activeRiskMode, PREDICTION_MODE_VIP);
        }
        // predictor_v2 integration end
        if (vipPredictPlayModeValue === "bao" && !t.keno) {
          const baoTickets = buildBaoPredictionTickets(
            type,
            count,
            Number(vipPredictBaoLevelValue || 0),
            Array.isArray(result?.topRanking) ? result.topRanking : [],
            Array.isArray(result?.topSpecialRanking) ? result.topSpecialRanking : [],
            Array.isArray(result?.tickets) ? result.tickets : []
          );
          if (baoTickets.length) result = { ...result, tickets: baoTickets };
        }
        const adaptiveVipMeta = getAdaptiveVipPredictorMeta(result);
        const isPredictorV2Vip = adaptiveVipMeta.active;
        const displayResult = applyVipPredictionProfile({
          ...result,
          createdAt: new Date().toISOString(),
          // predictor_v2 integration start
          engine: isPredictorV2Vip ? adaptiveVipMeta.key : engineMeta.key,
          engineKey: isPredictorV2Vip ? adaptiveVipMeta.key : engineMeta.key,
          engineLabel: isPredictorV2Vip ? adaptiveVipMeta.label : engineMeta.label,
          // predictor_v2 integration end
          riskMode: activeRiskMode,
          riskModeLabel: getPredictRiskModeMeta(activeRiskMode).label,
          riskModeSummary: getPredictRiskModeMeta(activeRiskMode).summary,
          playMode: vipPredictPlayModeValue,
          baoLevel: vipPredictPlayModeValue === "bao" ? Number(vipPredictBaoLevelValue || 0) : null,
          pickSize: t.keno ? kenoLevel : 0,
        }, count);
        if (result?.ready !== false && PREDICTION_LOG_TYPES.includes(type)) {
          const predictionDataset = buildPredictionResultDataset(type);
          const predictedKy = normalizeKy(result?.nextKy) || getNextPredictionKy(type, predictionDataset);
          if (predictedKy) {
            upsertPredictionLog(type, {
              createdAt: displayResult.createdAt,
              predictedKy,
              strategyKey: result?.model?.key || "",
              strategyLabel: result?.model?.label || "",
              modelKey: result?.model?.key || "",
              modelLabel: result?.model?.label || "",
              engineKey: isPredictorV2Vip ? String(displayResult?.engineKey || adaptiveVipMeta.key) : engineMeta.key,
              engineLabel: isPredictorV2Vip ? String(displayResult?.engineLabel || adaptiveVipMeta.label) : `${engineMeta.label} • Vip`,
              riskMode: activeRiskMode,
              riskModeLabel: getPredictRiskModeMeta(activeRiskMode).label,
              riskModeSummary: getPredictRiskModeMeta(activeRiskMode).summary,
              modelVersion: result?.modelVersion || "",
              championKey: result?.champion?.key || result?.model?.key || "",
              championLabel: `Vip • ${result?.champion?.label || result?.model?.label || ""}`.trim(),
              lastTrainedAt: result?.lastTrainedAt || "",
              confidence: Number(result?.confidence || 0),
              drawCount: Number(result?.historyCount || 0),
              historyFile: String(result?.historyFile || ""),
              historyCount: Number(result?.historyCount || 0),
              bundleCount: Array.isArray(displayResult?.tickets) ? displayResult.tickets.length : count,
              tickets: Array.isArray(displayResult?.tickets) ? displayResult.tickets : [],
              ticketSources: Array.isArray(displayResult?.ticketSources) ? displayResult.ticketSources : [],
              topMainRanking: Array.isArray(displayResult?.topRanking) ? displayResult.topRanking : [],
              topSpecialRanking: Array.isArray(displayResult?.topSpecialRanking) ? displayResult.topSpecialRanking : [],
              backtest: result?.backtest || null,
              metaSelectionMode: String(result?.metaSelectionMode || ""),
              metaScores: result?.metaScores || null,
              metaQuota: result?.metaQuota || null,
              metaPreferredEngine: String(result?.metaPreferredEngine || ""),
              metaSummary: String(displayResult?.vipSummary || result?.metaSummary || ""),
              playMode: vipPredictPlayModeValue,
              baoLevel: vipPredictPlayModeValue === "bao" ? Number(vipPredictBaoLevelValue || 0) : null,
              pickSize: t.keno ? kenoLevel : 0,
              stabilityScore: Number((result?.stabilityScore ?? result?.backtest?.stabilityScore) || 0),
              predictionMode: PREDICTION_MODE_VIP,
              vipProfile: String(displayResult?.vipProfile || "strict_select"),
            });
            saveStore();
          }
        }
        stopPredictLoading(engineMeta.key, Date.now() - startedAt);
        renderPredictVipOutput(displayResult);
        return displayResult;
      } catch (err) {
        if (out) {
          vipPredictLastDisplayResult = null;
          out.classList.remove("muted");
          line(out, `Không thể dự đoán Vip: ${err.message}`, "warn");
        }
        return null;
      } finally {
        predictFlowBusy = false;
      }
    }

    // ----- Hành động dự đoán ----- 
    // Nút Dự đoán đi qua đây để chọn engine phù hợp, gọi backend và đổ kết quả vào predictOut.
    document.getElementById("predictBtn").onclick = async () => {
      const type = document.getElementById("pdType").value;
      const c = Number(document.getElementById("pdCount").value || 0);
      const t = TYPES[type];
      const kenoLevel = t?.keno ? Number(document.getElementById("pdKenoLevel").value || 0) : 0;
      await runPredictFlow({
        type,
        count: c,
        kenoLevel,
        engineKey: String(predictEngineValue || "both").trim().toLowerCase() || "both",
        triggerMode: "manual",
      });
    };
    const vipPredictBtn = document.getElementById("vipPredictBtn");
    if (vipPredictBtn) {
      vipPredictBtn.onclick = async () => {
        await runVipPredictFlow();
      };
    }

    function countMainMatch(a, b) {
      const set = new Set(b);
      let c = 0;
      for (const n of a) if (set.has(n)) c++;
      return c;
    }

    function evalPrize(type, ticket, draw) {
      if (String(ticket?.playMode || "").trim().toLowerCase() === "bao") return null;
      const m = countMainMatch(ticket.main, draw.main);
      const hasDb = TYPES[type].hasSpecial;
      const hitDb = hasDb && ticket.special === draw.special;
      if (TYPES[type]?.threeDigit) {
        const targets = Array.isArray(ticket?.main)
          ? ticket.main.map(number => formatPredictNumber(number, type))
          : [];
        if (!targets.length) return null;
        const lines = Array.isArray(draw?.displayLines) ? draw.displayLines : [];
        const matchedTargets = new Set();
        const matchedLabels = [];
        for (const lineText of lines) {
          const line = String(lineText || "");
          const hitTargets = targets.filter(target => new RegExp(`(^|\\D)${target}(\\D|$)`).test(line));
          if (!hitTargets.length) continue;
          const label = line.includes(":") ? line.split(":")[0].trim() : "Trúng";
          hitTargets.forEach(target => matchedTargets.add(target));
          if (label) matchedLabels.push(label);
        }
        if (!matchedTargets.size) return null;
        const uniqueLabels = [...new Set(matchedLabels.filter(Boolean))];
        return [
          `Trúng ${matchedTargets.size}/${targets.length} bộ`,
          uniqueLabels.length ? uniqueLabels.join(" • ") : `Theo bảng thưởng ${TYPES[type]?.label || "3D"}`
        ];
      }
      if (type === "KENO") {
        const level = ticket.main.length;
        const money = KENO_PAYOUT[level]?.[m];
        if (!money) return null;
        return [`Trúng ${m}/${level} (bậc ${level})`, money];
      }
      if (type === "LOTO_5_35") {
        if (m === 5 && hitDb) return ["Giải Độc Đắc", "Tối thiểu 6 tỷ và tích lũy"];
        if (m === 5) return ["Giải Nhất", "10.000.000"];
        if (m === 4 && hitDb) return ["Giải Nhì", "5.000.000"];
        if (m === 4) return ["Giải Ba", "500.000"];
        if (m === 3 && hitDb) return ["Giải Tư", "100.000"];
        if (m === 3) return ["Giải Năm", "30.000"];
        if (hitDb && m <= 2) return ["Giải Khuyến Khích", "10.000"];
        return null;
      }
      if (type === "LOTO_6_45") {
        if (m === 6) return ["Giải Đặc biệt", "Tối thiểu 12 tỷ và tích lũy"];
        if (m === 5) return ["Giải Nhất", "10.000.000"];
        if (m === 4) return ["Giải Nhì", "300.000"];
        if (m === 3) return ["Giải Ba", "30.000"];
        return null;
      }
      if (m === 6) return ["Giải Jackpot 1", "Tối thiểu 30 tỷ và tích lũy"];
      if (m === 5 && hitDb) return ["Giải Jackpot 2", "Tối thiểu 3 tỷ và tích lũy"];
      if (m === 5) return ["Giải Nhất", "40.000.000"];
      if (m === 4) return ["Giải Nhì", "500.000"];
      if (m === 3) return ["Giải Ba", "50.000"];
      return null;
    }

    const lModeEl = document.getElementById("lMode");
    if (lModeEl) {
      lModeEl.onchange = e => {
        const quick = e.target.value === "quick";
        const quickBox = document.getElementById("quickBox");
        const otherBox = document.getElementById("otherBox");
        if (quickBox) quickBox.style.display = quick ? "block" : "none";
        if (otherBox) otherBox.style.display = quick ? "none" : "block";
      };
    }

    const lookupBtn = document.getElementById("lookupBtn");
    if (lookupBtn) lookupBtn.onclick = () => {
      const type = document.getElementById("lType").value;
      const mode = document.getElementById("lMode").value;
      const out = document.getElementById("lookupOut");
      if (!ensureDataReady(type, out, "Truy Cứu Số Trúng")) return;
      const resultMap = store.results[type];
      const resultKeys = store.resultOrder[type];
      const pickMap = store.picks[type];
      const pickKeys = store.pickOrder[type];
      if (!resultKeys.length) return line(out, "Chưa có KQ để tra.", "warn");

      if (mode === "quick") {
        try {
          const nums = parseNums(document.getElementById("lQuick").value);
          const t = TYPES[type];
          let ticket;
          if (t.keno) {
            const main = parseDistinctSortedNums(nums, t.mainMin, t.mainMax, t.pickMinCount || 1, t.pickMaxCount || 10, "Vé Keno tra nhanh");
            ticket = { main, special: null };
          } else {
            const need = t.mainCount + (t.hasSpecial ? 1 : 0);
            if (nums.length !== need) throw new Error(`Cần đúng ${need} số.`);
            ticket = { main: nums.slice(0, t.mainCount).sort((a,b)=>a-b), special: t.hasSpecial ? nums[t.mainCount] : null };
          }
          const hitLines = [];
          for (const ky of resultKeys) {
            const draw = resultMap[ky];
            const hit = evalPrize(type, ticket, draw);
            if (!hit) continue;
            hitLines.push(`Trùng với KỲ ${ky} - KQ ${formatTicket(draw, type)} -> ${hit[0]} | ${hit[1]} VNĐ`);
          }
          const top = `Trả kết quả -> ${TYPES[type].label} Số tra cứu ${formatTicket(ticket, type)}`;
          const total = `Tổng Tìm Thấy ${hitLines.length} Kỳ Trúng.`;
          line(out, [top, "", ...hitLines, "", total].join("\n"));
        } catch (e) {
          line(out, e.message, "warn");
        }
        return;
      }

      const qk = Number(document.getElementById("lCount").value || 0);
      if (!Number.isInteger(qk) || qk <= 0) return line(out, "Số lượng kỳ QK không hợp lệ.", "warn");
      const lastResult = resultKeys.slice(-qk);
      const lastPick = pickKeys.slice(-qk);
      const cmp = lastPick.filter(k => lastResult.includes(k));
      const lines = [
        `Kỳ KQ được tra: ${lastResult.join(", ") || "(không có)"}`,
        `Kỳ vé được tra: ${lastPick.join(", ") || "(không có)"}`,
        `Kỳ dùng để đối chiếu (giao nhau): ${cmp.join(", ") || "(không có)"}`,
        ""
      ];
      let checked = 0, win = 0;
      for (const ky of cmp) {
        const draw = resultMap[ky];
        const tickets = pickMap[ky] || [];
        lines.push(`${TYPES[type].label} Kỳ ${ky} - KQ: ${formatTicket(draw, type)}`);
        tickets.forEach((t, i) => {
          checked++;
          const hit = evalPrize(type, t, draw);
          if (!hit) return;
          win++;
          lines.push(`  Vé #${i + 1}: ${formatTicket(t, type)} -> ${hit[0]} | ${hit[1]} VNĐ`);
        });
        lines.push("");
      }
      if (!checked) lines.push("Không có vé nào để đối chiếu.");
      else lines.push(`Tổng vé đã tra: ${checked} | Tổng vé trúng: ${win}`);
      line(out, lines.join("\n"));
    };

    const delAllBtn = document.getElementById("delAllBtn");
    if (delAllBtn) delAllBtn.onclick = () => {
      const type = document.getElementById("dType").value;
      const target = document.getElementById("dTarget").value;
      const out = document.getElementById("dMsg");
      const meta = getDeleteTargetMeta(target);
      if (!ensureDeleteTargetReady(type, target, out)) return;
      if (!confirm(`Xóa hết ${meta.uiLabel} theo loại ${TYPES[type].label}?`)) return;
      store[meta.dataKey][type] = {};
      store[meta.orderKey][type] = [];
      saveStore();
      line(out, `Đã xóa toàn bộ ${meta.uiLabel} của ${TYPES[type].label}.`, "ok");
    };

    const delKyBtn = document.getElementById("delKyBtn");
    if (delKyBtn) delKyBtn.onclick = () => {
      const type = document.getElementById("dType").value;
      const target = document.getElementById("dTarget").value;
      const out = document.getElementById("dMsg");
      const meta = getDeleteTargetMeta(target);
      if (!ensureDeleteTargetReady(type, target, out)) return;
      const ky = normalizeKy(document.getElementById("dKy").value);
      if (!ky) return line(out, "Kỳ không hợp lệ.", "warn");
      let removed = false;
      if (store[meta.dataKey]?.[type]?.[ky]) {
        delete store[meta.dataKey][type][ky];
        store[meta.orderKey][type] = (store[meta.orderKey][type] || []).filter(k => k !== ky);
        removed = true;
      }
      saveStore();
      line(
        out,
        removed ? `Đã xóa ${meta.uiLabel} kỳ ${ky}.` : `Không tìm thấy ${meta.uiLabel} kỳ ${ky}.`,
        removed ? "ok" : "warn"
      );
    };

