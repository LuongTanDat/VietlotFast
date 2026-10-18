# Cấu hình đăng nhập Google, Facebook và Zalo

Giao diện và luồng OAuth được chuẩn bị sẵn. Khi chưa có ứng dụng nhà phát triển, các cổng mạng xã hội chưa được kích hoạt; đăng nhập/đăng ký bằng tên tài khoản vẫn hoạt động.

## Thiết lập trên máy

1. Sao chép `config/social-login.properties.example` thành `runtime/social-login.properties`.
2. Điền `publicBaseUrl` là origin của website. Website công khai cần HTTPS và reverse proxy trỏ vào server `127.0.0.1:8080`; không mở server trực tiếp ra Internet. Google có thể thử ở địa chỉ loopback HTTP đã khai báo. Facebook/Zalo phải tuân theo yêu cầu URL của ứng dụng tương ứng.
3. Điền ID và Secret của từng ứng dụng. Facebook cần thêm phiên bản Graph API đang được ứng dụng hỗ trợ, lấy trong Meta Developers. Để trống nhà cung cấp chưa dùng.
4. Đăng ký chính xác các callback dưới đây. Tải lại trang sau cấu hình; khởi động lại backend khi thay origin đang sử dụng.

| Nhà cung cấp | Callback |
|---|---|
| Google | `https://your-domain/api/auth/social/callback/google` |
| Facebook | `https://your-domain/api/auth/social/callback/facebook` |
| Zalo | `https://your-domain/api/auth/social/callback/zalo` |

Các URL ở bảng là ví dụ, phải thay bằng origin thật của bạn. Google thử cục bộ dùng `http://127.0.0.1:8080/api/auth/social/callback/google` và truy cập website cùng origin đó. Callback phải khớp cả giao thức, hostname, cổng và đường dẫn.

Có thể dùng biến môi trường thay file:

| Khóa file | Biến môi trường |
|---|---|
| `publicBaseUrl` | `LOTTO_PUBLIC_BASE_URL` |
| `google.clientId` / `google.clientSecret` | `LOTTO_OAUTH_GOOGLE_CLIENT_ID` / `LOTTO_OAUTH_GOOGLE_CLIENT_SECRET` |
| `facebook.clientId` / `facebook.clientSecret` | `LOTTO_OAUTH_FACEBOOK_CLIENT_ID` / `LOTTO_OAUTH_FACEBOOK_CLIENT_SECRET` |
| `facebook.graphVersion` | `LOTTO_OAUTH_FACEBOOK_GRAPH_VERSION` |
| `zalo.clientId` / `zalo.clientSecret` | `LOTTO_OAUTH_ZALO_CLIENT_ID` / `LOTTO_OAUTH_ZALO_CLIENT_SECRET` |

Giá trị môi trường ưu tiên hơn file. Không đưa khóa thật vào `frontend/`, file mẫu, Git hoặc chat. `runtime/` đã được Git bỏ qua. Backend không trả ID/Secret/token trong API cấu hình; token chỉ dùng trong lượt xác minh và không được lưu.

## Tạo ứng dụng

- Google: tạo OAuth client cho **Web application**, cấu hình consent screen và callback. Chỉ yêu cầu `openid profile`. Trong chế độ thử nghiệm, thêm tài khoản thử theo cấu hình của Google.
- Meta: tạo ứng dụng có Facebook Login, bật luồng web và khai báo callback; chọn phiên bản Graph API trong ứng dụng. Chỉ yêu cầu `public_profile`. Tài khoản ngoài danh sách vai trò thử nghiệm chỉ sử dụng được khi ứng dụng/quyền được Meta cho phép.
- Zalo: tạo ứng dụng **Zalo Social**, khai báo callback và thông tin ứng dụng. Luồng dùng User Access Token V4 và PKCE, không phải Official Account/OA.

## Tài khoản và phiên

Phải có admin cục bộ trước khi kích hoạt đăng nhập mạng xã hội. Tài khoản mới luôn là `user`; không tự cấp Admin/VIP/tài sản. Danh tính được lưu theo bộ nhà cung cấp + Client/App ID + ID người dùng đã xác minh; không tự gộp vào tài khoản cũ qua email hoặc tên hiển thị. Đăng nhập lại cùng danh tính trở về cùng tài khoản. Mỗi nhà cung cấp/ứng dụng có tài khoản riêng nếu chưa có luồng liên kết được xác thực. Thay Client/App ID được xem là ứng dụng khác; không tự ghép các ID người dùng có thể trùng giữa hai ứng dụng.

Backend kiểm tra state ngẫu nhiên, cookie gắn với trình duyệt, thời hạn 10 phút và sử dụng một lần. Google/Zalo dùng PKCE; Facebook được kiểm tra app ID/user ID qua token debugger và appsecret proof. Session ứng dụng dùng cơ chế hiện có, có kiểm tra khóa tài khoản, hết hạn và thay mật khẩu. Cookie được đặt Secure khi origin đã cấu hình là HTTPS.

Các nhà cung cấp dùng endpoint cố định, không nhận endpoint từ client. Request có timeout, giới hạn phản hồi và không theo redirect mang token. Chưa có khóa thật nên chưa thể kiểm chứng đăng nhập với tài khoản Google/Facebook/Zalo thật; kiểm thử dự án dùng nhà cung cấp giả lập riêng, không có hook giả lập trong server vận hành.

## Nguồn chính thức

- [Google OAuth cho ứng dụng web](https://developers.google.com/identity/protocols/oauth2/web-server), [hướng dẫn thương hiệu Google](https://developers.google.com/identity/branding-guidelines). Biểu tượng G dùng file gốc từ Google, lưu tại `frontend/auth-google-logo.png`.
- [Facebook Login](https://developers.facebook.com/docs/facebook-login/guides/advanced/manual-flow/), [SDK OAuth do Facebook phát hành](https://github.com/facebookarchive/php-graph-sdk/blob/5.x/src/Facebook/Authentication/OAuth2Client.php).
- [Zalo Developers](https://developers.zalo.me/), [SDK Zalo V4 chính thức](https://github.com/zaloplatform/zalo-php-sdk/blob/master/src/Authentication/OAuth2Client.php), [endpoint Social API](https://github.com/zaloplatform/zalo-php-sdk/blob/master/src/ZaloEndPoint.php).
