# Loto 5/35 Predictor

Predictor standalone cho `Vip 5/35`, tách riêng khỏi `predictor_v2` để đồng bộ cách tổ chức với `mega_6_45_predictor` và `power_6_55_predictor`.

## Chạy nhanh

```powershell
cd "c:\Users\Luong Tan Dat\OneDrive\Vsuacode\Dự Án\Lotto\ai\standalone_predictors\loto_5_35_predictor"
python main.py predict --csv data/loto_5_35.csv
```

## Lệnh hỗ trợ

```powershell
python main.py predict --csv data/loto_5_35.csv --slot 13:00
python main.py update --csv data/loto_5_35.csv --actual-ky 557
python main.py backtest --csv data/loto_5_35.csv
```

## Ghi chú

- Engine này kế thừa logic heuristic-first đang chạy ổn của `predictor_v2`, nhưng state, config và CLI đã được tách riêng.
- `predictor_v2` vẫn được giữ lại trong repo như fallback an toàn cho các nhánh cũ.
