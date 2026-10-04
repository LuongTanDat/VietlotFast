# Cột Nổ sau tiền thưởng

Cột mới chỉ có nội dung khi số lượng vé trúng giải tương ứng lớn hơn 0. Các dòng khác để trống. Đã đối chiếu đầy đủ 3.896 kỳ và giữ nguyên tất cả các giá trị trước đó trong 6 CSV (canonical và bản sao predictor).

| Game | Kỳ đã xác minh | Đánh dấu |
|---|---:|---|
| LOTO_5_35 | 925 | ĐB: 42 |
| LOTO_6_45 | 1569 | Jackpot: 165 |
| LOTO_6_55 | 1402 | Jackpot 2: 330, Jackpot 1: 40, Jackpot 1, 2: 18 |

Power dùng `Jackpot 1, 2` khi cả hai giải có vé trúng. Không lấy việc tiền thưởng giảm làm bằng chứng nổ.

Nguồn chính: bảng Số lượng trên MinhChinh, lưu HTML và JSON của từng trang trong `pages/`; kết quả từng kỳ trong `verified_draws.json`.

Mega #506 dùng [nguồn dự phòng](https://www.ketquadientoan.com/ket-qua-xo-so-dien-toan-mega-6-45/16-10-2019.html): số lượng Jackpot bằng 0. Đã kiểm tra kỳ, ngày và đủ sáu số trước khi dùng dữ liệu.

Chi tiết bảo toàn dữ liệu: `verification.json`. Backup trước khi thêm cột: `Bin/session_1_latest/files/`.

Kiểm thử: 85 test CSV/parser/API/giao diện/thống kê/phân tích và 3 test loader predictor đều qua (88 tổng cộng).
