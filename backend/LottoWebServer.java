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
import java.time.LocalDateTime;
import java.time.format.DateTimeParseException;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;

public class LottoWebServer {
    // ----- Cấu hình server -----
    // Gom các hằng số về cổng chạy, timeout tiến trình Python và loại vé được hỗ trợ.
    private static final int PORT = 8080;
    private static final String COOKIE_NAME = "LOTTO_AUTH";
    private static final String DB_FILE = "runtime/lotto_web.db";
    private static final long LIVE_RESULTS_TIMEOUT_SECONDS = 600;
    private static final long LIVE_RESULTS_PROGRESS_STALE_SECONDS = 120;
    private static final long KENO_SYNC_TIMEOUT_SECONDS = 150;
    private static final long KENO_PREDICT_TIMEOUT_SECONDS = 180;
    private static final long AI_PREDICT_TIMEOUT_SECONDS = 240;
    private static final long AI_SCORE_TIMEOUT_SECONDS = 420;
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

    private final Path rootDir;
    private final Path htmlFile;
    private final Path cssFile;
    private final Path jsFile;
    private final Path faviconFile;
    private final Path dbFile;
    private final DatabaseRepo repo;
    private final Map<String, String> sessions = new ConcurrentHashMap<>();
    private final SecureRandom random = new SecureRandom();

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

    private static final class JsonCursor {
        private final String text;
        private int index;

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
            expect('{');
            skipWhitespace();
            if (consumeIf('}')) return;
            while (true) {
                skipWhitespace();
                parseString();
                skipWhitespace();
                expect(':');
                parseValue();
                skipWhitespace();
                if (consumeIf('}')) return;
                expect(',');
            }
        }

        void parseArray() {
            expect('[');
            skipWhitespace();
            if (consumeIf(']')) return;
            while (true) {
                parseValue();
                skipWhitespace();
                if (consumeIf(']')) return;
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
        new LottoWebServer().start();
    }

    public LottoWebServer() {
        this.rootDir = Paths.get(System.getProperty("user.dir"));
        this.htmlFile = rootDir.resolve("frontend").resolve("vietlott-web.html");
        this.cssFile = rootDir.resolve("frontend").resolve("vietlott-web.css");
        this.jsFile = rootDir.resolve("frontend").resolve("vietlott-web.js");
        this.faviconFile = rootDir.resolve("frontend").resolve("favicon.svg");
        this.dbFile = rootDir.resolve(DB_FILE);
        this.repo = new DatabaseRepo(dbFile);
    }

    private void start() throws Exception {
        if (!Files.exists(htmlFile)) {
            throw new FileNotFoundException("Không tìm thấy file: " + htmlFile);
        }

        HttpServer server = HttpServer.create(new InetSocketAddress(PORT), 0);
        server.createContext("/", this::serveIndex);
        server.createContext("/vietlott-web.css", ex -> serveStaticTextFile(ex, cssFile, "text/css; charset=UTF-8"));
        server.createContext("/vietlott-web.js", ex -> serveStaticTextFile(ex, jsFile, "application/javascript; charset=UTF-8"));
        server.createContext("/favicon.svg", this::serveFavicon);
        server.createContext("/api/me", this::handleMe);
        server.createContext("/api/register", this::handleRegister);
        server.createContext("/api/login", this::handleLogin);
        server.createContext("/api/logout", this::handleLogout);
        server.createContext("/api/store", this::handleStore);
        server.createContext("/api/keno-predict-data", this::handleKenoPredictData);
        server.createContext("/api/keno-predict", this::handleKenoPredict);
        server.createContext("/api/ai-predict", this::handleAiPredict);
        server.createContext("/api/ai-score", this::handleAiScore);
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
        server.setExecutor(Executors.newCachedThreadPool());
        server.start();

        System.out.println("Lotto Web Server chạy tại http://localhost:" + PORT + "/");
        System.out.println("DB file: " + dbFile.toAbsolutePath());
    }

    // ----- Tài nguyên tĩnh -----
    // Phục vụ file HTML chính, favicon và phản hồi 404 cơ bản.
    private void serveIndex(HttpExchange ex) throws IOException {
        if (!"GET".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }
        String path = ex.getRequestURI() == null ? "/" : ex.getRequestURI().getPath();
        if (!"/".equals(path)
                && !"/index.html".equals(path)
                && !"/vong-quay".equals(path)
                && !"/vong-quay.html".equals(path)
                && !"/nap-tien".equals(path)
                && !"/nap-tien.html".equals(path)) {
            sendNotFound(ex);
            return;
        }
        byte[] bytes = Files.readAllBytes(htmlFile);
        Headers h = ex.getResponseHeaders();
        h.set("Content-Type", "text/html; charset=UTF-8");
        h.set("Cache-Control", "no-store, no-cache, must-revalidate");
        h.set("Pragma", "no-cache");
        h.set("Expires", "0");
        ex.sendResponseHeaders(200, bytes.length);
        try (OutputStream os = ex.getResponseBody()) {
            os.write(bytes);
        }
    }

    private void serveFavicon(HttpExchange ex) throws IOException {
        if (!"GET".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }
        if (!Files.exists(faviconFile)) {
            sendNotFound(ex);
            return;
        }
        byte[] bytes = Files.readAllBytes(faviconFile);
        Headers h = ex.getResponseHeaders();
        h.set("Content-Type", "image/svg+xml");
        ex.sendResponseHeaders(200, bytes.length);
        try (OutputStream os = ex.getResponseBody()) {
            os.write(bytes);
        }
    }

    private void serveStaticTextFile(HttpExchange ex, Path file, String contentType) throws IOException {
        if (!"GET".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }
        if (file == null || !Files.exists(file)) {
            sendNotFound(ex);
            return;
        }
        byte[] bytes = Files.readAllBytes(file);
        Headers h = ex.getResponseHeaders();
        h.set("Content-Type", contentType);
        h.set("Cache-Control", "no-store, no-cache, must-revalidate");
        h.set("Pragma", "no-cache");
        h.set("Expires", "0");
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

    private void handleRegister(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        if (!"POST".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }
        Map<String, String> f = parseForm(ex);
        String user = normalizeUser(f.get("username"));
        String pass = nvl(f.get("password")).trim();
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
        try {
            Account acc = repo.getUser(user);
            if (acc == null || !acc.enabled || !verifyPassword(pass, acc.salt, acc.passwordHash)) {
                sendJson(ex, 401, "{\"ok\":false,\"message\":\"Sai tài khoản hoặc mật khẩu\"}");
                return;
            }

            String token = UUID.randomUUID().toString() + Long.toHexString(random.nextLong());
            sessions.put(token, user);
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
        if (token != null) sessions.remove(token);
        setCookie(ex, COOKIE_NAME, "", true);
        sendJson(ex, 200, "{\"ok\":true}");
    }

    private void handleStore(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        SessionUser su = requireAuth(ex, true);
        if (su == null) return;
        if ("GET".equalsIgnoreCase(ex.getRequestMethod())) {
            try {
                String store = repo.getStore(su.username);
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
                repo.setStore(su.username, store);
                sendJson(ex, 200, "{\"ok\":true}");
            } catch (IllegalArgumentException e) {
                sendJson(ex, 400, "{\"ok\":false,\"message\":\"" + esc(e.getMessage()) + "\"}");
            } catch (RuntimeException e) {
                sendJson(ex, 500, "{\"ok\":false,\"message\":\"Lỗi DB khi lưu store: " + esc(rootCauseMsg(e)) + "\"}");
            }
            return;
        }
        sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
    }

    private void handleRecoverAdmin(HttpExchange ex) throws IOException {
        if (handleOptions(ex)) return;
        if (!"POST".equalsIgnoreCase(ex.getRequestMethod())) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }
        Map<String, String> f = parseForm(ex);
        String newPass = nvl(f.get("password")).trim();
        if (newPass.length() < 4) {
            sendJson(ex, 400, "{\"ok\":false,\"message\":\"Mật khẩu tối thiểu 4 ký tự\"}");
            return;
        }
        try {
            String adminUser = repo.recoverAdmin(newPass);
            sendJson(ex, 200, "{\"ok\":true,\"username\":\"" + esc(adminUser) + "\"}");
        } catch (RuntimeException e) {
            sendJson(ex, 500, "{\"ok\":false,\"message\":\"Lỗi DB khi khôi phục admin: " + esc(rootCauseMsg(e)) + "\"}");
        }
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
        if (!"POST".equalsIgnoreCase(method) && !"GET".equalsIgnoreCase(method)) {
            sendJson(ex, 405, "{\"ok\":false,\"message\":\"Method not allowed\"}");
            return;
        }
        Map<String, String> f = "POST".equalsIgnoreCase(method)
                ? parseForm(ex)
                : parseQuery(ex.getRequestURI() == null ? null : ex.getRequestURI().getRawQuery());
        // GET is kept only for compatibility with older admin flows.
        String user = normalizeUser(f.get("username"));
        int diamond = parseNonNegativeInt(f.get("diamond"));
        int paypal = parseNonNegativeInt(f.get("paypal"));
        try {
            repo.updateAssets(user, diamond, paypal);
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
        if (user == null) {
            if (sendErr) sendJson(ex, 401, "{\"ok\":false,\"message\":\"Phiên đăng nhập đã hết hạn\"}");
            return null;
        }
        Account acc = repo.getUser(user);
        if (acc == null || !acc.enabled) {
            sessions.remove(token);
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
        pb.redirectOutput(ProcessBuilder.Redirect.appendTo(logFile));
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
        byte[] out = json.getBytes(StandardCharsets.UTF_8);
        Headers h = ex.getResponseHeaders();
        addCors(ex);
        h.set("Content-Type", "application/json; charset=UTF-8");
        ex.sendResponseHeaders(status, out.length);
        try (OutputStream os = ex.getResponseBody()) {
            os.write(out);
        }
    }

    private boolean handleOptions(HttpExchange ex) throws IOException {
        if (!"OPTIONS".equalsIgnoreCase(ex.getRequestMethod())) return false;
        addCors(ex);
        ex.sendResponseHeaders(204, -1);
        ex.close();
        return true;
    }

    private void addCors(HttpExchange ex) {
        String origin = ex.getRequestHeaders().getFirst("Origin");
        Headers h = ex.getResponseHeaders();
        if (origin == null || isBlank(origin)) origin = "*";
        h.set("Access-Control-Allow-Origin", origin);
        h.set("Vary", "Origin");
        h.set("Access-Control-Allow-Credentials", "true");
        h.set("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
        h.set("Access-Control-Allow-Headers", "Content-Type");
    }

    private Map<String, String> parseForm(HttpExchange ex) throws IOException {
        String body = new String(readAllBytes(ex.getRequestBody()), StandardCharsets.UTF_8);
        return parseUrlEncoded(body);
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

    private static String esc(String s) {
        if (s == null) return "";
        return s.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n").replace("\r", "");
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
                    if (rs.next()) return rs.getString(1);
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

        synchronized void updateAssets(String user, int diamond, int paypal) {
            if (getUser(user) == null) throw new IllegalStateException("Không tìm thấy tài khoản");
            String store = getStore(user);
            if (store == null || isBlank(store)) store = "{}";
            store = upsertJsonNumber(store, "diamondBalance", Math.max(0, diamond));
            store = upsertJsonNumber(store, "paypalBalance", Math.max(0, paypal));
            setStore(user, store);
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
            if (json == null || isBlank(json)) return 0;
            String regex = "\\\"" + key + "\\\"\\s*:\\s*(-?\\d+)";
            java.util.regex.Matcher m = java.util.regex.Pattern.compile(regex).matcher(json);
            if (!m.find()) return 0;
            try {
                return Integer.parseInt(m.group(1));
            } catch (NumberFormatException ex) {
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
                p1.setString(1, user);
                p1.executeUpdate();
                p2.setString(1, user);
                p2.executeUpdate();
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
