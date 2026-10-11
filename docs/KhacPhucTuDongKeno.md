# Khắc phục Keno không tự chuyển kỳ — 09/10/2026

Nguyên nhân là worker Hiệu quả dự đoán chỉ đọc CSV canonical để chấm và khóa vé, chưa tự lấy kết quả Keno. Theo dõi vẫn bật, worker vẫn có `last_tick`, nhưng dữ liệu dừng ở kỳ 298625 lúc 10:24; đến lúc kiểm tra, hạn kỳ 10:32 đã qua. Lần Cập Nhật toàn bộ vừa chạy từ 10:31:16 đến 10:36:15, mất gần năm phút, nên không đáp ứng chuyển kỳ liên tục. Guard chặn khóa quá hạn đã hoạt động đúng.

Đã thêm `backend/keno_live_sync.py` và tích hợp vào tick Keno đang được Java gọi mỗi phút. Luồng mới lấy một trang kết quả gần nhất từ MinhChinh với User-Agent của crawler, timeout kết nối/đọc 4/12 giây và không lặp retry dài; có trang trực tiếp dự phòng. Khi một kỳ đã khóa còn thiếu kết quả, có thể hỏi đúng mã/ngày của tối đa ba kỳ trong lượt, thay vì quét hàng trăm ngày. Không chạy training, export scoring hoặc full repair trong lượt này.

Mỗi lượt thực hiện **lấy kết quả → thêm CSV → chấm kỳ đã khóa → xét khóa kỳ kế tiếp**. Kiểm tra mã kỳ, 20 số riêng biệt trong 1–80, ngày/giờ theo lịch tám phút, dữ liệu tương lai và chuỗi kỳ liên tiếp trước khi ghi. Kỳ qua hạn vẫn phải chờ kết quả thật; không tạo ngược các dự đoán đã bỏ lỡ. Kết quả về trễ được chấm theo mã kỳ/deadline đã lưu.

Loader/writer của lượt cập nhật nhanh có chế độ giữ nguyên lịch sử, tránh hàm chuẩn hóa giờ cũ tác động các bất thường đã xác minh. Chỉ thêm dòng mới, không thay kết quả cũ khi nguồn mâu thuẫn. Writer dùng khóa/version hiện có và đọc lại tối đa ba lần khi có cập nhật đồng thời. Nguồn không có kỳ mới thì không ghi lại CSV/metadata.

Đồng bộ chạy khi theo dõi bật hoặc còn kỳ pending; tắt theo dõi vẫn lấy/chấm vé đã khóa và không tạo vé mới. Đọc báo cáo và tick trên DB fixture không gọi mạng. Ban đêm ngừng polling ngoài 06:08–22:02; dự đoán qua đêm vẫn lấy giờ 06:08 ngày sau từ canonical. Lượt lỗi được thử lại sau khoảng một phút; kết quả canonical đang có vẫn được chấm.

SQLite thêm bảng một dòng `keno_effectiveness_source_state` để lưu lần thử/lần thành công, trạng thái, kỳ nguồn và lỗi. Báo cáo trả `automation.sourceSync`; giao diện hiển thị **Tự cập nhật Keno**, kỳ CSV và thời gian kiểm tra. Thông báo chờ nguồn dùng câu ngắn; chi tiết lỗi nằm trong dữ liệu trạng thái để chẩn đoán.

Đã kiểm chứng trên server đang chạy:

| Kỳ | Giờ quay | Giờ khóa thực tế | Kết quả vận hành |
| --- | --- | --- | --- |
| 298629 | 10:56 | 10:49:55 | Worker tự lấy kết quả và chấm lúc 10:57:44 |
| 298630 | 11:04 | 10:57:58 | Worker tự lấy kết quả và chấm lúc 11:05:55 |
| 298631 | 11:12 | 11:06:09 | Khóa sau khi chấm 298630, trước giờ quay |

Giờ trong bảng dùng múi giờ Việt Nam. Mỗi chu kỳ đủ 40 nhóm (10 bậc × 4 phương pháp), mặc định 120 vé; mọi checksum hợp lệ và thời điểm khóa trước deadline. So với CSV backup đầu phiên, **24.663 dòng cũ giữ nguyên mọi trường**, chỉ bổ sung các kỳ mới. SQLite `quick_check` đạt và server phục vụ JS đúng bản sửa. Thay đổi Python được worker nạp ở lượt tiếp theo, không cần dừng server hay mất phiên đăng nhập.

Bộ kiểm thử đầy đủ cuối đạt **310/310**, không bỏ qua test, chạy trong 247,844 giây. Bao gồm chuyển kỳ khi nguồn trễ, quá hạn/qua đêm, dừng theo dõi nhưng vẫn chấm pending, lỗi nguồn/thử lại, nguồn mâu thuẫn/tương lai, writer đồng thời, giữ bất thường lịch sử, không quét/training và trạng thái nguồn trên Chrome. Log và bằng chứng thực tế được lưu trong phiên sửa Keno lúc đó; phiên này đã hết vòng đời Bin sau đợt gỡ khung Lịch Sử CSV Tự Động ngày 09/10, theo quy tắc chỉ giữ hai phiên gần nhất.

Các file sửa: `ai/keno_effectiveness.py`, `backend/live_results.py`, `frontend/vietlott-web-effectiveness.js`, các test và tài liệu liên quan. Các file mới: helper đồng bộ, `tests/test_keno_live_sync.py` và báo cáo này. Bản trước sửa gồm mã nguồn, CSV/meta và snapshot SQLite đã được sao lưu trong phiên sửa Keno. Phiên sửa Keno đã hết hạn theo quy tắc chỉ giữ hai phiên gần nhất; xem `manifest.json` trong `Bin/session_1_latest` và `Bin/session_2_previous` để biết chính xác nội dung và đường dẫn khôi phục của từng phiên hiện còn. Dữ liệu và mã sửa Keno đang vận hành vẫn được giữ trong dự án.

Sử dụng: giữ server chạy và bật Theo dõi tự động cho Keno. Giao diện mở/làm mới báo cáo khoảng mỗi phút; có thể tải lại trang để thấy dòng trạng thái đồng bộ mới. Worker tiếp tục hoạt động khi tab Hiệu quả đóng.
