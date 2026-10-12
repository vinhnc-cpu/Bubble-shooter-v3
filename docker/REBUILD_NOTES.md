# Airflow trên server toh: image, thư viện và secret key

Cập nhật 2026-10-06.

## Image

- Các service Airflow trong `docker-compose.yaml` dùng image **`airflow-ml:2.9.0-lock-20261006`**, build từ `Dockerfile` trong thư mục này.
- `Dockerfile` cài thư viện từ **`requirements-lock.txt`**. File này gồm 63 gói, phiên bản lấy đúng từ `pip freeze` của worker đang chạy ổn định ngày 2026-10-06 (chỉ các gói khác image gốc `apache/airflow:2.9.0`).
- Đã kiểm tra trước khi đổi: `pip freeze` của image khớp 404/404 gói với worker, `pip check` giống hệt, đọc 23 DAG không có lỗi import.
- `requirements.txt` cũ (không ghi phiên bản) không còn được dùng. Bản sao lưu: `requirements.txt.bak_*`, `Dockerfile.bak_*`.

Trước ngày này, các container chạy image cũ `c40f95e540b4`, còn các thư viện ML (lightgbm, numba, mlflow, clickhouse-connect/driver, river, …) được cài thêm vào container lúc chạy. Tạo lại container bằng image cũ sẽ làm mất các thư viện này.

## Thêm hoặc đổi thư viện

1. Sửa `requirements-lock.txt` và luôn ghi phiên bản (`ten==phien_ban`).
2. Build với tag mới: `docker build -t airflow-ml:2.9.0-lock-<ngay> .`
3. Kiểm tra: `pip check`, và đọc DAG bằng `DagBag("/opt/airflow/dags")` trong image mới, phải không có lỗi import.
4. Đổi dòng `image:` trong `docker-compose.yaml` sang tag mới, rồi tạo lại container (mục dưới).

## Tạo lại container (lưu ý lỗi docker-compose 1.29.2)

Các container được tạo bằng `docker-compose` 1.29.2. Bản này lỗi `KeyError: 'ContainerConfig'` khi **tạo lại** container trên Docker Engine mới. Cách tránh:

```bash
cd ~/airflow
# chi lam khi khong co task nao dang chay
docker-compose stop airflow-webserver airflow-scheduler airflow-worker airflow-triggerer
docker-compose rm -f airflow-webserver airflow-scheduler airflow-worker airflow-triggerer airflow-init
docker-compose up -d
```

Không dùng `docker compose` (v2) với các container hiện tại: v2 đặt tên container khác (`airflow-airflow-worker-1`), có thể tạo trùng container.

## Secret key (sửa lỗi 403 khi xem log task trên giao diện web)

- Key chung nằm ở `.env` (`AIRFLOW__WEBSERVER__SECRET_KEY`) và được đưa vào container qua `docker-compose.yaml`.
- Các container đang chạy (tạo trước ngày 2026-10-06) nhận key qua `/opt/airflow/airflow.cfg` bên trong từng container (đã sửa tay và `docker restart`). Khi tạo lại container, key lấy từ `.env`, cùng giá trị.
