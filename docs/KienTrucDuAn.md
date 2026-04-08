# Kiến Trúc Dự Án

Tổng quan cấu trúc thư mục, backend, frontend, AI và luồng dữ liệu.

- `ai/`: mã AI, predictor, model, config, training
  Bên trong `ai/standalone_predictors/`: predictor standalone cho Vip 5/35, Mega 6/45, Power 6/55 và predictor_v2 legacy
- `docs/`: tài liệu vận hành và ghi chú dự án
- `data/`: dữ liệu canonical và export scoring
- `backend/`: backend Python, Java server, thư viện JDBC
- `frontend/`: giao diện HTML, CSS, JavaScript
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
