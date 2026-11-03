# Kiến Trúc Dự Án

## Thẻ nội bộ nhận thưởng (03/11/2026)

- `ai/account_card.py`: schema thẻ/giao dịch bất biến, chính sách đích nhận thưởng và chuyển thưởng ví cũ. Các bảng nằm trong DB tài khoản; account_cards dùng ID công khai 12 số làm chủ sở hữu, payout routes giữ liên kết với UUID danh mục nội bộ/charge/cycle. Chuyển lịch sử kiểm audit và liên kết ID, trừ ví/cộng thẻ nguyên tử, giữ nguyên prediction_payouts và chốt reward_card_migrations chống lặp.
- `ai/prediction_rewards.py`: đóng băng nơi nhận/currency/chủ thẻ trong bản tính và kiểm lại chính sách trước commit. Đích card ghi biên nhận gốc + route + giao dịch thẻ + audit prediction_card_reward trong cùng transaction; không tăng paypalBalance/walletVersion. Nhánh wallet giữ tương thích và phục vụ kiểm chứng lịch sử cũ. Chính sách triển khai là card/PayPal trong config/prediction-rewards.json.
- `backend/LottoWebServer.java`: GET `/api/account/card?history=0|1&kind=all|transfer|topup|withdraw|reward&page=...` xác thực chủ sở hữu, trả số dư/ID/tên và trang lịch sử; GET không tạo thẻ hay ghi tiền. Thẻ chưa có khoản ghi trả số dư 0 theo ID của tài khoản. API ví hiện chứng từ trừ khi chuyển thưởng cũ sang thẻ; không đưa audit thưởng mới trên thẻ thành khoản cộng ví.
- Frontend mở chung dialog với hai tab và request được hủy khi đổi tab/phiên. Thẻ dùng HTML/CSS/SVG, không cần ảnh ngoài, có nút mở lịch sử và bộ lọc. `tests/test_account_card.py` kiểm luồng tiền/rollback/đồng thời/đổi tên; `tests/test_account_card_web.py` kiểm API, cách ly tài khoản, chỉ đọc, phân trang và Chrome desktop/390px.

## Quyết toán thưởng theo biên nhận đã mua (03/11/2026)

- `ai/prediction_rewards.py`: lập kế hoạch chỉ đọc từ DB ví, paid_cycle_receipts và các summary điểm bất biến trong private ledger. Không tải payload/vé lớn, gọi predictor hay mở shared ledger để gán thưởng. Kiểm bốn phương pháp, đủ mười bậc Keno, thời điểm, bộ số thực tế, số vé và phí. Dùng hàm mức thưởng cùng quy ước với bảng hiệu quả, tính từng phương pháp riêng và đóng băng ngữ cảnh quỹ/mức trả/chi tiết vào biên nhận.
- DB ví thêm `prediction_payouts` có hai khóa chống lặp và trigger bất biến. Mỗi khoản cộng kiểm lại chủ sở hữu bất biến và charge dưới BEGIN IMMEDIATE; cập nhật ví/phiên bản, biên nhận, audit nguyên tử. Đổi tên giữ chủ theo UUID danh mục; không gán cho người đăng ký lại cùng tên. Dữ liệu lịch sử theo dõi giữ nguyên.
- `Scope.settle_rewards` trong `ai/personal_tracking.py` nối sau đối soát phí của lệnh tạo/chấm và worker, gồm danh mục đã tắt tạo mới nhưng còn thưởng chưa quyết toán. Lỗi thưởng trả pending riêng, không biến lần mua đã hoàn tất thành lỗi mua. Chỉ worker/luồng ghi được làm mới tối đa một ngữ cảnh thưởng Keno còn thiếu. File `config/prediction-rewards.json` là công tắc bật tự động; công thức phiên bản v1 cố định 5/4.
- CLI `python -m ai.prediction_rewards` xem trước chỉ đọc; `--apply` cộng một lần, `--owner` giới hạn tài khoản và `--output` lưu báo cáo. Lịch sử ví có kind `reward`; trả walletVersion cùng số dư để UI đồng bộ thanh đầu trang.
- `tests/test_prediction_rewards.py` kiểm công thức/các game, Bao, Keno, Jackpot độc lập, chờ dữ liệu, chống lặp/đồng thời, rollback và số dư tràn. `tests/test_prediction_rewards_web.py` kiểm luồng điểm/biên nhận → Python → SQLite/audit liên kết ID → Java API → trình duyệt/số dư.

## Bảng lịch sử ví (03/11/2026)

- `backend/LottoWebServer.java`: route GET `/api/account/wallet-history`, xác thực người xem, lọc và phân trang các sự kiện tiền của chính tài khoản từ `account_audit`/`account_activity_links` và `wallet_events`. Chỉ đọc DB tài khoản, không mở ledger vé lớn hoặc gọi Python. Kết quả đã chuẩn hóa không chứa nội dung quà bí mật/payload ví; tiền chênh lệch là chuỗi số nguyên, thiếu dữ liệu cũ là null. Count, trang và số dư trong cùng snapshot đọc, Cache-Control no-store.
- `frontend/vietlott-web-wallet.js` và `.css`: module độc lập tải sau core, nút ở thanh đầu trang mở native dialog, bộ lọc, phân trang, trạng thái tải/lỗi/rỗng; kiểm tra chủ phản hồi, AbortController/serial khi đóng hoặc thay phiên. Desktop dùng bảng, màn hình nhỏ dùng lưới hai cột theo giao dịch.
- `tests/test_wallet_history.py`: API/SQLite và Chrome với DB/phiên/ví thử riêng, kiểm tra cách ly tài khoản, không lặp phí, đọc không ghi, điều chỉnh/nạp/đổi lượt thực qua API, phân trang, đổi tên, lỗi, Escape và phiên thay đổi khi request chưa xong.

## Công cụ tra seed tổng quát (03/11/2026)

- `ai/seed_lookup.py`: thư viện đọc độc lập, không nối luồng thu phí. Chọn một private ledger rõ ràng, tìm seed bằng lịch root/context/index; chỉ tải xác suất, lịch và vé của prediction tìm thấy. Vé thường lớn lấy đúng khối theo global index, thiếu khối phải báo lỗi. Bao lấy đúng parent, không đọc/tạo lớp vé thường.
- Khớp game/kỳ/phương pháp/loại/số lượng giữa config và payload trước tái lập. Kiểm hash module seed, Bao/template liên quan với sourceManifest, bỏ qua file model/CSV đã thay đổi vì replay dùng vector xác suất và nguồn đã lưu. DB đóng trước bước tái lập dài để tránh giữ snapshot/WAL trong lúc tính toán.
- Tái lập dùng lại bộ sinh version hiện có với toàn bộ ngân sách/thứ tự, kể cả nhánh pool dày và khử trùng thưa; đối chiếu chính xác số chính/số phụ. Tách trạng thái verified/mismatch/unavailable/skipped và hiển thị mọi bộ khớp nếu có trùng ngữ cảnh. Không tạo chỉ mục seed/cache hoặc thay schema/payload DB.
- `scripts/tra_seed.py`: CLI nhập nhiều mã hoặc một mã, JSON, lọc loại/kỳ/phương pháp và chọn owner/DB. `scripts/tra_seed.bat` tự tìm và thử Python 3.10+ cài cục bộ/PATH, bỏ qua alias WindowsApps để tránh gọi nhầm bản Python cũ hỏng. Tính năng chạy độc lập, không cần khởi động lại web.

## Lịch seed của từng vé (03/11/2026)

- `ai/tracking_ticket_seed.py`: lịch seed phiên bản `tracking_ticket_seed_v1`, SHA256 theo ngữ cảnh/số thứ tự và luồng SplitMix64 riêng từng vé. Chỉ lưu lịch nhỏ, suy ra seed đúng chỉ số toàn cục khi đọc trang/xuất. Nhánh thưa dùng chọn số có trọng số và khử trùng, vector hóa khi có NumPy; nhánh dày dùng pool tổ hợp với cây Fenwick trọng số nguyên để lấy hết không kẹt hay sai số tích lũy.
- `prediction_effectiveness.cycle`: lấy vector xác suất từ pipeline/phương pháp hiện có rồi phân bổ vé theo luồng seed mới; Bao dùng nhóm hợp lệ trong cấu trúc đã kiểm chứng và seed từng Bao để chọn nhóm còn lại. Đóng băng `ticketSeedSchedule` trong payload, `ticketSeedSchedules` theo phương pháp trong config; execution manifest có hash module mới. Đây là phiên bản phân bổ mới, không tính lại lịch sử. Không thay model/CSV hoặc quy tắc tính phí.
- `tracking_bao.build(seed_schedule=...)`: giữ nguyên sức chứa và kiểm chứng bộ vé đầy đủ, hoán đổi các nhóm tương thích bằng stream riêng; lưu số gốc đầu vào trong lịch để tái lập. Nhánh mặc định không truyền lịch giữ tương thích công cụ/fixture cũ.
- API báo cáo/trang/JSON export thêm seed ở lớp đọc từ cấu hình nhỏ, không quét payload lịch sử chỉ để lấy seed. Bao không trả vé thường. Excel lớn tính seed từng dòng khi ghi, giữ kiểu text; bảng mới dùng tải XLSX server để dữ liệu seed thống nhất. Các kỳ không có lịch vẫn đọc nguyên bản, không gán seed ngược.

## Nhiều cơ cấu trong một kỳ tương lai (02/11/2026)

- `ai/prediction_effectiveness.py`: `effectiveness_cycles.selection_key` là `normal` hoặc `bao:<cấp>`, duy nhất theo `(game_type,target_draw_id,selection_key)` trong DB riêng của tài khoản. Khóa tiến trình theo tài khoản/game và ràng buộc SQLite chống tạo/thu phí hai lần.
- Nâng cấp tại `_connect` chỉ dựng lại bảng metadata nhỏ trong một giao dịch, giữ nguyên chín cột cũ, khóa ngoại và trigger bất biến; không sửa payload, biên nhận hay ví. `ai/tracking_storage.py` chuyển DB cũ bằng danh sách cột rõ ràng và tính khóa từ cấu hình đóng băng.
- `ai/personal_tracking.py` tiếp tục giữ mỗi khoản thu bằng chargeId và biên nhận cycleId; không thay đổi giá hay cơ chế hoàn phí. Đọc báo cáo/chấm/xuất không thu thêm.
- `frontend/vietlott-web-effectiveness.js` dùng cycleId để giữ trạng thái xem/chuyển phương pháp và tìm đúng bộ khi nhảy đến giải; tên Excel có cấp Bao. Các bộ cùng kỳ được hiển thị thành khung riêng, đúng cơ cấu đã mua.

Tổng quan cấu trúc thư mục, backend, frontend, AI và luồng dữ liệu.

- `ai/`: mã AI, predictor, model, config, training
  Bên trong `ai/standalone_predictors/`: predictor standalone cho Vip 5/35, Mega 6/45, Power 6/55 và predictor_v2 legacy
- `docs/`: tài liệu vận hành và ghi chú dự án
- `data/`: dữ liệu canonical và export scoring
- `backend/`: backend Python, Java server, thư viện JDBC
- `frontend/`: giao diện HTML, CSS, JavaScript
- `frontend/vietlott-web-numeric.js`: bộ định dạng số nguyên dùng chung, tải trước effectiveness/core/admin. Theo dõi vùng thay thế của IME để thêm dấu chấm mà không lặp chữ số; giữ con trỏ/vùng chọn, giá trị 0 mặc định và quy tắc kiểm tra nhóm số. Ô theo dõi truyền callback giới hạn theo game/bậc; tài khoản/quà tặng giữ giới hạn khi lưu hiện có. Java phục vụ qua route tĩnh riêng.
  Trang chủ giữ bảng kết quả live; lịch sử CSV chỉ xem tại Bảng Dữ Liệu. Bộ đọc/cache canonical và `/api/live-history` dùng chung cho bảng/Excel, thống kê và đối chiếu dự đoán; khung Lịch Sử CSV Tự Động riêng đã được gỡ.
- `runtime/`: database runtime và log
- `scripts/`: script chạy dự án
- `tests/`: khu vực test
- `Bin/`: lưu gói build theo phiên bản

Chi tiết `Bin/`:

- `Bin/session_1_latest/files/ai/`: snapshot AI của phiên gần nhất
- `Bin/session_1_latest/files/backend/`: snapshot backend của phiên gần nhất
- `Bin/session_1_latest/files/frontend/`: snapshot frontend của phiên gần nhất
- `Bin/session_1_latest/files/data/`: snapshot data của phiên gần nhất
- `Bin/session_1_latest/manifest.json`: metadata phiên gần nhất
- `Bin/session_2_previous/files/ai/`: snapshot AI của phiên cũ hơn
- `Bin/session_2_previous/files/backend/`: snapshot backend của phiên cũ hơn
- `Bin/session_2_previous/files/frontend/`: snapshot frontend của phiên cũ hơn
- `Bin/session_2_previous/files/data/`: snapshot data của phiên cũ hơn
- `Bin/session_2_previous/manifest.json`: metadata phiên cũ hơn

## Đăng nhập và OAuth

- `frontend/vietlott-web-auth.css`: giao diện đăng nhập riêng, tải sau CSS chung; không tác động trang đã đăng nhập.
- `frontend/vietlott-web-auth.js`: trạng thái/click nút mạng xã hội, gọi API start và chuyển sang nhà cung cấp; Enter trong các ô vẫn dùng luồng tài khoản cục bộ.
- `backend/LottoWebServer.java`: `/api/auth/social/providers`, `/api/auth/social/start`, `/api/auth/social/callback/{provider}`; state/PKCE và token exchange/profile validation chạy ở backend. Cấu hình từ `runtime/social-login.properties` hoặc môi trường; endpoint provider cố định. Bảng `social_identities` liên kết ID provider với `users`; dùng phiên hiện có, không lưu token.
- `config/social-login.properties.example` và `docs/DangNhapMangXaHoi.md`: mẫu không có khóa thật và hướng dẫn callback/ứng dụng.
- `tests/SocialOAuthFixture.java`: transport HTTPS giả chỉ trong entry point kiểm thử, không được đưa vào build triển khai; `tests/test_social_login.py` kiểm tra ba adapter và UI Chrome.

## Theo dõi danh mục lớn

- `ai/tracking_progress.py` theo dõi ba pha updating/creating/scoring ở tiến trình cha, ghi file nhỏ `runtime/effectiveness_progress_<game>.json` bằng thay thế nguyên tử và heartbeat 2 giây. Chỉ ghi telemetry, không sửa bảng lịch sử/tài khoản. ETA dùng phép đo ban đầu và tỷ lệ công việc đã hoàn tất; lỗi tiến trình được lưu riêng.
- `/api/ml/effectiveness-progress?type=...` yêu cầu đăng nhập, đọc file giới hạn 8 KiB, no-store, kiểm tra game/pha và heartbeat 20 giây; không gọi Python hoặc mở DB tracking. Frontend hỏi mỗi 3 giây khi tab hoạt động, đếm ETA tại chỗ, timeout request 8 giây, hủy khi đổi loại/phiên/đóng tab. Ô trạng thái nằm cạnh Loại xổ số, lỗi có thông báo riêng.
- ai/tracking_storage.py chuyển snapshot actor hệ thống và các bảng theo dõi sang runtime/tracking_ledger.db, giữ DB nguồn runtime/lotto_web.db cho tài khoản, ví, dự đoán cá nhân và registry. runtime/tracking-storage.json chỉ kích hoạt sau khi sao chép/kiểm tra xong; đường DB kiểm thử được chỉ định trực tiếp vẫn độc lập. Không tạo lịch sử trống khi thiếu DB đã chuyển.
- ai/tracking_portfolio.py hỗ trợ ngân sách yêu cầu đến 1.000.000; giới hạn theo tổ hợp khác nhau và giữ thứ tự/seed khi unrank bằng NumPy. ai/tracking_capacity.py kiểm tra dung lượng cho JSON, khối vé, WAL và staging, cộng 20 GB dự phòng.
- ai/keno_effectiveness.py chuẩn bị và chấm danh mục bằng tối đa bốn tiến trình, tối đa nửa số luồng CPU. Worker tạo không ghi DB; worker chấm chỉ mở DB read-only. Parent kiểm tra checksum/deadline/nguồn/cấu hình, ghi đủ 40 dự đoán hoặc toàn bộ điểm trong một giao dịch.
- effectiveness_ticket_index và effectiveness_ticket_chunks là dữ liệu phụ trợ bất biến, ghi cùng vé gốc; danh mục trên 10.000 vé chia khối 1.000 để đọc trang nhỏ. Dự đoán/điểm đã khóa giữ nguyên.
- ai/effectiveness_xlsx.py tạo XLSX nén trực tiếp ở backend cho danh mục lớn; Java gửi file theo luồng và dọn đúng file tạm. Trình duyệt tải file, không dựng hàng triệu dòng JSON/XML. File có Tổng quan và bốn phương pháp, AutoFilter và hàng đầu cố định.

## Bộ tạo Bao sau khôi phục 01/11/2026

- `ai/tracking_bao.py`: sức chứa từng mức, tạo nhóm nguyên vẹn và ánh xạ số theo phương pháp; không ghi ví/DB.
- `config/tracking-bao-packing-v2.json`: mẫu cấu trúc nhóm xác định, kiểm tra không trùng trước khi dùng; ghi nhận cùng execution manifest.
- `scripts/build_tracking_bao_packing.py`: tái tạo mẫu vào file runtime riêng để đối chiếu, không tự thay mẫu đang chạy.
- `ai/prediction_effectiveness.py`: schema cộng thêm cột Bao, cấu hình/hash, kiểm tra trước thu phí và ghi bốn phương pháp nguyên tử; lịch sử giữ bất biến.
- `frontend/vietlott-web-effectiveness.js`: chọn mức/Số Bao, hạn mức từ server, báo phí và xác nhận hash trước khóa.

## Định danh vé đầy đủ — v3

- `tracking_bao.ticket_key` dùng thống nhất khi kiểm tra khóa kỳ: 5/35 gồm số chính và ĐB; Mega/Power chỉ gồm số chính. Không dùng số thứ bảy dự đoán Power để né trùng.
- `tracking_bao._parent_groups` tạo luân phiên 12 luồng độc lập theo ĐB cho 5/35. Mỗi luồng dùng cấu trúc cơ sở đã kiểm chứng trong `tracking-bao-packing-v2.json`; định dạng mẫu cơ sở không đổi. `maxBaoCounts` nhân sức chứa họ với 12 cho 5/35 rồi giới hạn theo ngân sách vé con.
- `uniqueBy` và `baoRuleVersion` được đóng băng cùng cấu hình/payload/checksum của kỳ mới. Kỳ cũ giữ nguyên phiên bản, bộ số, số tiền và kết quả chấm; phần so sánh số trùng/Brier vẫn chấm số chính, phần giải chấm đúng ĐB.


## Lưu và đọc đúng lớp vé đã chọn

- `tracking_bao.build` tạo trực tiếp các nhóm Bao gốc từ vector/seed của phương pháp; không gọi `expand` để tạo một mảng vé thường. `ticketStorage=bao_parents_v1` ghi nhận biểu diễn mới, không đổi thuật toán khử trùng v3. `expand` giữ làm công cụ đối chiếu tương thích, không nằm trong nhánh khóa Bao mới.
- `prediction_effectiveness.cycle` dùng nhánh normal/bao riêng, xác minh kiểu và số lượng trước khóa, đóng băng lớp trong config và payload. Bao chỉ ghi mảng nhóm gốc; chỉ mục giữ số tổ hợp tương đương phục vụ tính phí/đối chứng, không ghi chunks của vé thường. Chấm giải có thể dựng tổ hợp nội bộ tạm từ nhóm bất biến, không lưu thành prediction hoặc danh mục khác.
- `tracking_bao.parent_prizes` đếm số tổ hợp theo nhóm số trúng/số phụ bằng hệ số tổ hợp; không dựng toàn bộ các vé thường để phân loại từng Bao trên API/Excel. Kiểm chứng với bộ phân loại chính xác cho cả 3 game, cả mức Bao thấp hơn/cao hơn cỡ vé chuẩn và Power Jackpot 2.
- `ticket_page(view=selected)` chọn đúng loại theo config kỳ; yêu cầu view trái loại bị từ chối. Tìm giải trong kỳ Bao dẫn tới Bao gốc, không sang trang vé thường. Báo cáo Bao không tải hoặc trả mảng vé thường; frontend không có bộ chuyển loại trong nhật ký.
- `effectiveness_xlsx` xuất đúng loại: mỗi dòng Bao là một nhóm gốc, gồm số tổ hợp quy đổi và tổng hợp giải. Dữ liệu Bao cũ đọc tương thích từ `bao.parents`; không sửa DB lịch sử hoặc ví.
