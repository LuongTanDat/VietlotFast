# Hướng Dẫn Codex
Project đã được tách theo các nhóm 
`ai`, `backend`, `frontend`, `data`, `runtime`, `scripts`.
# Hướng dẫn bắt buộc cho Codex

Trước khi sửa bất kỳ file nào trong dự án này, phải đọc theo thứ tự:

1. docs/QuyTac.md
2. docs/KienTrucDuAn.md
3. docs/NhatKyThayDoi.md

Quy tắc bắt buộc:
- Không tự ý đổi cấu trúc folder nếu chưa được phép.
- Không đổi tên file đang được hệ thống sử dụng nếu chưa kiểm tra toàn bộ import/reference.
- Không xóa dữ liệu CSV, model JSON, hoặc database nếu chưa được xác nhận.
- Không ghi đè logic AI predictor hiện tại nếu chưa backup.
- Mọi thay đổi được duyệt phải cập nhật lại:
  - docs/NhatKyThayDoi.md
  - docs/QuyTac.md nếu thay đổi đó trở thành quy tắc mới
  - docs/QuyTac.docx nếu người dùng yêu cầu đồng bộ bản chính thức
- Ưu tiên sửa tối thiểu, không refactor lan rộng.
- Luôn giải thích file nào sẽ bị sửa trước khi sửa.
## Quy tắc an toàn trước khi sửa

Trước khi xóa, đổi tên, hoặc ghi đè file/folder quan trọng:
1. Backup bản cũ vào đúng nhánh con trong `Bin/session_1_latest/files/`:
   `ai/`, `backend/`, `frontend/`, hoặc `data/`
2. Ghi metadata vào `Bin/session_1_latest/manifest.json`
3. Nếu `session_1_latest` đã tồn tại từ phiên trước:
   - chuyển nó sang `session_2_previous`
   - xóa nội dung cũ của `session_2_previous`
4. Chỉ sau đó mới được phép sửa/xóa file gốc

Không được xóa hẳn trực tiếp các file/folder quan trọng.
