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