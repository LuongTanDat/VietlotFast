import com.sun.net.httpserver.Headers;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import com.sun.net.httpserver.HttpServer;

import java.io.*;
import java.math.BigInteger;
import java.net.InetSocketAddress;
import java.net.URLDecoder;
import java.net.URL;
import java.net.URLEncoder;
import java.net.HttpURLConnection;
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
import java.time.OffsetDateTime;
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
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
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
    private final Map<String, SocialAttempt> socialAttempts = new ConcurrentHashMap<>();
    private final Map<String, String> sessions = new ConcurrentHashMap<>();
    private final Map<String, Long> sessionExpiry = new ConcurrentHashMap<>();
    private final Map<String, String> sessionPasswordHash = new ConcurrentHashMap<>();
    private final Map<String, long[]> loginAttempts = new ConcurrentHashMap<>();
    private final Map<String, long[]> codeAttempts = new ConcurrentHashMap<>();
    private static final int MAX_REQUEST_BYTES = 8 * 1024 * 1024;
    private static final long SESSION_TTL_MS = 12 * 60 * 60 * 1000L;
    private final Map<Path, StaticAsset> staticAssetCache = new ConcurrentHashMap<>();
    private final Map<String, TimedJsonPayload> heavyApiCache = new ConcurrentHashMap<>();
    private final SecureRandom random = new SecureRandom();
    private final AtomicBoolean effectivenessJobRunning = new AtomicBoolean();
    private final AtomicBoolean algorithmLabRunning = new AtomicBoolean();
    private final AtomicBoolean algorithmLabTrackingActionRunning = new AtomicBoolean();
    private final Map<String, AlgorithmLabJob> algorithmLabJobs = new ConcurrentHashMap<>();

    private static final class AlgorithmLabJob {
        final String id = UUID.randomUUID().toString();
        final String owner, type;
        final int ticketCount, validationCount, testCount;
        final Instant createdAt = Instant.now();
        String state = "running", finishedAt = "", report = "null", error = "";
        int completedFolds;
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
                    + ",\"progress\":{\"completed\":" + completedFolds + ",\"total\":" + (validationCount + testCount) + "}"
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

    private static final class LimitedProcessOutput extends OutputStream {
        private final ByteArrayOutputStream buffer = new ByteArrayOutputStream();
        private final int limit;
        private final Process process;
        volatile boolean exceeded;

        LimitedProcessOutput(int limit, Process process) { this.limit = limit; this.process = process; }

        @Override public synchronized void write(int value) { write(new byte[] {(byte)value}, 0, 1); }
        @Override public synchronized void write(byte[] bytes, int offset, int length) {
            int available = limit - buffer.size();
            if (available > 0) buffer.write(bytes, offset, Math.min(available, length));
            if (length > available && !exceeded) { exceeded = true; process.destroyForcibly(); }
        }
        synchronized byte[] bytes() { return buffer.toByteArray(); }
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
        Map<String, Long> prizeWinnerCounts = new LinkedHashMap<>();
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

        Map<String, String> readObjectMembers() {
            Map<String, String> members = new LinkedHashMap<>();
            expect('{');
            if (consumeIf('}')) return members;
            while (true) {
                skipWhitespace();
                int keyStart = index;
                parseString();
                String key = text.substring(keyStart + 1, index - 1);
                expect(':');
                skipWhitespace();
                int valueStart = index;
                parseValue();
                if (members.put(key, text.substring(valueStart, index)) != null) {
                    throw new IllegalArgumentException("Metadata chứa khóa trùng.");
                }
                if (consumeIf('}')) return members;
                expect(',');
            }
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
        server.createContext("/vietlott-web-numeric.js", ex -> serveStaticTextFile(ex, rootDir.resolve("frontend/vietlott-web-numeric.js"), "application/javascript; charset=UTF-8"));
        server.createContext("/vietlott-web-music.js", ex -> serveStaticTextFile(ex, rootDir.resolve("frontend/vietlott-web-music.js"), "application/javascript; charset=UTF-8"));
        server.createContext("/vietlott-web-admin.js", ex -> serveStaticTextFile(ex, rootDir.resolve("frontend/vietlott-web-admin.js"), "application/javascript; charset=UTF-8"));
        server.createContext("/vietlott-web-admin.css", ex -> serveStaticTextFile(ex, rootDir.resolve("frontend/vietlott-web-admin.css"), "text/css; charset=UTF-8"));
        server.createContext("/Music_V1.mp3", this::serveBackgroundMusic);
        server.createContext("/favicon.svg", this::serveFavicon);
        server.createContext("/api/me", this::handleMe);
        server.createContext("/api/register", this::handleRegister);
        server.createContext("/api/login", this::handleLogin);
        server.createContext("/api/auth/social/providers", this::handleSocialProviders);
        server.createContext("/api/auth/social/start", this::handleSocialStart);
        server.createContext("/api/auth/social/callback/", this::handleSocialCallback);
        server.createContext("/vietlott-web-auth.css", ex -> serveStaticTextFile(ex, rootDir.resolve("frontend/vietlott-web-auth.css"), "text/css; charset=UTF-8"));
        server.createContext("/vietlott-web-auth.js", ex -> serveStaticTextFile(ex, rootDir.resolve("frontend/vietlott-web-auth.js"), "application/javascript; charset=UTF-8"));
        server.createContext("/auth-google-logo.png", ex -> serveStaticTextFile(ex, rootDir.resolve("frontend/auth-google-logo.png"), "image/png"));
        server.createContext("/api/logout", this::handleLogout);
        server.createContext("/api/store", this::handleStore);
        server.createContext("/api/payments/vnpay", this::handleVnpay);
        server.createContext("/vietlott-web-payments.js", ex -> serveStaticTextFile(ex, rootDir.resolve("frontend/vietlott-web-payments.js"), "application/javascript; charset=UTF-8"));
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
        server.createContext("/api/ml/effectiveness-progress", this::handleMlEffectivenessProgress);
        server.createContext("/api/ml/effectiveness-settings", this::handleMlEffectivenessSettings);
        server.createContext("/api/ml/effectiveness-cycle", this::handleMlEffectivenessCycle);
        server.createContext("/api/ml/effectiveness-tickets", this::handleMlEffectivenessTickets);
        server.createContext("/api/ml/effectiveness-export", this::handleMlEffectivenessExport);
        server.createContext("/api/ml/algorithm-lab", this::handleAlgorithmLab);
        server.createContext("/api/live-results", this::handleLiveResults);
        server.createContext("/api/live-results-start", this::handleLiveResultsStart);
        server.createContext("/api/live-results-progress", this::handleLiveResultsProgress);
        server.createContext("/api/live-history", this::handleLiveHistory);
        server.createContext("/api/recover-admin", this::handleRecoverAdmin);
        server.createContext("/api/admin/users", this::handleAdminUsers);
        server.createContext("/api/admin/update-user", this::handleAdminUpdateUser);
        server.createContext("/api/admin/update-assets", this::handleAdminUpdateAssets);
        server.createContext("/api/admin/gift-codes", this::handleAdminGiftCodes);
        server.createContext("/api/gift-codes/redeem", this::handleRedeemGiftCode);
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
                && !"/admin".equals(path)
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

    private void serveBackgroundMusic(HttpExchange ex) throws IOException {
        if (!"/Music_V1.mp3".equals(ex.getRequestURI().getPath())) { sendNotFound(ex); return; }
        if (!isGetOrHead(ex)) { sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}"); return; }
        Path file = rootDir.resolve("frontend/Music_V1.mp3");
        if (!Files.isRegularFile(file)) { sendNotFound(ex); return; }
        StaticAsset asset = loadStaticAsset(file);
        Headers h = ex.getResponseHeaders();
        h.set("Content-Type", "audio/mpeg");
        h.set("Accept-Ranges", "bytes");
        h.set("Cache-Control", "private, max-age=86400, must-revalidate");
        h.set("ETag", asset.etag);
        if (asset.etag.equals(ex.getRequestHeaders().getFirst("If-None-Match"))) {
            ex.sendResponseHeaders(304, -1); ex.close(); return;
        }
        int start = 0, end = asset.raw.length - 1, code = 200;
        String range = ex.getRequestHeaders().getFirst("Range");
        String ifRange = ex.getRequestHeaders().getFirst("If-Range");
        if (range != null && (ifRange == null || ifRange.equals(asset.etag))) {
            try {
                if (!range.matches("bytes=\\d*-\\d*")) throw new IllegalArgumentException();
                String[] bounds = range.substring(6).split("-", -1);
                if (bounds[0].isEmpty()) {
                    long suffix = Long.parseLong(bounds[1]);
                    if (suffix <= 0) throw new IllegalArgumentException();
                    start = (int) Math.max(0L, asset.raw.length - suffix);
                } else {
                    long first = Long.parseLong(bounds[0]);
                    if (first >= asset.raw.length) throw new IllegalArgumentException();
                    start = (int) first;
                    if (!bounds[1].isEmpty()) end = (int) Math.min((long) end, Long.parseLong(bounds[1]));
                    if (end < start) throw new IllegalArgumentException();
                }
                code = 206;
                h.set("Content-Range", "bytes " + start + "-" + end + "/" + asset.raw.length);
            } catch (IllegalArgumentException error) {
                h.set("Content-Range", "bytes */" + asset.raw.length);
                ex.sendResponseHeaders(416, -1); ex.close(); return;
            }
        }
        int length = end - start + 1;
        h.set("Content-Length", String.valueOf(length));
        if ("HEAD".equalsIgnoreCase(ex.getRequestMethod())) { ex.sendResponseHeaders(code, -1); ex.close(); return; }
        ex.sendResponseHeaders(code, length);
        try (OutputStream out = ex.getResponseBody()) { out.write(asset.raw, start, length); }
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

    // OAuth secrets stay on the server; endpoints never come from request parameters.
    private Properties readSocialSettings() {
        Properties settings = new Properties();
        Path file = rootDir.resolve("runtime/social-login.properties");
        if (Files.isRegularFile(file)) {
            try (Reader reader = Files.newBufferedReader(file, StandardCharsets.UTF_8)) { settings.load(reader); }
            catch (IOException invalid) { return new Properties(); }
        }
        return settings;
    }
    private String socialSetting(Properties settings, String key, String env) {
        String value = System.getenv(env);
        return nvl(isBlank(value) ? settings.getProperty(key) : value).trim();
    }
    private String socialPublicBase(Properties settings) {
        String value = socialSetting(settings,"publicBaseUrl","LOTTO_PUBLIC_BASE_URL");
        try {
            java.net.URI uri = java.net.URI.create(value);
            String host = uri.getHost(), path = uri.getPath();
            boolean local = "localhost".equals(host) || "127.0.0.1".equals(host);
            if (host == null || uri.getRawUserInfo() != null || uri.getRawQuery() != null || uri.getRawFragment() != null || !(isBlank(path) || "/".equals(path))) return "";
            if (!"https".equals(uri.getScheme()) && !(local && "http".equals(uri.getScheme()))) return "";
            return value.endsWith("/") ? value.substring(0,value.length()-1) : value;
        } catch (IllegalArgumentException invalid) { return ""; }
    }
    private static class SocialProvider {
        String name,id,secret,base,version;
        boolean enabled() { return !isBlank(id) && !isBlank(secret) && !isBlank(base) && (!"facebook".equals(name) || version.matches("v[0-9]+[.][0-9]+")); }
        String callback() { return base+"/api/auth/social/callback/"+name; }
    }
    private static class SocialAttempt {
        SocialProvider provider; String browser,verifier; long expires;
    }
    private SocialProvider socialProvider(String name) {
        if (!Arrays.asList("google","facebook","zalo").contains(name)) return null;
        Properties settings = readSocialSettings();
        SocialProvider p = new SocialProvider(); p.name=name; p.base=socialPublicBase(settings);
        String prefix="LOTTO_OAUTH_"+name.toUpperCase(Locale.ROOT);
        p.id=socialSetting(settings,name+".clientId",prefix+"_CLIENT_ID");
        p.secret=socialSetting(settings,name+".clientSecret",prefix+"_CLIENT_SECRET");
        p.version=socialSetting(settings,"facebook.graphVersion","LOTTO_OAUTH_FACEBOOK_GRAPH_VERSION");
        return p;
    }
    private String socialRandom() { byte[] bytes=new byte[32];random.nextBytes(bytes);return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes); }
    private String socialEncode(Map<String,String> fields) {
        StringBuilder text=new StringBuilder();
        try {
            for (Map.Entry<String,String> e:fields.entrySet()) {
                if (text.length()>0) text.append('&');
                text.append(URLEncoder.encode(e.getKey(),"UTF-8")).append('=').append(URLEncoder.encode(e.getValue(),"UTF-8"));
            }
        } catch (UnsupportedEncodingException impossible) { throw new IllegalStateException("UTF-8 unavailable"); }
        return text.toString();
    }
    private void socialCookie(HttpExchange ex, String browser, boolean clear, boolean secure) {
        ex.getResponseHeaders().add("Set-Cookie","LOTTO_OAUTH="+browser+"; Path=/api/auth/social/; HttpOnly; SameSite=Lax; Max-Age="+(clear?0:600)+(secure?"; Secure":""));
    }
    private void socialRedirect(HttpExchange ex, String error) throws IOException {
        ex.getResponseHeaders().set("Location",isBlank(error)?"/":"/?auth_error="+error);
        ex.getResponseHeaders().set("Cache-Control","no-store");ex.getResponseHeaders().set("Referrer-Policy","no-referrer");
        ex.sendResponseHeaders(303,-1);ex.close();
    }
    private void handleSocialProviders(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        if (!"GET".equals(ex.getRequestMethod()) || !"/api/auth/social/providers".equals(ex.getRequestURI().getPath())) { sendNotFound(ex);return; }
        StringBuilder result=new StringBuilder("{\"ok\":true,\"providers\":{");
        for (String name:Arrays.asList("google","facebook","zalo")) {
            if (result.length()>24) result.append(',');
            result.append(quoteJson(name)).append(":{\"enabled\":").append(socialProvider(name).enabled()).append('}');
        }
        ex.getResponseHeaders().set("Cache-Control","no-store");sendJson(ex,200,result.append("}}").toString());
    }
    private void handleSocialStart(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        if (!"POST".equals(ex.getRequestMethod()) || !"/api/auth/social/start".equals(ex.getRequestURI().getPath())) { sendJson(ex,405,"{\"ok\":false}");return; }
        SocialProvider p=socialProvider(nvl(parseForm(ex).get("provider")));
        if (p==null) { sendJson(ex,400,"{\"ok\":false,\"message\":\"Phương thức đăng nhập không hợp lệ.\"}");return; }
        if (!p.enabled()) { sendJson(ex,503,"{\"ok\":false,\"message\":\"Đăng nhập mạng xã hội chưa được kích hoạt.\"}");return; }
        long now=System.currentTimeMillis();socialAttempts.entrySet().removeIf(e->e.getValue().expires<now);
        if (socialAttempts.size()>=1024) { sendJson(ex,429,"{\"ok\":false,\"message\":\"Hãy thử lại sau.\"}");return; }
        SocialAttempt attempt=new SocialAttempt();attempt.provider=p;attempt.browser=socialRandom();attempt.verifier=socialRandom();attempt.expires=now+600000;
        String state=socialRandom();socialAttempts.put(state,attempt);
        Map<String,String> params=new LinkedHashMap<>();params.put("state",state);params.put("redirect_uri",p.callback());
        String destination;
        if ("zalo".equals(p.name)) { params.put("app_id",p.id);destination="https://oauth.zaloapp.com/v4/permission"; }
        else { params.put("client_id",p.id);params.put("response_type","code");params.put("scope","google".equals(p.name)?"openid profile":"public_profile");destination="google".equals(p.name)?"https://accounts.google.com/o/oauth2/v2/auth":"https://www.facebook.com/"+p.version+"/dialog/oauth"; }
        if (!"facebook".equals(p.name)) {
            try { params.put("code_challenge",Base64.getUrlEncoder().withoutPadding().encodeToString(MessageDigest.getInstance("SHA-256").digest(attempt.verifier.getBytes(StandardCharsets.US_ASCII)))); }
            catch (Exception impossible) { throw new IllegalStateException(impossible); }
            if ("google".equals(p.name)) { params.put("code_challenge_method","S256");params.put("prompt","select_account"); }
        }
        socialCookie(ex,attempt.browser,false,p.base.startsWith("https://"));
        ex.getResponseHeaders().set("Cache-Control","no-store");
        sendJson(ex,200,"{\"ok\":true,\"url\":"+quoteJson(destination+"?"+socialEncode(params))+"}");
    }
    private Map<String,String> socialHttp(String url, Map<String,String> body, Map<String,String> headers) throws IOException {
        HttpURLConnection connection=(HttpURLConnection)new URL(url).openConnection();
        connection.setInstanceFollowRedirects(false);connection.setConnectTimeout(8000);connection.setReadTimeout(8000);
        connection.setRequestProperty("Accept","application/json");
        for (Map.Entry<String,String> h:headers.entrySet()) connection.setRequestProperty(h.getKey(),h.getValue());
        try {
            if (body!=null) {
                connection.setRequestMethod("POST");connection.setDoOutput(true);connection.setRequestProperty("Content-Type","application/x-www-form-urlencoded");
                byte[] bytes=socialEncode(body).getBytes(StandardCharsets.UTF_8);
                try(OutputStream stream=connection.getOutputStream()){stream.write(bytes);}
            }
            int status=connection.getResponseCode();if(status<200||status>=300) throw new IOException("Provider rejected request");
            ByteArrayOutputStream bytes=new ByteArrayOutputStream();
            try(InputStream stream=connection.getInputStream()) {
                byte[] buffer=new byte[4096];int count;
                while((count=stream.read(buffer))!=-1){if(bytes.size()+count>65536)throw new IOException("Provider response too large");bytes.write(buffer,0,count);}
            }
            return jsonFields(requireValidJsonObjectText(new String(bytes.toByteArray(),StandardCharsets.UTF_8)));
        } finally { connection.disconnect(); }
    }
    private String socialProof(String token,String secret) {
        try {
            javax.crypto.Mac mac=javax.crypto.Mac.getInstance("HmacSHA256");mac.init(new javax.crypto.spec.SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8),"HmacSHA256"));
            StringBuilder hex=new StringBuilder();for(byte b:mac.doFinal(token.getBytes(StandardCharsets.UTF_8)))hex.append(String.format(Locale.ROOT,"%02x",b&255));return hex.toString();
        } catch(Exception impossible){throw new IllegalStateException(impossible);}
    }
    private String socialIdentityText(String raw) {
        if (raw == null) return "";
        if (raw.startsWith("\"")) return jsonString(raw);
        return raw.matches("[0-9]+") ? raw : "";
    }
    private String[] socialProfile(SocialAttempt attempt,String code) throws IOException {
        SocialProvider p=attempt.provider;Map<String,String> fields=new LinkedHashMap<>(),headers=new LinkedHashMap<>();
        fields.put("code",code);fields.put("grant_type","authorization_code");
        String tokenUrl;
        if("zalo".equals(p.name)){fields.put("app_id",p.id);fields.put("code_verifier",attempt.verifier);headers.put("secret_key",p.secret);tokenUrl="https://oauth.zaloapp.com/v4/access_token";}
        else{fields.put("client_id",p.id);fields.put("client_secret",p.secret);fields.put("redirect_uri",p.callback());tokenUrl="google".equals(p.name)?"https://oauth2.googleapis.com/token":"https://graph.facebook.com/"+p.version+"/oauth/access_token";if("google".equals(p.name))fields.put("code_verifier",attempt.verifier);}
        Map<String,String> response="facebook".equals(p.name)?socialHttp(tokenUrl+"?"+socialEncode(fields),null,headers):socialHttp(tokenUrl,fields,headers);
        String token=jsonString(response.get("access_token"));if(isBlank(token)||token.length()>8192)throw new IOException("No access token");
        headers.clear();headers.put("Authorization","Bearer "+token);String profileUrl;
        if("google".equals(p.name))profileUrl="https://openidconnect.googleapis.com/v1/userinfo";
        else if("zalo".equals(p.name)){headers.clear();headers.put("access_token",token);profileUrl="https://graph.zaloapp.com/v2.0/me?fields=id,name&appsecret_proof="+socialProof(token,p.secret);}
        else profileUrl="https://graph.facebook.com/"+p.version+"/me?fields=id,name&appsecret_proof="+socialProof(token,p.secret);
        Map<String,String> profile=socialHttp(profileUrl,null,headers);
        String subject=socialIdentityText(profile.get("google".equals(p.name)?"sub":"id"));
        if(isBlank(subject)||!subject.matches("[A-Za-z0-9._:-]{1,256}"))throw new IOException("No verified identity");
        if("facebook".equals(p.name)){
            Map<String,String> auth=Collections.singletonMap("Authorization","Bearer "+p.id+"|"+p.secret);
            Map<String,String> debug=socialHttp("https://graph.facebook.com/"+p.version+"/debug_token?"+socialEncode(Collections.singletonMap("input_token",token)),null,auth);
            Map<String,String> metadata=jsonFields(debug.get("data"));
            if(!"true".equals(metadata.get("is_valid"))||!p.id.equals(socialIdentityText(metadata.get("app_id")))||!subject.equals(socialIdentityText(metadata.get("user_id"))))throw new IOException("Token identity mismatch");
        }
        String name=nvl(jsonString(profile.get("name"))).replaceAll("[\\p{Cntrl}]","");if(name.length()>128)name=name.substring(0,128);
        return new String[]{subject,name};
    }
    private void handleSocialCallback(HttpExchange ex) throws IOException {
        if(!"GET".equals(ex.getRequestMethod())){sendJson(ex,405,"{\"ok\":false}");return;}
        String prefix="/api/auth/social/callback/",provider=ex.getRequestURI().getPath().substring(prefix.length());
        Map<String,String> query=parseQuery(ex.getRequestURI().getRawQuery());String state=nvl(query.get("state"));
        SocialAttempt attempt=socialAttempts.get(state);
        if(attempt==null||attempt.expires<System.currentTimeMillis()||!provider.equals(attempt.provider.name)||!attempt.browser.equals(getCookie(ex,"LOTTO_OAUTH"))||!socialAttempts.remove(state,attempt)){socialRedirect(ex,"state");return;}
        socialCookie(ex,"",true,attempt.provider.base.startsWith("https://"));
        if(query.containsKey("error")){socialRedirect(ex,"cancelled");return;}
        String code=nvl(query.get("code"));if(isBlank(code)||code.length()>4096){socialRedirect(ex,"failed");return;}
        try {
            String[] profile=socialProfile(attempt,code);Account account=repo.socialAccount(provider,attempt.provider.id,profile[0],profile[1]);
            if(account==null||!account.enabled){socialRedirect(ex,"disabled");return;}
            long now=System.currentTimeMillis();
            for(String old:new ArrayList<>(sessions.keySet()))if(sessionExpiry.getOrDefault(old,0L)<=now){sessions.remove(old);sessionExpiry.remove(old);sessionPasswordHash.remove(old);}
            if(sessions.size()>=4096){socialRedirect(ex,"failed");return;}
            String old=getCookie(ex,COOKIE_NAME);if(old!=null){sessions.remove(old);sessionExpiry.remove(old);sessionPasswordHash.remove(old);}
            String token=socialRandom();sessions.put(token,account.username);sessionExpiry.put(token,now+SESSION_TTL_MS);sessionPasswordHash.put(token,account.passwordHash);
            setCookie(ex,COOKIE_NAME,token,false);socialRedirect(ex,"");
        } catch(IllegalStateException unavailable){socialRedirect(ex,"disabled");}
        catch(Exception failure){socialRedirect(ex,"failed");}
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
        StringBuilder countsJson = new StringBuilder("{");
        for (Map.Entry<String, Long> entry : row.prizeWinnerCounts.entrySet()) {
            if (countsJson.length() > 1) countsJson.append(',');
            countsJson.append('"').append(entry.getKey()).append("\":").append(entry.getValue());
        }
        countsJson.append('}');
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
                + ",\"prizeWinnerCounts\":" + countsJson
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

    private Map<String, String> canonicalJsonMembers(String raw) {
        JsonCursor cursor = new JsonCursor(raw);
        Map<String, String> values = cursor.readObjectMembers();
        cursor.skipWhitespace();
        if (!cursor.isEnd()) throw new IllegalArgumentException("Metadata có nội dung thừa.");
        return values;
    }

    private void readCanonicalWinnerCounts(String type, Path csvFile, List<CanonicalHistoryRow> rows) {
        List<String> keys;
        if ("LOTO_5_35".equals(type)) keys = Arrays.asList("specialPrize", "first", "second", "third", "fourth", "fifth", "consolation");
        else if ("LOTO_6_45".equals(type)) keys = Arrays.asList("jackpot", "first", "second", "third");
        else if ("LOTO_6_55".equals(type)) keys = Arrays.asList("jackpot1", "jackpot2", "first", "second", "third");
        else return;
        Path metaFile = csvFile.resolveSibling(csvFile.getFileName().toString().replaceFirst("\\.csv$", ".meta.json"));
        if (!Files.exists(metaFile)) return;
        try {
            if (Files.size(metaFile) > 20 * 1024 * 1024) return;
            Map<String, String> metadata = canonicalJsonMembers(new String(Files.readAllBytes(metaFile), StandardCharsets.UTF_8).replaceFirst("^\\uFEFF", ""));
            String winners = metadata.get("prizeWinners");
            if (winners == null) return;
            String evidenceRaw = canonicalJsonMembers(winners).get("countsByDraw");
            if (evidenceRaw == null) return;
            Map<String, String> evidence = canonicalJsonMembers(evidenceRaw);
            for (CanonicalHistoryRow row : rows) {
                String itemRaw = evidence.get(row.ky);
                if (itemRaw == null) continue;
                Map<String, String> item = canonicalJsonMembers(itemRaw);
                StringBuilder main = new StringBuilder();
                for (Integer ball : row.main) {
                    if (main.length() > 0) main.append(',');
                    main.append(ball);
                }
                String identity = row.date + "|" + row.time + "|" + main + "|" + (row.special == null ? "" : row.special);
                if (!("\"" + esc(identity) + "\"").equals(item.get("identity"))) continue;
                String countsRaw = item.get("counts");
                if (countsRaw == null) continue;
                Map<String, String> counts = canonicalJsonMembers(countsRaw);
                for (String key : keys) {
                    String countRaw = counts.get(key);
                    if (countRaw == null || !countRaw.matches("[0-9]+")) continue;
                    try {
                        long count = Long.parseLong(countRaw);
                        if (count >= 0 && count <= 9007199254740991L) row.prizeWinnerCounts.put(key, count);
                    } catch (NumberFormatException ignored) { }
                }
            }
        } catch (IOException | IllegalArgumentException invalidMetadata) {
            System.err.println("Winner statistics unavailable for " + type + ": " + invalidMetadata.getMessage());
        }
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
        readCanonicalWinnerCounts(type, csvFile, allRows);
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
        if (!Arrays.asList("LOTO_5_35", "LOTO_6_45", "LOTO_6_55", "KENO").contains(type)) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Hiệu quả dự đoán hỗ trợ 5/35, Mega, Power và Keno.\"}");
            return false;
        }
        return true;
    }

    private void sendEffectivenessResult(HttpExchange ex, List<String> command, boolean canManage) throws IOException {
        Process process = null;
        try {
            process = new ProcessBuilder(command).directory(rootDir.toFile()).start();
            ProcessOutput output = waitForProcessOutput(process, command.contains("cycle") ? AI_ML_TIMEOUT_SECONDS : AI_PREDICT_TIMEOUT_SECONDS, TimeUnit.SECONDS);
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
        if ("KENO".equals(type)) {
            int level = isBlank(query.get("level")) ? 10 : parseStrictPositiveInt(query.get("level"));
            int page = isBlank(query.get("page")) ? 1 : parseStrictPositiveInt(query.get("page"));
            if (level < 1 || level > 10 || page < 1 || page > 1000000) {
                sendJson(ex, 400, "{\"ok\":false,\"message\":\"Bậc Keno phải từ 1 đến 10; trang phải là số nguyên dương.\"}"); return;
            }
            command.add("--level=" + level);
            command.add("--page=" + page);
        }
        sendEffectivenessResult(ex, command, "admin".equals(su.account.role));
    }

    private void handleMlEffectivenessProgress(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        if (requireAuth(ex, true) == null) return;
        ex.getResponseHeaders().set("Cache-Control", "no-store");
        if (!"GET".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}"); return;
        }
        String type = normalizeLiveType(parseQuery(ex.getRequestURI().getRawQuery()).get("type"));
        if (!validateEffectivenessType(ex, type)) return;
        long now = System.currentTimeMillis();
        String progress = "{\"phase\":\"idle\",\"error\":\"\"}";
        Path file = rootDir.resolve("runtime").resolve("effectiveness_progress_" + type.toLowerCase(Locale.ROOT) + ".json");
        if (Files.isRegularFile(file)) {
            try {
                if (Files.size(file) > 8192) throw new IOException("Progress too large");
                String value = new String(Files.readAllBytes(file), StandardCharsets.UTF_8);
                String phase = extractJsonStringField(value, "phase");
                if (!type.equals(extractJsonStringField(value, "type")) || !Arrays.asList("idle", "updating", "creating", "scoring").contains(phase)) throw new IOException("Invalid progress");
                long updated = extractJsonLongField(value, "updatedAtMs", 0L);
                if (!"idle".equals(phase) && (updated <= 0 || now - updated > 20000 || updated - now > 5000)) {
                    progress = "{\"phase\":\"idle\",\"error\":\"Tiến trình bị gián đoạn. Đang chờ lượt chạy tiếp theo.\"}";
                } else progress = value;
            } catch (IOException | RuntimeException invalid) {
                progress = "{\"phase\":\"idle\",\"error\":\"Chưa đọc được trạng thái tiến trình.\"}";
            }
        }
        sendJson(ex, 200, "{\"ok\":true,\"type\":\"" + type + "\",\"serverTimeMs\":" + now + ",\"progress\":" + progress + "}");
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
            if (!("true".equals(enabled) || "false".equals(enabled)) || count < 1 || count > 1000000) {
                sendJson(ex, 400, "{\"ok\":false,\"message\":\"Chọn trạng thái tự động và từ 1 đến 1.000.000 vé.\"}"); return;
            }
            command.add("--enabled=" + enabled);
            command.add("--ticket-count=" + count);
            command.add("--actor=" + su.username);
        }
        sendEffectivenessResult(ex, command, "admin".equals(su.account.role));
    }

    private void handleMlEffectivenessTickets(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAuth(ex, true);
        if (su == null) return;
        if (!"GET".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}"); return;
        }
        Map<String, String> query = parseQuery(ex.getRequestURI().getRawQuery());
        String type = normalizeLiveType(query.get("type"));
        if (!validateEffectivenessType(ex, type)) return;
        int page = isBlank(query.get("page")) ? 1 : parseStrictPositiveInt(query.get("page"));
        String predictionId = nvl(query.get("predictionId"));
        if (page < 1 || page > 1000000 || !predictionId.matches("[a-fA-F0-9\\-]{36}")) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Mã dự đoán hoặc trang vé không hợp lệ.\"}"); return;
        }
        List<String> command = effectivenessCommand("tickets", type);
        command.add("--prediction-id=" + predictionId);
        command.add("--page=" + page);
        String prizeCode = query.get("prizeCode");
        if (prizeCode != null) {
            if (!prizeCode.matches("[A-Z][A-Z0-9_]{0,39}")) {
                sendJson(ex, 400, "{\"ok\":false,\"message\":\"Mã giải thưởng không hợp lệ.\"}"); return;
            }
            command.add("--prize-code=" + prizeCode);
        }
        String afterTicketIndex = query.get("afterTicketIndex");
        if (afterTicketIndex != null) {
            int cursor = parseStrictPositiveInt(afterTicketIndex);
            if (prizeCode == null || cursor < 1 || cursor > 1000000) {
                sendJson(ex, 400, "{\"ok\":false,\"message\":\"Vị trí vé đã xem không hợp lệ.\"}"); return;
            }
            command.add("--after-ticket-index=" + cursor);
        }
        sendEffectivenessResult(ex, command, "admin".equals(su.account.role));
    }

    private void handleMlEffectivenessExport(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAuth(ex, true);
        if (su == null) return;
        if (!"GET".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}"); return;
        }
        Map<String, String> query = parseQuery(ex.getRequestURI().getRawQuery());
        String type = normalizeLiveType(query.get("type"));
        if (!validateEffectivenessType(ex, type)) return;
        String cycleId = nvl(query.get("cycleId"));
        int level = isBlank(query.get("level")) ? 10 : parseStrictPositiveInt(query.get("level"));
        if (!validLabId(cycleId) || level < 1 || level > 10) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Mã kỳ dự đoán hoặc bậc Keno không hợp lệ.\"}"); return;
        }
        List<String> command = effectivenessCommand("export", type);
        command.add("--cycle-id=" + cycleId);
        command.add("--level=" + level);
        ex.getResponseHeaders().set("Cache-Control", "no-store");
        String format = query.get("format");
        if (format != null && !"xlsx".equals(format)) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Định dạng xuất không hợp lệ.\"}"); return;
        }
        if ("xlsx".equals(format)) {
            sendEffectivenessWorkbook(ex, type, cycleId, level);
            return;
        }
        sendEffectivenessResult(ex, command, "admin".equals(su.account.role));
    }

    private void sendEffectivenessWorkbook(HttpExchange ex, String type, String cycleId, int level) throws IOException {
        if (!effectivenessJobRunning.compareAndSet(false, true)) {
            sendJson(ex, 409, "{\"ok\":false,\"message\":\"Đang xử lý dự đoán hoặc Excel. Vui lòng thử lại sau.\"}"); return;
        }
        Process process = null;
        Path directory = null;
        Path file = null;
        try {
            Path runtime = rootDir.resolve("runtime");
            Files.createDirectories(runtime);
            directory = Files.createTempDirectory(runtime, "effectiveness_export_");
            file = directory.resolve("portfolio.xlsx");
            List<String> command = effectivenessCommand("export-file", type);
            command.add("--cycle-id=" + cycleId);
            command.add("--level=" + level);
            command.add("--output=" + file.toAbsolutePath());
            process = new ProcessBuilder(command).directory(rootDir.toFile()).start();
            ProcessOutput output = waitForProcessOutput(process, AI_ML_TIMEOUT_SECONDS, TimeUnit.SECONDS);
            if (!output.finished) {
                sendJson(ex, 504, "{\"ok\":false,\"message\":\"Xuất Excel quá thời gian chờ.\"}"); return;
            }
            if (output.exitCode != 0 || !Files.isRegularFile(file)) {
                sendJson(ex, 400, "{\"ok\":false,\"message\":\"Không xuất được Excel của kỳ đã chọn. Vui lòng thử lại.\"}"); return;
            }
            ex.getResponseHeaders().set("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
            ex.getResponseHeaders().set("Content-Disposition", "attachment; filename=\"du_doan_thuc_te_" + type.toLowerCase(Locale.ROOT) + "_" + cycleId + ".xlsx\"");
            ex.sendResponseHeaders(200, Files.size(file));
            try (OutputStream response = ex.getResponseBody()) { Files.copy(file, response); }
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            sendJson(ex, 503, "{\"ok\":false,\"message\":\"Xuất Excel bị gián đoạn.\"}");
        } finally {
            if (process != null) process.destroy();
            try {
                if (file != null) Files.deleteIfExists(file);
                if (directory != null) Files.deleteIfExists(directory);
            } finally {
                effectivenessJobRunning.set(false);
            }
        }
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

    private static boolean validLabId(String id) {
        return id.matches("[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}");
    }

    private String executeLabService(String script, String action, String owner, String type, String... options)
            throws Exception {
        Path source = rootDir.resolve("ai").resolve(script);
        if (!Files.isRegularFile(source)) throw new IOException("Lab service is unavailable");
        List<String> command = buildPythonCommand(source);
        command.add("--action=" + action);
        command.add("--owner=" + owner);
        command.add("--game=" + type);
        Collections.addAll(command, options);
        Process process = null;
        try {
            process = new ProcessBuilder(command).directory(rootDir.toFile()).start();
            ProcessOutput output = waitForLabProcessOutput(process, 30);
            if (!output.finished) throw new IOException("Lab service timeout");
            String payload = new String(output.stdout, StandardCharsets.UTF_8).trim();
            Map<String, String> fields = jsonFields(payload);
            if (output.exitCode != 0 || !"true".equals(fields.get("ok"))) {
                String message = jsonString(fields.get("message"));
                if (!isBlank(message)) throw new IllegalArgumentException(message);
                throw new IOException("Lab service did not return a valid result");
            }
            if (!type.equals(jsonString(fields.get("type")))) throw new IOException("Lab service game mismatch");
            return payload;
        } finally {
            if (process != null) process.destroyForcibly();
        }
    }

    private void sendAlgorithmLabServiceFailure(HttpExchange ex, Exception failure) throws IOException {
        if (failure instanceof InterruptedException) Thread.currentThread().interrupt();
        sendJson(ex, failure instanceof IllegalArgumentException ? 400 : 503,
                "{\"ok\":false,\"message\":" + quoteJson(failure instanceof IllegalArgumentException
                        ? nvl(failure.getMessage()) : "Không đọc hoặc cập nhật được dữ liệu phòng thử. Vui lòng thử lại.") + "}");
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
        if ("KENO".equals(type)) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Phòng thử hiện hỗ trợ 5/35, Mega và Power.\"}"); return;
        }
        String jobId = nvl(values.get("jobId")).trim();
        String candidateId = nvl(values.get("candidateId")).trim();
        if ((!isBlank(jobId) && !validLabId(jobId)) || (!isBlank(candidateId) && !validLabId(candidateId))) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Mã lượt thử hoặc ứng viên không hợp lệ.\"}"); return;
        }
        String action = nvl(values.get("action")).trim();
        if ("POST".equalsIgnoreCase(method) && ("start_tracking".equals(action) || "stop_tracking".equals(action))) {
            boolean start = "start_tracking".equals(action);
            if ((start && (isBlank(jobId) || !isBlank(candidateId))) || (!start && (isBlank(candidateId) || !isBlank(jobId)))) {
                sendJson(ex, 400, "{\"ok\":false,\"message\":\"Chọn lượt thử hoặc ứng viên cần theo dõi.\"}"); return;
            }
            if (!algorithmLabTrackingActionRunning.compareAndSet(false, true)) {
                sendJson(ex, 409, "{\"ok\":false,\"message\":\"Đang cập nhật theo dõi ứng viên. Vui lòng chờ.\"}"); return;
            }
            try {
                String payload = executeLabService("lab_trials.py", start ? "start" : "stop", su.username, type,
                        start ? "--run-id=" + jobId : "--candidate-id=" + candidateId);
                Map<String, String> fields = jsonFields(payload);
                sendJson(ex, 200, "{\"ok\":true,\"type\":" + quoteJson(type)
                        + ",\"canManage\":true,\"tracking\":" + fields.getOrDefault("tracking", "null") + "}");
            } catch (Exception failure) { sendAlgorithmLabServiceFailure(ex, failure); }
            finally { algorithmLabTrackingActionRunning.set(false); }
            return;
        }
        if (!isBlank(candidateId) || ("GET".equalsIgnoreCase(method) && !isBlank(action))) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Thao tác phòng thử không hợp lệ.\"}"); return;
        }
        AlgorithmLabJob selected = null;
        if (!isBlank(jobId)) {
            selected = algorithmLabJobs.get(jobId);
            if (selected != null && (!selected.owner.equals(su.username) || !selected.type.equals(type))) {
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
            try {
                String payload = isBlank(jobId)
                        ? executeLabService("lab_store.py", "overview", su.username, type)
                        : executeLabService("lab_store.py", "overview", su.username, type, "--run-id=" + jobId);
                Map<String, String> fields = jsonFields(payload);
                String storedJob = fields.getOrDefault("job", "null");
                String chosenJob = selected == null ? storedJob : selected.json();
                if (isBlank(jobId) && selected != null && !"null".equals(storedJob)) {
                    try {
                        Instant storedAt = Instant.parse(jsonString(jsonFields(storedJob).get("createdAt")));
                        if (storedAt.isAfter(selected.createdAt)) chosenJob = storedJob;
                    } catch (RuntimeException ignored) { }
                }
                if (!isBlank(jobId) && "null".equals(chosenJob)) {
                    sendJson(ex, 404, "{\"ok\":false,\"message\":\"Không tìm thấy lượt thử của tài khoản này.\"}"); return;
                }
                sendJson(ex, 200, "{\"ok\":true,\"type\":" + quoteJson(type)
                        + ",\"canManage\":" + "admin".equals(su.account.role) + ",\"job\":" + chosenJob
                        + ",\"history\":" + fields.getOrDefault("history", "[]")
                        + ",\"tracking\":" + fields.getOrDefault("tracking", "null") + "}");
            } catch (Exception failure) { sendAlgorithmLabServiceFailure(ex, failure); }
            return;
        }
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
        int validation = isBlank(values.get("validationCount")) ? 20 : parseStrictPositiveInt(values.get("validationCount"));
        int test = isBlank(values.get("testCount")) ? 30 : parseStrictPositiveInt(values.get("testCount"));
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
            ProcessOutput output = waitForLabProcessOutput(process, AI_ML_TIMEOUT_SECONDS, job);
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
                String finishedAt = Instant.now().toString();
                Path reportFile = Files.createTempFile(rootDir.resolve("runtime"), "algorithm-lab-report-", ".json");
                try {
                    Files.write(reportFile, payload.getBytes(StandardCharsets.UTF_8));
                    executeLabService("lab_store.py", "save", job.owner, job.type,
                            "--run-id=" + job.id, "--created-at=" + job.createdAt,
                            "--finished-at=" + finishedAt, "--report-file=" + reportFile);
                } finally { Files.deleteIfExists(reportFile); }
                job.report = payload; job.state = "completed"; job.finishedAt = finishedAt;
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

    private void handleAdminGiftCodes(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAdmin(ex);
        if (su == null) return;
        try {
            if ("GET".equalsIgnoreCase(ex.getRequestMethod())) {
                sendJson(ex, 200, repo.listGiftCodes(parseQuery(ex.getRequestURI().getRawQuery())));
            } else if ("POST".equalsIgnoreCase(ex.getRequestMethod())) {
                Map<String, String> form = parseForm(ex);
                sendJson(ex, 200, "set-active".equals(form.get("action"))
                        ? repo.setGiftCodeActive(form, su.username) : "delete".equals(form.get("action"))
                        ? repo.deleteGiftCodes(form, su.username) : repo.createGiftCode(form, su.username));
            } else { sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}"); }
        } catch (IllegalStateException e) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":" + quoteJson(e.getMessage()) + "}");
        }
    }

    private void handleRedeemGiftCode(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAuth(ex, true);
        if (su == null) return;
        if (!"POST".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}"); return;
        }
        long now = System.currentTimeMillis();
        codeAttempts.entrySet().removeIf(entry -> entry.getValue()[0] < now - 60000);
        long[] attempts = codeAttempts.computeIfAbsent(su.username, key -> new long[]{now, 0});
        synchronized (attempts) {
            if (++attempts[1] > 20) {
                sendJson(ex, 429, "{\"ok\":false,\"message\":\"Bạn đã thử quá nhiều code. Vui lòng chờ 1 phút.\"}"); return;
            }
        }
        try {
            sendJson(ex, 200, repo.redeemGiftCode(su.username, parseForm(ex).get("code")));
        } catch (IllegalStateException e) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":" + quoteJson(e.getMessage()) + "}");
        }
    }

    private static String normalizeGiftCode(String raw) {
        String code = nvl(raw).trim().toUpperCase(Locale.ROOT);
        if (!code.matches("[A-Z0-9_-]{4,64}")) throw new IllegalStateException("Code cần 4–64 ký tự: chữ, số, dấu - hoặc _.");
        return code;
    }

    private static long giftReward(Map<String, String> form, String key, long limit) {
        long value = parseAccountBalance(form.containsKey(key) ? form.get(key) : "0", key);
        if (value > limit) throw new IllegalStateException(key + " vượt giới hạn " + limit + ".");
        return value;
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
        try {
            long diamond = parseAccountBalance(f.get("diamond"), "Kim cương");
            long paypal = parseAccountBalance(f.get("paypal"), "PayPal");
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
        if (socialPublicBase(readSocialSettings()).startsWith("https://") || readVnpayConfig().base.startsWith("https://")) cookie += "; Secure";
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
            return origin.equals(socialPublicBase(readSocialSettings())) || origin.equals(readVnpayConfig().base) || Arrays.asList(System.getProperty("lotto.allowedOrigins", "").split(",")).contains(origin);
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

    private static long parseAccountBalance(String raw, String label) {
        String value = nvl(raw).trim();
        if (!value.matches("[0-9]+")) {
            throw new IllegalStateException(label + " phải là số nguyên không âm.");
        }
        try {
            long amount = Long.parseLong(value);
            if (amount > 9007199254740991L) throw new NumberFormatException();
            return amount;
        } catch (NumberFormatException invalid) {
            throw new IllegalStateException(label + " vượt giới hạn 9.007.199.254.740.991.");
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
        return key.equals("paymentOrders") || key.equals("diamondBalance") || key.equals("paypalBalance") || key.startsWith("vip")
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

    // VNPAY 2.1.0: browser return never settles an order; only verified IPN does.
    private static class VnpayConfig {
        boolean enabled; String mode, tmn, secret, base; long maximum = 10000000L;
        boolean ready() { return ("sandbox".equals(mode) || "production".equals(mode)) && tmn.matches("[A-Za-z0-9]{8}") && secret.length() >= 16 && !base.isEmpty(); }
        String endpoint() { return "production".equals(mode) ? "https://pay.vnpay.vn/vpcpay.html" : "https://sandbox.vnpayment.vn/paymentv2/vpcpay.html"; }
    }

    private VnpayConfig readVnpayConfig() {
        Properties p = new Properties();
        Path file = rootDir.resolve("runtime/vnpay.properties");
        if (Files.isRegularFile(file)) try (Reader reader = Files.newBufferedReader(file, StandardCharsets.UTF_8)) { p.load(reader); }
        catch (IOException invalid) { p.clear(); }
        VnpayConfig cfg = new VnpayConfig();
        cfg.enabled = "true".equals(socialSetting(p, "enabled", "LOTTO_VNPAY_ENABLED"));
        cfg.mode = socialSetting(p, "environment", "LOTTO_VNPAY_ENVIRONMENT");
        if (cfg.mode.isEmpty()) cfg.mode = "sandbox";
        cfg.tmn = socialSetting(p, "tmnCode", "LOTTO_VNPAY_TMN_CODE");
        cfg.secret = socialSetting(p, "hashSecret", "LOTTO_VNPAY_HASH_SECRET");
        cfg.base = socialSetting(p, "publicBaseUrl", "LOTTO_VNPAY_PUBLIC_BASE_URL");
        try {
            java.net.URI uri = java.net.URI.create(cfg.base);
            boolean local = "localhost".equals(uri.getHost()) || "127.0.0.1".equals(uri.getHost());
            if (uri.getHost() == null || uri.getRawUserInfo() != null || uri.getRawQuery() != null || uri.getRawFragment() != null
                    || !(isBlank(uri.getPath()) || "/".equals(uri.getPath()))
                    || !("https".equals(uri.getScheme()) || (local && "sandbox".equals(cfg.mode) && "http".equals(uri.getScheme())))
                    || (local && "production".equals(cfg.mode))) cfg.base = "";
            else if (cfg.base.endsWith("/")) cfg.base = cfg.base.substring(0, cfg.base.length() - 1);
        } catch (IllegalArgumentException invalid) { cfg.base = ""; }
        try { long max = Long.parseLong(socialSetting(p, "maxAmount", "LOTTO_VNPAY_MAX_AMOUNT")); if (max >= 10000 && max <= 100000000) cfg.maximum = max; }
        catch (NumberFormatException ignored) { }
        return cfg;
    }

    private static String vnpayQuery(Map<String, String> input) {
        List<String> parts = new ArrayList<>();
        for (Map.Entry<String, String> item : new TreeMap<>(input).entrySet()) {
            if (item.getKey().equals("vnp_SecureHash") || item.getKey().equals("vnp_SecureHashType") || isBlank(item.getValue())) continue;
            try { parts.add(URLEncoder.encode(item.getKey(), "UTF-8") + "=" + URLEncoder.encode(item.getValue(), "UTF-8")); }
            catch (UnsupportedEncodingException impossible) { throw new IllegalStateException(impossible); }
        }
        return String.join("&", parts);
    }

    private static String vnpayHash(String secret, Map<String, String> fields) {
        try {
            Mac mac = Mac.getInstance("HmacSHA512");
            mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA512"));
            StringBuilder result = new StringBuilder();
            for (byte value : mac.doFinal(vnpayQuery(fields).getBytes(StandardCharsets.UTF_8))) result.append(String.format("%02x", value & 255));
            return result.toString();
        } catch (Exception invalid) { throw new IllegalStateException("Không tạo được chữ ký VNPAY", invalid); }
    }

    private static Map<String, String> vnpayFields(String query) {
        if (query == null || query.length() > 16384) throw new IllegalArgumentException("Invalid callback");
        Map<String, String> fields = new TreeMap<>();
        for (String part : query.split("&")) {
            int equals = part.indexOf('=');
            if (equals < 1 || fields.size() >= 40) throw new IllegalArgumentException("Invalid callback");
            try {
                String key = URLDecoder.decode(part.substring(0, equals), "UTF-8");
                String value = URLDecoder.decode(part.substring(equals + 1), "UTF-8");
                if (!key.matches("vnp_[A-Za-z0-9_]+") || fields.put(key, value) != null) throw new IllegalArgumentException("Duplicate or invalid parameter");
            } catch (UnsupportedEncodingException impossible) { throw new IllegalStateException(impossible); }
        }
        return fields;
    }

    private static String vnpayAck(String code) {
        String message = "00".equals(code) ? "Confirm Success" : "02".equals(code) ? "Order already confirmed" : "01".equals(code) ? "Order not found" : "04".equals(code) ? "Invalid amount" : "97".equals(code) ? "Invalid signature" : "Processing error";
        return "{\"RspCode\":" + quoteJson(code) + ",\"Message\":" + quoteJson(message) + "}";
    }

    private String vnpayPaymentUrl(Map<String, String> order, VnpayConfig cfg, String ip) {
        Map<String, String> p = new TreeMap<>();
        DateTimeFormatter format = DateTimeFormatter.ofPattern("yyyyMMddHHmmss").withZone(ZoneId.of("Asia/Ho_Chi_Minh"));
        p.put("vnp_Version", "2.1.0"); p.put("vnp_Command", "pay"); p.put("vnp_TmnCode", cfg.tmn);
        p.put("vnp_Amount", Long.toString(Long.parseLong(order.get("amount")) * 100)); p.put("vnp_CurrCode", "VND");
        p.put("vnp_BankCode", "VNPAYQR"); p.put("vnp_Locale", "vn"); p.put("vnp_OrderType", "other");
        p.put("vnp_TxnRef", order.get("id")); p.put("vnp_OrderInfo", "Nap PayPal " + order.get("id"));
        p.put("vnp_ReturnUrl", cfg.base + "/api/payments/vnpay/return"); p.put("vnp_IpAddr", ip);
        p.put("vnp_CreateDate", format.format(Instant.parse(order.get("createdAt"))));
        p.put("vnp_ExpireDate", format.format(Instant.parse(order.get("expiresAt"))));
        return cfg.endpoint() + "?" + vnpayQuery(p) + "&vnp_SecureHash=" + vnpayHash(cfg.secret, p);
    }

    private void handleVnpay(HttpExchange ex) throws IOException {
        ex.getResponseHeaders().set("Cache-Control", "no-store");
        String path = ex.getRequestURI().getPath(), method = ex.getRequestMethod();
        VnpayConfig cfg = readVnpayConfig();
        if (path.equals("/api/payments/vnpay/ipn")) {
            if (!"GET".equals(method)) { sendJson(ex, 405, vnpayAck("99")); return; }
            try {
                Map<String, String> p = vnpayFields(ex.getRequestURI().getRawQuery());
                String signature = p.getOrDefault("vnp_SecureHash", "");
                if (!cfg.ready() || !signature.matches("[a-fA-F0-9]{128}") || !cfg.tmn.equals(p.get("vnp_TmnCode"))
                        || !MessageDigest.isEqual(signature.toLowerCase(Locale.ROOT).getBytes(StandardCharsets.US_ASCII), vnpayHash(cfg.secret, p).getBytes(StandardCharsets.US_ASCII))) {
                    sendJson(ex, 200, vnpayAck("97")); return;
                }
                sendJson(ex, 200, vnpayAck(repo.settleVnpay(p, cfg)));
            } catch (IllegalArgumentException invalid) { sendJson(ex, 200, vnpayAck("97")); }
            catch (RuntimeException failed) { sendJson(ex, 200, vnpayAck("99")); }
            return;
        }
        if (path.equals("/api/payments/vnpay/return")) {
            if (!"GET".equals(method)) { sendJson(ex, 405, "{\"ok\":false}"); return; }
            String id = "";
            try { id = vnpayFields(ex.getRequestURI().getRawQuery()).getOrDefault("vnp_TxnRef", ""); } catch (IllegalArgumentException ignored) { }
            ex.getResponseHeaders().set("Location", "/nap-tien" + (id.matches("[a-f0-9]{32}") ? "?payment=" + id : ""));
            ex.getResponseHeaders().set("Referrer-Policy", "no-referrer");
            ex.sendResponseHeaders(303, -1); ex.close(); return;
        }
        if (handleOptions(ex)) return;
        SessionUser user = requireAuth(ex, true);
        if (user == null) return;
        if ("GET".equals(method) && path.equals("/api/payments/vnpay/config")) {
            sendJson(ex, 200, "{\"ok\":true,\"configured\":" + (cfg.enabled && cfg.ready()) + ",\"environment\":" + quoteJson(cfg.mode) + ",\"minimum\":10000,\"step\":1000,\"maximum\":" + cfg.maximum + "}"); return;
        }
        try {
            if ("GET".equals(method) && path.equals("/api/payments/vnpay/orders")) {
                sendJson(ex, 200, "{\"ok\":true,\"orders\":" + repo.listVnpay(user.username) + ",\"store\":" + repo.publicWallet(user.username) + "}"); return;
            }
            if ("POST".equals(method) && path.equals("/api/payments/vnpay/orders")) {
                if (!cfg.enabled || !cfg.ready()) { sendJson(ex, 503, "{\"ok\":false,\"message\":\"VNPAY chưa được cấu hình. Vui lòng liên hệ quản trị viên.\"}"); return; }
                Map<String, String> form = parseForm(ex);
                String raw = form.getOrDefault("amount", ""), request = form.getOrDefault("requestId", "");
                if (!raw.matches("[0-9]{1,9}") || !request.matches("[A-Za-z0-9_-]{16,64}")) throw new IllegalArgumentException("Số tiền hoặc mã yêu cầu không hợp lệ.");
                long amount = Long.parseLong(raw);
                if (amount < 10000 || amount > cfg.maximum || amount % 1000 != 0) throw new IllegalArgumentException("Số tiền phải từ 10.000 VNĐ, là bội số 1.000 VNĐ và trong giới hạn cho phép.");
                Map<String, String> order = repo.createVnpay(user.username, request, amount, cfg);
                String checkout = "";
                if (order.get("status").equals("PENDING") && Instant.parse(order.get("expiresAt")).isAfter(Instant.now())) checkout = vnpayPaymentUrl(order, cfg, ex.getRemoteAddress().getAddress().getHostAddress());
                sendJson(ex, 200, "{\"ok\":true,\"order\":" + paymentOrderJson(order) + ",\"paymentUrl\":" + quoteJson(checkout) + "}"); return;
            }
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Thao tác không được hỗ trợ\"}");
        } catch (IllegalArgumentException invalid) { sendJson(ex, 400, "{\"ok\":false,\"message\":" + quoteJson(invalid.getMessage()) + "}"); }
        catch (RuntimeException failed) { sendJson(ex, 500, "{\"ok\":false,\"message\":\"Chưa xử lý được giao dịch. Hãy thử lại với cùng yêu cầu.\"}"); }
    }

    private static String paymentOrderJson(Map<String, String> p) {
        Map<String, String> result = new LinkedHashMap<>();
        for (String key : Arrays.asList("id", "environment", "status", "createdAt", "expiresAt", "paidAt", "transactionNo")) result.put(key, quoteJson(p.getOrDefault(key, "")));
        if ("PENDING".equals(p.get("status")) && !Instant.parse(p.get("expiresAt")).isAfter(Instant.now())) result.put("status", quoteJson("EXPIRED"));
        for (String key : Arrays.asList("amount", "baseCredit", "bonusCredit", "credit")) result.put(key, p.get(key));
        return fieldsJson(result);
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

    private static ProcessOutput waitForLabProcessOutput(Process process) throws IOException, InterruptedException {
        return waitForLabProcessOutput(process, AI_ML_TIMEOUT_SECONDS);
    }

    private static ProcessOutput waitForLabProcessOutput(Process process, long timeoutSeconds) throws IOException, InterruptedException {
        return waitForLabProcessOutput(process, timeoutSeconds, null);
    }

    private static ProcessOutput waitForLabProcessOutput(Process process, long timeoutSeconds, AlgorithmLabJob job) throws IOException, InterruptedException {
        LimitedProcessOutput stdout = new LimitedProcessOutput(8 * 1024 * 1024, process);
        LimitedProcessOutput stderr = new LimitedProcessOutput(256 * 1024, process);
        Thread outThread = pumpProcessStream(process.getInputStream(), stdout, "lab-stdout");
        Thread errThread = job == null ? pumpProcessStream(process.getErrorStream(), stderr, "lab-stderr")
                : pumpLabProgress(process.getErrorStream(), stderr, job);
        boolean finished = process.waitFor(timeoutSeconds, TimeUnit.SECONDS);
        if (!finished) { process.destroyForcibly(); process.waitFor(5, TimeUnit.SECONDS); }
        joinQuietly(outThread, 5000); joinQuietly(errThread, 5000);
        if (stdout.exceeded || stderr.exceeded) throw new IllegalArgumentException("Lượt thử vượt giới hạn dung lượng báo cáo hoặc nhật ký.");
        return new ProcessOutput(finished, finished ? process.exitValue() : -1, stdout.bytes(), stderr.bytes());
    }

    private static Thread pumpLabProgress(InputStream input, LimitedProcessOutput output, AlgorithmLabJob job) {
        Thread thread = new Thread(() -> {
            ByteArrayOutputStream line = new ByteArrayOutputStream();
            boolean tooLong = false;
            try {
                byte[] bytes = new byte[8192];
                int count;
                while ((count = input.read(bytes)) != -1) {
                    output.write(bytes, 0, count);
                    for (int index = 0; index < count; index++) {
                        if (bytes[index] == '\n') {
                            if (!tooLong) {
                                try {
                                    Map<String, String> fields = jsonFields(new String(line.toByteArray(), StandardCharsets.UTF_8));
                                    int done = Integer.parseInt(fields.get("completed"));
                                    int total = Integer.parseInt(fields.get("total"));
                                    synchronized (job) {
                                        if (total == job.validationCount + job.testCount && done >= job.completedFolds && done <= total) {
                                            job.completedFolds = done;
                                        }
                                    }
                                } catch (RuntimeException ignored) { }
                            }
                            line.reset(); tooLong = false;
                        } else if (line.size() < 4096 && !tooLong) {
                            line.write(bytes[index]);
                        } else { tooLong = true; }
                    }
                }
            } catch (IOException ignored) { }
        }, "lab-progress");
        thread.setDaemon(true);
        thread.start();
        return thread;
    }

    private static Thread pumpProcessStream(InputStream input, OutputStream output, String name) {
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
                st.execute("CREATE TABLE IF NOT EXISTS social_identities (provider TEXT NOT NULL, client_id TEXT NOT NULL, subject TEXT NOT NULL, username TEXT NOT NULL, display_name TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(provider,client_id,subject), FOREIGN KEY(username) REFERENCES users(username) ON DELETE CASCADE)");
                st.execute("CREATE TABLE IF NOT EXISTS stores (" +
                        "username TEXT PRIMARY KEY," +
                        "store_json TEXT NOT NULL DEFAULT '{}'," +
                        "FOREIGN KEY(username) REFERENCES users(username) ON DELETE CASCADE" +
                        ")");
                st.execute("CREATE TABLE IF NOT EXISTS account_entitlements (username TEXT PRIMARY KEY, vip_expires_at TEXT NOT NULL, updated_at TEXT NOT NULL)");
                st.execute("CREATE TABLE IF NOT EXISTS wallet_events (username TEXT NOT NULL, request_id TEXT NOT NULL, action TEXT NOT NULL, response_json TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(username,request_id))");
                st.execute("CREATE TABLE IF NOT EXISTS account_audit (event_id TEXT PRIMARY KEY, actor TEXT NOT NULL, target TEXT NOT NULL, action TEXT NOT NULL, details_json TEXT NOT NULL, created_at TEXT NOT NULL)");
                st.execute("CREATE TABLE IF NOT EXISTS payment_orders (id TEXT PRIMARY KEY,username TEXT NOT NULL,request_id TEXT NOT NULL,environment TEXT NOT NULL,tmn_code TEXT NOT NULL,amount INTEGER NOT NULL,base_credit INTEGER NOT NULL,bonus_credit INTEGER NOT NULL,credit INTEGER NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,expires_at TEXT NOT NULL,paid_at TEXT NOT NULL DEFAULT '',transaction_no TEXT,UNIQUE(username,request_id))");
                st.execute("CREATE UNIQUE INDEX IF NOT EXISTS payment_transaction_unique ON payment_orders(environment,tmn_code,transaction_no) WHERE transaction_no IS NOT NULL");
                st.execute("CREATE TABLE IF NOT EXISTS gift_codes (code TEXT PRIMARY KEY, diamond INTEGER NOT NULL, paypal INTEGER NOT NULL, vip_days INTEGER NOT NULL, bonus_spins INTEGER NOT NULL, max_uses INTEGER NOT NULL, used_count INTEGER NOT NULL DEFAULT 0, expires_at TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL)");
                st.execute("CREATE TABLE IF NOT EXISTS gift_code_redemptions (code TEXT NOT NULL, username TEXT NOT NULL, redeemed_at TEXT NOT NULL, PRIMARY KEY(code,username))");
                Set<String> codeColumns = new HashSet<>();
                try (ResultSet columns = st.executeQuery("PRAGMA table_info(gift_codes)")) {
                    while (columns.next()) codeColumns.add(columns.getString("name"));
                }
                if (!codeColumns.contains("active")) st.execute("ALTER TABLE gift_codes ADD COLUMN active INTEGER NOT NULL DEFAULT 1");
                if (!codeColumns.contains("kind")) st.execute("ALTER TABLE gift_codes ADD COLUMN kind TEXT NOT NULL DEFAULT 'promotion'");
                if (!codeColumns.contains("max_per_user")) st.execute("ALTER TABLE gift_codes ADD COLUMN max_per_user INTEGER NOT NULL DEFAULT 1");
                if (!codeColumns.contains("cooldown_seconds")) st.execute("ALTER TABLE gift_codes ADD COLUMN cooldown_seconds INTEGER NOT NULL DEFAULT 0");
                if (!codeColumns.contains("activates_at")) st.execute("ALTER TABLE gift_codes ADD COLUMN activates_at TEXT NOT NULL DEFAULT ''");
                if (!codeColumns.contains("deleted_at")) st.execute("ALTER TABLE gift_codes ADD COLUMN deleted_at TEXT NOT NULL DEFAULT ''");
                Set<String> redemptionColumns = new HashSet<>();
                try (ResultSet columns = st.executeQuery("PRAGMA table_info(gift_code_redemptions)")) {
                    while (columns.next()) redemptionColumns.add(columns.getString("name"));
                }
                if (!redemptionColumns.contains("received_count")) st.execute("ALTER TABLE gift_code_redemptions ADD COLUMN received_count INTEGER NOT NULL DEFAULT 1");
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

        synchronized Account socialAccount(String provider,String clientId,String subject,String displayName) {
            try(Connection c=conn()) {
                c.setAutoCommit(false);
                try {
                    String user=null;
                    try(PreparedStatement ps=c.prepareStatement("SELECT username FROM social_identities WHERE provider=? AND client_id=? AND subject=?")) {
                        ps.setString(1,provider);ps.setString(2,clientId);ps.setString(3,subject);
                        try(ResultSet rs=ps.executeQuery()){if(rs.next())user=rs.getString(1);}
                    }
                    if(user!=null){c.commit();return getUser(user);}
                    if(countAdminUsers()==0)throw new IllegalStateException("Set up a local admin first");
                    do {user=provider+"_"+UUID.randomUUID().toString().replace("-","").substring(0,12);} while(getUser(user)!=null);
                    byte[] salt=new byte[16];random.nextBytes(salt);
                    String password=hashPassword(socialRandom(),salt);
                    try(PreparedStatement ps=c.prepareStatement("INSERT INTO users(username,salt,password_hash,role,enabled) VALUES(?,?,?,'user',1)")) {
                        ps.setString(1,user);ps.setString(2,Base64.getEncoder().encodeToString(salt));ps.setString(3,password);ps.executeUpdate();
                    }
                    try(PreparedStatement ps=c.prepareStatement("INSERT INTO social_identities VALUES(?,?,?,?,?,?)")) {
                        ps.setString(1,provider);ps.setString(2,clientId);ps.setString(3,subject);ps.setString(4,user);ps.setString(5,displayName);ps.setString(6,Instant.now().toString());ps.executeUpdate();
                    }
                    auditAccount(c,user,user,"social_register","{\"provider\":"+quoteJson(provider)+"}");
                    c.commit();return getUser(user);
                } catch(SQLException|RuntimeException failure){c.rollback();throw failure;}
            } catch(SQLException failure){throw new RuntimeException(failure);}
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

        private Map<String, String> paymentRow(ResultSet rs) throws SQLException {
            Map<String, String> p = new LinkedHashMap<>();
            String[] columns = {"id", "environment", "status", "created_at", "expires_at", "paid_at", "transaction_no", "amount", "base_credit", "bonus_credit", "credit"};
            String[] keys = {"id", "environment", "status", "createdAt", "expiresAt", "paidAt", "transactionNo", "amount", "baseCredit", "bonusCredit", "credit"};
            for (int i = 0; i < columns.length; i++) p.put(keys[i], nvl(rs.getString(columns[i])));
            return p;
        }

        synchronized Map<String, String> createVnpay(String user, String request, long amount, VnpayConfig cfg) {
            try (Connection c = conn()) {
                c.setAutoCommit(false);
                try {
                    try (PreparedStatement ps = c.prepareStatement("SELECT * FROM payment_orders WHERE username=? AND request_id=?")) {
                        ps.setString(1, user); ps.setString(2, request);
                        try (ResultSet rs = ps.executeQuery()) {
                            if (rs.next()) {
                                if (rs.getLong("amount") != amount || !cfg.mode.equals(rs.getString("environment")) || !cfg.tmn.equals(rs.getString("tmn_code"))) throw new IllegalArgumentException("Mã yêu cầu đã dùng cho giao dịch khác.");
                                Map<String, String> found = paymentRow(rs); c.commit(); return found;
                            }
                        }
                    }
                    Instant now = Instant.now();
                    try (PreparedStatement ps = c.prepareStatement("SELECT COUNT(*) FROM payment_orders WHERE username=? AND (created_at>? OR (status='PENDING' AND expires_at>?))")) {
                        ps.setString(1, user); ps.setString(2, now.minusSeconds(60).toString()); ps.setString(3, now.toString());
                        try (ResultSet rs = ps.executeQuery()) { if (rs.next() && rs.getInt(1) >= 5) throw new IllegalArgumentException("Bạn đang có nhiều yêu cầu thanh toán. Hãy hoàn tất hoặc chờ đơn cũ hết hạn."); }
                    }
                    long base = amount * 5 / 4;
                    long bonus = amount == 50000 ? 625 : amount == 100000 ? 1875 : amount == 200000 ? 5000 : amount == 500000 ? 15625 : 0;
                    String id = UUID.randomUUID().toString().replace("-", "");
                    try (PreparedStatement ps = c.prepareStatement("INSERT INTO payment_orders(id,username,request_id,environment,tmn_code,amount,base_credit,bonus_credit,credit,status,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?,'PENDING',?,?)")) {
                        ps.setString(1, id); ps.setString(2, user); ps.setString(3, request); ps.setString(4, cfg.mode); ps.setString(5, cfg.tmn);
                        ps.setLong(6, amount); ps.setLong(7, base); ps.setLong(8, bonus); ps.setLong(9, base + bonus); ps.setString(10, now.toString()); ps.setString(11, now.plusSeconds(900).toString()); ps.executeUpdate();
                    }
                    auditAccount(c, user, user, "vnpay_order_created", "{\"id\":" + quoteJson(id) + ",\"amount\":" + amount + ",\"environment\":" + quoteJson(cfg.mode) + "}");
                    Map<String, String> p;
                    try (PreparedStatement ps = c.prepareStatement("SELECT * FROM payment_orders WHERE id=?")) { ps.setString(1, id); try (ResultSet rs = ps.executeQuery()) { rs.next(); p = paymentRow(rs); } }
                    c.commit(); return p;
                } catch (Exception invalid) { c.rollback(); if (invalid instanceof IllegalArgumentException) throw (IllegalArgumentException) invalid; throw new RuntimeException(invalid); }
            } catch (SQLException failure) { throw new RuntimeException(failure); }
        }

        synchronized String listVnpay(String user) {
            List<String> orders = new ArrayList<>();
            try (Connection c = conn(); PreparedStatement ps = c.prepareStatement("SELECT * FROM payment_orders WHERE username=? ORDER BY created_at DESC,id DESC LIMIT 100")) {
                ps.setString(1, user); try (ResultSet rs = ps.executeQuery()) { while (rs.next()) orders.add(paymentOrderJson(paymentRow(rs))); }
                return "[" + String.join(",", orders) + "]";
            } catch (SQLException failure) { throw new RuntimeException(failure); }
        }

        synchronized String settleVnpay(Map<String, String> p, VnpayConfig cfg) {
            String id = p.getOrDefault("vnp_TxnRef", "");
            if (!id.matches("[a-f0-9]{32}")) return "01";
            try (Connection c = conn()) {
                c.setAutoCommit(false);
                try {
                    String user, status; long amount, credit;
                    try (PreparedStatement ps = c.prepareStatement("SELECT * FROM payment_orders WHERE id=? AND environment=? AND tmn_code=?")) {
                        ps.setString(1, id); ps.setString(2, cfg.mode); ps.setString(3, cfg.tmn);
                        try (ResultSet rs = ps.executeQuery()) {
                            if (!rs.next()) { c.rollback(); return "01"; }
                            user = rs.getString("username"); status = rs.getString("status"); amount = rs.getLong("amount"); credit = rs.getLong("credit");
                        }
                    }
                    String rawAmount = p.getOrDefault("vnp_Amount", "");
                    if (!rawAmount.matches("[0-9]{1,12}") || Long.parseLong(rawAmount) != amount * 100 || !p.getOrDefault("vnp_CurrCode", "VND").equals("VND")) { c.rollback(); return "04"; }
                    if (!p.getOrDefault("vnp_OrderInfo", "").equals("Nap PayPal " + id)) { c.rollback(); return "97"; }
                    if (!"PENDING".equals(status)) { c.rollback(); return "02"; }
                    boolean success = "00".equals(p.get("vnp_ResponseCode")) && "00".equals(p.get("vnp_TransactionStatus"));
                    if (!p.getOrDefault("vnp_ResponseCode", "").matches("[0-9]{2}") || !p.getOrDefault("vnp_TransactionStatus", "").matches("[0-9]{2}")) { c.rollback(); return "99"; }
                    String transaction = p.getOrDefault("vnp_TransactionNo", "");
                    if (success && (!transaction.matches("[0-9]{1,30}") || transaction.matches("0+"))) { c.rollback(); return "99"; }
                    if (getUser(user) == null) { c.rollback(); return "01"; }
                    String outcome = success ? ("production".equals(cfg.mode) ? "PAID" : "TEST_PAID") : "FAILED";
                    if (outcome.equals("PAID")) {
                        Map<String, String> fields;
                        try (PreparedStatement ps = c.prepareStatement("SELECT store_json FROM stores WHERE username=?")) {
                            ps.setString(1, user); try (ResultSet rs = ps.executeQuery()) { fields = jsonFields(rs.next() ? rs.getString(1) : "{}"); }
                        }
                        long balance = Math.addExact(fieldLong(fields, "paypalBalance", 0), credit);
                        if (balance > 9007199254740991L || balance < -9007199254740991L) throw new IllegalStateException("Wallet limit");
                        fields.put("paypalBalance", Long.toString(balance));
                        fields.put("walletVersion", Long.toString(Math.addExact(fieldLong(fields, "walletVersion", 0), 1)));
                        try (PreparedStatement ps = c.prepareStatement("INSERT OR REPLACE INTO stores(username,store_json) VALUES(?,?)")) { ps.setString(1, user); ps.setString(2, fieldsJson(fields)); ps.executeUpdate(); }
                    }
                    try (PreparedStatement ps = c.prepareStatement("UPDATE payment_orders SET status=?,paid_at=?,transaction_no=? WHERE id=? AND status='PENDING'")) {
                        ps.setString(1, outcome); ps.setString(2, success ? Instant.now().toString() : ""); ps.setString(3, success ? transaction : null); ps.setString(4, id);
                        if (ps.executeUpdate() != 1) throw new IllegalStateException("Order changed");
                    }
                    auditAccount(c, "vnpay_ipn", user, outcome.equals("PAID") ? "vnpay_credit" : "vnpay_" + outcome.toLowerCase(Locale.ROOT), "{\"id\":" + quoteJson(id) + ",\"amount\":" + amount + ",\"credit\":" + (outcome.equals("PAID") ? credit : 0) + ",\"transactionNo\":" + quoteJson(success ? transaction : "") + "}");
                    c.commit(); return "00";
                } catch (Exception failure) { c.rollback(); throw new RuntimeException(failure); }
            } catch (SQLException failure) { throw new RuntimeException(failure); }
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
                    long spins = Math.min(60, fieldLong(fields, "luckyWheelStoredSpins", 60));
                    long gained = (now - regen) / 600000;
                    spins = Math.min(60, spins + gained);
                    regen = spins == 60 ? now : regen + gained * 600000;
                    long paypal = fieldLong(fields, "paypalBalance", 0);
                    long diamond = fieldLong(fields, "diamondBalance", 0);
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

        private boolean giftCodeActivated(ResultSet row, Instant now) throws SQLException {
            if (row.getInt("active") == 1) return true;
            String activation = nvl(row.getString("activates_at"));
            if (activation.isEmpty()) return false;
            try { return !Instant.parse(activation).isAfter(now); }
            catch (DateTimeParseException invalid) { return false; }
        }

        synchronized String listGiftCodes(Map<String, String> query) {
            long page = query.containsKey("page") ? giftReward(query, "page", 1000000) : 1;
            if (page < 1) throw new IllegalStateException("Trang cần lớn hơn 0.");
            String search = nvl(query.get("q")).trim().toUpperCase(Locale.ROOT);
            if (search.length() > 64) throw new IllegalStateException("Tìm kiếm tối đa 64 ký tự.");
            String enabled = "(active=1 OR (activates_at<>'' AND julianday(activates_at)<=julianday('now')))";
            String ready = enabled + " AND (expires_at='' OR julianday(expires_at)>julianday('now')) AND used_count<max_uses";
            try (Connection c = conn()) {
                String stats;
                try (Statement st = c.createStatement(); ResultSet rs = st.executeQuery("SELECT COUNT(*) total, COALESCE(SUM(CASE WHEN " + ready + " THEN 1 ELSE 0 END),0) active, (SELECT COALESCE(SUM(used_count),0) FROM gift_codes) redemptions, COALESCE(SUM(CASE WHEN NOT " + enabled + " THEN 1 ELSE 0 END),0) inactive, COALESCE(SUM(CASE WHEN kind='promotion' THEN 1 ELSE 0 END),0) promotion, COALESCE(SUM(CASE WHEN kind='vip' THEN 1 ELSE 0 END),0) vip, COALESCE(SUM(CASE WHEN kind='gift' THEN 1 ELSE 0 END),0) gift, COALESCE(SUM(CASE WHEN substr(kind,1,7)='custom:' THEN 1 ELSE 0 END),0) custom, (SELECT COUNT(*) FROM users) users FROM gift_codes WHERE deleted_at=''")) {
                    rs.next();
                    stats = "{\"total\":" + rs.getLong("total") + ",\"active\":" + rs.getLong("active") + ",\"redemptions\":" + rs.getLong("redemptions") + ",\"inactive\":" + rs.getLong("inactive") + ",\"users\":" + rs.getLong("users") + ",\"promotion\":" + rs.getLong("promotion") + ",\"vip\":" + rs.getLong("vip") + ",\"gift\":" + rs.getLong("gift") + ",\"custom\":" + rs.getLong("custom") + "}";
                }
                long total;
                try (PreparedStatement ps = c.prepareStatement("SELECT COUNT(*) FROM gift_codes WHERE deleted_at='' AND instr(code,?)>0")) {
                    ps.setString(1, search);
                    try (ResultSet rs = ps.executeQuery()) { rs.next(); total = rs.getLong(1); }
                }
                StringBuilder rows = new StringBuilder("[");
                try (PreparedStatement ps = c.prepareStatement("SELECT * FROM gift_codes WHERE deleted_at='' AND instr(code,?)>0 ORDER BY created_at DESC,code ASC LIMIT 20 OFFSET ?")) {
                    ps.setString(1, search); ps.setLong(2, (page - 1) * 20);
                    try (ResultSet rs = ps.executeQuery()) {
                        while (rs.next()) {
                            if (rows.length() > 1) rows.append(',');
                            rows.append("{\"code\":").append(quoteJson(rs.getString("code")))
                                .append(",\"kind\":").append(quoteJson(rs.getString("kind")))
                                .append(",\"active\":").append(giftCodeActivated(rs, Instant.now()))
                                .append(",\"activatesAt\":").append(quoteJson(rs.getString("activates_at")))
                                .append(",\"diamond\":").append(rs.getLong("diamond"))
                                .append(",\"paypal\":").append(rs.getLong("paypal"))
                                .append(",\"vipDays\":").append(rs.getLong("vip_days"))
                                .append(",\"bonusSpins\":").append(rs.getLong("bonus_spins"))
                                .append(",\"maxUses\":").append(rs.getLong("max_uses"))
                                .append(",\"maxPerUser\":").append(rs.getLong("max_per_user"))
                                .append(",\"cooldownSeconds\":").append(rs.getLong("cooldown_seconds"))
                                .append(",\"usedCount\":").append(rs.getLong("used_count"))
                                .append(",\"expiresAt\":").append(quoteJson(rs.getString("expires_at")))
                                .append(",\"createdAt\":").append(quoteJson(rs.getString("created_at"))).append('}');
                        }
                    }
                }
                return "{\"ok\":true,\"codes\":" + rows.append(']') + ",\"total\":" + total + ",\"page\":" + page + ",\"pageSize\":20,\"stats\":" + stats + "}";
            } catch (SQLException failure) { throw new RuntimeException(failure); }
        }

        synchronized String deleteGiftCodes(Map<String, String> form, String actor) {
            String reclaimValue = form.containsKey("reclaimRewards") ? form.get("reclaimRewards") : "0";
            if (!"0".equals(reclaimValue) && !"1".equals(reclaimValue)) throw new IllegalStateException("Lựa chọn thu hồi không hợp lệ.");
            boolean reclaim = "1".equals(reclaimValue);
            String raw = nvl(form.get("codes"));
            if (raw.isEmpty() || raw.length() > 1300) throw new IllegalStateException("Chọn từ 1 đến 20 Code cần xóa.");
            String[] items = raw.split("\\r?\\n", -1);
            if (items.length > 20) throw new IllegalStateException("Chỉ xóa tối đa 20 Code mỗi lần.");
            Set<String> codes = new LinkedHashSet<>();
            for (String item : items) codes.add(normalizeGiftCode(item));
            try (Connection c = conn()) {
                c.setAutoCommit(false);
                try {
                    String at = Instant.now().toString();
                    StringBuilder detail = new StringBuilder("{\"codes\":[");
                    try (PreparedStatement ps = c.prepareStatement("UPDATE gift_codes SET deleted_at=? WHERE code=? AND deleted_at=''")) {
                        for (String code : codes) {
                            ps.setString(1, at); ps.setString(2, code);
                            if (ps.executeUpdate() != 1) throw new IllegalStateException("Code không tồn tại hoặc đã bị xóa. Hãy làm mới danh sách.");
                            if (detail.length() > 10) detail.append(',');
                            detail.append(quoteJson(code));
                        }
                    }
                    int affectedUsers = reclaim ? reclaimGiftRewards(c, codes, actor) : 0;
                    auditAccount(c, actor, actor, "delete_gift_codes", detail.append("],\"reclaimRewards\":").append(reclaim).append('}').toString());
                    c.commit(); return "{\"ok\":true,\"deletedCount\":" + codes.size() + ",\"reclaimed\":" + reclaim + ",\"affectedUsers\":" + affectedUsers + "}";
                } catch (SQLException | RuntimeException failure) { c.rollback(); throw failure; }
            } catch (SQLException failure) { throw new RuntimeException(failure); }
        }

        private long checkedReclaimedBalance(long previous, BigInteger reward) {
            BigInteger result = BigInteger.valueOf(previous).subtract(reward);
            if (result.abs().compareTo(BigInteger.valueOf(9007199254740991L)) > 0) {
                throw new IllegalStateException("Số dư sau thu hồi vượt giới hạn số nguyên chính xác. Chưa xóa Code hoặc thu hồi quà.");
            }
            return result.longValue();
        }

        private int reclaimGiftRewards(Connection c, Set<String> codes, String actor) throws SQLException {
            Map<String, BigInteger[]> rewards = new LinkedHashMap<>();
            try (PreparedStatement ps = c.prepareStatement("SELECT r.username,r.received_count,g.diamond,g.paypal,g.vip_days,g.bonus_spins FROM gift_code_redemptions r JOIN gift_codes g ON g.code=r.code JOIN users u ON u.username=r.username WHERE r.code=?")) {
                for (String code : codes) {
                    ps.setString(1, code);
                    try (ResultSet rs = ps.executeQuery()) {
                        while (rs.next()) {
                            String user = rs.getString("username");
                            BigInteger[] amounts = rewards.computeIfAbsent(user, ignored -> new BigInteger[] {BigInteger.ZERO,BigInteger.ZERO,BigInteger.ZERO,BigInteger.ZERO});
                            BigInteger count = BigInteger.valueOf(rs.getLong("received_count"));
                            String[] keys = {"diamond", "paypal", "vip_days", "bonus_spins"};
                            for (int i = 0; i < keys.length; i++) amounts[i] = amounts[i].add(BigInteger.valueOf(rs.getLong(keys[i])).multiply(count));
                        }
                    }
                }
            }
            Instant now = Instant.now();
            for (Map.Entry<String, BigInteger[]> entry : rewards.entrySet()) {
                String user = entry.getKey(); BigInteger[] amounts = entry.getValue();
                Map<String, String> fields = new LinkedHashMap<>();
                try (PreparedStatement ps = c.prepareStatement("SELECT store_json FROM stores WHERE username=?")) {
                    ps.setString(1, user);
                    try (ResultSet rs = ps.executeQuery()) { if (rs.next()) fields = jsonFields(rs.getString(1)); }
                }
                long diamond = checkedReclaimedBalance(fieldLong(fields, "diamondBalance", 0), amounts[0]);
                long paypal = checkedReclaimedBalance(fieldLong(fields, "paypalBalance", 0), amounts[1]);
                fields.put("diamondBalance", Long.toString(diamond)); fields.put("paypalBalance", Long.toString(paypal));
                if (amounts[3].signum() > 0) {
                    long regen = now.toEpochMilli();
                    try { regen = Math.min(regen, Instant.parse(jsonString(fields.get("luckyWheelLastRegenAt"))).toEpochMilli()); }
                    catch (Exception invalid) { /* Missing timestamp starts at the current server time. */ }
                    long gained = (now.toEpochMilli() - regen) / 600000;
                    long spins = Math.min(60, fieldLong(fields, "luckyWheelStoredSpins", 60) + gained);
                    regen = spins == 60 ? now.toEpochMilli() : regen + gained * 600000;
                    spins = checkedReclaimedBalance(spins, amounts[3]);
                    fields.put("luckyWheelStoredSpins", Long.toString(spins));
                    fields.put("luckyWheelLastRegenAt", quoteJson(Instant.ofEpochMilli(regen).toString()));
                }
                if (amounts[2].signum() > 0) {
                    Instant expiry = now;
                    try (PreparedStatement ps = c.prepareStatement("SELECT vip_expires_at FROM account_entitlements WHERE username=?")) {
                        ps.setString(1, user);
                        try (ResultSet rs = ps.executeQuery()) {
                            if (rs.next()) { try { expiry = Instant.parse(rs.getString(1)); } catch (DateTimeParseException invalid) { /* No valid membership. */ } }
                        }
                    }
                    expiry = expiry.minus(Duration.ofDays(amounts[2].longValueExact()));
                    try (PreparedStatement ps = c.prepareStatement("INSERT OR REPLACE INTO account_entitlements VALUES(?,?,?)")) {
                        ps.setString(1,user); ps.setString(2,expiry.toString()); ps.setString(3,now.toString()); ps.executeUpdate();
                    }
                }
                fields.put("walletVersion", Long.toString(fieldLong(fields, "walletVersion", 0) + 1));
                try (PreparedStatement ps = c.prepareStatement("INSERT OR REPLACE INTO stores(username,store_json) VALUES(?,?)")) {
                    ps.setString(1,user); ps.setString(2,fieldsJson(fields)); ps.executeUpdate();
                }
                auditAccount(c,actor,user,"reclaim_gift_code_rewards","{\"diamond\":"+amounts[0]+",\"paypal\":"+amounts[1]+",\"vipDays\":"+amounts[2]+",\"bonusSpins\":"+amounts[3]+",\"diamondAfter\":"+diamond+",\"paypalAfter\":"+paypal+"}");
            }
            return rewards.size();
        }

        synchronized String setGiftCodeActive(Map<String, String> form, String actor) {
            String code = normalizeGiftCode(form.get("code")), active = nvl(form.get("active"));
            if (!"0".equals(active) && !"1".equals(active)) throw new IllegalStateException("Trạng thái kích hoạt không hợp lệ.");
            try (Connection c = conn()) {
                c.setAutoCommit(false);
                try {
                    try (PreparedStatement ps = c.prepareStatement("UPDATE gift_codes SET active=?,activates_at='' WHERE code=? AND deleted_at=''")) {
                        ps.setInt(1, Integer.parseInt(active)); ps.setString(2, code);
                        if (ps.executeUpdate() != 1) throw new IllegalStateException("Code không tồn tại.");
                    }
                    auditAccount(c, actor, actor, "set_gift_code_active", "{\"code\":" + quoteJson(code) + ",\"active\":" + active + "}");
                    c.commit(); return "{\"ok\":true}";
                } catch (SQLException | RuntimeException failure) { c.rollback(); throw failure; }
            } catch (SQLException failure) { throw new RuntimeException(failure); }
        }

        synchronized String createGiftCode(Map<String, String> form, String actor) {
            int quantity = (int)giftReward(form, "quantity", 100);
            if (!form.containsKey("quantity")) quantity = 1;
            if (quantity < 1) throw new IllegalStateException("Số lượng mã cần từ 1 đến 100.");
            String manualCode = nvl(form.get("code")).trim();
            if (!manualCode.isEmpty() && quantity != 1) throw new IllegalStateException("Code tùy chọn chỉ tạo một mã mỗi lần.");
            String prefix = nvl(form.get("prefix")).trim().toUpperCase(Locale.ROOT);
            if (!prefix.matches("[A-Z0-9_-]{0,20}")) throw new IllegalStateException("Tiền tố tối đa 20 ký tự: chữ, số, - hoặc _.");
            int length = form.containsKey("length") ? (int)giftReward(form, "length", 16) : 16;
            if (length != 8 && length != 12 && length != 16) throw new IllegalStateException("Độ dài mã cần là 8, 12 hoặc 16.");
            String active = nvl(form.get("active"));
            if (active.isEmpty()) active = "1";
            if (!"0".equals(active) && !"1".equals(active)) throw new IllegalStateException("Trạng thái kích hoạt không hợp lệ.");
            String kind = nvl(form.get("kind"));
            if (kind.isEmpty()) kind = "promotion";
            if ("custom".equals(kind)) {
                String name = nvl(form.get("kindName")).trim();
                if (name.isEmpty() || name.length() > 60 || name.matches("(?s).*\\p{Cntrl}.*")) {
                    throw new IllegalStateException("Tên loại Code cần từ 1 đến 60 ký tự và không chứa ký tự điều khiển.");
                }
                kind = "custom:" + name;
            } else if (!Arrays.asList("promotion", "vip", "gift").contains(kind)) {
                throw new IllegalStateException("Loại Code không hợp lệ.");
            }
            long diamond = giftReward(form, "diamond", 9007199254740991L);
            long paypal = giftReward(form, "paypal", 9007199254740991L);
            long vipDays = giftReward(form, "vipDays", 3660);
            long spins = giftReward(form, "bonusSpins", 60);
            long maxUses = giftReward(form, "maxUses", 1000000);
            if (maxUses < 1) throw new IllegalStateException("Số lượt sử dụng cần từ 1 đến 1.000.000.");
            long maxPerUser = form.containsKey("maxPerUser") ? giftReward(form, "maxPerUser", 1000000) : 1;
            if (form.containsKey("cooldownSeconds") && form.containsKey("cooldownHours")) {
                throw new IllegalStateException("Chỉ chọn một đơn vị thời gian chờ.");
            }
            long cooldownSeconds = form.containsKey("cooldownSeconds")
                    ? giftReward(form, "cooldownSeconds", 31536000)
                    : giftReward(form, "cooldownHours", 8760) * 3600;
            if ((maxPerUser == 0 && cooldownSeconds == 0) || (maxPerUser > 0 && cooldownSeconds > 0)) {
                throw new IllegalStateException("Chọn số lần nhận từ 1 đến 1.000.000 hoặc thời gian chờ từ 1 giây đến 365 ngày.");
            }
            if (diamond == 0 && paypal == 0 && vipDays == 0 && spins == 0) throw new IllegalStateException("Chọn ít nhất một phần quà lớn hơn 0.");
            String expiry = nvl(form.get("expiresAt")).trim();
            if (!expiry.isEmpty()) {
                try {
                    Instant time = OffsetDateTime.parse(expiry).toInstant();
                    if (!time.isAfter(Instant.now())) throw new DateTimeParseException("Expired", expiry, 0);
                    expiry = time.toString();
                } catch (DateTimeParseException invalid) { throw new IllegalStateException("Hạn code phải là thời gian tương lai hợp lệ."); }
            }
            String activation = nvl(form.get("activatesAt")).trim();
            if (!activation.isEmpty()) {
                if (!"0".equals(active)) throw new IllegalStateException("Code kích hoạt ngay không được kèm lịch kích hoạt.");
                try {
                    Instant time = OffsetDateTime.parse(activation).toInstant();
                    if (!time.isAfter(Instant.now())) throw new DateTimeParseException("Past activation", activation, 0);
                    if (!expiry.isEmpty() && !time.isBefore(Instant.parse(expiry))) {
                        throw new IllegalStateException("Ngày giờ kích hoạt phải trước ngày hết hạn.");
                    }
                    activation = time.toString();
                } catch (DateTimeParseException invalid) { throw new IllegalStateException("Ngày giờ kích hoạt phải là thời gian tương lai hợp lệ."); }
            }
            try (Connection c = conn()) {
                c.setAutoCommit(false);
                try {
                    List<String> codes = new ArrayList<>();
                    for (int i = 0; i < quantity; i++) {
                    String code = manualCode.isEmpty() ? (prefix.isEmpty() ? "" : prefix + "-") + UUID.randomUUID().toString().replace("-", "").substring(0, length).toUpperCase(Locale.ROOT) : normalizeGiftCode(manualCode);
                    try (PreparedStatement check = c.prepareStatement("SELECT code FROM gift_codes WHERE code=?")) {
                        check.setString(1, code);
                        try (ResultSet rs = check.executeQuery()) {
                            if (rs.next()) throw new IllegalStateException("Code này đã tồn tại. Hãy chọn code khác.");
                        }
                    }
                    try (PreparedStatement ps = c.prepareStatement("INSERT INTO gift_codes(code,diamond,paypal,vip_days,bonus_spins,max_uses,expires_at,created_by,created_at,active,kind,max_per_user,cooldown_seconds,activates_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)")) {
                        ps.setString(1, code); ps.setLong(2, diamond); ps.setLong(3, paypal); ps.setLong(4, vipDays);
                        ps.setLong(5, spins); ps.setLong(6, maxUses); ps.setString(7, expiry); ps.setString(8, actor); ps.setString(9, Instant.now().toString()); ps.setInt(10, Integer.parseInt(active)); ps.setString(11, kind); ps.setLong(12, maxPerUser); ps.setLong(13, cooldownSeconds); ps.setString(14, activation); ps.executeUpdate();
                    }
                    auditAccount(c, actor, actor, "create_gift_code", "{\"code\":" + quoteJson(code) + "}");
                    codes.add(code);
                    }
                    c.commit();
                    StringBuilder codeJson = new StringBuilder("[");
                    for (String value : codes) { if (codeJson.length() > 1) codeJson.append(','); codeJson.append(quoteJson(value)); }
                    return "{\"ok\":true,\"code\":" + quoteJson(codes.get(0)) + ",\"codes\":" + codeJson.append(']') + ",\"maxUses\":" + maxUses + ",\"expiresAt\":" + quoteJson(expiry) + ",\"activatesAt\":" + quoteJson(activation) + "}";
                } catch (SQLException | RuntimeException failure) { c.rollback(); throw failure; }
            } catch (SQLException failure) { throw new RuntimeException(failure); }
        }

        synchronized String redeemGiftCode(String user, String rawCode) {
            String code = normalizeGiftCode(rawCode);
            try (Connection c = conn()) {
                c.setAutoCommit(false);
                try {
                    long diamond, paypal, vipDays, spins, maxPerUser, cooldownSeconds, remainingGifts;
                    long receivedCount = 0;
                    Instant redeemedAt = Instant.now();
                    try (PreparedStatement ps = c.prepareStatement("SELECT * FROM gift_codes WHERE code=?")) {
                        ps.setString(1, code);
                        try (ResultSet rs = ps.executeQuery()) {
                            if (!rs.next()) throw new IllegalStateException("Code không tồn tại.");
                            if (!nvl(rs.getString("deleted_at")).isEmpty()) throw new IllegalStateException("Code đã bị xóa.");
                            if (!giftCodeActivated(rs, redeemedAt)) throw new IllegalStateException("Code chưa được kích hoạt.");
                            String expiry = rs.getString("expires_at");
                            if (!expiry.isEmpty() && !Instant.parse(expiry).isAfter(Instant.now())) throw new IllegalStateException("Code đã hết hạn.");
                            if (rs.getLong("used_count") >= rs.getLong("max_uses")) throw new IllegalStateException("Code đã hết lượt sử dụng.");
                            diamond = rs.getLong("diamond"); paypal = rs.getLong("paypal"); vipDays = rs.getLong("vip_days"); spins = rs.getLong("bonus_spins");
                            maxPerUser = rs.getLong("max_per_user"); cooldownSeconds = rs.getLong("cooldown_seconds");
                            remainingGifts = rs.getLong("max_uses") - rs.getLong("used_count") - 1;
                        }
                    }
                    try (PreparedStatement ps = c.prepareStatement("SELECT received_count,redeemed_at FROM gift_code_redemptions WHERE code=? AND username=?")) {
                        ps.setString(1, code); ps.setString(2, user);
                        try (ResultSet rs = ps.executeQuery()) {
                            if (rs.next()) {
                                receivedCount = rs.getLong("received_count");
                                if (maxPerUser > 0 && receivedCount >= maxPerUser) {
                                    throw new IllegalStateException(maxPerUser == 1 ? "Bạn đã sử dụng code này rồi." : "Bạn đã nhận đủ " + maxPerUser + " phần quà từ code này.");
                                }
                                if (cooldownSeconds > 0) {
                                    Instant next = Instant.parse(rs.getString("redeemed_at")).plusSeconds(cooldownSeconds);
                                    if (redeemedAt.isBefore(next)) {
                                        String time = next.atZone(ZoneId.of("Asia/Ho_Chi_Minh")).format(DateTimeFormatter.ofPattern("HH:mm dd/MM/yyyy"));
                                        throw new IllegalStateException("Chưa đủ thời gian chờ. Bạn có thể nhận lại lúc " + time + ".");
                                    }
                                }
                            }
                        }
                    }
                    Map<String, String> fields = new LinkedHashMap<>();
                    try (PreparedStatement ps = c.prepareStatement("SELECT store_json FROM stores WHERE username=?")) {
                        ps.setString(1, user);
                        try (ResultSet rs = ps.executeQuery()) { if (rs.next()) fields = jsonFields(rs.getString(1)); }
                    }
                    long oldDiamond = fieldLong(fields, "diamondBalance", 0), oldPaypal = fieldLong(fields, "paypalBalance", 0);
                    if (oldDiamond > 9007199254740991L - diamond || oldPaypal > 9007199254740991L - paypal) throw new IllegalStateException("Số dư sau nhận quà vượt giới hạn. Code chưa được sử dụng.");
                    long storedSpins = fieldLong(fields, "luckyWheelStoredSpins", 60);
                    long spinRegen = System.currentTimeMillis();
                    if (spins > 0) {
                        long now = spinRegen;
                        try { spinRegen = Math.min(now, Instant.parse(jsonString(fields.get("luckyWheelLastRegenAt"))).toEpochMilli()); }
                        catch (Exception invalid) { spinRegen = now; }
                        long gained = (now - spinRegen) / 600000;
                        storedSpins = Math.min(60, storedSpins + gained);
                        spinRegen = storedSpins == 60 ? now : spinRegen + gained * 600000;
                    }
                    if (spins > 0 && storedSpins > 60 - spins) throw new IllegalStateException("Kho lượt quay tối đa 60. Hãy dùng bớt lượt trước khi nhận code này.");
                    fields.put("diamondBalance", Long.toString(oldDiamond + diamond));
                    fields.put("paypalBalance", Long.toString(oldPaypal + paypal));
                    if (spins > 0) {
                        fields.put("luckyWheelStoredSpins", Long.toString(storedSpins + spins));
                        fields.put("luckyWheelLastRegenAt", quoteJson(Instant.ofEpochMilli(storedSpins + spins == 60 ? System.currentTimeMillis() : spinRegen).toString()));
                    }
                    fields.put("walletVersion", Long.toString(fieldLong(fields, "walletVersion", 0) + 1));
                    String expiry = "";
                    try (PreparedStatement ps = c.prepareStatement("SELECT vip_expires_at FROM account_entitlements WHERE username=?")) {
                        ps.setString(1, user);
                        try (ResultSet rs = ps.executeQuery()) { if (rs.next()) expiry = rs.getString(1); }
                    }
                    if (vipDays > 0) {
                        Instant start = Instant.now();
                        try { Instant old = Instant.parse(expiry); if (old.isAfter(start)) start = old; }
                        catch (DateTimeParseException invalid) { /* Expired/missing membership starts today. */ }
                        expiry = start.plus(Duration.ofDays(vipDays)).toString();
                        try (PreparedStatement ps = c.prepareStatement("INSERT OR REPLACE INTO account_entitlements VALUES(?,?,?)")) {
                            ps.setString(1, user); ps.setString(2, expiry); ps.setString(3, Instant.now().toString()); ps.executeUpdate();
                        }
                    }
                    try (PreparedStatement ps = c.prepareStatement("INSERT OR REPLACE INTO stores(username,store_json) VALUES(?,?)")) {
                        ps.setString(1, user); ps.setString(2, fieldsJson(fields)); ps.executeUpdate();
                    }
                    try (PreparedStatement ps = c.prepareStatement("INSERT INTO gift_code_redemptions(code,username,redeemed_at,received_count) VALUES(?,?,?,?) ON CONFLICT(code,username) DO UPDATE SET redeemed_at=excluded.redeemed_at,received_count=excluded.received_count")) {
                        ps.setString(1, code); ps.setString(2, user); ps.setString(3, redeemedAt.toString()); ps.setLong(4, receivedCount + 1); ps.executeUpdate();
                    }
                    try (PreparedStatement ps = c.prepareStatement("UPDATE gift_codes SET used_count=used_count+1 WHERE code=? AND used_count<max_uses")) {
                        ps.setString(1, code);
                        if (ps.executeUpdate() != 1) throw new IllegalStateException("Code đã hết lượt sử dụng.");
                    }
                    String reward = "{\"diamond\":" + diamond + ",\"paypal\":" + paypal + ",\"vipDays\":" + vipDays + ",\"bonusSpins\":" + spins + "}";
                    auditAccount(c, user, user, "redeem_gift_code", "{\"code\":" + quoteJson(code) + ",\"reward\":" + reward + "}");
                    c.commit();
                    fields.keySet().removeIf(key -> !protectedStoreField(key));
                    fields.put("vipExpiresAt", quoteJson(expiry));
                    String nextEligibleAt = cooldownSeconds > 0 && remainingGifts > 0 ? redeemedAt.plusSeconds(cooldownSeconds).toString() : "";
                    String claim = "{\"receivedCount\":" + (receivedCount + 1) + ",\"maxPerUser\":" + maxPerUser + ",\"cooldownSeconds\":" + cooldownSeconds + ",\"nextEligibleAt\":" + quoteJson(nextEligibleAt) + ",\"remainingGifts\":" + remainingGifts + "}";
                    return "{\"ok\":true,\"reward\":" + reward + ",\"claim\":" + claim + ",\"store\":" + fieldsJson(fields) + "}";
                } catch (SQLException | RuntimeException failure) { c.rollback(); throw failure; }
            } catch (SQLException failure) { throw new RuntimeException(failure); }
        }

        synchronized void updateAssets(String user, long diamond, long paypal, String actor) {
            if (getUser(user) == null) throw new IllegalStateException("Không tìm thấy tài khoản");
            String store = getStore(user);
            if (store == null || isBlank(store)) store = "{}";
            Map<String, String> fields = jsonFields(store);
            fields.put("diamondBalance", Long.toString(diamond));
            fields.put("paypalBalance", Long.toString(paypal));
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
                    uv.diamondBalance = readBalanceFromJson(sj, "diamondBalance");
                    uv.paypalBalance = readBalanceFromJson(sj, "paypalBalance");
                    out.add(uv);
                }
            } catch (SQLException e) {
                throw new RuntimeException(e);
            }
            return out;
        }

        private long readBalanceFromJson(String json, String key) {
            try {
                return fieldLong(jsonFields(json), key, 0);
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
                    for (String table : Arrays.asList("account_entitlements", "wallet_events", "gift_code_redemptions", "social_identities", "payment_orders")) {
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
                try (PreparedStatement payments = c.prepareStatement("UPDATE payment_orders SET username=?,status=CASE WHEN status='PENDING' THEN 'OWNER_DELETED' ELSE status END WHERE username=?")) {
                    payments.setString(1, "deleted:" + UUID.randomUUID().toString()); payments.setString(2, user); payments.executeUpdate();
                }
                for (String table : Arrays.asList("account_entitlements", "wallet_events", "gift_code_redemptions", "social_identities")) {
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
        long diamondBalance;
        long paypalBalance;
    }

    static class Account {
        String username;
        String salt;
        String passwordHash;
        String role;
        boolean enabled;
    }
}
