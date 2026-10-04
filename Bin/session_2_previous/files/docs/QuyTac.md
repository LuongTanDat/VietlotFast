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
