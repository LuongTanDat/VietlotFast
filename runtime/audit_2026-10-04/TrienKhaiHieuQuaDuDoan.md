# Triển khai Hiệu quả dự đoán — 05/10/2026

Đã triển khai tab Hiệu quả dự đoán, tác vụ tự khóa/chấm kỳ thực tế và ba đối chứng ngẫu nhiên, Bayesian, EWMA. Server mới đang chạy tại `http://localhost:8080`; đã bật theo dõi 5/35, Mega và Power với 3 vé cho mỗi phương pháp ở mỗi kỳ. Các chu kỳ đầu đã khóa đủ bốn phương pháp, chưa có kết quả nên chỉ số hiệu quả để trống.

| Game | Kỳ đã khóa | Cutoff dữ liệu | Hạn khóa/giờ quay theo lịch (Việt Nam) |
|---|---:|---:|---|
| Loto 5/35 | 927 | 926 | 05/10/2026 13:00 |
| Mega 6/45 | 1572 | 1571 | 07/10/2026 18:00 |
| Power 6/55 | 1407 | 1406 | 06/10/2026 18:00 |

## Hành vi đã hoàn thành

- Theo dõi pipeline web thường classic/balanced, gồm chọn strategy/fallback và Adaptive Coverage; nếu có champion hợp lệ thì ghi đúng engine/model thực được production dùng. Lịch sử canonical được ghim chỉ đọc khi tạo dự đoán, không thay thuật toán production.
- Đối chứng cùng cỡ vé/số vé và cùng snapshot: ngẫu nhiên với seed cố định theo chu kỳ, Bayesian prior 100 kỳ, EWMA bán rã 60 kỳ có co về prior. Tham số được cố định trước theo dõi, không chọn phương pháp thắng trên kết quả mục tiêu.
- Một game/kỳ chỉ khóa một lần. Bốn prediction và mapping ghi trong cùng giao dịch; hủy toàn bộ nếu dữ liệu/config/model/code thay đổi hoặc hết deadline. Lưu cutoff, deadline UTC+7, checksum dữ liệu/payload, config và seed thực của Adaptive Coverage.
- Worker Java kiểm tra mỗi 60 giây, chấm pending khi canonical đã có đúng kỳ thực tế và tạo kỳ tiếp theo cho game bật theo dõi. Chấm bốn phương pháp cùng giao dịch, kiểm tra tính hợp lệ của kết quả và checksum. Scorer chung không được chấm riêng các run hệ thống.
- API xem yêu cầu đăng nhập; lưu cấu hình/khóa ngay yêu cầu admin. Tên actor hệ thống được giữ riêng, không thể đăng ký/đổi tên/đăng nhập bằng tên đó. Dashboard không đọc/chấm lịch sử cá nhân.
- Bảng có số kỳ, số trùng trung bình mỗi vé, tỷ lệ vé trùng ≥3/≥4, Brier/log loss, chênh lệch với đối chứng và CI bootstrap ghép cặp theo kỳ. Biểu đồ có bật/tắt từng phương pháp; nhật ký mở được bộ số dự đoán và kết quả thật, tô số trùng và hiện engine/model.
- Tổng hợp dùng tất cả chu kỳ đã chấm hoàn chỉnh; lựa chọn 30/100/300 chỉ giới hạn nhật ký. Ghi rõ khi gộp nhiều cấu hình/ngân sách. Dữ liệu rỗng dùng dấu —, không tạo điểm lịch sử hoặc confidence giả.

## Kiểm thử và xác minh

- **182/182 unittest chính đạt**, gồm 20 kiểm thử prospective, 5 kiểm thử HTTP Java/Python và 1 kiểm thử giao diện Chrome mới. Log: `effectiveness_final_tests.log`.
- Kiểm thử chống khóa kỳ cũ/hết hạn, dữ liệu nguồn đổi, xác suất/vé sai, giao dịch ghi dở, payload đổi, kết quả canonical hỏng, sai slot, gọi lại cùng kỳ và scorer chung chạm run hệ thống.
- Chrome thử dữ liệu rỗng, pending/scored, bảng/biểu đồ, số trùng, quyền admin, lỗi API, chèn HTML, đổi tài khoản/logout và màn hình 390px. Fixture HTTP đầy đủ xác minh frontend boot, tab mới, phân quyền và cấu hình lưu thật vào DB tạm.
- Probe gọi pipeline web thật cho cả ba game trên dữ liệu hiện có, khóa vào DB tạm: CSV/model sản xuất không đổi. Bằng chứng: `effectiveness_real_pipeline_result.json`.
- HTTP vận hành: `/api/time` 200; ba route mới chưa đăng nhập 401; JS phục vụ khớp file mới và ETag trả 304. Bằng chứng: `effectiveness_production_http.json`.
- Sau bật tự động: mỗi game có một chu kỳ pending, không có điểm đã chấm giả. `PRAGMA quick_check=ok`, users/stores vẫn 1/1. Bằng chứng: `effectiveness_production_setup.json`, `effectiveness_production_reports.json`.
- Đã quan sát worker server tự chạy ở lượt sau, timestamp tăng ở cả ba game, không lỗi và không khóa trùng: vẫn 3 chu kỳ/12 prediction/0 điểm đã chấm. Bằng chứng: `effectiveness_worker_verification.json`.
- Backup trước sửa nằm trong `Bin/session_1_latest`, gồm code/build và snapshot SQLite nhất quán có dữ liệu WAL. Không đổi CSV/model sản xuất, không tự promote. Server log: `runtime/logs/server_effectiveness_2026-10-05.*.log`.

## Cách dùng và giới hạn

Ctrl+F5 rồi đăng nhập lại, mở **Dự đoán → Hiệu quả dự đoán**. Admin có thể đổi số vé, tắt/bật từng game hoặc khóa kỳ ngay; mọi thay đổi chỉ áp dụng kỳ chưa khóa. Làm mới báo cáo chỉ đọc dữ liệu.

Server phải đang chạy và kết quả canonical phải được cập nhật theo luồng hiện có để tự chấm và tiến sang kỳ mới. Không tạo ngược dự đoán khi server tắt hoặc thiếu kết quả. Số chính là phạm vi đánh giá hiện tại; đoán đúng số phụ Power không được gọi là trúng Jackpot 2.

Xác suất biên vẫn chưa hiệu chỉnh ngoài mẫu. Dưới 30 kỳ báo chưa đủ bằng chứng; CI dương chỉ là tín hiệu trong mẫu, chưa điều chỉnh thử nhiều phương pháp. Chưa có kết quả tương lai nào được chấm lúc triển khai; hệ thống này giúp kiểm chứng lợi thế, không bảo đảm dự đoán đúng kỳ tới. Calibration, logistic regression, backtest toàn luồng web trên các snapshot lịch sử và replay đầy đủ vẫn là bước phát triển tiếp.
