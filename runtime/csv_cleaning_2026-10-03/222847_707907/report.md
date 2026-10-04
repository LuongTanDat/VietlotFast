# Làm sạch CSV dự án

Áp dụng: True. Lỗi: 0.

| CSV | Số dòng | Ô thay đổi |
|---|---:|---:|
| ai/standalone_predictors/loto_5_35_predictor/data/loto_5_35.csv | 556 | 602 |
| ai/standalone_predictors/mega_6_45_predictor/data/mega_6_45.csv | 1490 | 1497 |
| ai/standalone_predictors/power_6_55_predictor/data/power_6_55.csv | 1323 | 2660 |
| data/exports/scoring/keno_number_scoring_full_latest.csv | 80 | 0 |
| data/exports/scoring/loto_5_35_number_scoring_full_latest.csv | 35 | 0 |
| data/exports/scoring/loto_5_35_special_number_scoring_full_latest.csv | 12 | 0 |
| data/exports/scoring/loto_6_45_number_scoring_full_latest.csv | 45 | 0 |
| data/exports/scoring/loto_6_55_number_scoring_full_latest.csv | 55 | 0 |
| data/exports/scoring/max_3d_number_scoring_full_latest.csv | 1000 | 0 |
| data/exports/scoring/max_3d_pro_number_scoring_full_latest.csv | 1000 | 0 |

CSV bộ dự đoán được giữ nguyên phạm vi kỳ; tiền thưởng đối chiếu với CSV canonical.
CSV điểm số được kiểm tra đủ số, hạng duy nhất, điểm hữu hạn và thứ tự xếp hạng.
Cảnh báo nguồn KENO: ['276032', '276033'], ['12:40', '12:24']; giữ nguyên giờ đã xác minh.
