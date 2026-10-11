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

## Dọn file tạm và bản nháp

- Chỉ dọn theo danh sách đã rà soát đường dẫn và nơi tham chiếu. Không coi một module là thừa chỉ vì tên cũ, không được import trực tiếp hoặc trùng nội dung với module khác; phải kiểm tra cả CLI, fallback và đường tải asset.
- Giữ CSV canonical, CSV/state của predictor đang dùng, model/artifact, database vận hành, WAL/SHM và khóa ghi đang dùng. Bản sao DB/CSV kiểm thử phải xác nhận là độc lập trước khi dọn.
- Có thể lưu bản nháp, dữ liệu tải về và output kiểm thử cũ trong ZIP của phiên Bin. Phải kiểm tra SHA-256 từng mục sau giải nén trong bộ nhớ trước khi xóa bản rời; manifest ghi đường dẫn gốc, lý do và nơi khôi phục. Quy tắc tối đa hai phiên Bin vẫn áp dụng.
- Cache Python, profile Chrome kiểm thử đã dừng và build Java kiểm thử cũ có thể tái tạo. Không dọn profile trình duyệt hay file đang được tiến trình giữ; giữ build Java đang phục vụ web. Giữ báo cáo tổng kết và kết quả kiểm chứng nhỏ ở đường dẫn cũ.

## Cột CSV theo từng loại vé

- Lịch sử CSV được xem/lọc/xuất Excel tại Bảng Dữ Liệu; bỏ khung Lịch Sử CSV Tự Động riêng trên trang chủ. API `/api/live-history` và bộ đọc/cache canonical vẫn dùng chung cho bảng, thống kê và đối chiếu dự đoán; không xóa nguồn CSV khi gỡ giao diện.
- File riêng từng game không lưu cột `Loại`; bộ đọc lấy tên game từ cấu hình hoặc tên file.
- Loto 5/35, Mega 6/45 và Power 6/55 chỉ lưu kết quả trong `Bộ Số` và `ĐB` nếu có; không lưu thêm `Hiển thị` trùng kết quả.
- Mega 6/45 không có số đặc biệt nên không lưu cột `ĐB`.
- Max 3D và Max 3D Pro giữ kết quả phân nhóm giải trong `Hiển thị`, không lưu `Giờ`, `Bộ Số`, `ĐB`. Phải giữ số 0 ở đầu và các vị trí trúng lặp trong từng nhóm giải.
- Bộ ghi và script dọn dữ liệu dùng schema riêng từng game; bộ đọc vẫn hỗ trợ CSV cũ và dựng phần hiển thị trong bộ nhớ khi cần.
- CSV 5/35, Mega 6/45 và Power 6/55 có một cột `Nổ` ngay sau các cột tiền thưởng. Khi bảng số lượng vé trúng xác nhận có ít nhất một vé trúng giải tương ứng, điền `ĐB`, `Jackpot`, `Jackpot 1`, `Jackpot 2` hoặc `Jackpot 1, 2`. Riêng 5/35, nếu xác nhận có 0 vé trúng ĐB và tiền thưởng kỳ kế tiếp (đúng kỳ N+1, thời gian sau kỳ N) nhỏ hơn tiền thưởng kỳ N, điền `Chia Giải` ở kỳ N. Ví dụ kỳ 15 có 12 tỷ, 0 vé trúng ĐB, kỳ 16 còn 6 tỷ thì kỳ 15 là `Chia Giải`; kỳ 16 không tự có nhãn. Có 1 hoặc nhiều vé trúng ĐB vẫn là `ĐB`. Thiếu kỳ kế tiếp/tiền thưởng/số vé trúng hoặc tiền thưởng chưa giảm thì không tự gán chia giải; số vé trúng chưa biết không được coi là 0. Mega/Power không suy diễn nhãn từ tiền thưởng giảm/reset.
- Số vé trúng ĐB đã xác minh của 5/35 được lưu trong metadata `prizeSharing.winnerEvidenceByDraw`, gắn với ngày/giờ/bộ số/ĐB của đúng kỳ; không thêm cột CSV. Tải lại canonical phải khôi phục bằng chứng đúng bộ số, giữ qua nguồn fallback và tính lại nhãn chia giải khi có kỳ sau hoặc nguồn sửa tiền thưởng/số vé trúng. Nguồn thiếu số lượng vé trúng giữ nhãn đã xác minh; sửa nhận diện kỳ không tái dùng bằng chứng cũ.
- Bảng Dữ Liệu trên web và file Excel xuất từ bảng phải giữ cột `Nổ` sau tiền thưởng, lấy trực tiếp từ trường `prizeHit` của API canonical. Ô không nổ để trống; chỉ các cột tiền thưởng được định dạng tiền VNĐ.
- Bảng Dữ Liệu có hai nút bật/tắt cạnh nhau: `Nổ` chỉ lấy kỳ có vé trúng ĐB/Jackpot; `Chia giải` chỉ lấy kỳ 5/35 có nhãn `Chia Giải`. Bật cả hai lấy hợp của hai nhóm, không dùng giao và không lặp kỳ; tắt cả hai xem tất cả. Bộ lọc giải kết hợp với lọc thời gian trước khi giới hạn số dòng. Excel dùng cùng bộ lọc và tên file ghi `_no`, `_chia_giai` hoặc cả hai; `Xóa lọc` bỏ cả hai nút và thời gian. Chuyển khỏi 5/35 tắt/vô hiệu hóa Chia giải; Keno/Max 3D/Pro tắt/vô hiệu hóa cả hai.

## Xác thực, tài sản và VIP

- Thông báo mặc định xem 5 tin mới nhất; Xem thêm chuyển sang 10 tin/trang với nút về trang mới hơn/cũ hơn. Mỗi lần mở lại bắt đầu từ 5 tin. Lưu lịch sử thông báo đã nhận trong trình duyệt theo từng tài khoản, chống lặp ID kỳ/dự đoán; làm mới cùng kỳ không đẩy tin cũ lên đầu và không tự cắt bỏ tin chưa đọc khi lịch sử tăng. Đọc trang chỉ đánh dấu các tin đang xem; bấm nội dung đánh dấu từng tin đã đọc và hiện ✓. Xóa đã đọc áp dụng mọi trang; nút xóa riêng chỉ hiện khi đã đọc, hàm xóa phải kiểm tra trạng thái đã đọc trước khi ghi ID đã ẩn. Không xóa tin chưa đọc hoặc ảnh hưởng dữ liệu xổ số/dự đoán gốc.

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

## Hiệu năng thống kê Keno

- Khi nhập một danh sách lịch sử, gom các kỳ và xử lý trùng trước, chỉ dựng/sắp xếp thứ tự một lần sau khi nhập xong. Cập nhật từng kỳ riêng vẫn giữ thứ tự đúng và toàn bộ metadata.
- Mở/làm mới mục Thống Kê đọc CSV canonical hiện có, không tự gọi repair/backfill hoặc tải lại nguồn ngoài. Cập Nhật và sửa canonical là luồng riêng. Hiển thị thống kê ngay sau khi đọc lịch sử, không chờ đồng bộ ledger xong; tác vụ cũ không tạo chu kỳ thống kê sau khi người dùng đổi loại xổ số.
- Giữ toàn bộ lịch sử và tính đúng phạm vi bộ lọc, không âm thầm cắt số kỳ để giảm tải. Tính thống kê nặng dùng Worker hiện có; tự làm mới tạm dừng khi trang trình duyệt bị ẩn.

## Theo dõi hiệu quả trên kỳ tương lai

- Dashboard hiệu quả chỉ dùng chu kỳ hệ thống có đủ bốn phương pháp web/ngẫu nhiên/Bayesian/EWMA đã khóa trước giờ quay. Không tạo ngược dự đoán lịch sử hoặc gộp prediction cá nhân vào báo cáo chung.
- Một game/kỳ chỉ khóa một lần; bốn prediction và mapping được ghi trong cùng giao dịch. Tất cả dùng cùng cutoff/snapshot, số vé và cỡ vé; kiểm tra lại canonical, config, manifest và deadline ngay trước khi ghi. Đổi cấu hình chỉ tác động kỳ mới.
- Tự động theo dõi do admin bật theo game, mặc định tắt; chấm chu kỳ pending vẫn tiếp tục khi tắt tạo dự đoán. Worker chạy khi server sống và khi có kết quả canonical. Không bỏ qua kết quả chưa cập nhật để dự đoán cho kỳ xa hơn hoặc bù các kỳ đã quay.
- Số trùng/Brier/log loss/CI của báo cáo vẫn chấm số chính; hạng giải của từng vé được phân loại riêng theo thể lệ vé chuẩn. Jackpot 2 Power cần 5 số chính trùng và bóng thứ bảy thực tế nằm trong 6 số đã chọn; số phụ dự đoán riêng không quyết định giải. Xác suất biên chưa hiệu chỉnh phải ghi đúng trạng thái. Không dùng Nổ/tiền thưởng của kỳ mục tiêu làm feature.
- Thống kê dùng mọi chu kỳ hoàn chỉnh đã chấm với trọng số bằng nhau theo kỳ; giới hạn nhật ký chỉ giới hạn chi tiết hiển thị. CI dùng cặp chênh lệch theo kỳ, so cùng ngân sách. Dưới 30 kỳ ghi chưa đủ bằng chứng; CI dương chỉ là dấu hiệu trong mẫu, không tự promote hoặc cam kết lợi thế.
- Lưu cấu hình/budget thực của từng chu kỳ, model/engine/seed/hash đã dùng; báo rõ khi gộp nhiều cấu hình. Không đổi payload đã khóa hoặc tự ghi đè model sản xuất để làm đối chứng.
- Cấu hình theo dõi nhận 1–10.000 vé/phương pháp. Các bộ số chính phải khác nhau; giới hạn số vé theo không gian tổ hợp của bậc. Khi vượt ngân sách cũ, dùng danh mục mở rộng có seed từ xác suất của luồng web, giữ vé gốc và lưu rõ engine/cách phân bổ `tracking_unique_portfolio_v1`, không mô tả như phân bổ web cũ. Giữ nguyên vector xác suất số chính; ĐB/số phụ của vé thêm lấy ngẫu nhiên có seed.
- Ô Vé / phương pháp hiện chữ mờ Max theo loại/bậc đang chọn: Keno bậc 1 là 80, bậc 2 là 3.160, các trường hợp còn lại là 10.000. Gõ/dán vượt giới hạn tự đưa về tối đa; kiểm tra lại khi lưu. Ô trống vẫn hiện gợi ý trong lúc nhập, rời ô trả về tối thiểu một vé. Đổi ô hoặc đổi bậc không tự lưu cấu hình; cấu hình Keno vẫn áp dụng chung cả 10 bậc và chỉ tác động kỳ chưa khóa.
- Bảng đối chiếu chỉ tải 20 vé/phương pháp/trang, có chuyển trang và nhập số trang; lưu/khóa/chấm toàn bộ danh mục, mọi thống kê dùng toàn bộ vé. API trang vé yêu cầu đăng nhập và chỉ đọc prediction đã thuộc chu kỳ hệ thống. Với danh mục lớn, điểm lưu kết quả thực tế và tổng hợp chính xác; phân loại từng vé được dựng từ bộ số bất biến và kết quả đã lưu, không đọc lại kết quả CSV để thay điểm.
- Danh sách đối chiếu từng kỳ hiển thị tối đa 3 kỳ/trang cho 5/35, Mega 6/45 và Power 6/55; Keno tối đa 10 kỳ/trang. Thanh số trang dưới danh sách có trước/sau, trang hiện tại, đầu/cuối và dấu … khi nhiều trang. Phân trang chỉ giới hạn chi tiết hiển thị, không giới hạn thống kê tổng hợp hoặc sửa dự đoán đã khóa; làm mới giữ trang hợp lệ, đổi loại/số kỳ nhật ký về trang đầu.
- Phân loại giải dùng kết quả thực tế đã lưu trong điểm ledger. Thiếu số đặc biệt cũ ghi chưa xác định khi hạng giải phụ thuộc số đó; không lấy CSV hiện tại để bổ sung hoặc sửa điểm đã lưu. Vé bao phải tách thành vé chuẩn; không coi quỹ Jackpot công bố là tiền một vé lĩnh thưởng hoặc xác nhận vé dự đoán đã được mua.

## Keno trong Hiệu quả dự đoán

Các quy tắc riêng của Keno trong Hiệu quả dự đoán:

- Worker backend chủ động lấy trang kết quả Keno mới nhất khoảng mỗi phút khi theo dõi bật hoặc còn kỳ đã khóa chờ chấm; chạy cả khi không mở tab Hiệu quả. Chỉ lấy một trang gần nhất, dùng User-Agent của crawler và timeout có giới hạn; có thể truy vấn đúng mã/ngày của kỳ đã khóa bị thiếu. Không chạy quét lịch sử toàn bộ, huấn luyện hoặc xuất điểm số trong lượt này. Ngừng gọi nguồn ngoài giờ 06:08–22:02, giữ dự đoán qua đêm đúng lịch.
- Đồng bộ nguồn trước, chấm kỳ đã khóa sau, rồi xét khóa kỳ mới. Chỉ thêm kết quả đủ 20 số hợp lệ, đúng mã/ngày/giờ và đã đến giờ quay. Giữ nguyên các dòng cũ và bất thường giờ lịch sử đã xác minh; mâu thuẫn nguồn/canonical phải báo lỗi. Loader/writer của luồng cập nhật nhanh không tự chuẩn hóa giờ lịch sử. Ghi CSV dùng khóa/version và đọc lại khi có writer khác cập nhật.
- Đọc báo cáo và tick trên DB riêng không gọi nguồn; dừng theo dõi vẫn lấy/chấm kết quả cho kỳ đã khóa, rồi ngừng tạo kỳ mới. Lỗi/độ trễ nguồn được lưu riêng và tự thử lại, không cản chấm kết quả canonical đã có. Báo cáo có trạng thái lần đồng bộ nguồn để kiểm tra hoạt động.
- Khóa một lần mã kỳ canonical mới nhất + 1 với đủ 10 bậc × bốn phương pháp trong cùng giao dịch; mặc định ba vé/phương pháp/bậc, cấu hình tối đa 10.000. Bậc 1 tối đa 80 bộ khác nhau, bậc 2 tối đa 3.160; bậc 3–10 tối đa 10.000. Lưu cả số yêu cầu và số thực dùng của từng bậc; bốn phương pháp cùng bậc có cùng ngân sách thực. Tất cả dùng cùng lịch sử và deadline; chọn bậc/trang là thao tác đọc, không tạo lại vé.
- Giờ quay lấy từ kỳ canonical, theo lịch 06:08–21:52, tám phút/kỳ; kỳ sau 21:52 là 06:08 ngày sau. Không dùng thời điểm nhận kết quả cộng tám phút. Giờ ghi điểm lưu riêng; chấm mã kỳ và ngày/giờ khớp deadline, kể cả kết quả về trễ hoặc theo dõi đã tắt.
- Khi canonical chưa cập nhật và deadline đã qua, bỏ lỡ khóa và chờ nguồn mới; không nhảy mã kỳ hoặc dựng lại dự đoán quá hạn. Số/giờ/mã kỳ mới nhất không hợp lệ chặn toàn bộ lần khóa. Bất thường giờ giữa các kỳ cũ được đếm và công bố trong snapshot, không tự sửa CSV và không chặn kỳ mới hợp lệ.
- Báo cáo chỉ mở chi tiết một bậc, 10 kỳ/trang; tổng quan 10 dòng và thống kê dùng mọi kỳ đã chấm. Query metadata/metrics nhỏ, không đọc tất cả payload/vé lịch sử để phân trang. Khóa và chấm đủ 40 prediction cùng giao dịch; generic ledger cá nhân không chấm các run của actor hệ thống.
- So cùng bậc và ngân sách; baseline số trùng kỳ vọng là bậc/4. Tỷ lệ có giải tính theo các hạng Keno chọn số, gồm trùng 0 ở bậc 8–10; không gộp với trùng đủ và không suy ra tiền thực nhận. Chẵn/lẻ và lớn/nhỏ là cách chơi khác, chưa nằm trong theo dõi này.
- CI ghép cặp theo khối ngày, mỗi kỳ trọng số bằng nhau; dưới 300 kỳ hoặc 7 ngày ghi chưa đủ bằng chứng. Thử nhiều bậc/phương pháp là thăm dò, chưa hiệu chỉnh nhiều giả thuyết; không tự promote/chọn bậc bằng kết quả đã xem. Ranking/xác suất/seed/manifest đã dùng được lưu để kiểm tra; tối ưu tính chung 10 bậc phải giữ kết quả giống chạy riêng từng bậc.

## Phòng thử thuật toán (5/35, Mega, Power)

- Phòng thử là kiểm tra lịch sử theo thời gian, tách khỏi các chu kỳ tương lai đã khóa. Mỗi fold chỉ dùng lịch sử trước kỳ mục tiêu, so pipeline web thường classic/normal/balanced và ba đối chứng với sáu cấu hình chấm điểm/phân bổ vé cùng ngân sách. Sáu cấu hình ghép ba cửa sổ lịch sử/trọng số với hai chính sách phân bổ, dùng chung hàm dự đoán khi thử lịch sử và theo dõi kỳ tương lai. Xác suất trộn về phân bố đều vẫn là chưa hiệu chỉnh.
- Tập validation chọn phương pháp bằng Brier của số chính trước khi chấm tập test giữ riêng; không chọn lại bằng kết quả test. Hạng giải được đếm riêng, không diễn giải lựa chọn Brier là tối ưu trực tiếp xác suất ĐB/Jackpot. Giữ artifact/champion cố định, chỉ cho phép khi cutoff huấn luyện trước kỳ validation đầu tiên và snapshot huấn luyện khớp lịch sử. Không mô tả replay artifact cố định là huấn luyện lại từng fold.
- Chạy thử lịch sử không ghi ledger, canonical, tracking hoặc model sản xuất; không tự promote. Báo cáo ghi split, cutoff, seed, hash dữ liệu/mã/artifact, engine thực và trạng thái hiệu chỉnh. Khi dữ liệu/mã/artifact thay đổi trong lượt thử, phải hủy kết quả không còn cùng snapshot. Báo cáo hoàn tất được lưu bất biến theo tài khoản trong `runtime/algorithm_lab.db`, giữ sau khi khởi động lại. Lịch sử hiển thị 20 lượt gần nhất và đọc metadata nhỏ; giới hạn bộ nhớ Java chỉ áp dụng tác vụ đang chạy/thất bại/hủy.
- API tạo/hủy lượt thử và bật/dừng theo dõi ứng viên yêu cầu admin; đọc báo cáo yêu cầu đăng nhập và đúng tài khoản đã tạo. Chạy tối đa một lượt thử tại một thời điểm; 1–10 vé/phương pháp, 5–50 kỳ validation và 5–50 kỳ test, tối thiểu 60 kỳ lịch sử trước hai tập đánh giá. Mặc định 20 kỳ chọn cấu hình và 30 kỳ kiểm tra. Lượt chạy giới hạn 15 phút, stdout báo cáo 8 MiB và stderr 256 KiB; vượt giới hạn phải dừng tiến trình.
- Ứng viên cấu hình được chọn riêng bằng validation Brier, đồng điểm xét số trùng trên validation; không chọn lại bằng test. Kết luận lịch sử so ứng viên với cả ngẫu nhiên và web, ghi rõ dưới 30 kỳ hoặc CI chưa hỗ trợ lợi thế. Kết quả lịch sử chỉ là chẩn đoán; không tự áp dụng vào model web.
- Theo dõi ứng viên chỉ bật khi admin chọn báo cáo đã lưu, cấu hình/mã nguồn khớp và prefix lịch sử cũ còn đúng. Một tài khoản/game chỉ có một ứng viên hoạt động, toàn hệ thống tối đa 8. Ba bộ số ứng viên/ngẫu nhiên/web có cùng cutoff và ngân sách, khóa trong cùng giao dịch trước giờ quay và lưu riêng trong DB phòng thử. Lặp bật hoặc dừng/bật lại không đổi vé đã khóa cùng kỳ.
- Worker theo dõi chấm kết quả khi canonical có kỳ tương ứng, không tạo ngược các kỳ đã quay hoặc vượt qua dữ liệu còn thiếu. Dừng theo dõi ngăn tạo kỳ mới; kỳ đã khóa vẫn chấm. Điểm và bộ số đã ghi giữ bất biến; kết luận dùng mọi kỳ đủ ba phương pháp, nhật ký chỉ giới hạn chi tiết. Thay mã/cấu hình/prefix lịch sử cũ phải chặn khóa kỳ mới; các kỳ đã khóa còn được chấm theo dữ liệu và payload đã lưu.
