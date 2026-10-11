# Báo cáo dọn dự án — 09/10/2026

Đã dọn 4,118 file cũ và hai thư mục tạm rỗng. Dung lượng tệp của dự án giảm từ **764.3 MB xuống 195.2 MB**, tiết kiệm khoảng **569.1 MB (74.5%)**, đã tính cả bản sao lưu trong Bin. Runtime giảm từ **701.4 MB xuống 44.8 MB**.

Số liệu là tổng kích thước tệp tại thời điểm hoàn tất dọn, dùng MB thập phân và không tính thư mục lịch sử Git `.git`. Mốc trước dọn được chụp sau khi xoay hai phiên Bin theo quy tắc dự án. Cache Python có thể tự sinh lại khi server chạy. Phiên dọn đã hết thời hạn giữ sau hai đợt sửa Keno và giao diện tiếp theo; báo cáo này giữ lại số liệu tổng kết.

| Nhóm đã dọn khỏi cây làm việc | Số file | Dung lượng bản rời (MB) |
| --- | ---: | ---: |
| Cache Python, profile Chrome và build Java kiểm thử | 1,266 | 40.15 |
| Bản nháp, script vá một lần và chẩn đoán trùng | 9 | 0.52 |
| Output backtest chi tiết cũ | 21 | 13.41 |
| Bản sao CSV/metadata trước các đợt sửa | 166 | 40.87 |
| HTML/JSON nguồn tải về cũ | 2,610 | 489.26 |
| DB kiểm thử độc lập và file đi kèm | 8 | 69.80 |
| Ảnh/HTML kiểm chứng giao diện cũ | 38 | 6.79 |

**Sao lưu lúc hoàn tất:** 2,852 file, tổng 620.6 MB, được lưu trong ZIP 88.4 MB. Đã đọc lại mọi mục trong ZIP, kiểm tra CRC khi giải nén và đối chiếu SHA-256 với bản gốc trước khi xóa. Cache tái tạo được không sao lưu. Gói dọn này đã được loại khỏi Bin theo quy tắc tối đa hai phiên; hiện Bin giữ phiên chỉnh giao diện và phiên sửa tự động Keno.

Các bản nháp được lưu trong ZIP gồm `docs/Run_Website.docx`, `docs/Text_Note.docs`, `docs/UpdateNew.Docx`; đây là tệp ghi chú dạng văn bản, không phải tài liệu Word hợp lệ. Hướng dẫn chạy web hiện có trong README và launcher. Các yêu cầu lịch sử vẫn tra cứu được trong ZIP. Bốn script vá một lần trong đợt audit cũ (`backup_fixes.py`, `prepare_production_fixes.py`, `fix_python_ui.py`, `fix_wallet_ui.py`) cũng được lưu rồi dọn sau khi kiểm tra các tham chiếu/import của chúng.

**Các phần được giữ vì còn sử dụng:** toàn bộ frontend và asset, Java/JDBC/build đang phục vụ web, Python backend/AI, test và CLI bảo trì; CSV canonical/scoring, ba CSV standalone, model/scaler/state/config; hai SQLite vận hành và khóa ghi thật. Báo cáo tổng kết, số liệu kiểm chứng nhỏ và helper triển khai còn được tham chiếu giữ ở đường dẫn cũ. Stub `vietlott-web.js` phục vụ cache cũ; `predictor_v2` vẫn là fallback. Ba module trùng nội dung giữa predictor_v2 và 5/35 (`modulo_engine`, `pair_engine`, `regime_engine`) có import riêng nên được giữ. Hai requirements giống nhau phục vụ cài đặt riêng từng predictor.

**Kiểm chứng sau dọn:**

- **296/296** kiểm thử dự án đạt; gồm HTTP Java/Python trên DB riêng, biên dịch Java trong fixture, Keno, phòng thử, bảo mật và giao diện Chrome.
- **14/14** kiểm thử standalone đạt: 5/35 có 5, Mega có 4, Power có 5. Tổng **310/310**, không bỏ qua test.
- **251/251** file nguồn, data, model, state/config và build được bảo vệ giữ nguyên SHA-256 sau toàn bộ kiểm thử.
- `PRAGMA quick_check` của `runtime/lotto_web.db` và `runtime/algorithm_lab.db` đều `ok`; số bản ghi tất cả bảng giữ nguyên.
- **13/13** kiểm tra server 8080 đạt: 10 trang/asset trả 200 và nội dung khớp file, `/api/time` trả 200; hai API history/hiệu quả vẫn trả 401 khi chưa đăng nhập. Luồng API có đăng nhập được kiểm tra trên fixture riêng. Server đang chạy được giữ trong suốt đợt dọn.
- Git status đọc được, không còn cảnh báo thư mục fixture cũ. Các thay đổi có sẵn của người dùng được giữ.

Log và kết quả chi tiết từng nằm trong phiên Bin của đợt dọn, nay đã hết thời hạn giữ; các kết quả chính được ghi lại ở báo cáo này.

**Khôi phục:** gói ZIP của phiên dọn không còn trong Bin sau khi xoay hai phiên tiếp theo. Khi còn bản sao lưu của một phiên, giải nén file vào thư mục riêng và đối chiếu SHA-256 trong manifest trước khi chép về dự án. Không cần khôi phục cache/output cũ để chạy web. Vòng đời Bin theo `docs/QuyTac.md`.

Phần dung lượng còn lại chủ yếu là Bin (125.5 MB) và dữ liệu vận hành/runtime. Dọn file giảm dung lượng và độ rối của cây dự án; thuật toán và kết quả dự đoán giữ nguyên.
