# Quy Tắc

Tài liệu quy tắc vận hành và nghiệp vụ dự án VietlotFast.
## Quy tắc Thùng Rác (Bin)

- Không được xóa hẳn file hoặc folder quan trọng ngay lập tức.
- Trước khi xóa, đổi tên, hoặc ghi đè mạnh, phải đưa bản cũ vào thư mục `Bin/`.
- `Bin/` chỉ lưu tối đa 2 phiên thay đổi gần nhất:
  - `session_1_latest`: phiên gần nhất
  - `session_2_previous`: phiên cũ hơn liền trước
- Khi tạo phiên mới:
  - nội dung của `session_1_latest` sẽ chuyển thành `session_2_previous`
  - nội dung cũ của `session_2_previous` sẽ bị xóa
- Mỗi phiên phải có `manifest.json` để ghi:
  - thời gian
  - file/folder nào bị ảnh hưởng
  - hành động: delete / replace / rename / refactor
  - lý do thay đổi
- Không được bỏ qua bước backup vào Bin với:
  - file cấu hình
  - CSV
  - model JSON
  - code predictor
  - file backend/frontend quan trọng

## Cột CSV theo từng loại vé

- File riêng từng game không lưu cột `Loại`; bộ đọc lấy tên game từ cấu hình hoặc tên file.
- Loto 5/35, Mega 6/45 và Power 6/55 chỉ lưu kết quả trong `Bộ Số` và `ĐB` nếu có; không lưu thêm `Hiển thị` trùng kết quả.
- Mega 6/45 không có số đặc biệt nên không lưu cột `ĐB`.
- Max 3D và Max 3D Pro giữ kết quả phân nhóm giải trong `Hiển thị`, không lưu `Giờ`, `Bộ Số`, `ĐB`. Phải giữ số 0 ở đầu và các vị trí trúng lặp trong từng nhóm giải.
- Bộ ghi và script dọn dữ liệu dùng schema riêng từng game; bộ đọc vẫn hỗ trợ CSV cũ và dựng phần hiển thị trong bộ nhớ khi cần.
- CSV 5/35, Mega 6/45 và Power 6/55 thêm một cột `Nổ` ngay sau các cột tiền thưởng. Chỉ điền khi bảng số lượng vé trúng xác nhận có ít nhất một vé trúng giải tương ứng: `ĐB`, `Jackpot`, `Jackpot 1`, `Jackpot 2` hoặc `Jackpot 1, 2`. Các dòng khác để trống; không suy diễn từ việc tiền thưởng giảm/reset. Khi nguồn không có số lượng vé trúng, phải giữ đánh dấu đã xác minh trước đó.
- Bảng Dữ Liệu trên web và file Excel xuất từ bảng phải giữ cột `Nổ` sau tiền thưởng, lấy trực tiếp từ trường `prizeHit` của API canonical. Ô không nổ để trống; chỉ các cột tiền thưởng được định dạng tiền VNĐ.
- Nút `Nổ` của Bảng Dữ Liệu chỉ lọc các kỳ có `prizeHit`, kết hợp với lọc thời gian trước khi giới hạn số dòng. Excel dùng cùng bộ lọc; `Xóa lọc` bỏ cả lọc thời gian và lọc Nổ. Keno và Max 3D/Pro không dùng nút này.

## Xác thực, tài sản và VIP

- HTTP không được khôi phục mật khẩu admin. Khôi phục dùng `LottoWebServer --recover-admin` trong terminal tương tác, nhập mật khẩu kín; API quản trị đổi mật khẩu vẫn yêu cầu admin.
- Server mặc định bind `127.0.0.1`, phiên hết hạn sau 12 giờ và mất hiệu lực khi mật khẩu thay đổi. Chỉ Origin nằm trong danh sách cho phép được dùng API có cookie; body tối đa 8 MiB.
- Trình duyệt chỉ ghi nhớ tên đăng nhập. Khi đọc dữ liệu ghi nhớ cũ, phải bỏ mật khẩu đã lưu.
- `/api/store` không nhận thay đổi số dư, hạn VIP, trạng thái/lịch sử vòng quay hay phiên bản ví từ client. Tài sản do admin chỉnh hoặc backend cộng/trừ trong giao dịch; vòng quay dùng mã giao dịch chống cộng hai lần. Các số dư PP/KC là điểm nội bộ, chưa phải giao dịch thanh toán PayPal.
- Quyền VIP lấy từ bảng `account_entitlements`; người dùng không tự cấp qua store. Admin cấp/thu hồi tại Quản lý tài khoản; thay đổi VIP và tài sản ghi `account_audit`. Hạn VIP cũ chỉ nằm trong JSON client không được coi là xác minh quyền.

## Đánh giá dự đoán và model

- Lift ledger v2 dùng số trùng trung bình từng vé và baseline cùng cỡ vé. Điểm vé tốt nhất tách riêng, so với mô phỏng cùng danh mục để giữ số vé và mức trùng giữa vé. Không dùng baseline một vé để báo lợi thế của nhiều vé.
- Điểm lịch sử v1 giữ nguyên; giao diện ghi cần chấm lại, không hiển thị lift v1 như chỉ số đã sửa.
- Khóa dự đoán phải có target lớn hơn cutoff, chưa có kết quả canonical và chưa qua giờ quay. `created_at` lấy đồng hồ server; lưu model ID, checksum dữ liệu/payload và seed.
- Mega/Power Deep phải tạo đặc trưng từ lịch sử đầy đủ rồi lấy sequence cuối; cùng cutoff phải có input giống đường huấn luyện. Head regime hiện có phân loại lịch sử quan sát, không tự chứng minh dự đoán kỳ sau.
- Xác suất chuẩn hóa từ ranking phải ghi `uncalibrated`; khóa `calibratedProbability` cũ chỉ giữ để tương thích. Không diễn giải điểm chất lượng/confidence thành xác suất trúng cả vé.
- Backtest trả metrics cùng `evaluated_mode` và folds. Winner chọn trên chính tập đánh giá là kết quả chẩn đoán, không đủ làm bằng chứng promote. `retrain_interval` cũ được ghi là yêu cầu chưa thực thi; artifact cố định không được mô tả là retrain từng fold.
- Candidate có artifact riêng, hash và cutoff, chia lịch sử train/validation/test theo thời gian. Luồng registry đầu tiên dùng baseline Bayesian với prior cố định; model Deep hiện có tiếp tục là engine legacy. Không tự promote.
- Promote phải có metric hữu hạn, manifest đúng dữ liệu/kỳ/pipeline, cải thiện Brier và log loss so ngẫu nhiên, CI Brier hỗ trợ cải thiện, artifact hợp lệ; champion được so trên đúng tập test candidate. Promote/rollback đổi con trỏ registry trong giao dịch SQLite và inference đọc artifact từ con trỏ đó. Snapshot engine chưa duyệt không là mục tiêu rollback.
- Writer CSV dùng khóa chung theo file, file tạm riêng cho mỗi lần ghi và kiểm tra version đối với dữ liệu đã load. Khi nguồn đổi giữa đọc và ghi phải tải lại/thử lại, không ghi đè snapshot cũ.
- Max 3D/Pro có 20 vị trí giải; không suy ra số kỳ có mặt từ số lần lặp vị trí. Bảng/Excel bỏ Giờ và ĐB, gom nhóm giải vào một cột.
- Thống kê Keno combo lớn dùng cửa sổ sau sắp xếp phải ghi rõ phạm vi; không gọi đó là toàn bộ tổ hợp.
