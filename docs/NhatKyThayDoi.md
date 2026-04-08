# Nhật Ký Thay Đổi

- 2026-04-02: Tái cấu trúc project Lotto sang layout VietlotFast.
- 2026-04-03: Thêm predictor_v2 cho luồng Dự Đoán Vip Loto_5/35, giữ fallback predictor cũ và thêm state/tracking riêng.
- 2026-04-03: Cập nhật canonical CSV sang header tiếng Việt có cột Thứ và Link cập nhật, đồng thời giữ loader/writer tương thích cả format cũ lẫn mới.
- 2026-04-03: Nối Dự Đoán Vip 6/45 của web sang predictor adaptive riêng, đồng thời vá predictor_v2 đọc được header canonical CSV mới để Vip 5/35 không rơi về fallback.
- 2026-04-03: Thêm project standalone `power_6_55_predictor` cho Power 6/55 với parser schema tiếng Việt, tracking main/special tách riêng, scoring heuristic-first, scaffold deep model, CLI predict/update/backtest, và payload sẵn sàng để nối vào Vip sau.
- 2026-04-03: Nối Dự Đoán Vip 6/55 của web sang `power_6_55_predictor`, thêm wrapper adaptive trong `ai_predict.py`, cập nhật nhận diện engine/nhãn ở frontend, và giữ fallback predictor cũ nếu nhánh mới lỗi.
- 2026-04-03: Đổi tên thư mục predictor Mega 6/45 từ `lotto_6_45_predictor` sang `mega_6_45_predictor` để khớp đúng tên game và cập nhật đường dẫn gọi Vip tương ứng.
- 2026-04-03: Tách Vip 5/35 thành project standalone `loto_5_35_predictor`, giữ `predictor_v2` làm fallback, và đổi web/backend sang dùng predictor mới với nhãn riêng như Mega 6/45 và Power 6/55.
- 2026-04-03: Dọn lại cấu trúc repo, gom toàn bộ predictor standalone và `predictor_v2` vào `ai/standalone_predictors/`, chuyển state của `predictor_v2` vào đúng project, và làm sạch các thư mục cache để cây thư mục gọn hơn.
