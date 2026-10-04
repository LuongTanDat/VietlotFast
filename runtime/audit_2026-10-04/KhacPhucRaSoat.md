# Khắc phục sau rà soát — 04/10/2026

Đã sửa các lỗi xác nhận về xác thực, quyền tài khoản, chấm dự đoán, feature Deep, gate và artifact registry; đồng bộ giao diện và thêm kiểm thử hành vi. Bản Java mới đã build và chạy trên localhost:8080. Gói trước sửa nằm ở `Bin/session_1_latest`, gồm code/build và bản sao SQLite nhất quán có cả dữ liệu đã nằm trong WAL.

Không thay CSV canonical, không retrain/ghi đè các model Deep sản xuất và không tự promote model trong lần sửa này. Database vận hành được bổ sung bảng quyền VIP và audit/giao dịch; kiểm tra số lượng users/stores trước và sau giống nhau. Các phép thử tạo tài khoản, cấp VIP, quay thưởng và đổi mật khẩu chạy trong DB tạm.

## Thay đổi đã thực hiện

| Phát hiện | Bản sửa và bằng chứng |
|---|---|
| Recovery admin không xác minh | HTTP luôn trả 403. CLI `--recover-admin` yêu cầu console tương tác, nhập mật khẩu kín và xác nhận. Test chứng minh mật khẩu admin cũ không bị đổi bởi request HTTP. |
| Client tự khai số dư/VIP | Store bỏ thay đổi các trường được bảo vệ. VIP lấy từ `account_entitlements`, API Vip kiểm tra quyền thực; admin cấp/thu hồi bằng nút ở Quản lý tài khoản. Số dư và lượt quay do server cập nhật; `wallet_events` chống xử lý hai lần cùng mã giao dịch; số dư/trạng thái/history có version chống response cũ ghi đè giao diện. |
| Mật khẩu trong trình duyệt | Chỉ lưu username; xóa trường pass của bản ghi cũ khi đọc. Bỏ setter VIP công khai; nhãn ghi nhớ đã sửa. |
| CORS/session/request không giới hạn rõ | Bind loopback mặc định; Origin allowlist và từ chối request Origin lạ trước handler; body tối đa 8 MiB, thread pool/hàng đợi hữu hạn, giới hạn phiên và login; TTL phiên 12h, hủy phiên khi đổi mật khẩu. Chỉnh số dư chỉ chấp nhận POST. |
| Lift nhiều vé dùng sai baseline | Scoring v2 lưu điểm từng vé và trung bình, lift chính so đúng cỡ vé. Best-hit danh mục có baseline mô phỏng 1.024 kỳ với cùng vé/mức trùng; vé đơn dùng kỳ vọng chính xác. Mô phỏng 1.000 kỳ ngẫu nhiên không còn lift tăng giả do có 10 vé. |
| Lock target cũ/sau giờ quay | Numeric target phải sau cutoff; production đối chiếu canonical và giờ quay theo lịch game. Kỳ đã có kết quả hoặc đã đến giờ quay bị trả `validation_rejected`, `ready=false`. Thời điểm lock lấy server; payload chứa data hash/model ID/config hash/seed. |
| Feature Deep Mega/Power khác train | Context giữ toàn bộ history; inference tính các bước sequence cuối với nền lịch sử đầy đủ. Test thực gọi `score_numbers` xác nhận input giống train tại cùng cutoff ở cả hai game. Không đổi weights/scaler hiện có. |
| Metrics không thuộc winner | `metrics`, `evaluated_mode`, folds cùng mode; có `mode_metrics` và flag chọn trên tập đánh giá. Retrain cũ được ghi rõ chưa thực thi; không còn nói cố định artifact là retrain từng fold. |
| Gate chấp nhận thiếu/NaN | Bắt buộc metric và CI hữu hạn, manifest kỳ/dữ liệu/pipeline/cỡ vé, artifact/hash/cutoff đúng; Brier và log loss phải tốt hơn uniform, CI Brier hỗ trợ cải thiện. Không gộp metric validation với test. Chặn chọn winner trên tập đánh giá làm bằng chứng promote. |
| Candidate không có artifact thật | `ai/controlled_models.py` huấn luyện baseline Bayesian với prior cố định vào thư mục riêng, có hash/config/cutoff và train/validation/test theo thời gian. Fast dùng 120 kỳ validation và 120 kỳ test; không tự duyệt. Đây là model main-number; số phụ khi inference dùng đối chứng đều với seed, chưa có model số phụ được duyệt. |
| Registry không điều khiển inference | Nếu có champion hợp lệ, predict đọc artifact champion. So champion trên đúng các kỳ/dữ liệu của candidate; promote/rollback dùng giao dịch SQLite và kiểm tra con trỏ chưa đổi giữa đánh giá và cập nhật. Test chứng minh promote thay bộ số và rollback phục hồi đúng artifact. |
| Prediction thiếu model ID | Prediction mới ghi ID phiên bản thực thi; engine legacy được đánh dấu execution snapshot chưa duyệt, không tự thành champion và không dùng làm rollback. Không gán ngược model ID giả cho lịch sử cũ. |
| Gọi chuẩn hóa là calibration | Thêm `estimatedProbability` và `calibrationStatus=uncalibrated`; giữ alias cũ để tương thích. UI ghi ước lượng chưa hiệu chỉnh; không hứa xác suất trúng cả vé. |
| Race CSV/temp trùng tên | Khóa liên tiến trình theo file, temp có PID/UUID. Loader giữ version; writer từ chối dữ liệu cũ nếu nguồn đổi giữa đọc/ghi. Test hai snapshot chứng minh writer cũ không làm mất kỳ mới. Trường hợp bị từ chối phải reload/thử lại. |
| Max config/cột UI | Thống nhất 20 vị trí giải; bỏ Giờ/ĐB trên bảng và Excel, giữ một cột Nhóm giải với tên giải, số 0 đầu và kết quả lặp. |
| Combo Keno lớn dễ hiểu sai | Summary ghi rõ cửa sổ liền nhau sau sắp xếp, không phải mọi tổ hợp. Chưa bổ sung API đếm combo tự nhập chính xác. |
| Mega Vip engine/risk không tác động | Ẩn các lựa chọn này ở Mega Vip; payload ghi rõ request không áp dụng và cấu hình thực dùng. |
| Tài liệu cũ | README cập nhật Nổ/Excel, unittest, CNN–GRU NumPy, candidate/registry, VIP và recovery. QuyTac/NhatKyThayDoi cập nhật. |

`backend/LottoWebServer.java` xử lý bảo mật và giao dịch; `ai/prediction_ledger.py`, `ai/ml_pipeline.py`, `ai/controlled_models.py` xử lý đánh giá/registry. Các sửa feature nằm trong predictor Mega/Power; ba `backtest.py` có metadata mode. `backend/file_guard.py` và `live_results.py` bảo vệ CSV. Core/data/stats frontend đồng bộ các luồng mới.

## Kiểm thử và xác minh

- Bộ unittest chính: **156/156 qua**, gồm các regression mới.
- Ba predictor standalone: **5 + 4 + 5 = 14/14 qua**; tổng **170 unittest riêng biệt qua**. Các bộ standalone chạy process/cwd riêng để tránh package `src` trùng tên.
- Kiểm thử Java trên DB tạm có 23 kiểm tra về recovery, tài khoản, store, VIP, idempotency/thưởng vòng quay, Origin, giới hạn body/login và hủy phiên sau reset mật khẩu.
- Chrome mở đầy đủ frontend/server trong fixture riêng: đăng nhập được, chỉ nhớ username, admin render VIP đúng, spinner nhận snapshot từ backend, history/amount khớp server, không có boot error. Max giữ tên nhóm giải, số 0 đầu và số lặp, không có cột Giờ/ĐB. Evidence: `fix_browser_smoke_result.txt`.
- Regression ML xác nhận feature parity, mode/folds, gate invalid/NaN/artifact/manifest, model thật với split đúng, promote/rollback đúng artifact và writer CSV không ghi đè snapshot mới.
- HTTP vận hành: time 200; store/admin chưa đăng nhập 401; recovery 403; Origin lạ 403; source JS đang phục vụ khớp file mới; ETag 304; SQLite `quick_check=ok`. Evidence: `fix_production_verification.json`.
- Log chính: `fix_all_tests.log`; regression: `fix_regression_tests.log`, `fix_final_ml_tests.log`. Bản Java đã biên dịch thành `backend/bin`; log server ở `runtime/logs/server_audit_fixes_2026-10-04.*.log`.

## Đánh giá lại sau sửa feature

Giữ weights hiện có, cố định mode blended và dùng 79 kỳ sau cutoff cho từng game; không ghi state/model sản xuất. Kết quả mới lưu riêng trong `fixes_backtests/`, giữ nguyên bằng chứng audit ban đầu.

| Game | Số kỳ | Trùng trung bình/vé | Uniform cùng cỡ vé | Brier mới | Brier uniform |
|---|---:|---:|---:|---:|---:|
| Mega | 79 | 0,7342 | 0,8000 | 0,12829 | 0,11556 |
| Power | 79 | 0,6709 | 0,6545 | 0,10331 | 0,09719 |

CI chênh lệch số trùng của cả hai vẫn chứa 0. Sửa input là khắc phục tính nhất quán, không chứng minh đã tăng năng lực dự báo. Không promote model sản xuất dựa vào các kết quả này. Backtest standalone vẫn khác pipeline web thường; không dùng số liệu này để chứng nhận mọi engine.

## Giới hạn và phần phát triển tiếp

- Điểm ledger v1 và prediction thiếu model ID trước đây giữ nguyên. UI không còn diễn giải lift v1 như điểm đã sửa; chưa có job backfill/rescore lịch sử.
- Alias `calibratedProbability` giữ để client cũ không lỗi; **chưa fit calibration ngoài mẫu cho engine legacy**. Bayesian là baseline được kiểm soát, chưa phải bằng chứng lợi thế. Deep cũ không được tự nâng thành champion; muốn registry điều khiển phiên bản Deep cần adapter/huấn luyện artifact riêng tương đương baseline adapter.
- Execution snapshot legacy ghi hash mã/config/state/artifact; chưa là một gói replay đầy đủ với mọi binary và dữ liệu đã lưu độc lập. Champion Bayesian có artifact riêng có thể kiểm tra hash; giao diện replay/quản lý model chưa được thêm.
- Regime head cũ vẫn phân loại nhãn từ lịch sử quan sát. Không đổi mục tiêu/retrain head trong lần này; không coi accuracy regime là lợi thế dự đoán bộ số.
- Khóa/version CSV không thay cho hàng đợi tác vụ toàn ứng dụng. Mọi tiến trình ghi cần dùng code mới; writer không giữ version từ loader riêng cần tích hợp thêm. State/tracking/model của các CLI legacy cần cơ chế giao dịch xuyên suốt read–modify–write nếu cho chạy đồng thời ngoài web.
- Thread pool và request đã có giới hạn; chưa có job queue/progress/retry/cancel thống nhất. Chưa stress-test tải lớn, chưa tối ưu toàn bộ Keno analysis `all` hoặc thêm bitset cho exact combo.
- Các trang Chất lượng dữ liệu, Hiệu quả dự đoán, Replay, quản lý artifact và các bộ lọc Nổ chi tiết vẫn là đề xuất phát triển mới, không phải lỗi đã vá.

Sau cập nhật, **Ctrl+F5 rồi đăng nhập lại**. VIP của tài khoản thường được admin cấp tại Quản lý tài khoản; admin có quyền quản trị. Nếu bị chặn vì kỳ đã đến giờ quay, cập nhật kết quả trước khi dự đoán lại. PP/KC là điểm nội bộ; cổng thanh toán PayPal chưa được nối.
