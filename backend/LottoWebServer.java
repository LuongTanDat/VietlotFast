import com.sun.net.httpserver.Headers;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import com.sun.net.httpserver.HttpServer;

import java.io.*;
import java.net.InetSocketAddress;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.zip.GZIPOutputStream;

import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;

public class LottoWebServer {
    // ----- Cấu hình server -----
    // Gom các hằng số về cổng chạy, timeout tiến trình Python và loại vé được hỗ trợ.
    private static final int PORT = Integer.getInteger("lotto.port", 8080);
    private static final String COOKIE_NAME = "LOTTO_AUTH";
    private static final String DB_FILE = "runtime/lotto_web.db";
    private static final String EFFECTIVENESS_SYSTEM_USER = "__effectiveness_system__";
    private static final long LIVE_RESULTS_TIMEOUT_SECONDS = 600;
    private static final long LIVE_RESULTS_PROGRESS_STALE_SECONDS = 120;
    private static final long KENO_SYNC_TIMEOUT_SECONDS = 150;
    private static final long KENO_PREDICT_TIMEOUT_SECONDS = 180;
    private static final long AI_PREDICT_TIMEOUT_SECONDS = 240;
    private static final long AI_SCORE_TIMEOUT_SECONDS = 420;
    private static final long AI_ML_TIMEOUT_SECONDS = 900;
    private static final long STATS_V2_TIMEOUT_SECONDS = 180;
    private static final long ANALYSIS_TIMEOUT_SECONDS = 180;
    private static final long HEAVY_API_CACHE_TTL_MS = 5 * 60 * 1000L;
    private static final int HEAVY_API_CACHE_MAX_ENTRIES = 128;
    private static final int KENO_MIN_ORDER = 1;
    private static final int KENO_MAX_ORDER = 10;
    private static final Set<String> LIVE_TYPE_KEYS = Collections.unmodifiableSet(new LinkedHashSet<>(Arrays.asList(
            "LOTO_5_35", "LOTO_6_45", "LOTO_6_55", "KENO", "MAX_3D", "MAX_3D_PRO"
    )));
    private static final Set<String> AI_PREDICT_TYPE_KEYS = Collections.unmodifiableSet(new LinkedHashSet<>(Arrays.asList(
            "LOTO_5_35", "LOTO_6_45", "LOTO_6_55", "KENO", "MAX_3D", "MAX_3D_PRO"
    )));
    private static final Set<String> AI_PREDICT_ENGINE_KEYS = Collections.unmodifiableSet(new LinkedHashSet<>(Arrays.asList(
            "classic", "gen_local", "luan_so"
    )));
    private static final Set<String> AI_PREDICT_RISK_MODE_KEYS = Collections.unmodifiableSet(new LinkedHashSet<>(Arrays.asList(
            "stable", "balanced", "aggressive"
    )));
    private static final Set<String> ML_TYPE_KEYS = Collections.unmodifiableSet(new LinkedHashSet<>(Arrays.asList(
            "KENO", "LOTO_5_35", "LOTO_6_45", "LOTO_6_55"
    )));
    private static final Set<String> ANALYSIS_MODE_KEYS = Collections.unmodifiableSet(new LinkedHashSet<>(Arrays.asList(
            "overview", "general", "distribution", "ratios", "latest_draw", "consecutive",
            "overdue", "poisson", "knn", "chain", "relationships", "modulo", "advanced",
            "special", "weekday", "smart_wheel", "score", "all"
    )));

    private final Path rootDir;
    private final Path htmlFile;
    private final Path cssFile;
    private final Path extraCssFile;
    private final Path jsFile;
    private final Path coreJsFile;
    private final Path statsJsFile;
    private final Path dataJsFile;
    private final Path chatbotJsFile;
    private final Path effectivenessJsFile;
    private final Path faviconFile;
    private final Path dbFile;
    private final DatabaseRepo repo;
    private final Map<String, String> sessions = new ConcurrentHashMap<>();
    private final Map<String, Long> sessionExpiry = new ConcurrentHashMap<>();
    private final Map<String, String> sessionPasswordHash = new ConcurrentHashMap<>();
    private final Map<String, long[]> loginAttempts = new ConcurrentHashMap<>();
    private static final int MAX_REQUEST_BYTES = 8 * 1024 * 1024;
    private static final long SESSION_TTL_MS = 12 * 60 * 60 * 1000L;
    private final Map<Path, StaticAsset> staticAssetCache = new ConcurrentHashMap<>();
    private final Map<String, TimedJsonPayload> heavyApiCache = new ConcurrentHashMap<>();
    private final SecureRandom random = new SecureRandom();
    private final AtomicBoolean effectivenessJobRunning = new AtomicBoolean();
    private final AtomicBoolean algorithmLabRunning = new AtomicBoolean();
    private final Map<String, AlgorithmLabJob> algorithmLabJobs = new ConcurrentHashMap<>();

    private static final class AlgorithmLabJob {
        final String id = UUID.randomUUID().toString();
        final String owner, type;
        final int ticketCount, validationCount, testCount;
        final Instant createdAt = Instant.now();
        String state = "running", finishedAt = "", report = "null", error = "";
        boolean cancelled;
        Process process;

        AlgorithmLabJob(String owner, String type, int ticketCount, int validationCount, int testCount) {
            this.owner = owner; this.type = type; this.ticketCount = ticketCount;
            this.validationCount = validationCount; this.testCount = testCount;
        }

        synchronized String json() {
            return "{\"id\":" + quoteJson(id) + ",\"type\":" + quoteJson(type)
                    + ",\"state\":" + quoteJson(state) + ",\"createdAt\":" + quoteJson(createdAt.toString())
                    + ",\"finishedAt\":" + quoteJson(finishedAt) + ",\"ticketCount\":" + ticketCount
                    + ",\"validationCount\":" + validationCount + ",\"testCount\":" + testCount
                    + ",\"report\":" + report + ",\"error\":" + quoteJson(error) + "}";
        }
    }

    // ----- Helper lồng bên trong -----
    // Các lớp nhỏ phục vụ đọc JSON tay và gom stdout/stderr của tiến trình con.
    private static final class ProcessOutput {
        final boolean finished;
        final int exitCode;
        final byte[] stdout;
        final byte[] stderr;

        ProcessOutput(boolean finished, int exitCode, byte[] stdout, byte[] stderr) {
            this.finished = finished;
            this.exitCode = exitCode;
            this.stdout = stdout;
            this.stderr = stderr;
        }
    }

    private static final class StaticAsset {
        final long lastModified;
        final long size;
        final byte[] raw;
        final byte[] gzip;
        final String etag;

        StaticAsset(long lastModified, long size, byte[] raw, byte[] gzip, String etag) {
            this.lastModified = lastModified;
            this.size = size;
            this.raw = raw;
            this.gzip = gzip;
            this.etag = etag;
        }
    }

    private static final class CanonicalHistoryRow {
        String ky = "";
        String date = "";
        String time = "";
        List<Integer> main = new ArrayList<>();
        Integer special = null;
        List<String> displayLines = new ArrayList<>();
        String label = "";
        String sourceUrl = "";
        String sourceDate = "";
        String prizeHit = "";
        Map<String, Long> prizes = new LinkedHashMap<>();
        LocalDate parsedDate = null;
    }

    private static final class TimedJsonPayload {
        final String payload;
        final long expiresAtMs;

        TimedJsonPayload(String payload, long expiresAtMs) {
            this.payload = payload;
            this.expiresAtMs = expiresAtMs;
        }
    }

    private static final class JsonCursor {
        private final String text;
        private int index;
        private int depth;

        JsonCursor(String text) {
            this.text = text == null ? "" : text;
            this.index = 0;
        }

        void skipWhitespace() {
            while (index < text.length()) {
                char ch = text.charAt(index);
                if (!Character.isWhitespace(ch)) break;
                index++;
            }
        }

        boolean isEnd() {
            return index >= text.length();
        }

        void parseValue() {
            skipWhitespace();
            if (isEnd()) throw new IllegalArgumentException("JSON bị thiếu giá trị.");
            char ch = text.charAt(index);
            if (ch == '{') {
                parseObject();
                return;
            }
            if (ch == '[') {
                parseArray();
                return;
            }
            if (ch == '"') {
                parseString();
                return;
            }
            if (ch == '-' || Character.isDigit(ch)) {
                parseNumber();
                return;
            }
            if (text.startsWith("true", index)) {
                index += 4;
                return;
            }
            if (text.startsWith("false", index)) {
                index += 5;
                return;
            }
            if (text.startsWith("null", index)) {
                index += 4;
                return;
            }
            throw new IllegalArgumentException("JSON có giá trị không hợp lệ tại vị trí " + index + ".");
        }

        void parseObject() {
            if (++depth > 64) throw new IllegalArgumentException("JSON lồng quá sâu");
            expect('{');
            skipWhitespace();
            if (consumeIf('}')) { depth--; return; }
            while (true) {
                skipWhitespace();
                parseString();
                skipWhitespace();
                expect(':');
                parseValue();
                skipWhitespace();
                if (consumeIf('}')) { depth--; return; }
                expect(',');
            }
        }

        void parseArray() {
            if (++depth > 64) throw new IllegalArgumentException("JSON lồng quá sâu");
            expect('[');
            skipWhitespace();
            if (consumeIf(']')) { depth--; return; }
            while (true) {
                parseValue();
                skipWhitespace();
                if (consumeIf(']')) { depth--; return; }
                expect(',');
            }
        }

        void parseString() {
            expect('"');
            while (!isEnd()) {
                char ch = text.charAt(index++);
                if (ch == '"') {
                    return;
                }
                if (ch == '\\') {
                    if (isEnd()) throw new IllegalArgumentException("JSON có escape string bị thiếu.");
                    char esc = text.charAt(index++);
                    if ("\"\\/bfnrt".indexOf(esc) >= 0) {
                        continue;
                    }
                    if (esc == 'u') {
                        for (int i = 0; i < 4; i++) {
                            if (isEnd() || !isHexDigit(text.charAt(index++))) {
                                throw new IllegalArgumentException("JSON có mã unicode không hợp lệ.");
                            }
                        }
                        continue;
                    }
                    throw new IllegalArgumentException("JSON có escape string không hợp lệ.");
                }
                if (ch < 0x20) {
                    throw new IllegalArgumentException("JSON string chứa ký tự điều khiển không hợp lệ.");
                }
            }
            throw new IllegalArgumentException("JSON bị thiếu dấu đóng chuỗi.");
        }

        void parseNumber() {
            int start = index;
            if (text.charAt(index) == '-') index++;
            if (isEnd()) throw new IllegalArgumentException("JSON có số không hợp lệ.");
            if (text.charAt(index) == '0') {
                index++;
            } else if (Character.isDigit(text.charAt(index))) {
                while (!isEnd() && Character.isDigit(text.charAt(index))) index++;
            } else {
                throw new IllegalArgumentException("JSON có số không hợp lệ.");
            }
            if (!isEnd() && text.charAt(index) == '.') {
                index++;
                if (isEnd() || !Character.isDigit(text.charAt(index))) {
                    throw new IllegalArgumentException("JSON có phần thập phân không hợp lệ.");
                }
                while (!isEnd() && Character.isDigit(text.charAt(index))) index++;
            }
            if (!isEnd() && (text.charAt(index) == 'e' || text.charAt(index) == 'E')) {
                index++;
                if (!isEnd() && (text.charAt(index) == '+' || text.charAt(index) == '-')) index++;
                if (isEnd() || !Character.isDigit(text.charAt(index))) {
                    throw new IllegalArgumentException("JSON có số mũ không hợp lệ.");
                }
                while (!isEnd() && Character.isDigit(text.charAt(index))) index++;
            }
            if (index <= start) throw new IllegalArgumentException("JSON có số không hợp lệ.");
        }

        boolean consumeIf(char expected) {
            skipWhitespace();
            if (!isEnd() && text.charAt(index) == expected) {
                index++;
                return true;
            }
            return false;
        }

        void expect(char expected) {
            skipWhitespace();
            if (isEnd() || text.charAt(index) != expected) {
                throw new IllegalArgumentException("JSON bị thiếu ký tự '" + expected + "' tại vị trí " + index + ".");
            }
            index++;
        }

        private boolean isHexDigit(char ch) {
            return (ch >= '0' && ch <= '9')
                    || (ch >= 'a' && ch <= 'f')
                    || (ch >= 'A' && ch <= 'F');
        }
    }

    // ----- Khởi động và đăng ký route -----
    // Tạo HTTP server, ánh xạ toàn bộ route web/API và bật executor cho server.
    public static void main(String[] args) throws Exception {
        if (args.length == 1 && "--recover-admin".equals(args[0])) {
            Console console = System.console();
            if (console == null) throw new IllegalStateException("Khôi phục cần terminal tương tác để nhập mật khẩu kín.");
            char[] password = console.readPassword("Mật khẩu admin mới: ");
            char[] confirm = console.readPassword("Nhập lại mật khẩu: ");
            try {
                if (password == null || confirm == null || password.length < 8 || !Arrays.equals(password, confirm))
                    throw new IllegalArgumentException("Mật khẩu cần ít nhất 8 ký tự và nhập lại trùng khớp.");
                System.out.println("Đã khôi phục: " + new LottoWebServer().repo.recoverAdmin(new String(password)));
            } finally {
                if (password != null) Arrays.fill(password, '\0');
                if (confirm != null) Arrays.fill(confirm, '\0');
            }
            return;
        }
        new LottoWebServer().start();
    }

    public LottoWebServer() {
        this.rootDir = Paths.get(System.getProperty("user.dir"));
        this.htmlFile = rootDir.resolve("frontend").resolve("vietlott-web.html");
        this.cssFile = rootDir.resolve("frontend").resolve("vietlott-web.css");
        this.extraCssFile = rootDir.resolve("frontend").resolve("vietlott-web-extra.css");
        this.jsFile = rootDir.resolve("frontend").resolve("vietlott-web.js");
        this.coreJsFile = rootDir.resolve("frontend").resolve("vietlott-web-core.js");
        this.statsJsFile = rootDir.resolve("frontend").resolve("vietlott-web-stats.js");
        this.dataJsFile = rootDir.resolve("frontend").resolve("vietlott-web-data.js");
        this.chatbotJsFile = rootDir.resolve("frontend").resolve("vietlott-web-chatbot.js");
        this.effectivenessJsFile = rootDir.resolve("frontend").resolve("vietlott-web-effectiveness.js");
        this.faviconFile = rootDir.resolve("frontend").resolve("favicon.svg");
        this.dbFile = rootDir.resolve(DB_FILE);
        this.repo = new DatabaseRepo(dbFile);
    }

    private void start() throws Exception {
        if (!Files.exists(htmlFile)) {
            throw new FileNotFoundException("Không tìm thấy file: " + htmlFile);
        }

        HttpServer server = HttpServer.create(new InetSocketAddress(System.getProperty("lotto.bind", "127.0.0.1"), PORT), 64);
        server.createContext("/", this::serveIndex);
        server.createContext("/vietlott-web.css", ex -> serveStaticTextFile(ex, cssFile, "text/css; charset=UTF-8"));
        server.createContext("/vietlott-web-extra.css", ex -> serveStaticTextFile(ex, extraCssFile, "text/css; charset=UTF-8"));
        server.createContext("/vietlott-web.js", ex -> serveStaticTextFile(ex, jsFile, "application/javascript; charset=UTF-8"));
        server.createContext("/vietlott-web-core.js", ex -> serveStaticTextFile(ex, coreJsFile, "application/javascript; charset=UTF-8"));
        server.createContext("/vietlott-web-stats.js", ex -> serveStaticTextFile(ex, statsJsFile, "application/javascript; charset=UTF-8"));
        server.createContext("/vietlott-web-data.js", ex -> serveStaticTextFile(ex, dataJsFile, "application/javascript; charset=UTF-8"));
        server.createContext("/vietlott-web-chatbot.js", ex -> serveStaticTextFile(ex, chatbotJsFile, "application/javascript; charset=UTF-8"));
        server.createContext("/vietlott-web-effectiveness.js", ex -> serveStaticTextFile(ex, effectivenessJsFile, "application/javascript; charset=UTF-8"));
        server.createContext("/favicon.svg", this::serveFavicon);
        server.createContext("/api/me", this::handleMe);
        server.createContext("/api/register", this::handleRegister);
        server.createContext("/api/login", this::handleLogin);
        server.createContext("/api/logout", this::handleLogout);
        server.createContext("/api/store", this::handleStore);
        server.createContext("/api/wheel", this::handleWheel);
        server.createContext("/api/admin/vip", this::handleAdminVip);
        server.createContext("/api/time", this::handleServerTime);
        server.createContext("/api/stats-v2", this::handleStatsV2);
        server.createContext("/api/analysis", this::handleAnalysis);
        server.createContext("/api/keno-predict-data", this::handleKenoPredictData);
        server.createContext("/api/keno-predict", this::handleKenoPredict);
        server.createContext("/api/ai-predict", this::handleAiPredict);
        server.createContext("/api/ai-score", this::handleAiScore);
        server.createContext("/api/ml/status", this::handleMlStatus);
        server.createContext("/api/ml/predictions", this::handleMlPredictions);
        server.createContext("/api/ml/backtest", this::handleMlBacktest);
        server.createContext("/api/ml/score-pending", this::handleMlScorePending);
        server.createContext("/api/ml/train-candidate", this::handleMlTrainCandidate);
        server.createContext("/api/ml/promote", this::handleMlPromote);
        server.createContext("/api/ml/rollback", this::handleMlRollback);
        server.createContext("/api/ml/effectiveness", this::handleMlEffectiveness);
        server.createContext("/api/ml/effectiveness-settings", this::handleMlEffectivenessSettings);
        server.createContext("/api/ml/effectiveness-cycle", this::handleMlEffectivenessCycle);
        server.createContext("/api/ml/algorithm-lab", this::handleAlgorithmLab);
        server.createContext("/api/live-results", this::handleLiveResults);
        server.createContext("/api/live-results-start", this::handleLiveResultsStart);
        server.createContext("/api/live-results-progress", this::handleLiveResultsProgress);
        server.createContext("/api/live-history", this::handleLiveHistory);
        server.createContext("/api/recover-admin", this::handleRecoverAdmin);
        server.createContext("/api/admin/users", this::handleAdminUsers);
        server.createContext("/api/admin/update-user", this::handleAdminUpdateUser);
        server.createContext("/api/admin/update-assets", this::handleAdminUpdateAssets);
        server.createContext("/api/admin/rename-user", this::handleAdminRenameUser);
        server.createContext("/api/admin/reset-password", this::handleAdminResetPassword);
        server.createContext("/api/admin/delete-user", this::handleAdminDeleteUser);
        server.setExecutor(new ThreadPoolExecutor(8, 24, 60, TimeUnit.SECONDS,
                new ArrayBlockingQueue<Runnable>(64), new ThreadPoolExecutor.CallerRunsPolicy()));
        server.start();
        startEffectivenessWorker();

        System.out.println("Lotto Web Server chạy tại http://localhost:" + PORT + "/");
        System.out.println("DB file: " + dbFile.toAbsolutePath());
        Thread.currentThread().join();
    }

    // ----- Tài nguyên tĩnh -----
    // Phục vụ file HTML chính, favicon và phản hồi 404 cơ bản.
    private void serveIndex(HttpExchange ex) throws IOException {
        if (!isGetOrHead(ex)) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }
        String path = ex.getRequestURI() == null ? "/" : ex.getRequestURI().getPath();
        if (!"/".equals(path)
                && !"/index.html".equals(path)
                && !"/vong-quay".equals(path)
                && !"/vong-quay.html".equals(path)
                && !"/nap-tien".equals(path)
                && !"/nap-tien.html".equals(path)
                && !"/bang-du-lieu".equals(path)
                && !"/bang-du-lieu.html".equals(path)) {
            sendNotFound(ex);
            return;
        }
        serveCachedAsset(ex, htmlFile, "text/html; charset=UTF-8", "no-cache, must-revalidate");
    }

    private void serveFavicon(HttpExchange ex) throws IOException {
        if (!isGetOrHead(ex)) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }
        if (!Files.exists(faviconFile)) {
            sendNotFound(ex);
            return;
        }
        serveCachedAsset(ex, faviconFile, "image/svg+xml", "private, max-age=86400");
    }

    private void serveStaticTextFile(HttpExchange ex, Path file, String contentType) throws IOException {
        if (!isGetOrHead(ex)) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }
        if (file == null || !Files.exists(file)) {
            sendNotFound(ex);
            return;
        }
        serveCachedAsset(ex, file, contentType, "private, max-age=300, must-revalidate");
    }

    private boolean isGetOrHead(HttpExchange ex) {
        String method = ex.getRequestMethod();
        return "GET".equalsIgnoreCase(method) || "HEAD".equalsIgnoreCase(method);
    }

    private StaticAsset loadStaticAsset(Path file) throws IOException {
        Path key = file.toAbsolutePath().normalize();
        long lastModified = Files.getLastModifiedTime(key).toMillis();
        long size = Files.size(key);
        StaticAsset cached = staticAssetCache.get(key);
        if (cached != null && cached.lastModified == lastModified && cached.size == size) {
            return cached;
        }
        byte[] raw = Files.readAllBytes(key);
        byte[] gzip = raw.length >= 1024 ? gzip(raw) : raw;
        String etag = "\"" + Long.toHexString(lastModified) + "-" + Long.toHexString(size) + "\"";
        StaticAsset next = new StaticAsset(lastModified, size, raw, gzip, etag);
        staticAssetCache.put(key, next);
        return next;
    }

    private void serveCachedAsset(HttpExchange ex, Path file, String contentType, String cacheControl) throws IOException {
        StaticAsset asset = loadStaticAsset(file);
        Headers h = ex.getResponseHeaders();
        h.set("Content-Type", contentType);
        h.set("Cache-Control", cacheControl);
        h.set("ETag", asset.etag);
        h.add("Vary", "Accept-Encoding");
        if (asset.etag.equals(ex.getRequestHeaders().getFirst("If-None-Match"))) {
            ex.sendResponseHeaders(304, -1);
            ex.close();
            return;
        }
        boolean useGzip = acceptsGzip(ex) && asset.gzip.length < asset.raw.length;
        byte[] bytes = useGzip ? asset.gzip : asset.raw;
        if (useGzip) h.set("Content-Encoding", "gzip");
        if ("HEAD".equalsIgnoreCase(ex.getRequestMethod())) {
            h.set("Content-Length", String.valueOf(bytes.length));
            ex.sendResponseHeaders(200, -1);
            ex.close();
            return;
        }
        ex.sendResponseHeaders(200, bytes.length);
        try (OutputStream os = ex.getResponseBody()) {
            os.write(bytes);
        }
    }

    private void sendNotFound(HttpExchange ex) throws IOException {
        byte[] bytes = "Not Found".getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().set("Content-Type", "text/plain; charset=UTF-8");
        ex.sendResponseHeaders(404, bytes.length);
        try (OutputStream os = ex.getResponseBody()) {
            os.write(bytes);
        }
    }

    // ----- API đăng nhập và store -----
    // Xử lý xác thực người dùng, đọc/lưu store và khôi phục tài khoản admin.
    private void handleMe(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        if (!"GET".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }
        SessionUser su = requireAuth(ex, false);
        if (su == null) {
            sendJson(ex, 200, "{\"ok\":false}");
            return;
        }
        sendJson(ex, 200, "{\"ok\":true,\"username\":\"" + esc(su.username) + "\",\"role\":\"" + esc(su.account.role) + "\"}");
    }

    private void handleServerTime(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        if (!"GET".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }
        long nowMs = System.currentTimeMillis();
        String zone = ZoneId.systemDefault().getId();
        sendJson(
                ex,
                200,
                "{\"ok\":true,\"serverTimeMs\":" + nowMs
                        + ",\"serverIso\":\"" + esc(Instant.ofEpochMilli(nowMs).toString()) + "\""
                        + ",\"timezone\":\"" + esc(zone) + "\"}"
        );
    }

    private void handleRegister(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        if (!"POST".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }
        Map<String, String> f = parseForm(ex);
        String user = normalizeUser(f.get("username"));
        String pass = nvl(f.get("password")).trim();
        if (EFFECTIVENESS_SYSTEM_USER.equals(user)) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Tên này dành riêng cho tác vụ hệ thống.\"}"); return;
        }
        if (user.length() < 3) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Tên đăng nhập tối thiểu 3 ký tự\"}");
            return;
        }
        if (pass.length() < 4) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Mật khẩu tối thiểu 4 ký tự\"}");
            return;
        }
        try {
            repo.register(user, pass);
            sendJson(ex, 200, "{\"ok\":true}");
        } catch (IllegalStateException e) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"" + esc(e.getMessage()) + "\"}");
        } catch (RuntimeException e) {
            sendJson(ex, 500, "{\"ok\":false,\"message\":\"Lỗi DB khi đăng ký: " + esc(rootCauseMsg(e)) + "\"}");
        }
    }

    private void handleLogin(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        if (!"POST".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }
        Map<String, String> f = parseForm(ex);
        String user = normalizeUser(f.get("username"));
        String pass = nvl(f.get("password")).trim();
        if (EFFECTIVENESS_SYSTEM_USER.equals(user)) {
            sendJson(ex, 403, "{\"ok\":false,\"message\":\"Tài khoản hệ thống không dùng để đăng nhập.\"}"); return;
        }
        try {
            String attemptKey = ex.getRemoteAddress().getAddress().getHostAddress() + "|" + user;
            if (loginAttempts.size() > 4096) loginAttempts.entrySet().removeIf(entry -> entry.getValue()[0] < System.currentTimeMillis() - 900000);
            if (loginAttempts.size() >= 4096 && !loginAttempts.containsKey(attemptKey)) {
                sendJson(ex, 429, "{\"ok\":false,\"message\":\"Đã đạt giới hạn yêu cầu đăng nhập\"}"); return;
            }
            long[] attempts = loginAttempts.computeIfAbsent(attemptKey, key -> new long[]{System.currentTimeMillis(), 0});
            synchronized (attempts) {
                if (attempts[0] < System.currentTimeMillis() - 900000) { attempts[0] = System.currentTimeMillis(); attempts[1] = 0; }
                if (++attempts[1] > 10) { sendJson(ex, 429, "{\"ok\":false,\"message\":\"Thử đăng nhập quá nhiều, chờ 15 phút\"}"); return; }
            }
            Account acc = repo.getUser(user);
            if (acc == null || !acc.enabled || !verifyPassword(pass, acc.salt, acc.passwordHash)) {
                sendJson(ex, 401, "{\"ok\":false,\"message\":\"Sai tài khoản hoặc mật khẩu\"}");
                return;
            }

            String token = UUID.randomUUID().toString() + Long.toHexString(random.nextLong());
            long sessionNow = System.currentTimeMillis();
            for (String oldToken : new ArrayList<>(sessions.keySet())) {
                if (sessionExpiry.getOrDefault(oldToken, 0L) <= sessionNow) {
                    sessions.remove(oldToken); sessionExpiry.remove(oldToken); sessionPasswordHash.remove(oldToken);
                }
            }
            if (sessions.size() >= 4096) { sendJson(ex, 429, "{\"ok\":false,\"message\":\"Đã đạt giới hạn phiên đăng nhập\"}"); return; }
            sessions.put(token, user);
            sessionExpiry.put(token, System.currentTimeMillis() + SESSION_TTL_MS);
            sessionPasswordHash.put(token, acc.passwordHash);
            loginAttempts.remove(attemptKey);
            setCookie(ex, COOKIE_NAME, token, false);
            sendJson(ex, 200, "{\"ok\":true,\"username\":\"" + esc(user) + "\",\"role\":\"" + esc(acc.role) + "\"}");
        } catch (RuntimeException e) {
            sendJson(ex, 500, "{\"ok\":false,\"message\":\"Lỗi DB khi đăng nhập: " + esc(rootCauseMsg(e)) + "\"}");
        }
    }

    private void handleLogout(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        if (!"POST".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }
        String token = getCookie(ex, COOKIE_NAME);
        if (token != null) { sessions.remove(token); sessionExpiry.remove(token); sessionPasswordHash.remove(token); }
        setCookie(ex, COOKIE_NAME, "", true);
        sendJson(ex, 200, "{\"ok\":true}");
    }

    private void handleStore(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAuth(ex, true);
        if (su == null) return;
        if ("GET".equalsIgnoreCase(ex.getRequestMethod())) {
            try {
                String store = repo.publicStore(su.username);
                sendJson(ex, 200, "{\"ok\":true,\"store\":" + (store == null || isBlank(store) ? "{}" : store) + "}");
            } catch (RuntimeException e) {
                sendJson(ex, 500, "{\"ok\":false,\"message\":\"Lỗi DB khi đọc store: " + esc(rootCauseMsg(e)) + "\"}");
            }
            return;
        }
        if ("POST".equalsIgnoreCase(ex.getRequestMethod())) {
            Map<String, String> f = parseForm(ex);
            try {
                String store = requireValidJsonObjectText(f.get("store"));
                repo.setClientStore(su.username, store);
                sendJson(ex, 200, "{\"ok\":true,\"store\":" + repo.publicWallet(su.username) + "}");
            } catch (IllegalArgumentException e) {
                sendJson(ex, 400, "{\"ok\":false,\"message\":\"" + esc(e.getMessage()) + "\"}");
            } catch (RuntimeException e) {
                sendJson(ex, 500, "{\"ok\":false,\"message\":\"Lỗi DB khi lưu store: " + esc(rootCauseMsg(e)) + "\"}");
            }
            return;
        }
        sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
    }

    private String getHeavyApiCachedPayload(String key) {
        TimedJsonPayload cached = heavyApiCache.get(key);
        if (cached == null) return null;
        if (cached.expiresAtMs <= System.currentTimeMillis()) {
            heavyApiCache.remove(key, cached);
            return null;
        }
        return cached.payload;
    }

    private void putHeavyApiCachedPayload(String key, String payload) {
        if (isBlank(key) || isBlank(payload)) return;
        if (heavyApiCache.size() >= HEAVY_API_CACHE_MAX_ENTRIES) heavyApiCache.clear();
        heavyApiCache.put(key, new TimedJsonPayload(payload, System.currentTimeMillis() + HEAVY_API_CACHE_TTL_MS));
    }

    private String canonicalDataVersion(String type) {
        String defaultCsv = canonicalDefaultCsv(type);
        if (defaultCsv.isEmpty()) return "missing";
        Path csvFile = resolveRegistryDataPath("canonical." + type + ".csv", defaultCsv, null);
        try {
            return Files.getLastModifiedTime(csvFile).toMillis() + ":" + Files.size(csvFile);
        } catch (IOException ignored) {
            return "missing";
        }
    }

    private String heavyApiCacheKey(String namespace, HttpExchange ex, String type) {
        String rawQuery = ex.getRequestURI() == null ? "" : nvl(ex.getRequestURI().getRawQuery());
        return namespace + "|" + rawQuery + "|" + canonicalDataVersion(type);
    }

    private boolean sendHeavyApiCacheHit(HttpExchange ex, String cacheKey) throws IOException {
        String cachedPayload = getHeavyApiCachedPayload(cacheKey);
        if (cachedPayload == null) return false;
        ex.getResponseHeaders().set("X-Lotto-Cache", "HIT");
        sendJson(ex, 200, cachedPayload);
        return true;
    }

    private void handleStatsV2(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAuth(ex, true);
        if (su == null) return;
        if (!"GET".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }

        Path scriptFile = rootDir.resolve("ai").resolve("stats").resolve("stats_v2.py");
        if (!Files.exists(scriptFile)) {
            sendJson(ex, 500, "{\"ok\":false,\"message\":\"Không tìm thấy stats_v2.py\"}");
            return;
        }

        Map<String, String> query = parseQuery(ex.getRequestURI() == null ? null : ex.getRequestURI().getRawQuery());
        String type = normalizeLiveType(query.get("type"));
        if (isBlank(type)) type = "LOTO_5_35";
        if (!LIVE_TYPE_KEYS.contains(type)) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Loại thống kê không hợp lệ\"}");
            return;
        }

        String period = nvl(query.get("period")).trim().toLowerCase(Locale.ROOT);
        if (isBlank(period)) period = "30d";
        if (!Arrays.asList("7d", "30d", "60d", "1y", "custom", "all").contains(period)) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Bộ lọc thời gian không hợp lệ\"}");
            return;
        }

        String group = nvl(query.get("group")).trim().toLowerCase(Locale.ROOT);
        if (isBlank(group)) group = "main";
        if (!Arrays.asList("main", "special").contains(group)) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Nhóm thống kê không hợp lệ\"}");
            return;
        }
        if ("special".equals(group) && !Arrays.asList("LOTO_5_35", "LOTO_6_55").contains(type)) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Loại này không có số đặc biệt\"}");
            return;
        }

        String comboSizeRaw = nvl(query.get("comboSize")).trim();
        if (isBlank(comboSizeRaw)) comboSizeRaw = nvl(query.get("combo-size")).trim();
        if (isBlank(comboSizeRaw)) comboSizeRaw = "1";
        int comboSize = parseStrictPositiveInt(comboSizeRaw);
        int maxComboSize = "KENO".equals(type) ? 10 : 5;
        if (comboSize < 1 || comboSize > maxComboSize) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Combo size phải từ 1 đến " + maxComboSize + "\"}");
            return;
        }
        if ("special".equals(group) && comboSize != 1) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Số đặc biệt chỉ hỗ trợ combo 1 số\"}");
            return;
        }

        String sort = nvl(query.get("sort")).trim().toLowerCase(Locale.ROOT);
        if (isBlank(sort)) sort = "most";
        if (!Arrays.asList("most", "least", "overdue", "streak").contains(sort)) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Kiểu sắp xếp không hợp lệ\"}");
            return;
        }

        String from = nvl(query.get("from")).trim();
        String to = nvl(query.get("to")).trim();
        if ((!isBlank(from) && !isValidStatsV2Date(from)) || (!isBlank(to) && !isValidStatsV2Date(to))) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Ngày custom không hợp lệ\"}");
            return;
        }

        String cacheKey = heavyApiCacheKey("stats-v2", ex, type);
        if (sendHeavyApiCacheHit(ex, cacheKey)) return;

        List<String> command = buildPythonCommand(scriptFile);
        command.add("stats_json");
        command.add("--type");
        command.add(type);
        command.add("--period");
        command.add(period);
        command.add("--group");
        command.add(group);
        command.add("--combo-size");
        command.add(String.valueOf(comboSize));
        command.add("--sort");
        command.add(sort);
        if (!isBlank(from)) {
            command.add("--from");
            command.add(from);
        }
        if (!isBlank(to)) {
            command.add("--to");
            command.add(to);
        }

        String payload = runPythonJsonCommand(
                ex,
                rootDir,
                command,
                STATS_V2_TIMEOUT_SECONDS,
                "Tính Thống Kê V2 quá thời gian chờ",
                "Stats V2 không trả dữ liệu",
                "Stats V2 exited with error",
                "Tiến trình Stats V2 bị gián đoạn",
                "Không chạy được Stats V2: ",
                null
        );
        if (payload == null) return;
        putHeavyApiCachedPayload(cacheKey, payload);
        ex.getResponseHeaders().set("X-Lotto-Cache", "MISS");
        sendJson(ex, 200, payload);
    }

    private void handleAnalysis(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAuth(ex, true);
        if (su == null) return;
        if (!"GET".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\",\"warnings\":[]}");
            return;
        }

        Path scriptFile = rootDir.resolve("ai").resolve("analysis").resolve("analysis.py");
        if (!Files.exists(scriptFile)) {
            sendJson(ex, 500, "{\"ok\":false,\"message\":\"Không tìm thấy analysis.py\",\"warnings\":[]}");
            return;
        }

        Map<String, String> query = parseQuery(ex.getRequestURI() == null ? null : ex.getRequestURI().getRawQuery());
        String type = normalizeLiveType(query.get("type"));
        if (isBlank(type)) type = "LOTO_5_35";
        if (!LIVE_TYPE_KEYS.contains(type)) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Loại phân tích không hợp lệ\",\"warnings\":[]}");
            return;
        }

        String period = nvl(query.get("period")).trim().toLowerCase(Locale.ROOT);
        if (isBlank(period)) period = "30d";
        if (!Arrays.asList("7d", "30d", "60d", "1y", "all", "custom").contains(period)) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Bộ lọc thời gian không hợp lệ\",\"warnings\":[]}");
            return;
        }

        String mode = nvl(query.get("mode")).trim().toLowerCase(Locale.ROOT).replace('-', '_');
        if (isBlank(mode)) mode = "overview";
        if (!ANALYSIS_MODE_KEYS.contains(mode)) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Chế độ phân tích không hợp lệ\",\"warnings\":[]}");
            return;
        }

        String from = nvl(query.get("from")).trim();
        String to = nvl(query.get("to")).trim();
        if ((!isBlank(from) && !isValidStatsV2Date(from)) || (!isBlank(to) && !isValidStatsV2Date(to))) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Ngày custom không hợp lệ\",\"warnings\":[]}");
            return;
        }

        String limitRaw = nvl(query.get("limit")).trim();
        if (isBlank(limitRaw)) limitRaw = "20";
        int limit = parseStrictPositiveInt(limitRaw);
        if (limit < 1 || limit > 100) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Limit phải từ 1 đến 100\",\"warnings\":[]}");
            return;
        }

        String kRaw = nvl(query.get("k")).trim();
        if (isBlank(kRaw)) kRaw = "5";
        int k = parseStrictPositiveInt(kRaw);
        if (k < 1 || k > 20) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"K phải từ 1 đến 20\",\"warnings\":[]}");
            return;
        }

        String comboSizeRaw = nvl(query.get("comboSize")).trim();
        if (isBlank(comboSizeRaw)) comboSizeRaw = nvl(query.get("combo-size")).trim();
        if (isBlank(comboSizeRaw)) comboSizeRaw = "2";
        int comboSize = parseStrictPositiveInt(comboSizeRaw);
        if (comboSize < 1 || comboSize > 3) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Combo size phải từ 1 đến 3\",\"warnings\":[]}");
            return;
        }

        boolean includeSpecial = isBlank(query.get("includeSpecial")) || isTruthyFlag(query.get("includeSpecial"));
        String numbers = nvl(query.get("numbers")).trim();

        String pickRaw = nvl(query.get("pick")).trim();
        int pick = 0;
        if (!isBlank(pickRaw)) {
            pick = parseStrictPositiveInt(pickRaw);
            if (pick < 1 || pick > 10) {
                sendJson(ex, 400, "{\"ok\":false,\"message\":\"Pick phải từ 1 đến 10\",\"warnings\":[]}");
                return;
            }
        }

        String maxTicketsRaw = nvl(query.get("maxTickets")).trim();
        if (isBlank(maxTicketsRaw)) maxTicketsRaw = nvl(query.get("max-tickets")).trim();
        int maxTickets = 20;
        if (!isBlank(maxTicketsRaw)) {
            maxTickets = parseStrictPositiveInt(maxTicketsRaw);
            if (maxTickets < 1 || maxTickets > 50) {
                sendJson(ex, 400, "{\"ok\":false,\"message\":\"Max tickets phải từ 1 đến 50\",\"warnings\":[]}");
                return;
            }
        }

        String cacheKey = heavyApiCacheKey("analysis", ex, type);
        if (sendHeavyApiCacheHit(ex, cacheKey)) return;

        List<String> command = buildPythonCommand(scriptFile);
        command.add("analysis_json");
        command.add("--type");
        command.add(type);
        command.add("--period");
        command.add(period);
        command.add("--mode");
        command.add(mode);
        command.add("--limit");
        command.add(String.valueOf(limit));
        command.add("--k");
        command.add(String.valueOf(k));
        command.add("--combo-size");
        command.add(String.valueOf(comboSize));
        command.add("--include-special");
        command.add(String.valueOf(includeSpecial));
        if (!isBlank(from)) {
            command.add("--from");
            command.add(from);
        }
        if (!isBlank(to)) {
            command.add("--to");
            command.add(to);
        }
        if (!isBlank(numbers)) {
            command.add("--numbers");
            command.add(numbers);
        }
        if (pick > 0) {
            command.add("--pick");
            command.add(String.valueOf(pick));
        }
        command.add("--max-tickets");
        command.add(String.valueOf(maxTickets));

        String payload = runPythonJsonCommand(
                ex,
                rootDir,
                command,
                ANALYSIS_TIMEOUT_SECONDS,
                "Tính Phân Tích quá thời gian chờ",
                "Phân Tích không trả dữ liệu",
                "Analysis exited with error",
                "Tiến trình Phân Tích bị gián đoạn",
                "Không chạy được Phân Tích: ",
                null
        );
        if (payload == null) return;
        putHeavyApiCachedPayload(cacheKey, payload);
        ex.getResponseHeaders().set("X-Lotto-Cache", "MISS");
        sendJson(ex, 200, payload);
    }

    private void handleRecoverAdmin(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        sendJson(ex, 403, "{\"ok\":false,\"message\":\"Khôi phục admin chỉ thực hiện bằng lệnh cục bộ --recover-admin\"}");
    }

    // ----- API cập nhật live-results -----
    // Khởi động luồng Cập Nhật, đọc progress, và trả lịch sử canonical cho frontend.
    private void handleLiveResults(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAuth(ex, true);
        if (su == null) return;
        if (!"GET".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }

        Path scriptFile = rootDir.resolve("backend").resolve("live_results.py");
        if (!Files.exists(scriptFile)) {
            sendJson(ex, 500, "{\"ok\":false,\"message\":\"Không tìm thấy live_results.py\"}");
            return;
        }

        Map<String, String> query = parseQuery(ex.getRequestURI() == null ? null : ex.getRequestURI().getRawQuery());
        String type = normalizeLiveType(query.get("type"));
        if (!isBlank(type) && !LIVE_TYPE_KEYS.contains(type)) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Loại live không hợp lệ\"}");
            return;
        }
        boolean repairCanonical = isTruthyFlag(query.get("repair"))
                || isTruthyFlag(query.get("canonical"))
                || isTruthyFlag(query.get("backfill"));
        Integer recentDays = null;
        String recentDaysRaw = isBlank(query.get("recentDays")) ? query.get("days") : query.get("recentDays");
        if (!isBlank(recentDaysRaw)) {
            try {
                recentDays = Math.max(1, Integer.parseInt(recentDaysRaw.trim()));
            } catch (NumberFormatException exNumber) {
                sendJson(ex, 400, "{\"ok\":false,\"message\":\"recentDays không hợp lệ\"}");
                return;
            }
        }
        if (repairCanonical && refreshLiveResultsProgressState()) {
            sendJson(ex, 409, buildBusyLiveResultsPayload());
            return;
        }
        List<String> command = buildPythonCommand(scriptFile);
        if (!isBlank(type)) command.add(type);
        if (repairCanonical) command.add("--repair-canonical");
        if (recentDays != null) {
            command.add("--recent-days");
            command.add(String.valueOf(recentDays));
        }
        String payload = runPythonJsonCommand(
                ex,
                rootDir,
                command,
                LIVE_RESULTS_TIMEOUT_SECONDS,
                "Lấy kết quả live quá thời gian chờ",
                "Python scraper không trả dữ liệu",
                "Python scraper exited with error",
                "Tiến trình live-results bị gián đoạn",
                "Không chạy được Python scraper: ",
                null
        );
        if (payload == null) return;
        sendJson(ex, 200, payload);
    }

    private void handleLiveResultsStart(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAuth(ex, true);
        if (su == null) return;
        if (!"POST".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }

        Path scriptFile = rootDir.resolve("backend").resolve("live_results.py");
        if (!Files.exists(scriptFile)) {
            sendJson(ex, 500, "{\"ok\":false,\"message\":\"Không tìm thấy live_results.py\"}");
            return;
        }

        boolean running = refreshLiveResultsProgressState();
        if (running) {
            sendJson(ex, 409, buildBusyLiveResultsPayload());
            return;
        }

        try {
            startLiveResultsRepairProcess(scriptFile);
        } catch (IOException e) {
            sendJson(ex, 500, "{\"ok\":false,\"message\":\"Không khởi động được tiến trình cập nhật: " + esc(rootCauseMsg(e)) + "\"}");
            return;
        }

        String progressJson = waitForLiveResultsProgressStartup(2500L);
        sendJson(ex, 202, "{\"ok\":true,\"started\":true,\"progress\":" + progressJson + "}");
    }

    private void handleLiveResultsProgress(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAuth(ex, true);
        if (su == null) return;
        if (!"GET".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }
        refreshLiveResultsProgressState();
        sendJson(ex, 200, readLiveResultsProgressJson());
    }

    private List<String> parseCanonicalCsvLine(String line) {
        List<String> cells = new ArrayList<>();
        StringBuilder current = new StringBuilder();
        boolean quoted = false;
        String value = nvl(line);
        for (int index = 0; index < value.length(); index++) {
            char ch = value.charAt(index);
            if (ch == '"') {
                if (quoted && index + 1 < value.length() && value.charAt(index + 1) == '"') {
                    current.append('"');
                    index++;
                } else {
                    quoted = !quoted;
                }
                continue;
            }
            if (ch == ',' && !quoted) {
                cells.add(current.toString());
                current.setLength(0);
                continue;
            }
            current.append(ch);
        }
        cells.add(current.toString());
        return cells;
    }

    private int canonicalColumnIndex(Map<String, Integer> columns, String name) {
        Integer index = columns.get(name);
        return index == null ? -1 : index;
    }

    private String canonicalCell(List<String> cells, Map<String, Integer> columns, String name) {
        int index = canonicalColumnIndex(columns, name);
        if (index < 0 || index >= cells.size()) return "";
        return nvl(cells.get(index)).trim();
    }

    private LocalDate parseCanonicalDate(String value) {
        try {
            return LocalDate.parse(nvl(value).trim(), DateTimeFormatter.ofPattern("dd/MM/yyyy"));
        } catch (RuntimeException ignored) {
            return null;
        }
    }

    private List<Integer> parseCanonicalNumbers(String value) {
        List<Integer> numbers = new ArrayList<>();
        Matcher matcher = Pattern.compile("\\d+").matcher(nvl(value));
        while (matcher.find()) {
            try {
                numbers.add(Integer.parseInt(matcher.group()));
            } catch (NumberFormatException ignored) {
            }
        }
        return numbers;
    }

    private List<String> parseCanonicalDisplayLines(String value) {
        List<String> lines = new ArrayList<>();
        for (String part : nvl(value).split("\\s*\\|\\|\\s*")) {
            String line = part.trim();
            if (!line.isEmpty()) lines.add(line);
        }
        return lines;
    }

    private String canonicalTypeLabel(String type) {
        switch (nvl(type)) {
            case "LOTO_5_35": return "Loto_5/35";
            case "LOTO_6_45": return "Mega_6/45";
            case "LOTO_6_55": return "Power_6/55";
            case "KENO": return "Keno";
            case "MAX_3D": return "Max 3D";
            case "MAX_3D_PRO": return "Max 3D Pro";
            default: return nvl(type);
        }
    }

    private String canonicalDefaultCsv(String type) {
        switch (nvl(type)) {
            case "LOTO_5_35": return "data/canonical/loto_5_35_all_day.csv";
            case "LOTO_6_45": return "data/canonical/mega_6_45_all_day.csv";
            case "LOTO_6_55": return "data/canonical/power_6_55_all_day.csv";
            case "KENO": return "data/canonical/keno_all_day.csv";
            case "MAX_3D": return "data/canonical/max_3d_all_day.csv";
            case "MAX_3D_PRO": return "data/canonical/max_3d_pro_all_day.csv";
            default: return "";
        }
    }

    private String jsonIntegerArray(List<Integer> values) {
        StringBuilder out = new StringBuilder("[");
        for (int index = 0; index < values.size(); index++) {
            if (index > 0) out.append(',');
            out.append(values.get(index));
        }
        return out.append(']').toString();
    }

    private String jsonStringArray(List<String> values) {
        StringBuilder out = new StringBuilder("[");
        for (int index = 0; index < values.size(); index++) {
            if (index > 0) out.append(',');
            out.append('"').append(esc(values.get(index))).append('"');
        }
        return out.append(']').toString();
    }

    private String canonicalHistoryRowJson(CanonicalHistoryRow row) {
        StringBuilder prizesJson = new StringBuilder();
        for (Map.Entry<String, Long> prize : row.prizes.entrySet()) {
            prizesJson.append(",\"").append(prize.getKey()).append("\":").append(prize.getValue());
        }
        return "{"
                + "\"ky\":\"" + esc(row.ky) + "\","
                + "\"date\":\"" + esc(row.date) + "\","
                + "\"time\":\"" + esc(row.time) + "\","
                + "\"main\":" + jsonIntegerArray(row.main) + ","
                + "\"special\":" + (row.special == null ? "null" : row.special) + ","
                + "\"displayLines\":" + jsonStringArray(row.displayLines) + ","
                + "\"label\":\"" + esc(row.label) + "\","
                + "\"sourceUrl\":\"" + esc(row.sourceUrl) + "\","
                + "\"sourceDate\":\"" + esc(row.sourceDate) + "\""
                + ",\"prizeHit\":\"" + esc(row.prizeHit) + "\""
                + prizesJson
                + "}";
    }

    private void readCanonicalPrize(CanonicalHistoryRow row, List<String> cells,
                                    Map<String, Integer> columns, String header, String key) {
        String raw = canonicalCell(cells, columns, header);
        if (!raw.matches("[0-9]+")) return;
        try {
            long amount = Long.parseLong(raw);
            if (amount > 0) row.prizes.put(key, amount);
        } catch (NumberFormatException ignored) {
        }
    }

    private String canonicalHistoryRangeLabel(String type, String count) {
        if (!"KENO".equals(type)) return "";
        switch (nvl(count)) {
            case "today": return "Hôm Nay";
            case "3d": return "3 Ngày";
            case "1w": return "1 Tuần";
            case "1m": return "1 Tháng";
            case "3m": return "3 Tháng";
            case "6m": return "6 Tháng";
            case "1y": return "1 Năm";
            case "all": return "Tất cả Kỳ";
            default: return "";
        }
    }

    private LocalDate canonicalHistoryStartDate(String count, LocalDate today) {
        switch (nvl(count)) {
            case "today": return today;
            case "3d": return today.minusDays(2);
            case "1w": return today.minusDays(6);
            case "1m": return today.withDayOfMonth(1);
            case "3m": return today.minusMonths(2).withDayOfMonth(1);
            case "6m": return today.minusMonths(5).withDayOfMonth(1);
            case "1y": return today.withDayOfYear(1);
            default: return null;
        }
    }

    private Set<String> parseCanonicalDrawIds(String value) {
        Set<String> drawIds = new LinkedHashSet<>();
        for (String part : nvl(value).split(",")) {
            String normalized = part.replaceAll("\\D", "");
            if (!normalized.isEmpty()) drawIds.add(normalized);
            if (drawIds.size() >= 240) break;
        }
        return drawIds;
    }

    private String buildCanonicalHistoryPayload(String type, String count, Set<String> selectedDrawIds) throws IOException {
        String defaultCsv = canonicalDefaultCsv(type);
        if (defaultCsv.isEmpty()) return null;
        Path csvFile = resolveRegistryDataPath("canonical." + type + ".csv", defaultCsv, null);
        if (!Files.exists(csvFile)) return null;

        List<CanonicalHistoryRow> allRows = new ArrayList<>();
        try (BufferedReader reader = Files.newBufferedReader(csvFile, StandardCharsets.UTF_8)) {
            String headerLine = reader.readLine();
            if (headerLine == null) return null;
            List<String> headers = parseCanonicalCsvLine(headerLine.replace("\uFEFF", ""));
            Map<String, Integer> columns = new LinkedHashMap<>();
            for (int index = 0; index < headers.size(); index++) {
                columns.put(nvl(headers.get(index)).trim(), index);
            }

            String line;
            while ((line = reader.readLine()) != null) {
                if (line.trim().isEmpty()) continue;
                List<String> cells = parseCanonicalCsvLine(line);
                CanonicalHistoryRow row = new CanonicalHistoryRow();
                row.ky = canonicalCell(cells, columns, "Kỳ");
                row.date = canonicalCell(cells, columns, "Ngày");
                row.time = canonicalCell(cells, columns, "Giờ");
                row.main = parseCanonicalNumbers(canonicalCell(cells, columns, "Bộ Số"));
                String specialRaw = canonicalCell(cells, columns, "ĐB");
                if (!specialRaw.isEmpty()) {
                    try {
                        row.special = Integer.parseInt(specialRaw.replaceAll("\\D", ""));
                    } catch (NumberFormatException ignored) {
                        row.special = null;
                    }
                }
                row.displayLines = parseCanonicalDisplayLines(canonicalCell(cells, columns, "Hiển thị"));
                if (row.displayLines.isEmpty() && !row.main.isEmpty()) {
                    StringBuilder display = new StringBuilder();
                    for (Integer number : row.main) {
                        if (display.length() > 0) display.append(' ');
                        display.append(String.format(Locale.ROOT, "%02d", number));
                    }
                    if (row.special != null) display.append(String.format(Locale.ROOT, " | ĐB %02d", row.special));
                    row.displayLines.add(display.toString());
                }
                if (row.main.isEmpty() && ("MAX_3D".equals(type) || "MAX_3D_PRO".equals(type))) {
                    Set<Integer> unique = new TreeSet<>();
                    for (String displayLine : row.displayLines) {
                        Matcher matcher = Pattern.compile("(?<!\\d)\\d{3}(?!\\d)").matcher(displayLine);
                        while (matcher.find()) unique.add(Integer.parseInt(matcher.group()));
                    }
                    row.main = new ArrayList<>(unique);
                }
                row.label = canonicalCell(cells, columns, "Loại");
                if (row.label.isEmpty()) row.label = canonicalTypeLabel(type);
                row.sourceUrl = canonicalCell(cells, columns, "Link cập nhật");
                row.sourceDate = canonicalCell(cells, columns, "Ngày cập nhật");
                row.prizeHit = canonicalCell(cells, columns, "Nổ");
                if (row.sourceDate.isEmpty()) row.sourceDate = row.date;
                if ("LOTO_5_35".equals(type)) {
                    readCanonicalPrize(row, cells, columns, "Giải Đặc biệt (VNĐ)", "specialPrize");
                } else if ("LOTO_6_45".equals(type)) {
                    readCanonicalPrize(row, cells, columns, "Jackpot (VNĐ)", "jackpot");
                } else if ("LOTO_6_55".equals(type)) {
                    readCanonicalPrize(row, cells, columns, "Jackpot 1 (VNĐ)", "jackpot1");
                    readCanonicalPrize(row, cells, columns, "Jackpot 2 (VNĐ)", "jackpot2");
                }
                row.parsedDate = parseCanonicalDate(row.date);
                if (!row.ky.isEmpty()) allRows.add(row);
            }
        }

        if (allRows.isEmpty()) return null;
        LocalDate today = LocalDate.now();
        long todayCount = allRows.stream().filter(row -> today.equals(row.parsedDate)).count();
        List<CanonicalHistoryRow> selectedRows = new ArrayList<>();
        LocalDate startDate = "KENO".equals(type) ? canonicalHistoryStartDate(count, today) : null;
        if (selectedDrawIds != null && !selectedDrawIds.isEmpty()) {
            for (CanonicalHistoryRow row : allRows) {
                if (selectedDrawIds.contains(row.ky.replaceAll("\\D", ""))) selectedRows.add(row);
            }
        } else if (startDate != null) {
            for (CanonicalHistoryRow row : allRows) {
                if (row.parsedDate == null || row.parsedDate.isBefore(startDate) || row.parsedDate.isAfter(today)) continue;
                selectedRows.add(row);
            }
        } else if ("all".equals(count)) {
            selectedRows.addAll(allRows);
        } else {
            int limit;
            try {
                limit = Math.max(1, Integer.parseInt(count));
            } catch (NumberFormatException ignored) {
                limit = 20;
            }
            selectedRows.addAll(allRows.subList(0, Math.min(limit, allRows.size())));
        }

        CanonicalHistoryRow latest = allRows.get(0);
        CanonicalHistoryRow earliest = allRows.get(allRows.size() - 1);
        StringBuilder historyJson = new StringBuilder("[");
        for (int index = 0; index < selectedRows.size(); index++) {
            if (index > 0) historyJson.append(',');
            historyJson.append(canonicalHistoryRowJson(selectedRows.get(index)));
        }
        historyJson.append(']');
        String fileName = csvFile.getFileName().toString();
        String responseCount = selectedDrawIds != null && !selectedDrawIds.isEmpty() ? "selected" : count;
        return "{"
                + "\"ok\":true,\"mode\":\"canonical_history_fast\","
                + "\"type\":\"" + esc(type) + "\","
                + "\"label\":\"" + esc(canonicalTypeLabel(type)) + "\","
                + "\"count\":\"" + esc(responseCount) + "\","
                + "\"returnedCount\":" + selectedRows.size() + ","
                + "\"canonicalCount\":" + allRows.size() + ","
                + "\"canonicalFile\":\"" + esc(fileName) + "\","
                + "\"allCount\":" + allRows.size() + ","
                + "\"todayCount\":" + todayCount + ","
                + "\"allFile\":\"" + esc(fileName) + "\","
                + "\"todayFile\":\"" + esc(fileName) + "\","
                + "\"latestKy\":\"" + esc(latest.ky) + "\","
                + "\"latestDate\":\"" + esc(latest.date) + "\","
                + "\"latestTime\":\"" + esc(latest.time) + "\","
                + "\"effectiveEarliestKy\":\"" + esc(earliest.ky) + "\","
                + "\"effectiveEarliestDate\":\"" + esc(earliest.date) + "\","
                + "\"rangeLabel\":\"" + esc(selectedDrawIds != null && !selectedDrawIds.isEmpty() ? "" : canonicalHistoryRangeLabel(type, count)) + "\","
                + "\"historyNote\":\"\",\"repairAttempted\":false,"
                + "\"repairNewRows\":0,\"repairRepairedDates\":0,\"repairRepairedKyGaps\":0,\"repairErrors\":[],"
                + "\"fetchedAt\":\"" + esc(LocalDateTime.now().withNano(0).toString()) + "\","
                + "\"history\":" + historyJson
                + "}";
    }

    private void handleLiveHistory(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAuth(ex, true);
        if (su == null) return;
        if (!"GET".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }

        Path scriptFile = rootDir.resolve("backend").resolve("live_results.py");
        if (!Files.exists(scriptFile)) {
            sendJson(ex, 500, "{\"ok\":false,\"message\":\"Không tìm thấy live_results.py\"}");
            return;
        }

        Map<String, String> query = parseQuery(ex.getRequestURI() == null ? null : ex.getRequestURI().getRawQuery());
        String type = normalizeLiveType(query.get("type"));
        String count = nvl(query.get("count")).trim().toLowerCase(Locale.ROOT);
        Set<String> selectedDrawIds = parseCanonicalDrawIds(query.get("drawIds"));
        if (isBlank(type)) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Thiếu loại lịch sử\"}");
            return;
        }
        if (!LIVE_TYPE_KEYS.contains(type)) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Loại lịch sử không hợp lệ\"}");
            return;
        }
        if (isBlank(count)) count = "20";
        boolean isNumericCount = count.chars().allMatch(Character::isDigit);
        boolean isKenoRangeCount = "KENO".equals(type)
                && Arrays.asList("today", "3d", "1w", "1m", "3m", "6m", "1y", "all").contains(count);
        if (!"all".equals(count) && !isNumericCount && !isKenoRangeCount) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Số kỳ lịch sử không hợp lệ\"}");
            return;
        }
        boolean repairCanonical = isTruthyFlag(query.get("repair"))
                || isTruthyFlag(query.get("canonical"))
                || isTruthyFlag(query.get("backfill"));
        Integer recentDays = null;
        String recentDaysRaw = isBlank(query.get("recentDays")) ? query.get("days") : query.get("recentDays");
        if (!isBlank(recentDaysRaw)) {
            try {
                recentDays = Math.max(1, Integer.parseInt(recentDaysRaw.trim()));
            } catch (NumberFormatException exNumber) {
                sendJson(ex, 400, "{\"ok\":false,\"message\":\"recentDays không hợp lệ\"}");
                return;
            }
        }

        if (!repairCanonical && recentDays == null) {
            try {
                String fastPayload = buildCanonicalHistoryPayload(type, count, selectedDrawIds);
                if (fastPayload != null) {
                    ex.getResponseHeaders().set("X-Lotto-History-Source", "java-csv");
                    sendJson(ex, 200, fastPayload);
                    return;
                }
            } catch (RuntimeException | IOException fastReadError) {
                System.err.println("Fast canonical history fallback for " + type + ": " + rootCauseMsg(fastReadError));
            }
        }

        List<String> command = buildPythonCommand(scriptFile);
        if (repairCanonical) command.add("--repair-canonical");
        if (recentDays != null) {
            command.add("--recent-days");
            command.add(String.valueOf(recentDays));
        }
        command.add("live_history");
        command.add(type);
        command.add(count);
        String payload = runPythonJsonCommand(
                ex,
                rootDir,
                command,
                LIVE_RESULTS_TIMEOUT_SECONDS,
                "Tải lịch sử CSV quá thời gian chờ",
                "Python history không trả dữ liệu",
                "Python history exited with error",
                "Tiến trình live-history bị gián đoạn",
                "Không chạy được Python history: ",
                null
        );
        if (payload == null) return;
        sendJson(ex, 200, payload);
    }

    // ----- API Keno và AI predict -----
    // Cầu nối giữa web với Python cho Keno data, Keno predict và AI predict chung.
    private void handleKenoPredictData(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAuth(ex, true);
        if (su == null) return;
        if (!"GET".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }

        Path projectRoot = rootDir.getParent() == null ? rootDir : rootDir.getParent();
        Path scriptFile = projectRoot.resolve("Test").resolve("L1.py").normalize();
        Path csvFile = resolveRegistryDataPath(
                "canonical.KENO.csv",
                "data/canonical/keno_all_day.csv",
                projectRoot.resolve("keno_all_day.csv")
        );
        if (!Files.exists(scriptFile)) {
            sendJson(ex, 500, "{\"ok\":false,\"message\":\"Không tìm thấy Test/L1.py\"}");
            return;
        }

        List<String> command = buildPythonCommand(scriptFile);
        command.add("sync");
        String syncPayload = runPythonJsonCommand(
                ex,
                projectRoot,
                command,
                KENO_SYNC_TIMEOUT_SECONDS,
                "Đồng bộ CSV Keno quá thời gian chờ",
                null,
                "Python sync exited with error",
                "Tiến trình sync CSV Keno bị gián đoạn",
                "Không chạy được Python sync: ",
                "{}"
        );
        if (syncPayload == null) return;
        if (!Files.exists(csvFile)) {
            sendJson(ex, 500, "{\"ok\":false,\"message\":\"Đã sync nhưng chưa tạo được keno_all_day.csv\"}");
            return;
        }

        String csvText = new String(Files.readAllBytes(csvFile), StandardCharsets.UTF_8);
        sendJson(
                ex,
                200,
                "{\"ok\":true,\"status\":" + syncPayload
                + ",\"csvFileName\":\"" + esc(csvFile.getFileName().toString()) + "\""
                + ",\"csvText\":\"" + esc(csvText) + "\"}"
        );
    }

    private void handleKenoPredict(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAuth(ex, true);
        if (su == null) return;
        if (!"GET".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }

        Map<String, String> query = parseQuery(ex.getRequestURI() == null ? null : ex.getRequestURI().getRawQuery());
        String orderRaw = nvl(query.get("order")).trim();
        String bundlesRaw = nvl(query.get("bundles")).trim();
        if (isBlank(orderRaw) || isBlank(bundlesRaw)) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Thiếu tham số order hoặc bundles\"}");
            return;
        }
        int order = parseStrictPositiveInt(orderRaw);
        if (order < KENO_MIN_ORDER || order > KENO_MAX_ORDER) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Bậc Keno phải trong khoảng 1-10\"}");
            return;
        }
        int bundles = parseStrictPositiveInt(bundlesRaw);
        int maxBundles = 80 / order;
        if (bundles <= 0 || bundles > maxBundles) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Số bộ Keno phải trong khoảng 1-" + maxBundles + " cho bậc " + order + "\"}");
            return;
        }

        Path projectRoot = rootDir.getParent() == null ? rootDir : rootDir.getParent();
        Path scriptFile = projectRoot.resolve("Test").resolve("L1.py").normalize();
        if (!Files.exists(scriptFile)) {
            sendJson(ex, 500, "{\"ok\":false,\"message\":\"Không tìm thấy Test/L1.py\"}");
            return;
        }

        List<String> command = buildPythonCommand(scriptFile);
        command.add("predict_json");
        command.add(String.valueOf(order));
        command.add(String.valueOf(bundles));

        String payload = runPythonJsonCommand(
                ex,
                projectRoot,
                command,
                KENO_PREDICT_TIMEOUT_SECONDS,
                "Dự đoán Keno quá thời gian chờ",
                "Python predict không trả dữ liệu",
                "Python predict exited with error",
                "Tiến trình dự đoán Keno bị gián đoạn",
                "Không chạy được Python predict: ",
                null
        );
        if (payload == null) return;
        sendJson(ex, 200, payload);
    }

    private void handleAiPredict(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAuth(ex, true);
        if (su == null) return;
        if (!"GET".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }

        Path scriptFile = rootDir.resolve("ai").resolve("predictors").resolve("ai_predict.py");
        if (!Files.exists(scriptFile)) {
            sendJson(ex, 500, "{\"ok\":false,\"message\":\"Không tìm thấy ai_predict.py\"}");
            return;
        }

        Map<String, String> query = parseQuery(ex.getRequestURI() == null ? null : ex.getRequestURI().getRawQuery());
        String type = normalizeLiveType(query.get("type"));
        if (!AI_PREDICT_TYPE_KEYS.contains(type)) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Loại AI không hợp lệ\"}");
            return;
        }
        String engine = normalizeAiEngine(query.get("engine"));
        if (!AI_PREDICT_ENGINE_KEYS.contains(engine)) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Engine AI không hợp lệ\"}");
            return;
        }
        String riskMode = normalizeAiRiskMode(query.get("riskMode"));
        if (!AI_PREDICT_RISK_MODE_KEYS.contains(riskMode)) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Chế độ AI không hợp lệ\"}");
            return;
        }
        String predictionMode = "vip".equalsIgnoreCase(nvl(query.get("predictionMode")).trim()) ? "vip" : "normal";
        if ("vip".equals(predictionMode) && !"admin".equals(su.account.role) && !repo.hasVip(su.username)) {
            sendJson(ex, 403, "{\"ok\":false,\"message\":\"Tài khoản chưa có quyền VIP còn hạn\"}");
            return;
        }

        int count = parseStrictPositiveInt(query.get("count"));
        if (count <= 0) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Số bộ dự đoán không hợp lệ\"}");
            return;
        }

        String kenoLevelRaw = nvl(query.get("kenoLevel")).trim();
        if ("KENO".equals(type)) {
            int kenoLevel = parseStrictPositiveInt(kenoLevelRaw);
            if (kenoLevel < KENO_MIN_ORDER || kenoLevel > KENO_MAX_ORDER) {
                sendJson(ex, 400, "{\"ok\":false,\"message\":\"Bậc Keno phải trong khoảng 1-10\"}");
                return;
            }
        }

        List<String> command = buildPythonCommand(scriptFile);
        command.add("predict_json");
        command.add(type);
        command.add(String.valueOf(count));
        if ("KENO".equals(type)) {
            command.add(kenoLevelRaw);
        }
        command.add("--engine=" + engine);
        command.add("--risk-mode=" + riskMode);
        command.add("--prediction-mode=" + predictionMode);
        command.add("--username=" + su.username);

        String payload = runPythonJsonCommand(
                ex,
                rootDir,
                command,
                AI_PREDICT_TIMEOUT_SECONDS,
                "Dự đoán AI quá thời gian chờ",
                "AI predictor không trả dữ liệu",
                "AI predictor exited with error",
                "Tiến trình AI predict bị gián đoạn",
                "Không chạy được AI predictor: ",
                null
        );
        if (payload == null) return;
        sendJson(ex, 200, payload);
    }

    private void handleAiScore(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAuth(ex, true);
        if (su == null) return;
        if (!"GET".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }

        Path scriptFile = rootDir.resolve("ai").resolve("predictors").resolve("ai_predict.py");
        if (!Files.exists(scriptFile)) {
            sendJson(ex, 500, "{\"ok\":false,\"message\":\"Không tìm thấy ai_predict.py\"}");
            return;
        }

        Map<String, String> query = parseQuery(ex.getRequestURI() == null ? null : ex.getRequestURI().getRawQuery());
        String type = normalizeLiveType(query.get("type"));
        if (!AI_PREDICT_TYPE_KEYS.contains(type)) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Loại scoring không hợp lệ\"}");
            return;
        }

        String recentWindowRaw = nvl(query.get("recentWindow")).trim();
        if (!isBlank(recentWindowRaw)) {
            int recentWindow = parseStrictPositiveInt(recentWindowRaw);
            if (recentWindow <= 0) {
                sendJson(ex, 400, "{\"ok\":false,\"message\":\"recentWindow không hợp lệ\"}");
                return;
            }
        }

        String coTopKRaw = nvl(query.get("coTopK")).trim();
        if (!isBlank(coTopKRaw)) {
            int coTopK = parseStrictPositiveInt(coTopKRaw);
            if (coTopK <= 0) {
                sendJson(ex, 400, "{\"ok\":false,\"message\":\"coTopK không hợp lệ\"}");
                return;
            }
        }

        String backtestTopKRaw = nvl(query.get("backtestTopK")).trim();
        if (!isBlank(backtestTopKRaw)) {
            int backtestTopK = parseStrictPositiveInt(backtestTopKRaw);
            if (backtestTopK <= 0) {
                sendJson(ex, 400, "{\"ok\":false,\"message\":\"backtestTopK không hợp lệ\"}");
                return;
            }
        }

        String limitRaw = nvl(query.get("limit")).trim();
        if (!isBlank(limitRaw)) {
            int limit = parseStrictPositiveInt(limitRaw);
            if (limit <= 0) {
                sendJson(ex, 400, "{\"ok\":false,\"message\":\"limit không hợp lệ\"}");
                return;
            }
        }

        String weights = nvl(query.get("weights")).trim();
        boolean includeBacktest = isTruthyFlag(query.get("backtest"));
        boolean topOnly = isTruthyFlag(query.get("topOnly"));
        boolean exportCsv = isTruthyFlag(query.get("exportCsv"));

        List<String> command = buildPythonCommand(scriptFile);
        command.add("score_json");
        command.add(type);
        if (!isBlank(recentWindowRaw)) {
            command.add("--recent-window=" + recentWindowRaw);
        }
        if (!isBlank(weights)) {
            command.add("--weights=" + weights);
        }
        if (!isBlank(coTopKRaw)) {
            command.add("--co-top-k=" + coTopKRaw);
        }
        if (includeBacktest) {
            command.add("--backtest");
        }
        if (!isBlank(backtestTopKRaw)) {
            command.add("--backtest-top-k=" + backtestTopKRaw);
        }
        if (!isBlank(limitRaw)) {
            command.add("--limit=" + limitRaw);
        }
        if (topOnly) {
            command.add("--top-only");
        }
        if (exportCsv) {
            command.add("--export-csv");
        }

        String payload = runPythonJsonCommand(
                ex,
                rootDir,
                command,
                AI_SCORE_TIMEOUT_SECONDS,
                "Number scoring quá thời gian chờ",
                "Number scoring không trả dữ liệu",
                "Number scoring exited with error",
                "Tiến trình number scoring bị gián đoạn",
                "Không chạy được number scoring: ",
                null
        );
        if (payload == null) return;
        sendJson(ex, 200, payload);
    }

    private Path aiPredictScriptFile() {
        return rootDir.resolve("ai").resolve("predictors").resolve("ai_predict.py");
    }

    private boolean validateMlType(HttpExchange ex, String type) throws IOException {
        if (!ML_TYPE_KEYS.contains(type)) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Loại ML không hợp lệ\"}");
            return false;
        }
        return true;
    }

    private String runAiMlCommand(HttpExchange ex, List<String> command, String timeoutMessage) throws IOException {
        return runPythonJsonCommand(
                ex,
                rootDir,
                command,
                AI_ML_TIMEOUT_SECONDS,
                timeoutMessage,
                "ML pipeline không trả dữ liệu",
                "ML pipeline exited with error",
                "Tiến trình ML bị gián đoạn",
                "Không chạy được ML pipeline: ",
                null
        );
    }

    private boolean appendOptionalPositiveArg(HttpExchange ex, List<String> command, String flagName, String value, String errorMessage) throws IOException {
        String raw = nvl(value).trim();
        if (isBlank(raw)) return true;
        int parsed = parseStrictPositiveInt(raw);
        if (parsed <= 0) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"" + esc(errorMessage) + "\"}");
            return false;
        }
        command.add(flagName + "=" + parsed);
        return true;
    }

    private List<String> effectivenessCommand(String action, String type) {
        List<String> command = buildPythonCommand(rootDir.resolve("ai").resolve("prediction_effectiveness.py"));
        command.add(action);
        if (!isBlank(type)) command.add(type);
        return command;
    }

    private boolean validateEffectivenessType(HttpExchange ex, String type) throws IOException {
        if (!Arrays.asList("LOTO_5_35", "LOTO_6_45", "LOTO_6_55").contains(type)) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Hiệu quả dự đoán hỗ trợ 5/35, Mega và Power.\"}");
            return false;
        }
        return true;
    }

    private void sendEffectivenessResult(HttpExchange ex, List<String> command, boolean canManage) throws IOException {
        Process process = null;
        try {
            process = new ProcessBuilder(command).directory(rootDir.toFile()).start();
            ProcessOutput output = waitForProcessOutput(process, AI_PREDICT_TIMEOUT_SECONDS, TimeUnit.SECONDS);
            if (!output.finished) {
                sendJson(ex, 504, "{\"ok\":false,\"message\":\"Đánh giá dự đoán quá thời gian chờ.\"}"); return;
            }
            String payload = new String(output.stdout, StandardCharsets.UTF_8).trim();
            // Domain errors still carry valid JSON and a nonzero CLI exit code.
            Map<String, String> fields = jsonFields(payload);
            fields.put("canManage", canManage ? "true" : "false");
            sendJson(ex, "false".equals(fields.get("ok")) ? 400 : output.exitCode == 0 ? 200 : 500, fieldsJson(fields));
        } catch (IllegalArgumentException invalid) {
            sendJson(ex, 500, "{\"ok\":false,\"message\":\"Dữ liệu đánh giá không hợp lệ.\"}");
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            sendJson(ex, 503, "{\"ok\":false,\"message\":\"Đánh giá bị gián đoạn.\"}");
        } catch (IOException failure) {
            sendJson(ex, 500, "{\"ok\":false,\"message\":\"Không chạy được đánh giá dự đoán.\"}");
        } finally {
            if (process != null) process.destroy();
        }
    }

    private void handleMlEffectiveness(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAuth(ex, true);
        if (su == null) return;
        if (!"GET".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}"); return;
        }
        Map<String, String> query = parseQuery(ex.getRequestURI().getRawQuery());
        String type = normalizeLiveType(query.get("type"));
        if (!validateEffectivenessType(ex, type)) return;
        int limit = isBlank(query.get("limit")) ? 100 : parseStrictPositiveInt(query.get("limit"));
        if (limit < 1 || limit > 300) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Số kỳ phải từ 1 đến 300.\"}"); return;
        }
        List<String> command = effectivenessCommand("report", type);
        command.add("--limit=" + limit);
        sendEffectivenessResult(ex, command, "admin".equals(su.account.role));
    }

    private void handleMlEffectivenessSettings(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        boolean read = "GET".equalsIgnoreCase(ex.getRequestMethod());
        SessionUser su = read ? requireAuth(ex, true) : requireAdmin(ex);
        if (su == null) return;
        if (!read && !"POST".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}"); return;
        }
        Map<String, String> values = read ? parseQuery(ex.getRequestURI().getRawQuery()) : parseForm(ex);
        String type = normalizeLiveType(values.get("type"));
        if (!validateEffectivenessType(ex, type)) return;
        List<String> command = effectivenessCommand(read ? "settings" : "configure", type);
        if (!read) {
            String enabled = nvl(values.get("enabled"));
            int count = parseStrictPositiveInt(values.get("ticketCount"));
            if (!("true".equals(enabled) || "false".equals(enabled)) || count < 1 || count > 10) {
                sendJson(ex, 400, "{\"ok\":false,\"message\":\"Chọn trạng thái tự động và từ 1 đến 10 vé.\"}"); return;
            }
            command.add("--enabled=" + enabled);
            command.add("--ticket-count=" + count);
            command.add("--actor=" + su.username);
        }
        sendEffectivenessResult(ex, command, "admin".equals(su.account.role));
    }

    private void handleMlEffectivenessCycle(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAdmin(ex);
        if (su == null) return;
        if (!"POST".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}"); return;
        }
        Map<String, String> values = parseForm(ex);
        String type = normalizeLiveType(values.get("type"));
        if (!validateEffectivenessType(ex, type)) return;
        if (!effectivenessJobRunning.compareAndSet(false, true)) {
            sendJson(ex, 409, "{\"ok\":false,\"message\":\"Đang xử lý đánh giá. Vui lòng tải lại sau.\"}"); return;
        }
        try {
            sendEffectivenessResult(ex, effectivenessCommand("cycle", type), true);
        } finally {
            effectivenessJobRunning.set(false);
        }
    }

    private void startEffectivenessWorker() {
        if (!Boolean.parseBoolean(System.getProperty("lotto.effectivenessWorker", "true"))) return;
        Executors.newSingleThreadScheduledExecutor(task -> {
            Thread thread = new Thread(task, "prediction-effectiveness");
            thread.setDaemon(true);
            return thread;
        }).scheduleWithFixedDelay(() -> {
            if (!Files.exists(rootDir.resolve("ai").resolve("prediction_effectiveness.py"))
                    || !effectivenessJobRunning.compareAndSet(false, true)) return;
            Process process = null;
            try {
                process = new ProcessBuilder(effectivenessCommand("tick", null)).directory(rootDir.toFile()).start();
                ProcessOutput output = waitForProcessOutput(process, AI_ML_TIMEOUT_SECONDS, TimeUnit.SECONDS);
                if (!output.finished || output.exitCode != 0) {
                    System.err.println("Effectiveness worker failed: " + new String(output.stderr, StandardCharsets.UTF_8));
                }
            } catch (Exception failure) {
                if (failure instanceof InterruptedException) Thread.currentThread().interrupt();
                System.err.println("Effectiveness worker: " + rootCauseMsg(failure));
            } finally {
                if (process != null) process.destroy();
                effectivenessJobRunning.set(false);
            }
        }, 15, 60, TimeUnit.SECONDS);
    }

    private void pruneAlgorithmLabJobs() {
        Instant oldestAllowed = Instant.now().minus(Duration.ofDays(1));
        algorithmLabJobs.entrySet().removeIf(entry -> {
            AlgorithmLabJob job = entry.getValue();
            synchronized (job) { return !"running".equals(job.state) && job.createdAt.isBefore(oldestAllowed); }
        });
        while (algorithmLabJobs.size() >= 8) {
            AlgorithmLabJob oldest = null;
            for (AlgorithmLabJob job : algorithmLabJobs.values()) {
                synchronized (job) {
                    if (!"running".equals(job.state) && (oldest == null || job.createdAt.isBefore(oldest.createdAt))) oldest = job;
                }
            }
            if (oldest == null) break;
            algorithmLabJobs.remove(oldest.id, oldest);
        }
    }

    private void sendAlgorithmLabJob(HttpExchange ex, int status, AlgorithmLabJob job, boolean canManage) throws IOException {
        sendJson(ex, status, "{\"ok\":true,\"canManage\":" + canManage + ",\"job\":" + (job == null ? "null" : job.json()) + "}");
    }

    private void handleAlgorithmLab(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        String method = ex.getRequestMethod();
        SessionUser su = "GET".equalsIgnoreCase(method) ? requireAuth(ex, true) : requireAdmin(ex);
        if (su == null) return;
        if (!"GET".equalsIgnoreCase(method) && !"POST".equalsIgnoreCase(method)) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}"); return;
        }
        Map<String, String> values = "GET".equalsIgnoreCase(method) ? parseQuery(ex.getRequestURI().getRawQuery()) : parseForm(ex);
        String type = normalizeLiveType(values.get("type"));
        if (!validateEffectivenessType(ex, type)) return;
        pruneAlgorithmLabJobs();
        String jobId = nvl(values.get("jobId")).trim();
        AlgorithmLabJob selected = null;
        if (!isBlank(jobId)) {
            selected = algorithmLabJobs.get(jobId);
            if (selected == null || !selected.owner.equals(su.username) || !selected.type.equals(type)) {
                sendJson(ex, 404, "{\"ok\":false,\"message\":\"Không tìm thấy lượt thử của tài khoản này.\"}"); return;
            }
        }
        if ("GET".equalsIgnoreCase(method)) {
            if (isBlank(jobId)) {
                for (AlgorithmLabJob job : algorithmLabJobs.values()) {
                    if (job.owner.equals(su.username) && job.type.equals(type)
                            && (selected == null || job.createdAt.isAfter(selected.createdAt))) selected = job;
                }
            }
            sendAlgorithmLabJob(ex, 200, selected, "admin".equals(su.account.role)); return;
        }
        String action = nvl(values.get("action")).trim();
        if ("cancel".equals(action)) {
            if (selected == null) {
                sendJson(ex, 400, "{\"ok\":false,\"message\":\"Thiếu mã lượt thử cần hủy.\"}"); return;
            }
            synchronized (selected) {
                if ("running".equals(selected.state)) {
                    selected.cancelled = true; selected.state = "cancelled";
                    selected.finishedAt = Instant.now().toString();
                    if (selected.process != null) selected.process.destroyForcibly();
                }
            }
            sendAlgorithmLabJob(ex, 200, selected, true); return;
        }
        if ((!isBlank(action) && !"run".equals(action)) || !isBlank(jobId)) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Thao tác phòng thử không hợp lệ.\"}"); return;
        }
        int tickets = isBlank(values.get("ticketCount")) ? 3 : parseStrictPositiveInt(values.get("ticketCount"));
        int validation = isBlank(values.get("validationCount")) ? 10 : parseStrictPositiveInt(values.get("validationCount"));
        int test = isBlank(values.get("testCount")) ? 20 : parseStrictPositiveInt(values.get("testCount"));
        if (tickets < 1 || tickets > 10 || validation < 5 || validation > 50 || test < 5 || test > 50 || validation + test > 100) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Chọn 1–10 vé và 5–50 kỳ cho mỗi tập chọn/đánh giá.\"}"); return;
        }
        if (!Files.isRegularFile(rootDir.resolve("ai").resolve("algorithm_lab.py"))) {
            sendJson(ex, 503, "{\"ok\":false,\"message\":\"Phòng thử chưa sẵn sàng trên server.\"}"); return;
        }
        if (!algorithmLabRunning.compareAndSet(false, true)) {
            sendJson(ex, 409, "{\"ok\":false,\"message\":\"Đang có lượt thử thuật toán chạy. Vui lòng chờ hoàn tất.\"}"); return;
        }
        AlgorithmLabJob job = new AlgorithmLabJob(su.username, type, tickets, validation, test);
        algorithmLabJobs.put(job.id, job);
        Thread worker = new Thread(() -> runAlgorithmLab(job), "algorithm-lab-" + job.id);
        worker.setDaemon(true);
        try { worker.start(); }
        catch (RuntimeException failure) {
            algorithmLabJobs.remove(job.id); algorithmLabRunning.set(false);
            sendJson(ex, 503, "{\"ok\":false,\"message\":\"Không khởi chạy được phòng thử.\"}"); return;
        }
        sendAlgorithmLabJob(ex, 202, job, true);
    }

    private void runAlgorithmLab(AlgorithmLabJob job) {
        Process process = null;
        try {
            List<String> command = buildPythonCommand(rootDir.resolve("ai").resolve("algorithm_lab.py"));
            command.add("--action=run"); command.add("--game=" + job.type);
            command.add("--ticket-count=" + job.ticketCount);
            command.add("--validation-count=" + job.validationCount); command.add("--test-count=" + job.testCount);
            synchronized (job) {
                if (job.cancelled) return;
                process = new ProcessBuilder(command).directory(rootDir.toFile()).start(); job.process = process;
            }
            ProcessOutput output = waitForProcessOutput(process, AI_ML_TIMEOUT_SECONDS, TimeUnit.SECONDS);
            String payload = new String(output.stdout, StandardCharsets.UTF_8).trim();
            synchronized (job) {
                if (job.cancelled) return;
                if (!output.finished) throw new IllegalArgumentException("Lượt thử quá thời gian chờ; hãy giảm số kỳ.");
                Map<String, String> fields = jsonFields(payload);
                if (output.exitCode != 0 || !"true".equals(fields.get("ok"))) {
                    String message = jsonString(fields.get("message"));
                    throw new IllegalArgumentException(isBlank(message) ? "Không hoàn tất lượt thử thuật toán." : message);
                }
                if (!job.type.equals(jsonString(fields.get("type")))) throw new IllegalArgumentException("Báo cáo không khớp loại xổ số đã chọn.");
                job.report = payload; job.state = "completed"; job.finishedAt = Instant.now().toString();
            }
        } catch (Exception failure) {
            if (failure instanceof InterruptedException) Thread.currentThread().interrupt();
            synchronized (job) {
                if (!job.cancelled) {
                    job.state = "failed";
                    job.error = failure instanceof IllegalArgumentException ? nvl(failure.getMessage()) : "Không chạy được phòng thử thuật toán.";
                    job.finishedAt = Instant.now().toString();
                }
            }
        } finally {
            if (process != null) process.destroyForcibly();
            synchronized (job) { job.process = null; if (isBlank(job.finishedAt)) job.finishedAt = Instant.now().toString(); }
            algorithmLabRunning.set(false);
        }
    }

    private void handleMlStatus(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAuth(ex, true);
        if (su == null) return;
        if (!"GET".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }
        Path scriptFile = aiPredictScriptFile();
        if (!Files.exists(scriptFile)) {
            sendJson(ex, 500, "{\"ok\":false,\"message\":\"Không tìm thấy ai_predict.py\"}");
            return;
        }
        Map<String, String> query = parseQuery(ex.getRequestURI() == null ? null : ex.getRequestURI().getRawQuery());
        String type = normalizeLiveType(query.get("type"));
        if (!isBlank(type) && !validateMlType(ex, type)) return;
        List<String> command = buildPythonCommand(scriptFile);
        command.add("ml_status");
        if (!isBlank(type)) command.add(type);
        String payload = runAiMlCommand(ex, command, "ML status quá thời gian chờ");
        if (payload == null) return;
        sendJson(ex, 200, payload);
    }

    private void handleMlPredictions(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAuth(ex, true);
        if (su == null) return;
        if (!"GET".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }
        Path scriptFile = aiPredictScriptFile();
        if (!Files.exists(scriptFile)) {
            sendJson(ex, 500, "{\"ok\":false,\"message\":\"Không tìm thấy ai_predict.py\"}");
            return;
        }
        Map<String, String> query = parseQuery(ex.getRequestURI() == null ? null : ex.getRequestURI().getRawQuery());
        String type = normalizeLiveType(query.get("type"));
        if (!isBlank(type) && !validateMlType(ex, type)) return;
        List<String> command = buildPythonCommand(scriptFile);
        command.add("ml_predictions");
        if (!isBlank(type)) command.add(type);
        command.add("--username=" + su.username);
        String payload = runAiMlCommand(ex, command, "ML predictions quá thời gian chờ");
        if (payload == null) return;
        sendJson(ex, 200, payload);
    }

    private void handleMlBacktest(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAuth(ex, true);
        if (su == null) return;
        if (!"POST".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }
        Path scriptFile = aiPredictScriptFile();
        if (!Files.exists(scriptFile)) {
            sendJson(ex, 500, "{\"ok\":false,\"message\":\"Không tìm thấy ai_predict.py\"}");
            return;
        }
        Map<String, String> f = parseForm(ex);
        String type = normalizeLiveType(f.get("type"));
        if (!validateMlType(ex, type)) return;
        String mode = "full".equalsIgnoreCase(nvl(f.get("mode")).trim()) ? "full" : "fast";
        String window = "rolling".equalsIgnoreCase(nvl(f.get("window")).trim()) ? "rolling" : "expanding";
        List<String> command = buildPythonCommand(scriptFile);
        command.add("ml_backtest");
        command.add(type);
        command.add("--mode=" + mode);
        command.add("--window=" + window);
        if (!appendOptionalPositiveArg(ex, command, "--rolling-window", f.get("rollingWindow"), "rollingWindow không hợp lệ")) return;
        if (!appendOptionalPositiveArg(ex, command, "--min-history", f.get("minHistory"), "minHistory không hợp lệ")) return;
        if (!appendOptionalPositiveArg(ex, command, "--retrain-interval", f.get("retrainInterval"), "retrainInterval không hợp lệ")) return;
        String payload = runAiMlCommand(ex, command, "ML backtest quá thời gian chờ");
        if (payload == null) return;
        sendJson(ex, 200, payload);
    }

    private void handleMlScorePending(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAuth(ex, true);
        if (su == null) return;
        if (!"POST".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }
        Path scriptFile = aiPredictScriptFile();
        if (!Files.exists(scriptFile)) {
            sendJson(ex, 500, "{\"ok\":false,\"message\":\"Không tìm thấy ai_predict.py\"}");
            return;
        }
        Map<String, String> f = parseForm(ex);
        String type = normalizeLiveType(f.get("type"));
        if (!validateMlType(ex, type)) return;
        List<String> command = buildPythonCommand(scriptFile);
        command.add("ml_score_pending");
        command.add(type);
        String payload = runAiMlCommand(ex, command, "ML score pending quá thời gian chờ");
        if (payload == null) return;
        sendJson(ex, 200, payload);
    }

    private void handleMlTrainCandidate(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAdmin(ex);
        if (su == null) return;
        if (!"POST".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }
        Path scriptFile = aiPredictScriptFile();
        if (!Files.exists(scriptFile)) {
            sendJson(ex, 500, "{\"ok\":false,\"message\":\"Không tìm thấy ai_predict.py\"}");
            return;
        }
        Map<String, String> f = parseForm(ex);
        String type = normalizeLiveType(f.get("type"));
        if (!validateMlType(ex, type)) return;
        String mode = "full".equalsIgnoreCase(nvl(f.get("mode")).trim()) ? "full" : "fast";
        List<String> command = buildPythonCommand(scriptFile);
        command.add("ml_train_candidate");
        command.add(type);
        command.add("--mode=" + mode);
        String payload = runAiMlCommand(ex, command, "ML train candidate quá thời gian chờ");
        if (payload == null) return;
        sendJson(ex, 200, payload);
    }

    private void handleMlPromote(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAdmin(ex);
        if (su == null) return;
        if (!"POST".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }
        Path scriptFile = aiPredictScriptFile();
        if (!Files.exists(scriptFile)) {
            sendJson(ex, 500, "{\"ok\":false,\"message\":\"Không tìm thấy ai_predict.py\"}");
            return;
        }
        Map<String, String> f = parseForm(ex);
        String type = normalizeLiveType(f.get("type"));
        if (!validateMlType(ex, type)) return;
        String modelId = nvl(f.get("modelId")).trim();
        if (isBlank(modelId)) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Thiếu modelId\"}");
            return;
        }
        List<String> command = buildPythonCommand(scriptFile);
        command.add("ml_promote");
        command.add(type);
        command.add("--model-id=" + modelId);
        String payload = runAiMlCommand(ex, command, "ML promote quá thời gian chờ");
        if (payload == null) return;
        sendJson(ex, 200, payload);
    }

    private void handleMlRollback(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAdmin(ex);
        if (su == null) return;
        if (!"POST".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }
        Path scriptFile = aiPredictScriptFile();
        if (!Files.exists(scriptFile)) {
            sendJson(ex, 500, "{\"ok\":false,\"message\":\"Không tìm thấy ai_predict.py\"}");
            return;
        }
        Map<String, String> f = parseForm(ex);
        String type = normalizeLiveType(f.get("type"));
        if (!validateMlType(ex, type)) return;
        List<String> command = buildPythonCommand(scriptFile);
        command.add("ml_rollback");
        command.add(type);
        String payload = runAiMlCommand(ex, command, "ML rollback quá thời gian chờ");
        if (payload == null) return;
        sendJson(ex, 200, payload);
    }

    // ----- API quản trị -----
    // Nhóm route chỉ dành cho admin: user list, sửa quyền, đổi tên, reset/xóa tài khoản.
    private void handleAdminUsers(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAdmin(ex);
        if (su == null) return;
        if (!"GET".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }
        List<UserView> users = repo.listUsers();
        StringBuilder sb = new StringBuilder();
        sb.append("{\"ok\":true,\"users\":[");
        for (int i = 0; i < users.size(); i++) {
            UserView u = users.get(i);
            if (i > 0) sb.append(",");
            sb.append("{\"username\":\"").append(esc(u.username)).append("\",")
                    .append("\"role\":\"").append(esc(u.role)).append("\",")
                    .append("\"enabled\":").append(u.enabled).append(",")
                    .append("\"hasData\":").append(u.hasData).append(",")
                    .append("\"diamondBalance\":").append(u.diamondBalance).append(",")
                    .append("\"paypalBalance\":").append(u.paypalBalance).append("}");
        }
        sb.append("]}");
        sendJson(ex, 200, sb.toString());
    }

    private void handleAdminUpdateUser(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAdmin(ex);
        if (su == null) return;
        if (!"POST".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }
        Map<String, String> f = parseForm(ex);
        String user = normalizeUser(f.get("username"));
        String role = "admin".equalsIgnoreCase(f.get("role")) ? "admin" : "user";
        boolean enabled = "true".equalsIgnoreCase(f.get("enabled")) || "1".equals(f.get("enabled")) || "on".equalsIgnoreCase(f.get("enabled"));
        try {
            repo.updateUser(user, role, enabled, su.username);
            sendJson(ex, 200, "{\"ok\":true}");
        } catch (IllegalStateException e) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"" + esc(e.getMessage()) + "\"}");
        }
    }

    private void handleAdminRenameUser(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAdmin(ex);
        if (su == null) return;
        if (!"POST".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }
        Map<String, String> f = parseForm(ex);
        String user = normalizeUser(f.get("username"));
        String newUser = normalizeUser(f.get("newUsername"));
        try {
            repo.renameUser(user, newUser);
            if (su.username.equals(user)) {
                String token = getCookie(ex, COOKIE_NAME);
                if (token != null) sessions.put(token, newUser);
            }
            sendJson(ex, 200, "{\"ok\":true}");
        } catch (IllegalStateException e) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"" + esc(e.getMessage()) + "\"}");
        }
    }

    private void handleAdminUpdateAssets(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAdmin(ex);
        if (su == null) return;
        String method = ex.getRequestMethod();
        if (!"POST".equalsIgnoreCase(method)) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }
        Map<String, String> f = parseForm(ex);
        String user = normalizeUser(f.get("username"));
        int diamond = parseNonNegativeInt(f.get("diamond"));
        int paypal = parseNonNegativeInt(f.get("paypal"));
        try {
            repo.updateAssets(user, diamond, paypal, su.username);
            sendJson(ex, 200, "{\"ok\":true}");
        } catch (IllegalStateException e) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"" + esc(e.getMessage()) + "\"}");
        }
    }

    private void handleAdminResetPassword(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAdmin(ex);
        if (su == null) return;
        if (!"POST".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }
        Map<String, String> f = parseForm(ex);
        String user = normalizeUser(f.get("username"));
        String pass = nvl(f.get("newPassword")).trim();
        try {
            repo.resetPassword(user, pass);
            sendJson(ex, 200, "{\"ok\":true}");
        } catch (IllegalStateException e) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"" + esc(e.getMessage()) + "\"}");
        }
    }

    private void handleAdminDeleteUser(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAdmin(ex);
        if (su == null) return;
        if (!"POST".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }
        Map<String, String> f = parseForm(ex);
        String user = normalizeUser(f.get("username"));
        try {
            repo.deleteUser(user, su.username);
            sendJson(ex, 200, "{\"ok\":true}");
        } catch (IllegalStateException e) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"" + esc(e.getMessage()) + "\"}");
        }
    }

    private SessionUser requireAuth(HttpExchange ex, boolean sendErr) throws IOException {
        String token = getCookie(ex, COOKIE_NAME);
        if (token == null) {
            if (sendErr) sendJson(ex, 401, "{\"ok\":false,\"message\":\"Chưa đăng nhập\"}");
            return null;
        }
        String user = sessions.get(token);
        if (user == null || EFFECTIVENESS_SYSTEM_USER.equals(user) || sessionExpiry.getOrDefault(token, 0L) <= System.currentTimeMillis()) {
            sessions.remove(token);
            sessionExpiry.remove(token);
            sessionPasswordHash.remove(token);
            if (sendErr) sendJson(ex, 401, "{\"ok\":false,\"message\":\"Phiên đăng nhập đã hết hạn\"}");
            return null;
        }
        Account acc = repo.getUser(user);
        if (acc == null || !acc.enabled || !Objects.equals(acc.passwordHash, sessionPasswordHash.get(token))) {
            sessions.remove(token);
            sessionExpiry.remove(token);
            sessionPasswordHash.remove(token);
            if (sendErr) sendJson(ex, 403, "{\"ok\":false,\"message\":\"Tài khoản không còn truy cập\"}");
            return null;
        }
        return new SessionUser(user, acc);
    }

    private SessionUser requireAdmin(HttpExchange ex) throws IOException {
        SessionUser su = requireAuth(ex, true);
        if (su == null) return null;
        if (!"admin".equals(su.account.role)) {
            sendJson(ex, 403, "{\"ok\":false,\"message\":\"Yêu cầu quyền admin\"}");
            return null;
        }
        return su;
    }

    private void setCookie(HttpExchange ex, String name, String value, boolean expired) {
        String cookie = name + "=" + value + "; Path=/; HttpOnly; SameSite=Lax";
        if (expired) cookie += "; Max-Age=0";
        ex.getResponseHeaders().add("Set-Cookie", cookie);
    }

    private String getCookie(HttpExchange ex, String name) {
        String cookie = ex.getRequestHeaders().getFirst("Cookie");
        if (cookie == null) return null;
        for (String part : cookie.split(";")) {
            String p = part.trim();
            int idx = p.indexOf('=');
            if (idx <= 0) continue;
            if (name.equals(p.substring(0, idx))) return p.substring(idx + 1);
        }
        return null;
    }

    // ----- Helper chạy nền cho live-results -----
    // Quản lý file progress, stale state, log runtime và tiến trình Cập Nhật chạy nền.
    private Path getLiveResultsProgressFile() {
        return rootDir.resolve("runtime").resolve("logs").resolve("live_results_progress.json");
    }

    private Path getLiveResultsProgressLockFile() {
        return rootDir.resolve("runtime").resolve("logs").resolve("live_results_progress.lock");
    }

    private Path getLiveResultsLogFile() {
        return rootDir.resolve("runtime").resolve("logs").resolve("live_results_manual_update.log");
    }

    private Path getDataRegistryFile() {
        return rootDir.resolve("ai").resolve("configs").resolve("data_registry.json");
    }

    private String readDataRegistryJson() {
        Path dataRegistryFile = getDataRegistryFile();
        if (!Files.exists(dataRegistryFile)) return "";
        try {
            return new String(Files.readAllBytes(dataRegistryFile), StandardCharsets.UTF_8);
        } catch (IOException e) {
            return "";
        }
    }

    private Path resolveRegistryDataPath(String registryKey, String defaultRelative, Path legacyFallback) {
        String relative = extractJsonStringField(readDataRegistryJson(), registryKey);
        if (isBlank(relative)) relative = nvl(defaultRelative).trim();
        Path preferred = rootDir.resolve(relative).normalize();
        if (Files.exists(preferred) || legacyFallback == null || !Files.exists(legacyFallback)) {
            return preferred;
        }
        return legacyFallback.normalize();
    }

    private String defaultLiveResultsProgressJson() {
        return "{\"ok\":true,\"running\":false,\"done\":false,\"runId\":\"\",\"startedAt\":\"\",\"updatedAt\":\"\",\"completedAt\":\"\",\"phase\":\"\",\"currentType\":\"\",\"completedSteps\":0,\"totalSteps\":0,\"percent\":0,\"etaSeconds\":null,\"message\":\"\",\"warnings\":[],\"errors\":[],\"typeStates\":{}}";
    }

    private String readLiveResultsProgressJson() {
        Path progressFile = getLiveResultsProgressFile();
        if (!Files.exists(progressFile)) return defaultLiveResultsProgressJson();
        try {
            return new String(Files.readAllBytes(progressFile), StandardCharsets.UTF_8);
        } catch (IOException e) {
            return defaultLiveResultsProgressJson();
        }
    }

    private boolean extractJsonBooleanField(String json, String field, boolean fallback) {
        Matcher matcher = Pattern.compile("\"" + Pattern.quote(field) + "\"\\s*:\\s*(true|false)", Pattern.CASE_INSENSITIVE)
                .matcher(nvl(json));
        if (!matcher.find()) return fallback;
        return "true".equalsIgnoreCase(matcher.group(1));
    }

    private String extractJsonStringField(String json, String field) {
        Matcher matcher = Pattern.compile("\"" + Pattern.quote(field) + "\"\\s*:\\s*\"((?:\\\\.|[^\\\\\"])*)\"")
                .matcher(nvl(json));
        if (!matcher.find()) return "";
        return matcher.group(1).replace("\\\"", "\"").replace("\\\\", "\\");
    }

    private long extractJsonLongField(String json, String field, long fallback) {
        Matcher matcher = Pattern.compile("\"" + Pattern.quote(field) + "\"\\s*:\\s*(-?\\d+)")
                .matcher(nvl(json));
        if (!matcher.find()) return fallback;
        try {
            return Long.parseLong(matcher.group(1));
        } catch (NumberFormatException e) {
            return fallback;
        }
    }

    private boolean isPidRunning(long pid) {
        if (pid <= 0) return false;
        Process process = null;
        try {
            process = new ProcessBuilder("cmd", "/c", "tasklist /FI \"PID eq " + pid + "\" /FO CSV /NH").start();
            ProcessOutput output = waitForProcessOutput(process, 5, TimeUnit.SECONDS);
            if (!output.finished || output.exitCode != 0) return false;
            String text = new String(output.stdout, StandardCharsets.UTF_8).trim();
            return !isBlank(text) && !text.startsWith("INFO:");
        } catch (Exception e) {
            return false;
        } finally {
            if (process != null) process.destroy();
        }
    }

    private void ensureLiveResultsRuntimeDir() throws IOException {
        Files.createDirectories(getLiveResultsProgressFile().getParent());
    }

    private void writeLiveResultsProgressJson(String json) {
        try {
            ensureLiveResultsRuntimeDir();
            Files.write(getLiveResultsProgressFile(), json.getBytes(StandardCharsets.UTF_8));
        } catch (IOException ignored) {
        }
    }

    private String buildStaleLiveResultsProgressJson(String message) {
        String safe = esc(isBlank(message) ? "Phiên cập nhật trước đã bị gián đoạn." : message);
        return "{\"ok\":false,\"running\":false,\"done\":true,\"runId\":\"\",\"startedAt\":\"\",\"updatedAt\":\"\",\"completedAt\":\"\",\"phase\":\"failed\",\"currentType\":\"\",\"completedSteps\":0,\"totalSteps\":0,\"percent\":0,\"etaSeconds\":null,\"message\":\"" + safe + "\",\"warnings\":[],\"errors\":[\"" + safe + "\"],\"typeStates\":{}}";
    }

    private String buildPendingLiveResultsProgressJson() {
        String now = LocalDateTime.now().toString();
        return "{\"ok\":true,\"running\":false,\"done\":false,\"runId\":\"\",\"startedAt\":\"" + esc(now) + "\",\"updatedAt\":\"" + esc(now) + "\",\"completedAt\":\"\",\"phase\":\"prepare\",\"currentType\":\"\",\"completedSteps\":0,\"totalSteps\":0,\"percent\":0,\"etaSeconds\":null,\"message\":\"Đang khởi động cập nhật 6 loại từ MinhChinh.\",\"warnings\":[],\"errors\":[],\"typeStates\":{}}";
    }

    private boolean isProgressStale(String progressJson) {
        if (!extractJsonBooleanField(progressJson, "running", false)) return false;
        String updatedAt = extractJsonStringField(progressJson, "updatedAt");
        if (isBlank(updatedAt)) return true;
        try {
            long ageSeconds = Math.abs(Duration.between(LocalDateTime.parse(updatedAt), LocalDateTime.now()).getSeconds());
            return ageSeconds > LIVE_RESULTS_PROGRESS_STALE_SECONDS;
        } catch (DateTimeParseException e) {
            return true;
        }
    }

    private boolean refreshLiveResultsProgressState() {
        Path lockFile = getLiveResultsProgressLockFile();
        String progressJson = readLiveResultsProgressJson();
        boolean lockExists = Files.exists(lockFile);
        boolean running = extractJsonBooleanField(progressJson, "running", false);
        long pid = extractJsonLongField(readJsonFileIfExists(lockFile), "pid", 0L);
        boolean pidRunning = isPidRunning(pid);
        boolean stale = (running && !lockExists) || (lockExists && !pidRunning) || (running && isProgressStale(progressJson));
        if (stale) {
            try {
                Files.deleteIfExists(lockFile);
            } catch (IOException ignored) {
            }
            writeLiveResultsProgressJson(buildStaleLiveResultsProgressJson("Phiên cập nhật trước đã bị gián đoạn."));
            return false;
        }
        return lockExists && pidRunning && running;
    }

    private String readJsonFileIfExists(Path path) {
        if (path == null || !Files.exists(path)) return "";
        try {
            return new String(Files.readAllBytes(path), StandardCharsets.UTF_8);
        } catch (IOException e) {
            return "";
        }
    }

    private void startLiveResultsRepairProcess(Path scriptFile) throws IOException {
        ensureLiveResultsRuntimeDir();
        writeLiveResultsProgressJson(buildPendingLiveResultsProgressJson());
        File logFile = getLiveResultsLogFile().toFile();
        List<String> command = buildPythonCommand(scriptFile);
        command.add("--repair-canonical");
        ProcessBuilder pb = new ProcessBuilder(command);
        pb.directory(rootDir.toFile());
        pb.redirectErrorStream(true);
        // Chỉ giữ log của lần cập nhật gần nhất để tránh file lớn làm OneDrive đồng bộ liên tục.
        pb.redirectOutput(ProcessBuilder.Redirect.to(logFile));
        pb.start();
    }

    private String waitForLiveResultsProgressStartup(long timeoutMs) {
        long startedAt = System.currentTimeMillis();
        while (System.currentTimeMillis() - startedAt < Math.max(250L, timeoutMs)) {
            refreshLiveResultsProgressState();
            String json = readLiveResultsProgressJson();
            if (extractJsonBooleanField(json, "running", false) || extractJsonBooleanField(json, "done", false)) {
                return json;
            }
            try {
                Thread.sleep(150L);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                break;
            }
        }
        String json = readLiveResultsProgressJson();
        boolean running = extractJsonBooleanField(json, "running", false);
        boolean done = extractJsonBooleanField(json, "done", false);
        if (!running && !done) {
            String failed = buildStaleLiveResultsProgressJson("Không khởi động được tiến trình cập nhật.");
            writeLiveResultsProgressJson(failed);
            return failed;
        }
        return json;
    }

    private String buildBusyLiveResultsPayload() {
        return "{\"ok\":false,\"message\":\"Đang có phiên cập nhật đang chạy\",\"progress\":" + readLiveResultsProgressJson() + "}";
    }

    // ----- Tiện ích HTTP và parse dữ liệu -----
    // Gom các hàm gửi JSON, parse query/form, CORS, validate chuỗi và xử lý session.
    private void sendJson(HttpExchange ex, int status, String json) throws IOException {
        byte[] raw = json.getBytes(StandardCharsets.UTF_8);
        byte[] compressed = raw.length >= 1024 ? gzip(raw) : raw;
        boolean useGzip = acceptsGzip(ex) && compressed.length < raw.length;
        byte[] out = useGzip ? compressed : raw;
        Headers h = ex.getResponseHeaders();
        addCors(ex);
        h.set("Content-Type", "application/json; charset=UTF-8");
        h.set("Cache-Control", "no-store");
        h.add("Vary", "Accept-Encoding");
        if (useGzip) h.set("Content-Encoding", "gzip");
        long nowMs = System.currentTimeMillis();
        h.set("X-Server-Time-Ms", String.valueOf(nowMs));
        h.set("X-Server-Time-Iso", Instant.ofEpochMilli(nowMs).toString());
        h.set("X-Server-Timezone", ZoneId.systemDefault().getId());
        ex.sendResponseHeaders(status, out.length);
        try (OutputStream os = ex.getResponseBody()) {
            os.write(out);
        }
    }

    private boolean acceptsGzip(HttpExchange ex) {
        String value = ex.getRequestHeaders().getFirst("Accept-Encoding");
        return value != null && value.toLowerCase(Locale.ROOT).contains("gzip");
    }

    private static byte[] gzip(byte[] input) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream(Math.max(256, input.length / 3));
        try (GZIPOutputStream gzip = new GZIPOutputStream(out)) {
            gzip.write(input);
        }
        return out.toByteArray();
    }

    private boolean handleOptions(HttpExchange ex) throws IOException {
        if (!allowedOrigin(ex)) {
            sendJson(ex, 403, "{\"ok\":false,\"message\":\"Origin không được phép\"}");
            return true;
        }
        String length = ex.getRequestHeaders().getFirst("Content-Length");
        if (length != null) {
            try {
                if (Long.parseLong(length) > MAX_REQUEST_BYTES) {
                    sendJson(ex, 413, "{\"ok\":false,\"message\":\"Request quá lớn\"}");
                    return true;
                }
            } catch (NumberFormatException invalid) {
                sendJson(ex, 400, "{\"ok\":false,\"message\":\"Content-Length không hợp lệ\"}");
                return true;
            }
        }
        if (!"OPTIONS".equalsIgnoreCase(ex.getRequestMethod())) return false;
        addCors(ex);
        ex.sendResponseHeaders(204, -1);
        ex.close();
        return true;
    }

    private void addCors(HttpExchange ex) {
        String origin = ex.getRequestHeaders().getFirst("Origin");
        Headers h = ex.getResponseHeaders();
        if (origin == null || isBlank(origin) || !allowedOrigin(ex)) return;
        h.set("Access-Control-Allow-Origin", origin);
        h.set("Vary", "Origin");
        h.set("Access-Control-Allow-Credentials", "true");
        h.set("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
        h.set("Access-Control-Allow-Headers", "Content-Type");
        h.set("Access-Control-Expose-Headers", "X-Server-Time-Ms, X-Server-Time-Iso, X-Server-Timezone");
    }

    private Map<String, String> parseForm(HttpExchange ex) throws IOException {
        try {
            String body = new String(readAllBytes(ex.getRequestBody()), StandardCharsets.UTF_8);
            return parseUrlEncoded(body);
        } catch (IOException limit) {
            sendJson(ex, 413, "{\"ok\":false,\"message\":\"Request quá lớn hoặc không đọc được\"}");
            throw limit;
        }
    }

    private boolean allowedOrigin(HttpExchange ex) {
        String origin = ex.getRequestHeaders().getFirst("Origin");
        if (isBlank(origin)) return true;
        try {
            java.net.URI uri = java.net.URI.create(origin);
            String host = uri.getHost();
            if (!"http".equals(uri.getScheme()) && !"https".equals(uri.getScheme())) return false;
            if (uri.getRawUserInfo() != null || !isBlank(uri.getRawQuery()) || !isBlank(uri.getRawFragment())
                    || (uri.getPath() != null && !uri.getPath().isEmpty())) return false;
            if (uri.getPort() == PORT && ("localhost".equals(host) || "127.0.0.1".equals(host))) return true;
            return Arrays.asList(System.getProperty("lotto.allowedOrigins", "").split(",")).contains(origin);
        } catch (IllegalArgumentException invalid) { return false; }
    }

    private Map<String, String> parseQuery(String rawQuery) {
        return parseUrlEncoded(rawQuery);
    }

    private Map<String, String> parseUrlEncoded(String body) {
        Map<String, String> map = new HashMap<>();
        if (isBlank(body)) return map;
        for (String pair : body.split("&")) {
            int i = pair.indexOf('=');
            String k = i >= 0 ? pair.substring(0, i) : pair;
            String v = i >= 0 ? pair.substring(i + 1) : "";
            map.put(urlDecode(k), urlDecode(v));
        }
        return map;
    }

    private String urlDecode(String s) {
        try {
            return URLDecoder.decode(s, "UTF-8");
        } catch (UnsupportedEncodingException e) {
            throw new IllegalStateException("UTF-8 not supported", e);
        }
    }

    private static String nvl(String s) {
        return s == null ? "" : s;
    }

    private static String normalizeUser(String u) {
        return nvl(u).trim().toLowerCase(Locale.ROOT);
    }

    private static int parseNonNegativeInt(String s) {
        try {
            return Math.max(0, Integer.parseInt(nvl(s).trim()));
        } catch (Exception e) {
            return 0;
        }
    }

    private static int parseStrictPositiveInt(String s) {
        try {
            int value = Integer.parseInt(nvl(s).trim());
            return value > 0 ? value : -1;
        } catch (Exception e) {
            return -1;
        }
    }

    private static String normalizeLiveType(String raw) {
        return nvl(raw).trim().toUpperCase(Locale.ROOT);
    }

    private static String normalizeAiEngine(String raw) {
        String value = nvl(raw).trim().toLowerCase(Locale.ROOT).replace('-', '_');
        if (value.isEmpty()) return "classic";
        if ("gen".equals(value) || "genlocal".equals(value)) return "gen_local";
        if ("luanso".equals(value) || "luan so".equals(value)) return "luan_so";
        return value;
    }

    private static String normalizeAiRiskMode(String raw) {
        String value = nvl(raw).trim().toLowerCase(Locale.ROOT).replace('-', '_');
        if (value.isEmpty()) return "balanced";
        if ("on_dinh".equals(value) || "stable_mode".equals(value)) return "stable";
        if ("can_bang".equals(value) || "balance".equals(value)) return "balanced";
        if ("tan_cong".equals(value) || "attack".equals(value)) return "aggressive";
        return value;
    }

    private static boolean isTruthyFlag(String s) {
        String value = nvl(s).trim().toLowerCase(Locale.ROOT);
        return "1".equals(value)
                || "true".equals(value)
                || "yes".equals(value)
                || "y".equals(value)
                || "on".equals(value);
    }

    private static boolean isValidStatsV2Date(String value) {
        String text = nvl(value).trim();
        return text.matches("\\d{4}-\\d{2}-\\d{2}") || text.matches("\\d{1,2}/\\d{1,2}/\\d{4}");
    }

    private static String esc(String s) {
        if (s == null) return "";
        StringBuilder result = new StringBuilder();
        for (int i = 0; i < s.length(); i++) {
            char ch = s.charAt(i);
            if (ch == '"' || ch == '\\') result.append('\\').append(ch);
            else if (ch < 0x20) result.append(String.format("\\u%04x", (int)ch));
            else result.append(ch);
        }
        return result.toString();
    }

    private static String rootCauseMsg(Throwable t) {
        Throwable cur = t;
        while (cur.getCause() != null && cur.getCause() != cur) {
            cur = cur.getCause();
        }
        String msg = cur.getMessage();
        return isBlank(msg) ? cur.getClass().getSimpleName() : msg;
    }

    private static boolean isBlank(String value) {
        return value == null || value.trim().isEmpty();
    }

    private static String requireValidJsonObjectText(String jsonText) {
        String trimmed = nvl(jsonText).trim();
        if (trimmed.isEmpty()) return "{}";
        JsonCursor cursor = new JsonCursor(trimmed);
        cursor.skipWhitespace();
        cursor.parseObject();
        cursor.skipWhitespace();
        if (!cursor.isEnd()) {
            throw new IllegalArgumentException("Store JSON chỉ chấp nhận một object hợp lệ.");
        }
        return trimmed;
    }

    // Parse root fields, preserving nested JSON and decoding escaped key names.
    private static Map<String, String> jsonFields(String json) {
        JsonCursor cursor = new JsonCursor(requireValidJsonObjectText(json));
        Map<String, String> fields = new LinkedHashMap<>();
        cursor.expect('{');
        if (cursor.consumeIf('}')) return fields;
        while (true) {
            cursor.skipWhitespace();
            int start = cursor.index;
            cursor.parseString();
            String key = jsonString(cursor.text.substring(start, cursor.index));
            cursor.expect(':');
            cursor.skipWhitespace();
            start = cursor.index;
            cursor.parseValue();
            if (fields.put(key, cursor.text.substring(start, cursor.index)) != null)
                throw new IllegalArgumentException("JSON có khóa lặp: " + key);
            if (cursor.consumeIf('}')) return fields;
            cursor.expect(',');
        }
    }

    private static String jsonString(String raw) {
        if (raw == null || raw.equals("null")) return "";
        StringBuilder result = new StringBuilder();
        for (int i = 1; i < raw.length() - 1; i++) {
            char ch = raw.charAt(i);
            if (ch == '\\') {
                ch = raw.charAt(++i);
                if (ch == 'u') { result.append((char)Integer.parseInt(raw.substring(i + 1, i + 5), 16)); i += 4; continue; }
                int special = "bfnrt".indexOf(ch);
                if (special >= 0) ch = "\b\f\n\r\t".charAt(special);
            }
            result.append(ch);
        }
        return result.toString();
    }

    private static String fieldsJson(Map<String, String> fields) {
        StringBuilder result = new StringBuilder("{");
        for (Map.Entry<String, String> field : fields.entrySet()) {
            if (result.length() > 1) result.append(',');
            result.append('"').append(esc(field.getKey())).append("\":").append(field.getValue());
        }
        return result.append('}').toString();
    }

    private static String quoteJson(String text) { return "\"" + esc(text) + "\""; }

    private static long fieldLong(Map<String, String> fields, String key, long fallback) {
        try { return Long.parseLong(fields.get(key)); } catch (Exception invalid) { return fallback; }
    }

    private static boolean protectedStoreField(String key) {
        return key.equals("diamondBalance") || key.equals("paypalBalance") || key.startsWith("vip")
                || key.startsWith("luckyWheel") || key.equals("walletVersion");
    }

    private static String prependJsonArray(String array, String item, int limit) {
        List<String> entries = new ArrayList<>();
        entries.add(item);
        try {
            JsonCursor cursor = new JsonCursor(array == null ? "[]" : array);
            cursor.expect('[');
            if (!cursor.consumeIf(']')) {
                do {
                    cursor.skipWhitespace(); int start = cursor.index; cursor.parseValue();
                    entries.add(cursor.text.substring(start, cursor.index));
                    if (entries.size() >= limit || cursor.consumeIf(']')) break;
                    cursor.expect(',');
                } while (true);
            }
        } catch (IllegalArgumentException ignored) { /* Keep the validated new event. */ }
        return "[" + String.join(",", entries) + "]";
    }

    private void handleWheel(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAuth(ex, true);
        if (su == null) return;
        if (!"POST".equalsIgnoreCase(ex.getRequestMethod())) { sendJson(ex, 405, "{\"ok\":false}"); return; }
        Map<String, String> form = parseForm(ex);
        try {
            sendJson(ex, 200, repo.wheel(su.username, form.get("requestId"), form.get("action"), form.get("count")));
        } catch (IllegalArgumentException invalid) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":" + quoteJson(invalid.getMessage()) + "}");
        }
    }

    private void handleAdminVip(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAdmin(ex);
        if (su == null) return;
        if (!"POST".equalsIgnoreCase(ex.getRequestMethod())) { sendJson(ex, 405, "{\"ok\":false}"); return; }
        Map<String, String> form = parseForm(ex);
        try {
            repo.grantVip(normalizeUser(form.get("username")), form.get("expiresAt"), su.username);
            sendJson(ex, 200, "{\"ok\":true}");
        } catch (IllegalArgumentException invalid) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":" + quoteJson(invalid.getMessage()) + "}");
        }
    }

    private static String normalizeStoredJsonObjectText(String jsonText) {
        String trimmed = nvl(jsonText).trim();
        if (trimmed.isEmpty()) return "{}";
        try {
            return requireValidJsonObjectText(trimmed);
        } catch (IllegalArgumentException ignored) {
        }

        String unescaped = trimmed;
        if (unescaped.startsWith("\"") && unescaped.endsWith("\"") && unescaped.length() >= 2) {
            unescaped = unescaped.substring(1, unescaped.length() - 1);
        }
        unescaped = unescaped
                .replace("\\\"", "\"")
                .replace("\\\\", "\\")
                .replace("\\n", "\n")
                .replace("\\r", "\r")
                .replace("\\t", "\t");
        try {
            return requireValidJsonObjectText(unescaped);
        } catch (IllegalArgumentException ignored) {
        }

        System.err.println("Store JSON không hợp lệ, fallback về {}.");
        return "{}";
    }

    private static List<String> buildPythonCommand(Path scriptFile) {
        List<String> command = new ArrayList<>();
        Path pythonExe = resolvePreferredPythonExecutable();
        if (pythonExe != null) {
            command.add(pythonExe.toString());
        } else {
            command.add("py");
            command.add("-3");
        }
        command.add(scriptFile.toString());
        return command;
    }

    private static Path resolvePreferredPythonExecutable() {
        String localAppData = nvl(System.getenv("LOCALAPPDATA")).trim();
        if (localAppData.isEmpty()) return null;
        String[] versions = {"Python313", "Python312", "Python311", "Python310"};
        for (String version : versions) {
            Path candidate = Paths.get(localAppData, "Programs", "Python", version, "python.exe");
            if (Files.exists(candidate)) return candidate;
        }
        return null;
    }

    // ----- Cầu nối sang Python -----
    // Chạy script Python, chờ timeout, đọc stdout/stderr và trả lỗi chuẩn về cho web.
    private String runPythonJsonCommand(
            HttpExchange ex,
            Path workingDir,
            List<String> command,
            long timeoutSeconds,
            String timeoutMessage,
            String emptyPayloadMessage,
            String defaultErrorMessage,
            String interruptedMessage,
            String ioErrorPrefix,
            String emptyPayloadFallback
    ) throws IOException {
        Process process = null;
        try {
            ProcessBuilder pb = new ProcessBuilder(command);
            pb.directory(workingDir.toFile());
            process = pb.start();

            ProcessOutput output = waitForProcessOutput(process, timeoutSeconds, TimeUnit.SECONDS);
            if (!output.finished) {
                sendJson(ex, 504, "{\"ok\":false,\"message\":\"" + esc(timeoutMessage) + "\"}");
                return null;
            }

            if (output.exitCode != 0) {
                String err = new String(output.stderr, StandardCharsets.UTF_8).trim();
                if (isBlank(err)) err = defaultErrorMessage;
                sendJson(ex, 500, "{\"ok\":false,\"message\":\"" + esc(err) + "\"}");
                return null;
            }

            String payload = new String(output.stdout, StandardCharsets.UTF_8).trim();
            if (isBlank(payload)) {
                if (emptyPayloadFallback != null) return emptyPayloadFallback;
                sendJson(ex, 500, "{\"ok\":false,\"message\":\"" + esc(emptyPayloadMessage) + "\"}");
                return null;
            }
            return payload;
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            sendJson(ex, 500, "{\"ok\":false,\"message\":\"" + esc(interruptedMessage) + "\"}");
            return null;
        } catch (IOException e) {
            sendJson(ex, 500, "{\"ok\":false,\"message\":\"" + esc(ioErrorPrefix + rootCauseMsg(e)) + "\"}");
            return null;
        } finally {
            if (process != null) process.destroy();
        }
    }

    private static ProcessOutput waitForProcessOutput(Process process, long timeout, TimeUnit unit)
            throws IOException, InterruptedException {
        ByteArrayOutputStream stdout = new ByteArrayOutputStream();
        ByteArrayOutputStream stderr = new ByteArrayOutputStream();
        Thread stdoutThread = pumpProcessStream(process.getInputStream(), stdout, "process-stdout");
        Thread stderrThread = pumpProcessStream(process.getErrorStream(), stderr, "process-stderr");

        boolean finished = process.waitFor(timeout, unit);
        if (!finished) {
            process.destroyForcibly();
            process.waitFor(5, TimeUnit.SECONDS);
        }

        joinQuietly(stdoutThread, 5000);
        joinQuietly(stderrThread, 5000);

        int exitCode = finished ? process.exitValue() : -1;
        return new ProcessOutput(finished, exitCode, stdout.toByteArray(), stderr.toByteArray());
    }

    private static Thread pumpProcessStream(InputStream input, ByteArrayOutputStream output, String name) {
        Thread thread = new Thread(() -> {
            try {
                byte[] buffer = new byte[8192];
                int read;
                while ((read = input.read(buffer)) != -1) {
                    output.write(buffer, 0, read);
                }
            } catch (IOException ignored) {
            }
        }, name);
        thread.setDaemon(true);
        thread.start();
        return thread;
    }

    private static void joinQuietly(Thread thread, long timeoutMillis) throws InterruptedException {
        if (thread == null) return;
        thread.join(timeoutMillis);
    }

    private static byte[] readAllBytes(InputStream in) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        int read;
        while ((read = in.read(buffer)) != -1) {
            if (out.size() + read > MAX_REQUEST_BYTES) throw new IOException("Request body limit exceeded");
            out.write(buffer, 0, read);
        }
        return out.toByteArray();
    }

    private String hashPassword(String password, byte[] salt) {
        try {
            PBEKeySpec spec = new PBEKeySpec(password.toCharArray(), salt, 65536, 256);
            SecretKeyFactory skf = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256");
            byte[] hash = skf.generateSecret(spec).getEncoded();
            return Base64.getEncoder().encodeToString(hash);
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

    private boolean verifyPassword(String password, String saltB64, String hashB64) {
        if (password == null || saltB64 == null || hashB64 == null) return false;
        byte[] salt = Base64.getDecoder().decode(saltB64);
        String calc = hashPassword(password, salt);
        return MessageDigest.isEqual(calc.getBytes(StandardCharsets.UTF_8), hashB64.getBytes(StandardCharsets.UTF_8));
    }

    // ----- Repository SQLite -----
    // Lớp thao tác DB cho user/store, khởi tạo schema và các truy vấn quản trị tài khoản.
    private class DatabaseRepo {
        private final String jdbcUrl;

        DatabaseRepo(Path file) {
            this.jdbcUrl = "jdbc:sqlite:" + file.toAbsolutePath();
            ensureDriver();
            initSchema();
        }

        private void ensureDriver() {
            try {
                Class.forName("org.sqlite.JDBC");
            } catch (ClassNotFoundException e) {
                throw new IllegalStateException("Thiếu sqlite-jdbc.jar trong classpath. Hãy thêm driver SQLite để chạy server.", e);
            }
        }

        private Connection conn() throws SQLException {
            Connection c = DriverManager.getConnection(jdbcUrl);
            try (Statement st = c.createStatement()) {
                st.execute("PRAGMA busy_timeout=5000");
            }
            return c;
        }

        private void initSchema() {
            try (Connection c = conn(); Statement st = c.createStatement()) {
                st.execute("CREATE TABLE IF NOT EXISTS users (" +
                        "username TEXT PRIMARY KEY," +
                        "salt TEXT NOT NULL," +
                        "password_hash TEXT NOT NULL," +
                        "role TEXT NOT NULL," +
                        "enabled INTEGER NOT NULL DEFAULT 1" +
                        ")");
                st.execute("CREATE TABLE IF NOT EXISTS stores (" +
                        "username TEXT PRIMARY KEY," +
                        "store_json TEXT NOT NULL DEFAULT '{}'," +
                        "FOREIGN KEY(username) REFERENCES users(username) ON DELETE CASCADE" +
                        ")");
                st.execute("CREATE TABLE IF NOT EXISTS account_entitlements (username TEXT PRIMARY KEY, vip_expires_at TEXT NOT NULL, updated_at TEXT NOT NULL)");
                st.execute("CREATE TABLE IF NOT EXISTS wallet_events (username TEXT NOT NULL, request_id TEXT NOT NULL, action TEXT NOT NULL, response_json TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(username,request_id))");
                st.execute("CREATE TABLE IF NOT EXISTS account_audit (event_id TEXT PRIMARY KEY, actor TEXT NOT NULL, target TEXT NOT NULL, action TEXT NOT NULL, details_json TEXT NOT NULL, created_at TEXT NOT NULL)");
            } catch (SQLException e) {
                throw new RuntimeException("Không thể khởi tạo schema SQLite: " + e.getMessage(), e);
            }
        }

        synchronized Account getUser(String user) {
            try (Connection c = conn();
                 PreparedStatement ps = c.prepareStatement("SELECT username,salt,password_hash,role,enabled FROM users WHERE username=?")) {
                ps.setString(1, user);
                try (ResultSet rs = ps.executeQuery()) {
                    if (!rs.next()) return null;
                    Account a = new Account();
                    a.username = rs.getString("username");
                    a.salt = rs.getString("salt");
                    a.passwordHash = rs.getString("password_hash");
                    a.role = rs.getString("role");
                    a.enabled = rs.getInt("enabled") == 1;
                    return a;
                }
            } catch (SQLException e) {
                throw new RuntimeException(e);
            }
        }

        synchronized void register(String user, String password) {
            if (EFFECTIVENESS_SYSTEM_USER.equals(user)) throw new IllegalStateException("Tên này dành riêng cho tác vụ hệ thống.");
            if (getUser(user) != null) throw new IllegalStateException("Tên đăng nhập đã tồn tại");
            byte[] salt = new byte[16];
            random.nextBytes(salt);
            String saltB64 = Base64.getEncoder().encodeToString(salt);
            String hash = hashPassword(password, salt);
            String role = countUsers() == 0 ? "admin" : "user";
            try (Connection c = conn();
                 PreparedStatement ps = c.prepareStatement("INSERT INTO users(username,salt,password_hash,role,enabled) VALUES(?,?,?,?,1)")) {
                ps.setString(1, user);
                ps.setString(2, saltB64);
                ps.setString(3, hash);
                ps.setString(4, role);
                ps.executeUpdate();
            } catch (SQLException e) {
                throw new RuntimeException(e);
            }
        }

        synchronized String recoverAdmin(String newPass) {
            String admin = firstAdminUser();
            if (admin == null) {
                if (countUsers() == 0) {
                    register("admin", newPass);
                    return "admin";
                }
                admin = firstAnyUser();
            }
            updatePasswordInternal(admin, newPass);
            try (Connection c = conn();
                 PreparedStatement ps = c.prepareStatement("UPDATE users SET role='admin', enabled=1 WHERE username=?")) {
                ps.setString(1, admin);
                ps.executeUpdate();
            } catch (SQLException e) {
                throw new RuntimeException(e);
            }
            return admin;
        }

        synchronized String getStore(String user) {
            try (Connection c = conn();
                 PreparedStatement ps = c.prepareStatement("SELECT store_json FROM stores WHERE username=?")) {
                ps.setString(1, user);
                try (ResultSet rs = ps.executeQuery()) {
                    if (rs.next()) {
                        String raw = rs.getString(1);
                        String normalized = normalizeStoredJsonObjectText(raw);
                        if (!normalized.equals(nvl(raw).trim())) {
                            try {
                                setStore(user, normalized);
                            } catch (RuntimeException ignored) {
                            }
                        }
                        return normalized;
                    }
                }
            } catch (SQLException e) {
                throw new RuntimeException(e);
            }
            return "{}";
        }

        synchronized void setStore(String user, String storeJson) {
            try (Connection c = conn()) {
                try (PreparedStatement up = c.prepareStatement("UPDATE stores SET store_json=? WHERE username=?")) {
                    up.setString(1, storeJson);
                    up.setString(2, user);
                    int affected = up.executeUpdate();
                    if (affected == 0) {
                        try (PreparedStatement ins = c.prepareStatement("INSERT INTO stores(username,store_json) VALUES(?,?)")) {
                            ins.setString(1, user);
                            ins.setString(2, storeJson);
                            ins.executeUpdate();
                        }
                    }
                }
            } catch (SQLException e) {
                throw new RuntimeException("Không thể lưu store cho tài khoản " + user, e);
            }
        }

        synchronized String publicStore(String user) {
            Map<String, String> fields = jsonFields(getStore(user));
            fields.put("vipExpiresAt", quoteJson(vipExpiry(user)));
            return fieldsJson(fields);
        }

        synchronized String publicWallet(String user) {
            Map<String, String> fields = jsonFields(publicStore(user));
            fields.keySet().removeIf(key -> !protectedStoreField(key));
            return fieldsJson(fields);
        }

        synchronized void setClientStore(String user, String json) {
            Map<String, String> oldFields = jsonFields(getStore(user));
            Map<String, String> fields = jsonFields(json);
            fields.keySet().removeIf(LottoWebServer::protectedStoreField);
            for (Map.Entry<String, String> entry : oldFields.entrySet())
                if (protectedStoreField(entry.getKey())) fields.put(entry.getKey(), entry.getValue());
            fields.putIfAbsent("diamondBalance", "0");
            fields.putIfAbsent("paypalBalance", "0");
            fields.putIfAbsent("luckyWheelStoredSpins", "60");
            fields.putIfAbsent("luckyWheelLastRegenAt", quoteJson(Instant.now().toString()));
            setStore(user, fieldsJson(fields));
        }

        private String vipExpiry(String user) {
            try (Connection c = conn(); PreparedStatement ps = c.prepareStatement("SELECT vip_expires_at FROM account_entitlements WHERE username=?")) {
                ps.setString(1, user);
                try (ResultSet rs = ps.executeQuery()) { return rs.next() ? rs.getString(1) : ""; }
            } catch (SQLException failure) { throw new RuntimeException(failure); }
        }

        synchronized boolean hasVip(String user) {
            try { return Instant.parse(vipExpiry(user)).isAfter(Instant.now()); }
            catch (DateTimeParseException invalid) { return false; }
        }

        private void auditAccount(Connection c, String actor, String target, String action, String details) throws SQLException {
            try (PreparedStatement ps = c.prepareStatement("INSERT INTO account_audit VALUES(?,?,?,?,?,?)")) {
                ps.setString(1, UUID.randomUUID().toString()); ps.setString(2, actor); ps.setString(3, target);
                ps.setString(4, action); ps.setString(5, details); ps.setString(6, Instant.now().toString()); ps.executeUpdate();
            }
        }

        synchronized void grantVip(String user, String expiry, String actor) {
            if (getUser(user) == null) throw new IllegalArgumentException("Không tìm thấy tài khoản");
            String normalized;
            try { normalized = Instant.parse(nvl(expiry)).toString(); }
            catch (DateTimeParseException invalid) { throw new IllegalArgumentException("Hạn VIP cần ISO UTC hợp lệ"); }
            try (Connection c = conn(); PreparedStatement ps = c.prepareStatement("INSERT OR REPLACE INTO account_entitlements VALUES(?,?,?)")) {
                c.setAutoCommit(false);
                ps.setString(1, user); ps.setString(2, normalized); ps.setString(3, Instant.now().toString()); ps.executeUpdate();
                auditAccount(c, actor, user, "grant_vip", "{\"expiresAt\":" + quoteJson(normalized) + "}");
                c.commit();
            } catch (SQLException failure) { throw new RuntimeException(failure); }
        }

        synchronized String wheel(String user, String requestId, String action, String countText) {
            if (requestId == null || !requestId.matches("[a-zA-Z0-9_-]{16,64}")) throw new IllegalArgumentException("Mã giao dịch không hợp lệ");
            int count;
            try { count = Integer.parseInt(countText); } catch (Exception invalid) { throw new IllegalArgumentException("Số lượt không hợp lệ"); }
            if (!"spin".equals(action) && !"exchange".equals(action) && !"clear".equals(action)) throw new IllegalArgumentException("Thao tác không hợp lệ");
            if (count < 1 || count > ("spin".equals(action) ? 60 : 50)) throw new IllegalArgumentException("Số lượt ngoài giới hạn");
            try (Connection c = conn()) {
                c.setAutoCommit(false);
                try {
                    try (PreparedStatement ps = c.prepareStatement("SELECT action,response_json FROM wallet_events WHERE username=? AND request_id=?")) {
                        ps.setString(1, user); ps.setString(2, requestId);
                        try (ResultSet rs = ps.executeQuery()) {
                            if (rs.next()) {
                                if (!rs.getString(1).equals(action + ":" + count)) throw new IllegalArgumentException("Mã giao dịch đã dùng cho thao tác khác");
                                return rs.getString(2);
                            }
                        }
                    }
                    Map<String, String> fields;
                    try (PreparedStatement ps = c.prepareStatement("SELECT store_json FROM stores WHERE username=?")) {
                        ps.setString(1, user);
                        try (ResultSet rs = ps.executeQuery()) { fields = jsonFields(rs.next() ? rs.getString(1) : "{}"); }
                    }
                    long now = System.currentTimeMillis();
                    String today = LocalDate.now(ZoneId.of("Asia/Ho_Chi_Minh")).toString();
                    long regen;
                    try { regen = Instant.parse(jsonString(fields.get("luckyWheelLastRegenAt"))).toEpochMilli(); }
                    catch (Exception invalid) { regen = now; }
                    regen = Math.min(now, regen);
                    long spins = Math.max(0, Math.min(60, fieldLong(fields, "luckyWheelStoredSpins", 60)));
                    long gained = (now - regen) / 600000;
                    spins = Math.min(60, spins + gained);
                    regen = spins == 60 ? now : regen + gained * 600000;
                    long paypal = Math.max(0, fieldLong(fields, "paypalBalance", 0));
                    long diamond = Math.max(0, fieldLong(fields, "diamondBalance", 0));
                    long exchanged = today.equals(jsonString(fields.get("luckyWheelExchangeDayKey"))) ? fieldLong(fields, "luckyWheelDailyExchangeSpins", 0) : 0;
                    long dailySpins = today.equals(jsonString(fields.get("luckyWheelMilestoneDayKey"))) ? fieldLong(fields, "luckyWheelDailySpinCount", 0) : 0;
                    int index = -1;
                    if ("exchange".equals(action)) {
                        long cost = count * 2000L;
                        if (paypal < cost || spins + count > 60 || exchanged + count > 1000) throw new IllegalArgumentException("Không đủ điểm, kho lượt hoặc giới hạn ngày");
                        paypal -= cost; spins += count; exchanged += count;
                    } else if ("spin".equals(action)) {
                        if (spins < count) throw new IllegalArgumentException("Không đủ lượt quay");
                        double[] weights = {28,10,5,1,.3,.4,5,45,.3,10};
                        int[] diamonds = {5,0,0,100,0,0,0,0,1000,10};
                        int[] paypals = {100,0,0,0,0,10000,1000,500,0,0};
                        int[] bonuses = {0,1,3,0,50,0,0,0,0,0};
                        double total = 0; for (double weight : weights) total += weight;
                        double pick = random.nextDouble() * total;
                        index = weights.length - 1;
                        for (int i = 0; i < weights.length; i++) { pick -= weights[i]; if (pick < 0) { index = i; break; } }
                        spins = Math.min(60, spins - count + bonuses[index] * count);
                        paypal += paypals[index] * count; diamond += diamonds[index] * count;
                        fields.put("luckyWheelSpinCount", Long.toString(fieldLong(fields, "luckyWheelSpinCount", 0) + count));
                        dailySpins += count;
                        String[] labels = {"5 Kim cương + 100 PayPal", "Thêm 1 lượt", "Thêm 3 lượt", "+100 Kim cương", "Thêm 50 lượt", "+10.000 PayPal", "+1.000 PayPal", "+500 PayPal", "+1.000 Kim cương", "+10 Kim cương"};
                        String rewardText = diamonds[index] * count + " KC + " + paypals[index] * count + " PP + " + bonuses[index] * count + " lượt";
                        String entry = "{\"at\":" + quoteJson(Instant.now().toString()) + ",\"label\":" + quoteJson(labels[index])
                                + ",\"rewardText\":" + quoteJson(rewardText) + ",\"multiplier\":" + count
                                + ",\"source\":\"stored\",\"timeText\":" + quoteJson(LocalDateTime.now(ZoneId.of("Asia/Ho_Chi_Minh")).toString())
                                + ",\"reward\":{\"diamond\":" + diamonds[index] * count + ",\"paypal\":" + paypals[index] * count + ",\"bonusSpins\":" + bonuses[index] * count + "}}";
                        fields.put("luckyWheelLastResult", entry);
                        fields.put("luckyWheelHistory", prependJsonArray(fields.get("luckyWheelHistory"), entry, 30));
                    } else {
                        fields.put("luckyWheelHistory", "[]"); fields.put("luckyWheelLastResult", "null");
                    }
                    fields.put("paypalBalance", Long.toString(paypal)); fields.put("diamondBalance", Long.toString(diamond));
                    fields.put("luckyWheelStoredSpins", Long.toString(spins));
                    fields.put("luckyWheelLastRegenAt", quoteJson(Instant.ofEpochMilli(spins == 60 ? now : regen).toString()));
                    fields.put("luckyWheelExchangeDayKey", quoteJson(today)); fields.put("luckyWheelDailyExchangeSpins", Long.toString(exchanged));
                    fields.put("luckyWheelMilestoneDayKey", quoteJson(today)); fields.put("luckyWheelDailySpinCount", Long.toString(dailySpins));
                    fields.put("walletVersion", Long.toString(fieldLong(fields, "walletVersion", 0) + 1));
                    if ("exchange".equals(action)) {
                        String entry = "{\"at\":" + quoteJson(Instant.now().toString()) + ",\"spins\":" + count + ",\"paypalCost\":" + count * 2000L + ",\"afterStoredSpins\":" + spins
                                + ",\"timeText\":" + quoteJson(LocalDateTime.now(ZoneId.of("Asia/Ho_Chi_Minh")).toString()) + "}";
                        fields.put("luckyWheelTopupHistory", prependJsonArray(fields.get("luckyWheelTopupHistory"), entry, 12));
                    }
                    String saved = fieldsJson(fields);
                    Map<String, String> wallet = new LinkedHashMap<>(fields);
                    wallet.keySet().removeIf(key -> !protectedStoreField(key));
                    wallet.put("vipExpiresAt", quoteJson(vipExpiry(user)));
                    String response = "{\"ok\":true,\"segmentIndex\":" + index + ",\"store\":" + fieldsJson(wallet) + "}";
                    try (PreparedStatement ps = c.prepareStatement("INSERT OR REPLACE INTO stores(username,store_json) VALUES(?,?)")) {
                        ps.setString(1, user); ps.setString(2, saved); ps.executeUpdate();
                    }
                    try (PreparedStatement ps = c.prepareStatement("INSERT INTO wallet_events VALUES(?,?,?,?,?)")) {
                        ps.setString(1, user); ps.setString(2, requestId); ps.setString(3, action + ":" + count);
                        ps.setString(4, response); ps.setString(5, Instant.now().toString()); ps.executeUpdate();
                    }
                    c.commit(); return response;
                } catch (Exception failure) { c.rollback(); throw failure; }
            } catch (SQLException failure) { throw new RuntimeException(failure); }
        }

        synchronized void updateAssets(String user, int diamond, int paypal, String actor) {
            if (getUser(user) == null) throw new IllegalStateException("Không tìm thấy tài khoản");
            String store = getStore(user);
            if (store == null || isBlank(store)) store = "{}";
            Map<String, String> fields = jsonFields(store);
            fields.put("diamondBalance", Integer.toString(Math.max(0, diamond)));
            fields.put("paypalBalance", Integer.toString(Math.max(0, paypal)));
            fields.put("walletVersion", Long.toString(fieldLong(fields, "walletVersion", 0) + 1));
            try (Connection c = conn(); PreparedStatement ps = c.prepareStatement("INSERT OR REPLACE INTO stores(username,store_json) VALUES(?,?)")) {
                c.setAutoCommit(false);
                ps.setString(1, user); ps.setString(2, fieldsJson(fields)); ps.executeUpdate();
                auditAccount(c, actor, user, "update_assets", "{\"diamond\":" + diamond + ",\"paypal\":" + paypal + "}");
                c.commit();
            } catch (SQLException failure) { throw new RuntimeException(failure); }
        }

        private String upsertJsonNumber(String json, String key, int value) {
            String trimmed = (json == null || isBlank(json)) ? "{}" : json.trim();
            if (!trimmed.startsWith("{") || !trimmed.endsWith("}")) trimmed = "{}";
            String pairRegex = "\\\"" + key + "\\\"\\s*:\\s*-?\\d+";
            String replacement = "\\\"" + key + "\\\":" + value;
            java.util.regex.Pattern p = java.util.regex.Pattern.compile(pairRegex);
            java.util.regex.Matcher m = p.matcher(trimmed);
            if (m.find()) {
                return m.replaceFirst(replacement);
            }
            String body = trimmed.substring(1, trimmed.length() - 1).trim();
            if (body.isEmpty()) return "{" + replacement + "}";
            return "{" + body + "," + replacement + "}";
        }

        synchronized List<UserView> listUsers() {
            List<UserView> out = new ArrayList<>();
            String sql = "SELECT u.username,u.role,u.enabled,COALESCE(s.store_json,'{}') store_json " +
                    "FROM users u LEFT JOIN stores s ON s.username=u.username ORDER BY u.username";
            try (Connection c = conn();
                 PreparedStatement ps = c.prepareStatement(sql);
                 ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    UserView uv = new UserView();
                    uv.username = rs.getString("username");
                    uv.role = rs.getString("role");
                    uv.enabled = rs.getInt("enabled") == 1;
                    String sj = rs.getString("store_json");
                    uv.hasData = sj != null && !isBlank(sj) && !"{}".equals(sj.trim());
                    uv.diamondBalance = readIntFromJson(sj, "diamondBalance");
                    uv.paypalBalance = readIntFromJson(sj, "paypalBalance");
                    out.add(uv);
                }
            } catch (SQLException e) {
                throw new RuntimeException(e);
            }
            return out;
        }

        private int readIntFromJson(String json, String key) {
            try {
                return (int)Math.max(0, Math.min(Integer.MAX_VALUE, fieldLong(jsonFields(json), key, 0)));
            } catch (IllegalArgumentException ex) {
                return 0;
            }
        }

        synchronized void updateUser(String user, String role, boolean enabled, String currentUser) {
            Account a = getUser(user);
            if (a == null) throw new IllegalStateException("Không tìm thấy tài khoản");
            if (user.equals(currentUser) && !enabled) throw new IllegalStateException("Không thể khóa tài khoản đang đăng nhập");
            int adminCount = countAdminUsers();
            if ("admin".equals(a.role) && !"admin".equals(role) && adminCount <= 1) {
                throw new IllegalStateException("Phải luôn có ít nhất 1 admin");
            }
            if ("admin".equals(a.role) && !enabled && adminCount <= 1) {
                throw new IllegalStateException("Không thể khóa admin cuối cùng");
            }
            try (Connection c = conn();
                 PreparedStatement ps = c.prepareStatement("UPDATE users SET role=?, enabled=? WHERE username=?")) {
                ps.setString(1, role);
                ps.setInt(2, enabled ? 1 : 0);
                ps.setString(3, user);
                ps.executeUpdate();
            } catch (SQLException e) {
                throw new RuntimeException(e);
            }
        }

        synchronized void renameUser(String user, String newUser) {
            if (EFFECTIVENESS_SYSTEM_USER.equals(newUser)) throw new IllegalStateException("Tên này dành riêng cho tác vụ hệ thống.");
            if (newUser.length() < 3) throw new IllegalStateException("Tên mới tối thiểu 3 ký tự");
            if (getUser(user) == null) throw new IllegalStateException("Không tìm thấy tài khoản");
            if (getUser(newUser) != null) throw new IllegalStateException("Tên tài khoản mới đã tồn tại");
            try (Connection c = conn()) {
                boolean originalAutoCommit = c.getAutoCommit();
                c.setAutoCommit(false);
                try (PreparedStatement p1 = c.prepareStatement("UPDATE users SET username=? WHERE username=?");
                     PreparedStatement p2 = c.prepareStatement("UPDATE stores SET username=? WHERE username=?")) {
                    p1.setString(1, newUser);
                    p1.setString(2, user);
                    p1.executeUpdate();
                    p2.setString(1, newUser);
                    p2.setString(2, user);
                    p2.executeUpdate();
                    for (String table : Arrays.asList("account_entitlements", "wallet_events")) {
                        try (PreparedStatement linked = c.prepareStatement("UPDATE " + table + " SET username=? WHERE username=?")) {
                            linked.setString(1, newUser); linked.setString(2, user); linked.executeUpdate();
                        }
                    }
                    c.commit();
                } catch (SQLException e) {
                    try {
                        c.rollback();
                    } catch (SQLException rollbackError) {
                        e.addSuppressed(rollbackError);
                    }
                    throw e;
                } finally {
                    try {
                        c.setAutoCommit(originalAutoCommit);
                    } catch (SQLException ignored) {
                    }
                }
            } catch (SQLException e) {
                throw new RuntimeException(e);
            }
        }

        synchronized void resetPassword(String user, String pass) {
            if (pass.length() < 4) throw new IllegalStateException("Mật khẩu tối thiểu 4 ký tự");
            if (getUser(user) == null) throw new IllegalStateException("Không tìm thấy tài khoản");
            updatePasswordInternal(user, pass);
        }

        synchronized void deleteUser(String user, String currentUser) {
            if (user.equals(currentUser)) throw new IllegalStateException("Không thể xóa tài khoản đang đăng nhập");
            Account a = getUser(user);
            if (a == null) throw new IllegalStateException("Không tìm thấy tài khoản");
            int adminCount = countAdminUsers();
            if ("admin".equals(a.role) && adminCount <= 1) throw new IllegalStateException("Không thể xóa admin cuối cùng");
            try (Connection c = conn();
                 PreparedStatement p1 = c.prepareStatement("DELETE FROM stores WHERE username=?");
                 PreparedStatement p2 = c.prepareStatement("DELETE FROM users WHERE username=?")) {
                c.setAutoCommit(false);
                for (String table : Arrays.asList("account_entitlements", "wallet_events")) {
                    try (PreparedStatement linked = c.prepareStatement("DELETE FROM " + table + " WHERE username=?")) {
                        linked.setString(1, user); linked.executeUpdate();
                    }
                }
                p1.setString(1, user);
                p1.executeUpdate();
                p2.setString(1, user);
                p2.executeUpdate();
                c.commit();
            } catch (SQLException e) {
                throw new RuntimeException(e);
            }
        }

        private void updatePasswordInternal(String user, String pass) {
            byte[] salt = new byte[16];
            random.nextBytes(salt);
            String saltB64 = Base64.getEncoder().encodeToString(salt);
            String hash = hashPassword(pass, salt);
            try (Connection c = conn();
                 PreparedStatement ps = c.prepareStatement("UPDATE users SET salt=?, password_hash=? WHERE username=?")) {
                ps.setString(1, saltB64);
                ps.setString(2, hash);
                ps.setString(3, user);
                ps.executeUpdate();
            } catch (SQLException e) {
                throw new RuntimeException(e);
            }
        }

        private int countUsers() {
            try (Connection c = conn();
                 PreparedStatement ps = c.prepareStatement("SELECT COUNT(*) FROM users");
                 ResultSet rs = ps.executeQuery()) {
                return rs.next() ? rs.getInt(1) : 0;
            } catch (SQLException e) {
                throw new RuntimeException(e);
            }
        }

        private int countAdminUsers() {
            try (Connection c = conn();
                 PreparedStatement ps = c.prepareStatement("SELECT COUNT(*) FROM users WHERE role='admin'");
                 ResultSet rs = ps.executeQuery()) {
                return rs.next() ? rs.getInt(1) : 0;
            } catch (SQLException e) {
                throw new RuntimeException(e);
            }
        }

        private String firstAnyUser() {
            try (Connection c = conn();
                 PreparedStatement ps = c.prepareStatement("SELECT username FROM users ORDER BY username LIMIT 1");
                 ResultSet rs = ps.executeQuery()) {
                return rs.next() ? rs.getString(1) : null;
            } catch (SQLException e) {
                throw new RuntimeException(e);
            }
        }

        private String firstAdminUser() {
            try (Connection c = conn();
                 PreparedStatement ps = c.prepareStatement("SELECT username FROM users WHERE role='admin' ORDER BY username LIMIT 1");
                 ResultSet rs = ps.executeQuery()) {
                return rs.next() ? rs.getString(1) : null;
            } catch (SQLException e) {
                throw new RuntimeException(e);
            }
        }
    }

    static class SessionUser {
        String username;
        Account account;

        SessionUser(String username, Account account) {
            this.username = username;
            this.account = account;
        }
    }

    static class UserView {
        String username;
        String role;
        boolean enabled;
        boolean hasData;
        int diamondBalance;
        int paypalBalance;
    }

    static class Account {
        String username;
        String salt;
        String passwordHash;
        String role;
        boolean enabled;
    }
}
