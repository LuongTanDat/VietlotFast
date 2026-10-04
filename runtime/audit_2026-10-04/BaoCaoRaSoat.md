# Rà soát dự án DVLF — 04/10/2026

Ứng dụng có nền tảng dữ liệu và kiểm thử khá đầy đủ, nhưng cách đo hiệu quả dự đoán còn những lỗi làm kết quả dễ bị hiểu cao hơn thực tế. Nên sửa xác thực, cách chấm dự đoán, đầu vào Deep và vòng đời model trước khi bổ sung model lớn hoặc thêm nhiều công thức.

Đây là báo cáo đánh giá và đề xuất. Các phép thử bảo mật chạy trên database tạm; database vận hành chỉ được truy vấn ở chế độ đọc. Backtest không ghi lại model/tracking sản xuất. Số liệu là ảnh chụp tại lúc kiểm tra; tiến trình cập nhật dữ liệu nền vẫn có thể tiếp tục.

**Phạm vi và bằng chứng**

- Lập danh mục và quét 157 file mã nguồn/cấu hình/tài liệu, tổng 82.757 dòng; phân tích cú pháp toàn bộ Python trong phạm vi này, không có lỗi cú pháp.
- Đọc và đối chiếu các luồng chính: Java HTTP/SQLite, đăng nhập/quản trị/store; CSV canonical/live/backfill; dự đoán thường/Vip và fallback; Adaptive Coverage; ba predictor standalone; CNN–GRU NumPy; ledger/registry/backtest; thống kê/phân tích; giao diện bảng dữ liệu, lịch sử, tài khoản, vòng quay, chatbot và scripts khởi động.
- Bản build, JAR, ảnh và file model nhị phân được kiểm tra theo vai trò/metadata; không coi chúng là mã nguồn cần đọc từng dòng. Đây không phải chứng nhận đã thử mọi tổ hợp thao tác giao diện hoặc kiểm thử tải lớn.
- Dữ liệu và phép thử chi tiết ở cùng thư mục báo cáo: `inventory.json`, `datasets.json`, `database_summary.json`, `deep_models.json`, `probes.json`, `security_probe.json`, `smoke_checks.json`, các file `*_backtest.json` và `*_extended_summary.json`.

**Kết quả chạy thử**

| Hạng mục | Kết quả |
|---|---|
| Bộ unittest chính | 145/145 qua |
| Predictor 5/35 | 5/5 qua |
| Predictor Mega | 4/4 qua |
| Predictor Power | 5/5 qua |
| Tổng unittest hiện có | 159/159 qua |
| Chatbot trên Chrome headless | 7 kiểm tra hành vi qua |
| Java history / cột thưởng / Nổ / Excel | Test thực thi Java và Chrome trong bộ chính qua |
| Phân tích và thống kê trên dữ liệu thật | Cả sáu game trả payload hợp lệ; chế độ phân tích `all`, khoảng 30 ngày, và thống kê combo 2 |
| Kiểm tra gradient CNN–GRU | 57 ô gradient được lấy mẫu; sai số tuyệt đối lớn nhất 0,0000584, dưới ngưỡng 0,002 |
| SQLite | `PRAGMA quick_check = ok` |
| HTTP đang chạy | Trang/tài nguyên trả 200; gzip và ETag/304 hoạt động; API lịch sử/admin từ chối người chưa đăng nhập bằng 401 |

Không thể suy ra dự án hết lỗi từ 159 test qua. Một số test kiểm tra chuỗi trong mã nguồn; các phép thử bổ sung bên dưới phát hiện hành vi sai mà bộ test hiện có chưa bao phủ. Kiểm tra gradient mới chỉ lấy mẫu, chưa phải xác minh toàn bộ mạng hoặc chất lượng huấn luyện.

**Dữ liệu hiện tại**

| Game | Số dòng | Phạm vi kỳ | Ngày của kỳ mới nhất |
|---|---:|---|---|
| 5/35 | 925 | 1–925 | 04/10/2026 |
| Mega | 1.569 | 2–1.570 | 02/10/2026 |
| Power | 1.402 | 5–1.406 | 03/10/2026 |
| Keno | 24.106 | 273.963–298.068 | 04/10/2026 |
| Max 3D | 1.140 | 1–1.140 | 02/10/2026 |
| Max 3D Pro | 787 | 1–787 | 03/10/2026 |

Tổng 29.929 dòng qua kiểm tra schema, số lượng/phạm vi số, số đặc biệt, nhóm giải Max, nguồn và giá trị tiền thưởng theo bộ kiểm tra hiện có. Không có kỳ trùng hoặc khoảng trống giữa hai đầu của từng phạm vi đang lưu. Kiểm tra này không đối chiếu lại mọi bộ số với website nguồn trong lần rà soát này, cũng không chứng minh toàn bộ lịch sử từ kỳ 1 đã được thu thập. Mega bắt đầu từ kỳ 2, Power từ kỳ 5, Keno chỉ có một phạm vi gần đây: nên hiển thị phạm vi dữ liệu rõ ràng và xác minh nguồn nếu muốn backfill phần đầu.

Cột Nổ hiện có 42 kỳ ĐB của 5/35; 165 kỳ Jackpot Mega; Power có 330 kỳ chỉ Jackpot 2, 40 kỳ chỉ Jackpot 1 và 18 kỳ cả hai. Đây là số kỳ có đánh dấu trong dữ liệu đã lưu.

**Backtest và ý nghĩa của kết quả**

Đã chạy backtest nhanh trên canonical: mỗi game số tự chọn 24 kỳ × 3 chế độ, Keno 48 kỳ. Sau đó mở rộng với một chế độ cố định `blended` cho ba game số tự chọn, tránh chọn cấu hình tốt nhất ngay trên tập đánh giá. Mega/Power dùng toàn bộ 79 kỳ sau cutoff của artifact hiện có; 5/35 dùng 120 kỳ gần nhất; Keno dùng 480 kỳ cho bộ xếp hạng lịch sử của ML pipeline.

| Game và cấu hình được thử | Số kỳ | Số trùng trung bình mỗi vé | Mức ngẫu nhiên cùng cỡ vé | Chênh lệch tương đối | Khoảng 95% của chênh lệch số trùng |
|---|---:|---:|---:|---:|---|
| 5/35, blended, vé 5 số | 120 | 0,7833 | 0,7143 | +9,67% | −0,0726 đến +0,2107 |
| Mega, blended, vé 6 số | 79 | 0,8101 | 0,8000 | +1,27% | −0,1671 đến +0,1873 |
| Power, blended, vé 6 số | 79 | 0,6709 | 0,6545 | +2,50% | −0,1229 đến +0,1556 |
| Keno history ranker, vé 10 số | 480 | 2,5479 | 2,5000 | +1,92% | −0,0583 đến +0,1771 |

Các khoảng đều chứa 0. Những lần thử này chưa cho bằng chứng rõ ràng về lợi thế dự đoán. Chênh lệch tương đối ở bảng là chênh lệch **số trùng trung bình**, không phải phần trăm tăng khả năng trúng Jackpot hay lợi nhuận.

Backtest nhanh chọn `deep_only` của 5/35 với 1,125 số trùng/kỳ trên 24 kỳ, so với ngẫu nhiên 0,7143. Đây là kết quả đáng thử tiếp, chưa đủ kết luận: cấu hình được chọn sau khi so ba chế độ trên chính tập này. Backtest mở rộng vừa chạy là kiểm tra chẩn đoán, không phải nghiên cứu đăng ký trước với một tập holdout hoàn toàn chưa từng được dùng để chọn feature/config. Việc chọn model và báo hiệu quả trên cùng tập có thể làm kết quả lạc quan; nên tách hai bước. [Cawley & Talbot, JMLR](https://www.jmlr.org/beta/papers/v11/cawley10a.html).

Các khoảng và p-value được lưu theo cách tính hiện có của dự án, dùng 500 lượt bootstrap/permutation. Không nên coi phép hoán đổi dấu với một hằng số kỳ vọng là thay thế đầy đủ cho mô phỏng danh mục vé ngẫu nhiên hoặc kiểm định đã điều chỉnh việc thử nhiều cấu hình.

Brier mở rộng của 5/35/Mega/Power/Keno lần lượt khoảng 0,12683 / 0,12857 / 0,10289 / 0,19605, đều cao hơn baseline xác suất đều tương ứng 0,12245 / 0,11556 / 0,09719 / 0,18750. Brier thấp hơn tốt hơn: các xác suất hiện tại chưa tốt hơn baseline trong các lần thử này.

Keno ở bảng sử dụng `_score_keno_history` của ML pipeline. Luồng Keno thường trên web dùng chọn strategy rồi Adaptive Coverage. Ba backtest standalone cũng không đi qua toàn bộ pipeline thường trên web. Vì vậy không lấy các kết quả này làm chứng nhận hiệu quả cho mọi engine/nút dự đoán của ứng dụng.

**Những việc cần sửa trước**

1. **P0 — Khôi phục admin chưa yêu cầu xác minh.** `backend/LottoWebServer.java:923`, `handleRecoverAdmin`, nhận mật khẩu mới và gọi `repo.recoverAdmin` mà không yêu cầu session, token hay xác minh chủ tài khoản. Phép thử Java trên DB tạm: không gửi cookie vẫn nhận 200, sau đó đăng nhập được bằng mật khẩu vừa thay. Server tại dòng 346 bind mọi địa chỉ, nên không thể mặc định chức năng này chỉ được gọi từ chính máy. Đề xuất chuyển khôi phục cục bộ sang CLI có kiểm soát, hoặc token dùng một lần có thời hạn; mặc định bind loopback nếu ứng dụng chỉ dùng cục bộ. Tiêu chí: yêu cầu không được xác minh không thể đổi mật khẩu. [OWASP Forgot Password](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html).

2. **P0/P1 tùy mục đích — Số dư và VIP được nhận trực tiếp từ client.** `handleStore` tại `LottoWebServer.java:594` cho tài khoản lưu toàn bộ JSON; frontend có `setVipMembershipExpiry` tại dòng 2339 và công khai hàm này ở dòng 2359. Phép thử tạm cho thấy số dư do client khai và hạn VIP năm 2099 được lưu. Nếu đây là điểm mô phỏng nội bộ thì nên ghi rõ và tách với dữ liệu quyền hạn. Nếu số dư/VIP có giá trị thực, chuyển thao tác tăng/giảm tiền, quay thưởng và cấp hạn VIP sang backend, dùng giao dịch có mã duy nhất; `/api/store` chỉ nhận tùy chọn giao diện. Nút/nội dung bị khóa ở frontend không thay thế kiểm tra quyền tại API. Tiêu chí: người dùng không tự sửa được số dư, lượt quay hoặc quyền VIP bằng store.

3. **P1 — Lift của nhiều vé bị phóng đại.** `ai/prediction_ledger.py:342–384` lấy `best_hit` trong danh sách vé, nhưng tính lift theo kỳ vọng một vé. Mô phỏng 2.000 kỳ với vé ngẫu nhiên: một vé có lift trung bình −0,31%; mười vé có lift bị báo +160,5%, dù không có model. Đề xuất lưu điểm từng vé, trung bình trên vé và kết quả cả danh mục riêng; khi báo vé tốt nhất phải so với danh mục ngẫu nhiên cùng số vé/cỡ vé/mức trùng, không dùng baseline một vé. Tiêu chí: danh mục ngẫu nhiên không bị báo có lợi thế do mua nhiều vé.

4. **P1 — Đặc trưng Deep khi dự đoán khác cách tạo lúc huấn luyện.** `mega_6_45_predictor/src/deep_model.py:327` và `power_6_55_predictor/src/deep_model.py:321` chỉ truyền `recent_secondary` vào `build_inference_sample`. Các đặc trưng như tần suất gần đây và lần trước cùng thứ được tính lại từ cửa sổ bị cắt. Phép thử trên cùng 10 kỳ cuối cho thấy 25 ô đặc trưng Mega và 28 ô Power khác cách tạo từ lịch sử đầy đủ. `recent_window_fill` lẽ ra đều 1 lại tăng từ 0 trong đầu vào sản xuất. Đề xuất tính đặc trưng với phần lịch sử làm nền đủ dài, rồi lấy sequence cuối; dùng chung một hàm cho train và inference. Tiêu chí: vector đầu vào của cùng mốc cutoff giống nhau ở hai đường đi.

5. **P1 — Cổng duyệt model chấp nhận chỉ số thiếu/NaN.** `_candidate_passes` tại `ai/ml_pipeline.py:468` chỉ kiểm tra Brier khi trường có giá trị; so sánh NaN cũng không chặn được. Các probe có 24 fold nhưng thiếu Brier/Log Loss hoặc chứa NaN đều được chấp nhận. Cần bắt buộc đủ chỉ số hữu hạn, số mẫu và manifest của tập đánh giá; không có dữ liệu phải trả trạng thái không đủ bằng chứng. So candidate/champion trên cùng kỳ, cùng cỡ vé và pipeline; thêm điều kiện log loss, calibration và mức bất định. Tiêu chí: thiếu chỉ số, NaN, Inf hoặc tập so không tương đương đều không được promote.

6. **P1 — Registry chưa điều khiển artifact dùng để dự đoán.** `train_candidate` tại `ai/ml_pipeline.py:426` chạy backtest rồi tạo registry record; `artifact_paths` ở dòng 444 chỉ có ghi chú, không có model ứng viên mới. Deep loader vẫn đọc artifact cố định trong thư mục predictor. Snapshot DB có 6 record model đều `rejected`, 0 champion; 229/229 prediction không có `model_id`. Điều này không chứng minh artifact đang chạy đã bị reject; nó cho thấy hai hệ thống chưa gắn với nhau. Cần huấn luyện vào thư mục ứng viên riêng, lưu hash model/scaler/config, promote đổi con trỏ artifact, rollback khôi phục đúng artifact, mỗi prediction ghi model ID. Tiêu chí: đổi champion làm đổi artifact được nạp, replay xác định được đúng phiên bản đã dùng.

7. **P1 — Ledger cho khóa dự đoán có target cũ hơn cutoff.** `lock_prediction` tại `ai/prediction_ledger.py:194` chưa kiểm tra quan hệ cutoff/target và thời điểm khóa. Probe `latestKy=101`, `target_draw_id=100` vẫn tạo bản ghi `locked`. Cần kiểm tra target sau cutoff, trước thời điểm đóng dự đoán của kỳ và chưa có kết quả; ghi data hash/cutoff/timezone/model/seed từ backend. Tiêu chí: dự đoán cho kỳ đã biết kết quả hoặc dùng dữ liệu sau target bị từ chối. Các guard artifact ở backtest là phần tốt đã có, nhưng chưa đủ bảo vệ ledger.

8. **P1 — Nhãn xác suất và báo cáo model chưa thống nhất.** `attach_controlled_probability_metadata` tại `ai/predictors/ai_predict.py:3362` thường đổi ranking thành phân phối bằng `scores_to_probabilities`; đây là chuẩn hóa tổng xác suất, chưa phải calibration học từ dữ liệu đánh giá. Probe score lệch cho một số cho ra p=1 mà không hề có mẫu calibration. Hàm Platt/isotonic đã tồn tại, cần nối vào luồng bằng dự đoán ngoài mẫu theo thời gian. Trước đó nên gọi là trọng số/xác suất ước lượng chưa hiệu chỉnh. [Tài liệu calibration của scikit-learn](https://scikit-learn.org/stable/modules/calibration.html).

9. **P1/P2 — Chọn winner và metrics có thể là hai chế độ khác nhau.** Các backtest chọn `winner_mode` nhưng `metrics` vẫn lấy `blended`; Mega tại `src/backtest.py:185–196` là ví dụ. Lần chạy nhanh 5/35/Mega chọn `deep_only`, còn metrics ghi `blended`; baseline lấy fold của winner. Cần trả metrics theo từng mode và một tên `evaluated_mode` rõ ràng; không gộp kết quả của các model khác nhau. `retrain_interval` hiện chủ yếu được trả lại như metadata, chưa điều khiển retrain trong vòng lặp: cần thực thi hoặc đổi tên/ẩn tùy chọn này.

**Những điểm nên hoàn thiện tiếp**

- **Ghi nhớ mật khẩu:** `frontend/vietlott-web-core.js:1836` lưu nguyên mật khẩu vào localStorage. Nên chỉ nhớ tên tài khoản hoặc dùng phiên/refresh token có thời hạn. Có thể giữ cookie HttpOnly hiện có; thêm hạn phiên và giới hạn lần đăng nhập sai.
- **CORS/tài nguyên:** Java phản chiếu Origin bất kỳ và cho credentials tại dòng 2383; thread pool và kích thước request body chưa có giới hạn rõ. Cần allowlist Origin, giới hạn body, hàng đợi tác vụ Python và thời hạn job. Đây là nhận định từ mã nguồn, chưa stress-test để đo khả năng quá tải.
- **Ghi CSV/state đồng thời:** các writer CSV dùng cùng tên `.tmp` và các job có lock riêng. Cần một cơ chế khóa theo tài nguyên/file, writer duy nhất cho canonical, tên tạm riêng và kiểm tra version trước ghi. Đây là nguy cơ cạnh tranh từ mã, chưa tái hiện ghi đè dữ liệu trong lần audit.
- **Max 3D:** fixture có 20 kết quả được parser phân tích đọc đủ, nhưng `analysis.GAME_CONFIGS` dùng `main_count=18`, Adaptive Coverage dùng `drawSize=21`. Chuẩn hóa cấu hình và phân biệt đếm vị trí giải với đếm kỳ có số xuất hiện; giữ số 0 và kết quả lặp hợp lệ. Các baseline phụ thuộc game cần được xác minh theo cơ cấu giải, không lấy những hằng số mâu thuẫn làm xác suất.
- **Combo Keno lớn:** `stats_v2.draw_combo_items` với combo >3 chỉ lấy cửa sổ liền nhau trên dãy đã sắp xếp. Fixture 20 số, combo 4 trả 17 nhóm thay vì 4.845 tổ hợp; nhóm 01–03–05–07 không được đếm. Backend có `comboMode=keno_window`, nhưng frontend chưa thể hiện rõ chế độ này. Nên có nhãn phạm vi và tính chính xác các combo người dùng nhập bằng giao các tập kỳ có từng số; không cần liệt kê toàn bộ tổ hợp 10 số.
- **Engine/risk ở Vip:** wrapper Mega nhận engine/risk nhưng chủ yếu ghi vào nhãn/notes; lời gọi `predict_pure` không chuyển yêu cầu này thành cấu hình blend. Nên cho lựa chọn thực sự tác động thuật toán hoặc ẩn lựa chọn không áp dụng, hiển thị engine thực dùng/fallback.
- **Regime accuracy:** nhãn regime của Deep được tạo từ lịch sử đã có, nên accuracy cao ở head này không đồng nghĩa dự báo tốt kỳ sau. Định nghĩa riêng regime hiện tại và mục tiêu regime kỳ kế; đánh giá thêm lợi ích với dự đoán bộ số khi bật/tắt head.
- **Bảng Dữ Liệu:** CSV đã dùng schema từng game, trong khi header UI vẫn tạo Giờ/ĐB cho game ba chữ số. Nên thống nhất schema hiển thị và tách nhóm giải Max thành phần dễ đọc; kiểm tra lại yêu cầu dọn cột trước khi thay.
- **Tài liệu:** README còn mô tả nút Tải Xuống và Xóa lọc chỉ thời gian; README predictor còn mô tả Deep là scaffold dù có model CNN–GRU thật. Cập nhật theo hành vi đang chạy.

**Chức năng nên bổ sung**

| Ưu tiên | Chức năng | Mục đích và điều kiện hoàn thành |
|---|---|---|
| Cao | Trang Chất lượng dữ liệu | Hiện kỳ mới nhất/phạm vi lịch sử/trạng thái nguồn/số kỳ thiếu/số kỳ đã xác minh Nổ; bấm mở nguồn theo kỳ |
| Cao | Trang Hiệu quả dự đoán | So engine với ngẫu nhiên cùng ngân sách; tách số trùng từng vé/danh mục/giải thưởng; hiện số mẫu và khoảng bất định |
| Cao | Replay một dự đoán | Dùng prediction ID, cutoff, artifact/config/data hash và seed để tái tạo đúng kết quả đã khóa |
| Cao | Trang quản lý model | Hiện artifact thực đang chạy, dữ liệu huấn luyện, candidate/champion, lý do reject, promote/rollback có bằng chứng |
| Trung bình | Tác vụ nền có trạng thái | Mở rộng progress hiện có thành hàng đợi job có ID, thời gian, lỗi nguồn, retry/hủy có kiểm soát; tránh nhiều job ghi cùng dữ liệu |
| Trung bình | Lọc Nổ theo giải | Chọn ĐB/Jackpot/Jackpot 1/Jackpot 2/cả hai và khoảng thời gian; Excel cùng bộ lọc |
| Trung bình | Đếm combo tự nhập chính xác | Cho người dùng kiểm tra một tập combo bất kỳ, đặc biệt Keno 4–10 số; ghi rõ khác biệt với thống kê cửa sổ |
| Trung bình | Nhật ký thao tác tài khoản | Ghi thay đổi quyền/số dư/VIP và người thực hiện ở backend; thao tác quan trọng có mã giao dịch chống lặp |
| Sau | Phân trang/tìm kỳ và biểu đồ lịch sử | Tải dữ liệu theo phần, lọc nhanh, tooltip nguồn và thời điểm xác minh; duy trì export đúng phạm vi |

**Hướng cải thiện thuật toán dự đoán**

1. **Xây phép đo đúng trước.** Chọn một metric chính trước mỗi thử nghiệm. Đánh giá theo thời gian với train → validation/calibration → test; chọn feature/trọng số ở vòng trong, đo ở vòng ngoài. Mỗi so sánh phải dùng cùng target kỳ, nguồn dữ liệu và số vé. Báo tất cả cấu hình đã thử, điều chỉnh việc thử nhiều cấu hình, rồi kiểm chứng thêm bằng dự đoán tương lai đã khóa trong ledger.

2. **Đối chứng đủ mạnh.** Bắt đầu với xác suất đều `k/N`, vé ngẫu nhiên và tần suất có co về prior. Dùng số trùng, phân phối 0/1/2/… số trùng, Brier/log loss, calibration và kết quả danh mục. Nếu đánh giá tiền thưởng, dùng cùng chi phí/số vé và cơ cấu giải đúng game; không suy luận lợi nhuận từ hit-rate.

3. **Ưu tiên mô hình gọn.** Thử tần suất có Bayesian shrinkage, cửa sổ/EWMA được chọn ở validation, và logistic regression regularization cho từng số. So feature gần đây, khoảng vắng, cùng thứ, cặp số, modulo bằng ablation; bỏ feature không có lợi ngoài mẫu. Các quan hệ nhìn đẹp trong dữ liệu lịch sử chỉ là giả thuyết cần thử.

4. **Calibration có dữ liệu thật.** Fit Platt trên dự đoán ngoài mẫu ở tập calibration, thử isotonic khi đủ dữ liệu và có lợi trên tập riêng. Kiểm tra tổng xác suất/giới hạn sau hiệu chỉnh và reliability diagram. Không đồng nhất confidence/quality score với xác suất trúng cả vé.

5. **Sửa train/inference của Deep trước khi retrain.** Chuẩn hóa feature builder, cutoff và artifact manifest; thêm test feature parity và chống dữ liệu tương lai. Giữ model hiện có làm benchmark sau khi sửa và đánh giá lại. Chỉ chọn Deep khi có lợi ngoài mẫu ổn định; thêm Transformer/LSTM lớn vào lúc này chưa có bằng chứng sẽ cải thiện.

6. **Tối ưu danh mục vé theo mục tiêu cụ thể.** Adaptive Coverage/Gumbel đã có khả năng tạo đa dạng. Thử giảm trùng giữa các vé, tăng độ phủ số/cặp và tối ưu danh mục theo cùng ngân sách. Đánh giá bằng mô phỏng ngẫu nhiên tương đương; không coi việc tăng số vé hoặc điểm hình dạng đẹp là tăng năng lực dự báo.

7. **Tách bài toán theo game.** 5/35 tách main và ĐB, kiểm chứng khác biệt 13h/21h; Power giữ điều kiện số thứ bảy nằm ngoài sáu số chính và chấm Jackpot 1/2 theo đúng luật; Keno đo riêng từng bậc và dùng đúng pipeline đã phát hành; Max giữ nhóm giải và mô hình xác suất phù hợp số ba chữ số có thể lặp. Cấu hình luật game nên dùng chung giữa dữ liệu, AI, thống kê và UI.

8. **Cột Nổ không phải tín hiệu biết trước.** Khi nghiên cứu feature từ Nổ/tiền thưởng, chỉ dùng dữ liệu đã biết trước kỳ cần dự đoán. Nổ của chính kỳ mục tiêu và tiền thưởng chỉ xác định sau quay sẽ làm rò rỉ đáp án nếu đưa vào đầu vào. Có thể dùng Nổ để tra cứu và phân tích lịch sử mà không diễn giải thành quy luật chắc chắn.

Nếu kết quả quay công bằng và độc lập, dữ liệu lịch sử không tự tạo ra lợi thế biết trước bộ số kỳ sau. Mục tiêu có thể cải thiện chắc chắn về kỹ thuật là dữ liệu đúng, phép đo trung thực, dự đoán tái lập được và chọn danh mục theo mục đích người dùng; lợi thế dự báo phải được chứng minh bằng thử nghiệm.

**Trình tự triển khai đề xuất**

- Đợt 1: khóa lỗ hổng recovery, phân quyền/store và mật khẩu nhớ; sửa lift nhiều vé, gate thiếu/NaN và guard cutoff/target. Thêm test hành vi cho từng lỗi đã tái hiện.
- Đợt 2: sửa feature parity Mega/Power, thống nhất evaluated mode/pipeline và định nghĩa game; nối artifact registry với inference/ledger. Lúc này mới chạy lại benchmark để không so số liệu trước/sau từ các đường khác nhau.
- Đợt 3: calibration và các baseline/mô hình nhỏ; walk-forward/holdout và dự đoán tương lai có khóa. Làm trang hiệu quả dự đoán từ các số liệu đã đúng.
- Đợt 4: chất lượng dữ liệu, combo chính xác, job queue và tối ưu frontend/phân tích. Trong smoke test, Keno analysis `all` khoảng 30 ngày mất 11,7 giây và stats combo 2 khoảng 4,3 giây trên máy hiện tại; nên tối ưu parse/aggregate và tránh tính lại toàn bộ. Cache versioned và gzip đã có, cần mở rộng đúng điểm nghẽn.

Giữ các phần đang có giá trị: CSV canonical/schema riêng và bằng chứng nguồn, test reader Python/Java, guard artifact tương lai, prediction ledger bất biến, seed tái lập, baseline xác suất, static cache/gzip, cùng UI phân tích/dữ liệu. Việc cải tiến nên có thay đổi nhỏ, đo được và dễ quay lại.

**Tái chạy các phép thử chính**

Dùng Python đang cài trên máy hoặc Python đã có dependency trong `requirements.txt`. Các script audit nằm cùng báo cáo và ghi đầu ra vào thư mục này; `inspect`/`probes` không cập nhật dữ liệu sản xuất.

```powershell
python -m unittest discover -s tests -v
python runtime/audit_2026-10-04/run_audit.py inspect
python runtime/audit_2026-10-04/run_audit.py probes
python runtime/audit_2026-10-04/security_probe.py
python runtime/audit_2026-10-04/gradient_probe.py
python runtime/audit_2026-10-04/run_audit.py backtests
python runtime/audit_2026-10-04/extended_backtest.py LOTO_5_35
python runtime/audit_2026-10-04/extended_backtest.py LOTO_6_45
python runtime/audit_2026-10-04/extended_backtest.py LOTO_6_55
python runtime/audit_2026-10-04/extended_backtest.py KENO
```

Ba bộ test standalone cần chạy từ thư mục predictor tương ứng để tránh trùng tên package `src` giữa các dự án. Chrome/JDK cần có cho phép thử trình duyệt và Java. Các test UI chạy trong fixture/profile riêng; lần audit này chưa thực hiện giao dịch tiền, đổi tài khoản hoặc thao tác admin trên database đang vận hành.
