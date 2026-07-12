# Vietlott Tra Cứu Nhanh Pro

Tên repo/nội bộ: `VietlotFast` / `Lotto`

Đây là ứng dụng web chạy cục bộ để tra cứu kết quả Vietlott, cập nhật dữ liệu CSV, dự đoán bộ số tham khảo, thống kê, phân tích, quản lý tài khoản và quản lý lịch sử dự đoán theo từng người dùng.

> Lưu ý: các tính năng dự đoán, thống kê và phân tích chỉ có giá trị tham khảo. Dự án không cam kết kết quả trúng thưởng.

## Loại Dự Án

- Web application full-stack chạy cục bộ trên máy Windows.
- Frontend HTML/CSS/JavaScript thuần.
- Backend Java HTTP server phục vụ giao diện, API và SQLite.
- Python data/AI pipeline cho đồng bộ kết quả, thống kê, phân tích, dự đoán, backtest và ML ledger.
- Bộ công cụ quản lý dữ liệu Vietlott bằng CSV/JSON/SQLite.

## Ngôn Ngữ Và Công Nghệ

- HTML5: giao diện chính trong `frontend/vietlott-web.html`.
- CSS3: style giao diện trong `frontend/vietlott-web.css` và `frontend/vietlott-web-extra.css`.
- JavaScript: logic UI, live data, dự đoán, thống kê, dashboard trong các file `frontend/*.js`.
- Java: server web/API trong `backend/LottoWebServer.java`.
- Python: backfill, live results, AI, ML, thống kê, phân tích trong `backend/*.py` và `ai/**/*.py`.
- SQLite: lưu user, session/store runtime và prediction ledger trong `runtime/lotto_web.db`.
- JDBC SQLite: driver `backend/lib/sqlite-jdbc-3.51.2.0.jar`.
- Batch/PowerShell: script khởi động trong `scripts/*.bat`.
- CSV/JSON: dữ liệu canonical, meta, model, scoring export và backtest audit.

## Các Loại Vé Hỗ Trợ

- `LOTO_5_35`: Loto 5/35.
- `LOTO_6_45`: Mega 6/45.
- `LOTO_6_55`: Power 6/55.
- `KENO`: Keno.
- `MAX_3D`: Max 3D.
- `MAX_3D_PRO`: Max 3D Pro.

## Các Nút Chức Năng Chính

### Đăng Nhập Và Tài Khoản

- `Đăng nhập`: đăng nhập vào ứng dụng và tải store riêng theo user.
- `Đăng ký` / `Tạo tài khoản`: tạo tài khoản mới.
- Nút mắt trong ô mật khẩu: ẩn/hiện mật khẩu đăng nhập, đăng ký và nhập lại mật khẩu.
- `Quên mật khẩu admin`: khôi phục mật khẩu admin cục bộ.
- `Đăng xuất`: thoát phiên hiện tại.
- `Quản lý tài khoản`: dành cho admin, mở bảng quản lý user.
- `Sửa`, `Lưu`, `Đóng`: sửa và lưu thông tin tài khoản trong popup admin.
- `Đổi mật khẩu`, `Xóa`: thao tác theo từng dòng trong bảng quản lý tài khoản.
- Nút đổi giao diện sáng/tối: lưu theme vào localStorage.

### Menu Và Điều Hướng

- `Mở menu` / nút đóng menu / overlay: mở và đóng side menu.
- `Trang chủ`: quay về màn hình chính.
- `Nạp tiền tài khoản`: mở màn nạp PayPal nội bộ.
- `Bảng Dữ Liệu`: mở bảng dữ liệu canonical CSV.
- `Vòng Quay May Mắn`: mở màn vòng quay.

Một số item side menu hiện là mục hiển thị/chưa có handler riêng: `Thông tin tài khoản`, `Nhật kí hoạt động`, `Lịch sử hoàn tiền`, `Cấp bậc Tài khoản`, `Chương trình Affiliates`.

### Bảng Dữ Liệu Canonical CSV

- `Hiển thị`: tải và hiển thị dữ liệu theo loại vé, số dòng và bộ lọc thời gian.
- `Tải Xuống`: xuất bảng hiện tại thành file tải về.
- `Xóa lọc`: reset bộ lọc thứ/ngày/tháng/năm.
- Các select `Loại`, `Số lượng`, `Thứ`, `Ngày`, `Tháng`, `Năm`: điều khiển tập dữ liệu đang xem.

### Nạp Tiền PayPal Nội Bộ

- `Tạo yêu cầu nạp`: tạo yêu cầu nạp, tính gói nạp/bonus và ghi lịch sử trong store.
- `Làm mới form`: reset form nạp tiền.
- Các nút gói nạp: chọn package nạp theo `data-package-id`.

### Vòng Quay May Mắn

- `x1`, `x3`, `x5`, `x10`: chọn hệ số số lần quay.
- Nút giữa vòng quay `QUAY NGAY`: quay một lần.
- `QUAY TỰ ĐỘNG`: bật/tắt quay tự động.
- `Mua Thêm Lượt Quay`: mở hộp thoại đổi PayPal lấy lượt quay.
- `Hủy`, `Xác nhận đổi`: hủy hoặc xác nhận đổi thêm lượt.
- Nút tăng/giảm trong hộp thoại: chỉnh số lượt muốn đổi.

### Cập Nhật Kết Quả Và Lịch Sử

- `Cập Nhật`: đồng bộ kết quả live, repair canonical khi cần.
- `Xem lịch sử CSV`: tải lịch sử CSV theo loại và số kỳ.
- `Cập Nhật` trong khung lịch sử: làm mới nhanh cửa sổ lịch sử gần đây.
- `Xem Cơ Cấu Thưởng`: hiện cơ cấu giải thưởng/luật trúng thưởng theo loại vé.

### Dự Đoán, Thống Kê Và Phân Tích

- Tab `Dự Đoán Thường`: màn dự đoán thường.
- Tab `Dự Đoán Vip`: màn dự đoán Vip.
- Tab `Thống Kê`: thống kê gần đây.
- Tab `Thống Kê V2`: thống kê tần suất/combo theo kỳ, ngày, custom range.
- Tab `Biểu Đồ`: biểu đồ thống kê.
- Tab `Dashboard`: dashboard tổng hợp theo game.
- Tab `Phân Tích`: phân tích xác suất, pattern, overdue, chuỗi, quan hệ cặp số.

Trong màn dự đoán:

- `Lịch Sử` / `Lịch Sử Vip`: mở lịch sử dự đoán.
- `Huấn Luyện: Tắt/Bật`: bật/tắt huấn luyện Keno khi có.
- `Cả 2`, `Luận Số`, `AI Gen`: chọn engine dự đoán.
- `Ổn Định`, `Cân Bằng`, `Tấn Công`: chọn mức rủi ro khi kết hợp engine.
- `Dự đoán` / `Dự đoán Vip`: chạy luồng dự đoán và lưu lịch sử.
- Các nút lịch sử: đóng popup, lùi/tiến bản ghi, cập nhật, lọc theo loại/khoảng/play mode, mở rộng chi tiết và copy kết quả.

Trong màn thống kê/phân tích/dashboard:

- `Làm mới`, `Cập nhật`: tải lại dashboard, thống kê hoặc phân tích.
- `Lưu lại`, `Mua ngay`: thao tác trên selection của Thống Kê V2.
- `Lưu phân tích`: lưu kết quả phân tích vào lịch sử local.
- Các tab/filter động: chọn loại vé, kỳ/ngày, combo size, sort, group, activity view, distribution view, analysis mode.

## Cấu Trúc Thư Mục

- `ai/`: predictor, model, training, config, ML pipeline, stats và analysis.
- `backend/`: Java web server, Python live/backfill jobs và thư viện JDBC.
- `frontend/`: HTML/CSS/JS của ứng dụng web.
- `data/`: dữ liệu canonical CSV/meta và scoring exports.
- `runtime/`: SQLite runtime, log, backtest audit.
- `scripts/`: batch script khởi động web và backfill.
- `tests/`: test cho analysis, stats, live results, ML pipeline, leakage và performance.
- `docs/`: tài liệu vận hành, kiến trúc, nhật ký thay đổi và báo cáo nút chức năng.
- `Bin/`: snapshot/phiên bản đóng gói.

## Cài Đặt Phụ Thuộc Python

```bash
python -m pip install -r requirements.txt
```

`requirements.txt` hiện gồm:

- `beautifulsoup4`
- `numpy`
- `requests`

Một số predictor standalone có `requirements.txt` riêng trong từng thư mục con.

## Chạy Website

Trên Windows, chạy script:

```bat
scripts\chay_lotto_web.bat
```

Script sẽ:

- Tìm `java.exe` và `javac.exe`.
- Kiểm tra cổng `8080`.
- Biên dịch `backend/LottoWebServer.java` vào `backend/bin`.
- Chạy server với SQLite JDBC.
- Mở trình duyệt tại `http://localhost:8080/`.

## Chạy Backfill/Cập Nhật Dữ Liệu Nền

```bat
scripts\chay_lotto_backfill.bat
```

Xem nhanh trạng thái:

```bat
scripts\chay_lotto_backfill.bat status
```

## ML Pipeline Có Kiểm Soát

Workflow ML có kiểm soát đang hỗ trợ `KENO`, `LOTO_5_35`, `LOTO_6_45` và `LOTO_6_55`.

Lệnh thường dùng:

```bash
python ai/predictors/ai_predict.py ml_status
python ai/predictors/ai_predict.py predict_json KENO 1 10 --engine=classic --pure
python ai/predictors/ai_predict.py ml_backtest KENO --mode=fast --window=expanding
python ai/predictors/ai_predict.py ml_backtest LOTO_6_45 --mode=fast --window=expanding
python ai/predictors/ai_predict.py ml_score_pending LOTO_6_45
python ai/predictors/ai_predict.py ml_train_candidate LOTO_6_45 --mode=fast
python ai/predictors/ai_predict.py ml_promote LOTO_6_45 --model-id=MODEL_ID
python ai/predictors/ai_predict.py ml_rollback LOTO_6_45
```

Backtest chạy walk-forward theo thứ tự kỳ quay. Mỗi fold chỉ dùng lịch sử trước kỳ target, từ chối artifact deep nếu `trained_on_latest_draw_id` không đúng cutoff, mô phỏng tracking tuần tự và ghi audit JSON vào `runtime/backtests/`.

## Dữ Liệu Và Lưu Trữ

- Canonical CSV: `data/canonical/*_all_day.csv`.
- Meta canonical: `data/canonical/*.meta.json`.
- Scoring export: `data/exports/scoring/`.
- Runtime DB: `runtime/lotto_web.db`.
- Backtest audit: `runtime/backtests/*.json`.
- Model/meta AI: `ai/models/` và các thư mục `ai/standalone_predictors/*/models/`.

## Test

Chạy test Python:

```bash
python -m pytest
```

Nếu chưa cài `pytest`, cài thêm trong môi trường Python đang dùng:

```bash
python -m pip install pytest
```
