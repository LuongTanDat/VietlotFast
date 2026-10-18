# Kiến Trúc Dự Án

Tổng quan cấu trúc thư mục, backend, frontend, AI và luồng dữ liệu.

- `ai/`: mã AI, predictor, model, config, training
  Bên trong `ai/standalone_predictors/`: predictor standalone cho Vip 5/35, Mega 6/45, Power 6/55 và predictor_v2 legacy
- `docs/`: tài liệu vận hành và ghi chú dự án
- `data/`: dữ liệu canonical và export scoring
- `backend/`: backend Python, Java server, thư viện JDBC
- `frontend/`: giao diện HTML, CSS, JavaScript
- `frontend/vietlott-web-numeric.js`: bộ định dạng số nguyên dùng chung, tải trước effectiveness/core/admin. Theo dõi vùng thay thế của IME để thêm dấu chấm mà không lặp chữ số; giữ con trỏ/vùng chọn, giá trị 0 mặc định và quy tắc kiểm tra nhóm số. Ô theo dõi truyền callback giới hạn theo game/bậc; tài khoản/quà tặng giữ giới hạn khi lưu hiện có. Java phục vụ qua route tĩnh riêng.
  Trang chủ giữ bảng kết quả live; lịch sử CSV chỉ xem tại Bảng Dữ Liệu. Bộ đọc/cache canonical và `/api/live-history` dùng chung cho bảng/Excel, thống kê và đối chiếu dự đoán; khung Lịch Sử CSV Tự Động riêng đã được gỡ.
- `runtime/`: database runtime và log
- `scripts/`: script chạy dự án
- `tests/`: khu vực test
- `Bin/`: lưu gói build theo phiên bản

Chi tiết `Bin/`:

- `Bin/session_1_latest/files/ai/`: snapshot AI của phiên gần nhất
- `Bin/session_1_latest/files/backend/`: snapshot backend của phiên gần nhất
- `Bin/session_1_latest/files/frontend/`: snapshot frontend của phiên gần nhất
- `Bin/session_1_latest/files/data/`: snapshot data của phiên gần nhất
- `Bin/session_1_latest/manifest.json`: metadata phiên gần nhất
- `Bin/session_2_previous/files/ai/`: snapshot AI của phiên cũ hơn
- `Bin/session_2_previous/files/backend/`: snapshot backend của phiên cũ hơn
- `Bin/session_2_previous/files/frontend/`: snapshot frontend của phiên cũ hơn
- `Bin/session_2_previous/files/data/`: snapshot data của phiên cũ hơn
- `Bin/session_2_previous/manifest.json`: metadata phiên cũ hơn

## Đăng nhập và OAuth

- `frontend/vietlott-web-auth.css`: giao diện đăng nhập riêng, tải sau CSS chung; không tác động trang đã đăng nhập.
- `frontend/vietlott-web-auth.js`: trạng thái/click nút mạng xã hội, gọi API start và chuyển sang nhà cung cấp; Enter trong các ô vẫn dùng luồng tài khoản cục bộ.
- `backend/LottoWebServer.java`: `/api/auth/social/providers`, `/api/auth/social/start`, `/api/auth/social/callback/{provider}`; state/PKCE và token exchange/profile validation chạy ở backend. Cấu hình từ `runtime/social-login.properties` hoặc môi trường; endpoint provider cố định. Bảng `social_identities` liên kết ID provider với `users`; dùng phiên hiện có, không lưu token.
- `config/social-login.properties.example` và `docs/DangNhapMangXaHoi.md`: mẫu không có khóa thật và hướng dẫn callback/ứng dụng.
- `tests/SocialOAuthFixture.java`: transport HTTPS giả chỉ trong entry point kiểm thử, không được đưa vào build triển khai; `tests/test_social_login.py` kiểm tra ba adapter và UI Chrome.

## Theo dõi danh mục lớn

- `ai/tracking_progress.py` theo dõi ba pha updating/creating/scoring ở tiến trình cha, ghi file nhỏ `runtime/effectiveness_progress_<game>.json` bằng thay thế nguyên tử và heartbeat 2 giây. Chỉ ghi telemetry, không sửa bảng lịch sử/tài khoản. ETA dùng phép đo ban đầu và tỷ lệ công việc đã hoàn tất; lỗi tiến trình được lưu riêng.
- `/api/ml/effectiveness-progress?type=...` yêu cầu đăng nhập, đọc file giới hạn 8 KiB, no-store, kiểm tra game/pha và heartbeat 20 giây; không gọi Python hoặc mở DB tracking. Frontend hỏi mỗi 3 giây khi tab hoạt động, đếm ETA tại chỗ, timeout request 8 giây, hủy khi đổi loại/phiên/đóng tab. Ô trạng thái nằm cạnh Loại xổ số, lỗi có thông báo riêng.
- ai/tracking_storage.py chuyển snapshot actor hệ thống và các bảng theo dõi sang runtime/tracking_ledger.db, giữ DB nguồn runtime/lotto_web.db cho tài khoản, ví, dự đoán cá nhân và registry. runtime/tracking-storage.json chỉ kích hoạt sau khi sao chép/kiểm tra xong; đường DB kiểm thử được chỉ định trực tiếp vẫn độc lập. Không tạo lịch sử trống khi thiếu DB đã chuyển.
- ai/tracking_portfolio.py hỗ trợ ngân sách yêu cầu đến 1.000.000; giới hạn theo tổ hợp khác nhau và giữ thứ tự/seed khi unrank bằng NumPy. ai/tracking_capacity.py kiểm tra dung lượng cho JSON, khối vé, WAL và staging, cộng 20 GB dự phòng.
- ai/keno_effectiveness.py chuẩn bị và chấm danh mục bằng tối đa bốn tiến trình, tối đa nửa số luồng CPU. Worker tạo không ghi DB; worker chấm chỉ mở DB read-only. Parent kiểm tra checksum/deadline/nguồn/cấu hình, ghi đủ 40 dự đoán hoặc toàn bộ điểm trong một giao dịch.
- effectiveness_ticket_index và effectiveness_ticket_chunks là dữ liệu phụ trợ bất biến, ghi cùng vé gốc; danh mục trên 10.000 vé chia khối 1.000 để đọc trang nhỏ. Dự đoán/điểm đã khóa giữ nguyên.
- ai/effectiveness_xlsx.py tạo XLSX nén trực tiếp ở backend cho danh mục lớn; Java gửi file theo luồng và dọn đúng file tạm. Trình duyệt tải file, không dựng hàng triệu dòng JSON/XML. File có Tổng quan và bốn phương pháp, AutoFilter và hàng đầu cố định.
