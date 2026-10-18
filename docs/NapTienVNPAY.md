# Nạp PayPal tự động qua VNPAY-QR

Giao diện `/nap-tien` tạo đơn ở server rồi cung cấp liên kết mở VNPAY-QR. Khách quét mã trên trang VNPAY bằng ứng dụng ngân hàng. Số dư PayPal trong ứng dụng là điểm nội bộ, không phải ví PayPal của nhà cung cấp PayPal.

## Đăng ký thử nghiệm khi chưa có merchant

1. Mở [Đăng ký Merchant môi trường test](https://sandbox.vnpayment.vn/devreg/). Điền tên website (ví dụ Lotto), địa chỉ URL website, email nhận thông tin, mật khẩu/nhập lại mật khẩu và mã xác nhận. URL phải là địa chỉ của website bạn dùng thử; không điền tên miền của người khác. Nếu form không chấp nhận localhost, cần chuẩn bị URL công khai trước; chưa xác minh VNPAY chấp nhận localhost khi đăng ký.
2. Kiểm tra email đã đăng ký, cả thư rác. Theo tài liệu VNPAY, hệ thống gửi thông tin kết nối về email này. Lấy TmnCode và HashSecret cho sandbox; không dùng mật khẩu tài khoản đăng ký làm HashSecret, không gửi khóa qua chat.
3. File `runtime/vnpay.properties` đã được tạo với `enabled=false`, `environment=sandbox` và khóa để trống. Điền hai giá trị tương ứng vào `tmnCode`/`hashSecret` trên máy. Khi có địa chỉ HTTPS công khai, điền origin đó vào `publicBaseUrl`, cấu hình reverse proxy và đăng ký hai URL IPN/Return bên dưới với VNPAY. Chỉ bật `enabled=true` khi các thông tin đã đầy đủ.
4. Mở website bằng địa chỉ HTTPS đã cấu hình, đăng nhập và tải lại trang Nạp tiền. Thử tạo đơn, thanh toán thử, quay về và nhận IPN. Chạy chỉ từ localhost chưa kiểm chứng được IPN từ VNPAY vào máy.
5. Xác nhận với VNPAY rằng merchant sandbox hỗ trợ VNPAY-QR. [Trang demo chính thức](https://sandbox.vnpayment.vn/apis/vnpay-demo/) lưu ý môi trường test chỉ hỗ trợ các thẻ thử được liệt kê; không mặc định mọi ngân hàng/QR đều dùng được. Nếu QR chưa được bật, cần VNPAY hỗ trợ hoặc bổ sung phương thức thẻ thử trước khi kiểm thử đầu-cuối. Không chuyển tiền thật để thử sandbox; bản tích hợp chỉ ghi nhận `TEST_PAID`, không cộng số dư thật.

Các bước và thông tin kết nối đối chiếu theo [tài liệu tích hợp VNPAY PAY](https://sandbox.vnpayment.vn/apis/docs/thanh-toan-pay/pay.html). Chưa có merchant hoặc HTTPS thì giao diện vẫn thông báo chưa cấu hình; không hiển thị thành công giả.

## Cấu hình

Điền thông tin do VNPAY cấp vào `runtime/vnpay.properties`; mẫu nằm tại [vnpay.properties.example](vnpay.properties.example). File runtime bị Git bỏ qua. Không đưa HashSecret vào frontend, ảnh chụp, chat hoặc commit.

| Trường | Giá trị |
| --- | --- |
| `enabled` | `true` khi đã cấu hình đầy đủ; mặc định `false` |
| `environment` | `sandbox` để thử; `production` để nạp thật |
| `tmnCode` | Mã website 8 ký tự VNPAY cấp cho đúng môi trường |
| `hashSecret` | Khóa bí mật VNPAY cấp cho đúng môi trường |
| `publicBaseUrl` | Origin HTTPS của website, không kèm đường dẫn/query |
| `maxAmount` | Mặc định 10.000.000 VNĐ, có thể đặt 10.000–100.000.000 |

Các biến môi trường tương ứng, nếu có, ưu tiên hơn file: `LOTTO_VNPAY_ENABLED`, `LOTTO_VNPAY_ENVIRONMENT`, `LOTTO_VNPAY_TMN_CODE`, `LOTTO_VNPAY_HASH_SECRET`, `LOTTO_VNPAY_PUBLIC_BASE_URL`, `LOTTO_VNPAY_MAX_AMOUNT`.

Server đọc cấu hình mỗi request; không cần restart sau khi điền/sửa file. Trình duyệt tải lại trang nạp để cập nhật trạng thái. Production yêu cầu HTTPS và từ chối origin localhost. Khi cấu hình origin HTTPS, truy cập website bằng chính origin HTTPS này để cookie đăng nhập hoạt động đúng. Sandbox có thể tạo URL từ localhost HTTP, nhưng để nhận IPN tự động vẫn cần endpoint công khai truy cập được qua HTTPS/proxy. Không mở DB hoặc file khóa ra Internet; reverse proxy chỉ chuyển các URL web/API cần thiết tới server hiện bind `127.0.0.1`.

Đăng ký với VNPAY:

- **IPN**: `https://TEN-MIEN/api/payments/vnpay/ipn`
- **Return URL**: `https://TEN-MIEN/api/payments/vnpay/return`

VNPAY phải bật phương thức VNPAY-QR cho merchant. Dùng TmnCode/HashSecret và tên miền đã được VNPAY chấp thuận; không dùng khóa mẫu trên mạng. Sandbox có thể đăng ký tại [trang đăng ký thử nghiệm VNPAY](https://sandbox.vnpayment.vn/devreg/).

## Luồng và tính toàn vẹn

- Chỉ tài khoản đăng nhập tạo/xem đơn của chính mình. Server tính tỷ lệ 1,25 và thưởng: 50.000 +625, 100.000 +1.875, 200.000 +5.000, 500.000 +15.625 PayPal; không nhận giá trị thưởng/số dư từ client.
- Tối thiểu 10.000 VNĐ, bội số 1.000 VNĐ để số điểm cộng vào ví là số nguyên. Đơn có hạn 15 phút; tối đa 5 đơn gần đây/đang còn hạn cho một tài khoản. Không xóa đơn cũ khi chạm giới hạn. Lịch sử trả tối đa 100 đơn mới nhất; toàn bộ bản ghi vẫn giữ trong DB.
- Mã đơn ngẫu nhiên, idempotency theo tài khoản + requestId. Thử lại khi mất mạng dùng cùng requestId để tránh tạo trùng. Cùng requestId nhưng khác số tiền/merchant/môi trường bị từ chối.
- URL VNPAY dùng 2.1.0, `vnp_BankCode=VNPAYQR`, VND, amount nhân 100, HMAC-SHA512 theo tham số đã encode và sắp xếp. URL/khóa không lấy từ trình duyệt.
- Return URL chỉ chuyển về trang nạp. Kể cả Return có chữ ký đúng và mã thành công, nó không cộng tiền.
- IPN kiểm tra chữ ký constant-time, từ chối tham số lặp, đối chiếu merchant/môi trường/mã đơn/số tiền/nội dung, yêu cầu cả `vnp_ResponseCode` và `vnp_TransactionStatus` bằng `00` để ghi nhận thành công.
- Production cập nhật trạng thái đơn, số dư, walletVersion và audit trong cùng transaction. Unique transaction number + trạng thái đơn chặn cộng hai lần khi IPN lặp/song song hoặc khi restart. RspCode đúng chuẩn `00/01/02/04/97/99`; lỗi DB/giới hạn ví rollback để VNPAY có thể gửi lại.
- IPN thành công đến trễ sau hạn hiển thị vẫn được xử lý nếu đơn còn pending và đối soát đúng; không làm mất thanh toán chỉ vì gửi thông báo chậm. Không tự suy thành công từ đếm ngược, URL quay về hay nút kiểm tra.
- Sandbox chỉ ghi `TEST_PAID` và audit, không cộng ví production. Không đổi mode/TmnCode/khóa khi còn đơn chưa đối soát; cần xử lý hết hoặc giữ cấu hình cũ để nhận lại IPN.
- Đổi tên tài khoản chuyển quyền sở hữu đơn trong cùng transaction; xóa tài khoản đưa đơn sang chủ sở hữu tombstone, đơn pending thành `OWNER_DELETED`, không chuyển tiền nhầm khi tên tài khoản được đăng ký lại.
- Frontend chỉ lấy wallet do server trả về. Đổi tài khoản/đăng xuất/ẩn trang dừng request và polling, bỏ phản hồi cũ. Yêu cầu nạp thủ công trước đây giữ để tham khảo, gắn Chưa xác minh và không dùng làm căn cứ cộng ví.

## Kiểm thử trước khi bật thật

Chạy `tests.test_vnpay_payments.VnpayBackendTests` và `tests.test_paypal_deposit_ui.PaypalDepositUITests`. Các test dùng DB riêng, khóa giả và callback ký trong fixture, không gọi cổng VNPAY và không tạo giao dịch thật.

Sau khi có thông tin merchant, cần chạy thử end-to-end trên sandbox VNPAY với domain/IPN đã đăng ký. Kiểm tra thanh toán thành công, hủy, timeout và IPN gửi lại; ví thật không tăng trong sandbox. Chỉ đổi sang production sau khi hoàn tất kiểm thử và nhận cấu hình production từ VNPAY.

Chưa có tự động hoàn tiền hoặc querydr định kỳ. Nếu IPN không đến/không được xác minh, đơn không được tự cộng; cần đối soát tại VNPAY và khắc phục IPN theo thông tin merchant. Kiểm tra DB `payment_orders` và `account_audit` khi cần hỗ trợ; không công khai HashSecret hay toàn bộ callback ngân hàng.

Tham chiếu: [đặc tả tích hợp VNPAY PAY 2.1.0, IPN và Return](https://sandbox.vnpayment.vn/apis/docs/thanh-toan-pay/pay.html).
