# Sửa các cột CSV còn sót

Nguyên nhân: schema chung giữ cột trùng dữ liệu hoặc không áp dụng cho từng game.

Đã đối chiếu với Bin/session_1_latest: giữ nguyên toàn bộ dòng và giá trị của các cột còn lại trong 6 CSV canonical và 3 snapshot predictor. 81 kiểm thử liên quan đã qua; lịch sử Java kiểm tra cả Max 3D/Pro, số 0 đầu và bộ lặp.

| File | Số dòng | Cột sau khi dọn |
|---|---:|---|
| data/canonical/loto_5_35_all_day.csv | 925 | Kỳ, Thứ, Ngày, Giờ, Bộ Số, ĐB, Link cập nhật, Ngày cập nhật, Giải Đặc biệt (VNĐ) |
| data/canonical/mega_6_45_all_day.csv | 1569 | Kỳ, Thứ, Ngày, Giờ, Bộ Số, Link cập nhật, Ngày cập nhật, Jackpot (VNĐ) |
| data/canonical/power_6_55_all_day.csv | 1402 | Kỳ, Thứ, Ngày, Giờ, Bộ Số, ĐB, Link cập nhật, Ngày cập nhật, Jackpot 1 (VNĐ), Jackpot 2 (VNĐ) |
| data/canonical/keno_all_day.csv | 24102 | Kỳ, Thứ, Ngày, Giờ, Bộ Số, Lớn/-/Nhỏ, Chẵn/-/Lẻ, Link cập nhật |
| data/canonical/max_3d_all_day.csv | 1140 | Kỳ, Thứ, Ngày, Hiển thị, Link cập nhật, Ngày cập nhật |
| data/canonical/max_3d_pro_all_day.csv | 787 | Kỳ, Thứ, Ngày, Hiển thị, Link cập nhật, Ngày cập nhật |
| ai/standalone_predictors/loto_5_35_predictor/data/loto_5_35.csv | 556 | Kỳ, Thứ, Ngày, Giờ, Bộ Số, ĐB, Link cập nhật, Ngày cập nhật, Giải Đặc biệt (VNĐ) |
| ai/standalone_predictors/mega_6_45_predictor/data/mega_6_45.csv | 1490 | Kỳ, Thứ, Ngày, Giờ, Bộ Số, Link cập nhật, Ngày cập nhật, Jackpot (VNĐ) |
| ai/standalone_predictors/power_6_55_predictor/data/power_6_55.csv | 1323 | Kỳ, Thứ, Ngày, Giờ, Bộ Số, ĐB, Link cập nhật, Ngày cập nhật, Jackpot 1 (VNĐ), Jackpot 2 (VNĐ) |

Bộ ghi dùng schema riêng; các script dọn dữ liệu chấp nhận cả schema cũ và mới. Bộ đọc dựng lại phần hiển thị và nhãn game trong bộ nhớ. Chạy lại script dọn snapshot: không có thay đổi dữ liệu hoặc cột.
