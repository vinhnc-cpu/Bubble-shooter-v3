# Bubble-shooter-v3

Bubble Shooter 3: model dự báo người chơi bỏ game sau mỗi lượt và policy thêm / giữ / bớt bóng (DDA). Code đang chạy trên Airflow server `toh`.

## Cấu trúc

| Đường dẫn | Nội dung |
|---|---|
| `dags/dag_bb3_dda_daily.py` | DAG `bb3_dda_daily_train`, 15:00 UTC hằng ngày |
| `dags/bb3_dda/` | Project: `configs/`, `core/fe_lib.py` (feature), `pipeline/` (build_dataset, train, package, publish), `client/` (C# đọc model, policy tham chiếu), `data/` |
| `docker/` | `Dockerfile`, `requirements-lock.txt` (image `airflow-ml:2.9.0-lock-20261006`), ghi chú dựng lại container |

Chi tiết luồng, gói model và tích hợp phía game: [`dags/bb3_dda/README.md`](dags/bb3_dda/README.md).

## Cài đặt

1. Chép `dags/` vào thư mục DAG của Airflow. Thêm `bb3_dda/` vào `.airflowignore` để Airflow không quét project như DAG.
2. Thông tin ClickHouse: đặt biến môi trường `BB3_CH_HOST`, `BB3_CH_PORT`, `BB3_CH_USER`, `BB3_CH_PASSWORD`, hoặc copy `dags/bb3_dda/configs/local_secrets.example.py` thành `local_secrets.py` rồi điền (file này không commit).
3. Image: build từ `docker/Dockerfile` (thư viện cố định trong `requirements-lock.txt`).

Không commit: `work/`, `runs/`, `releases/` (dữ liệu và model sinh ra khi chạy), log, `local_secrets.py`.
