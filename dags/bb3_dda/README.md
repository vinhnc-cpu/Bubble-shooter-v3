# bb3_dda — Bubble Shooter 3: model bỏ game + thêm/bớt bóng

DAG `bb3_dda_daily_train` (15:00 UTC hằng ngày) train lại model dự báo bỏ game sau mỗi lượt chơi và đóng gói để game dự báo trên máy user.

## Luồng

| Bước | Việc làm |
|---|---|
| `check_source` | Tìm ngày gần nhất có đủ dữ liệu (≥ 500k `level_up`). Bảng staging thường trễ 1-2 ngày; trễ > 4 ngày thì fail và thử lại sau 1 giờ |
| `build_dataset` | User Android có `first_open`, cài trong 240 ngày. Chỉ giữ lượt chơi đủ 7 ngày quan sát. Chia 40 phần theo hash user → `work/<ngày>/` |
| `train_model` | LightGBM tối đa 300 cây. Train trên user cài sớm; 35 ngày cài gần nhất làm valid (½ dừng sớm, ½ đánh giá và tính ngưỡng) → `runs/<ngày>/` |
| `package_model` | Xuất `model.bin` + `manifest.json` + `levels.json` + `country_tier.json`, kiểm tra dự báo từ `model.bin` khớp LightGBM |
| `gate_and_publish` | Chỉ thay model đang dùng nếu ROC không giảm quá 0.005 và PR-AUC không dưới 95% của model đang dùng → `releases/<version>/` và `releases/latest/` |
| `cleanup` | Xóa `work/<ngày>`, giữ 14 bản `runs/` và `releases/` gần nhất |

## Gói model cho game (`releases/latest/`)

| File | Nội dung |
|---|---|
| `model.bin` | Cây quyết định dạng mảng (định dạng BB3D v1, khoảng 0.6 MB; `model.bin.gz` để tải về) |
| `manifest.json` | `version`, thứ tự 40 feature, ngưỡng đánh dấu `thr_flag` và rủi ro thấp `thr_low` theo vùng màn, tham số policy, chỉ số đánh giá, sha256 từng file |
| `levels.json` | 1000 màn: `total_balls`, `mu`, `sd` (bóng dư khi thắng), `loss_rate`, `jump` |
| `country_tier.json` | Mã quốc gia → `tier_code` (0 T1, 1 T2, 2 T3, 3 Z; mặc định 3) |

`model.txt` (LightGBM) nằm cùng thư mục chỉ để so sánh lần sau, không đưa vào game.

## Tích hợp phía game

1. Đọc model: `client/DdaModel.cs` → `DdaModel.Load(bytes)`, rồi `Predict(double[40])`.
2. Tính 40 feature sau mỗi lượt theo đúng `core/fe_lib.py` và thứ tự trong `manifest.features`. Giá trị thiếu truyền `NaN`.
3. So điểm với `thr_flag` / `thr_low` theo vùng màn (1-5 / 6-10 / 11+), rồi áp dụng policy v6 (`dda_policy_v6.py`) với tham số trong `manifest.policy`.
4. Tracking (chỉ user nhóm treatment): thêm param vào `level_up`: `dda_model_version`, `dda_p_value`, `balls_base`, `balls_delta`, `dda_action`.
5. Kiểm tra `sha256` trước khi dùng file tải về; lỗi thì giữ model cũ.

## Chạy tay

```
airflow dags trigger bb3_dda_daily_train --conf '{"run_date": "2026-10-02"}'
```
