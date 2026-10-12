"""
DAG: bb3_dda_daily_train
Lịch: 15:00 UTC (22:00 VN) hằng ngày - sau dag_raw_to_staging (10 UTC) và các DAG ML lúc 12 UTC.

Bubble Shooter 3 - DDA: train lại model dự báo bỏ game sau mỗi lượt (LightGBM, tối đa 300 cây),
đóng gói nhỏ gọn để game dự báo trên máy user.

Luồng:
  check_source -> build_dataset -> train_model -> package_model -> gate_and_publish -> cleanup

  check_source     : tìm ngày gần nhất có đủ dữ liệu (bảng staging thường trễ 1-2 ngày); trễ > 4 ngày -> fail, thử lại sau 1 giờ
  build_dataset    : cohort Android first_open cài trong 240 ngày, chỉ giữ lượt đủ 7 ngày quan sát,
                     chia 40 phần theo hash user (vừa 16 GB RAM worker) -> work/<ds>/chunk_XX.parquet
  train_model      : train trên user cài sớm, valid = 35 ngày cài gần nhất (1/2 dừng sớm, 1/2 đánh giá),
                     tính ngưỡng gắn cờ 15% và rủi ro thấp 70% theo vùng màn -> runs/<ds>/
  package_model    : model.bin + manifest.json + levels.json + country_tier.json, kiểm tra parity với LightGBM
  gate_and_publish : model mới chỉ thay model đang dùng nếu không kém hơn trên cùng tập đánh giá
                     -> releases/<version>/ và releases/latest/ ; không đạt -> skip (giữ model cũ)
  cleanup          : xóa work/<ds> (chỉ khi các bước trước không lỗi, để chạy lại không phải dựng lại dữ liệu),
                     giữ 14 bản runs/ và releases/ gần nhất

Code: /opt/airflow/dags/bb3_dda (host: ~/airflow/dags/bb3_dda). Client đọc model: bb3_dda/client/DdaModel.cs

Chạy tay cho một ngày:
  airflow dags trigger bb3_dda_daily_train --conf '{"run_date": "2026-10-02"}'
"""
import logging
import os
import sys
from datetime import date, datetime, timedelta

from airflow import DAG
from airflow.exceptions import AirflowSkipException
from airflow.operators.python import PythonOperator

PROJECT_DIR = "/opt/airflow/dags/bb3_dda"
logger = logging.getLogger(__name__)

default_args = {
    "owner":            "ml-team",
    "retries":          1,
    "retry_delay":      timedelta(minutes=60),
    "email_on_failure": False,
}


def _setup():
    if PROJECT_DIR not in sys.path:
        sys.path.insert(0, PROJECT_DIR)
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpl")


def _run_date(context):
    conf = context["dag_run"].conf or {}
    if conf.get("run_date"):
        return date.fromisoformat(conf["run_date"])
    # lịch 15:00 UTC: data_interval_end = ngày chạy
    return context["data_interval_end"].date()


def _paths(run_date):
    from configs import settings as S
    tag = run_date.strftime("%Y%m%d")
    return os.path.join(S.WORK_DIR, tag), os.path.join(S.RUNS_DIR, tag)


def _check_source(**context):
    _setup()
    from pipeline.build_dataset import check_source
    data_end = check_source(_run_date(context))
    context["ti"].xcom_push(key="data_end", value=data_end)
    logger.info("[bb3_dda] du lieu day du den het %s", data_end)


def _build_dataset(**context):
    _setup()
    from pipeline.build_dataset import build_dataset
    rd = _run_date(context)
    work, _ = _paths(rd)
    data_end = date.fromisoformat(context["ti"].xcom_pull(task_ids="check_source", key="data_end"))
    info = build_dataset(data_end, work)
    context["ti"].xcom_push(key="windows", value=info)
    logger.info("[bb3_dda] build_dataset: %s", info)


def _train_model(**context):
    _setup()
    from pipeline.train import train_model
    work, run = _paths(_run_date(context))
    res = train_model(work, run)
    logger.info("[bb3_dda] train: trees=%s new=%s prod=%s", res["trees"], res["new"]["roc"],
                res.get("prod", {}).get("roc"))


def _package_model(**context):
    _setup()
    import json
    from pipeline.package import package
    rd = _run_date(context)
    _, run = _paths(rd)
    metrics = json.load(open(os.path.join(run, "metrics.json")))
    windows = context["ti"].xcom_pull(task_ids="build_dataset", key="windows") or {}
    out = package(run, rd, windows, metrics)
    context["ti"].xcom_push(key="version", value=out["version"])
    logger.info("[bb3_dda] package: %s", out)


def _gate_and_publish(**context):
    _setup()
    import json
    from pipeline.publish import gate, publish
    _, run = _paths(_run_date(context))
    metrics = json.load(open(os.path.join(run, "metrics.json")))
    ok, why = gate(metrics)
    logger.info("[bb3_dda] gate: %s | %s", "DAT" if ok else "KHONG DAT", why)
    if not ok:
        raise AirflowSkipException("Model moi kem hon model dang dung - giu model cu. " + why)
    version = context["ti"].xcom_pull(task_ids="package_model", key="version")
    publish(run, version)


def _cleanup(**context):
    _setup()
    from pipeline.publish import cleanup
    work, run = _paths(_run_date(context))
    # chỉ xóa dữ liệu tạm khi train đã xong (có metrics.json); nếu lần chạy bị dừng giữa chừng
    # (các bước bị đánh dấu skipped) thì giữ lại để lần sau dùng tiếp, không phải dựng lại từ đầu
    if not os.path.exists(os.path.join(run, "metrics.json")):
        logger.info("[bb3_dda] cleanup: train chua xong -> giu %s", work)
        return
    cleanup(work)


with DAG(
    dag_id="bb3_dda_daily_train",
    description="Bubble Shooter 3 DDA: train lai model bo game hang ngay + dong goi cho thiet bi",
    schedule="0 15 * * *",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["ml", "bubble_shooter_v3", "dda", "training"],
) as dag:
    t1 = PythonOperator(task_id="check_source", python_callable=_check_source)
    t2 = PythonOperator(task_id="build_dataset", python_callable=_build_dataset,
                        execution_timeout=timedelta(hours=3))
    t3 = PythonOperator(task_id="train_model", python_callable=_train_model,
                        execution_timeout=timedelta(hours=2))
    t4 = PythonOperator(task_id="package_model", python_callable=_package_model,
                        execution_timeout=timedelta(minutes=30))
    t5 = PythonOperator(task_id="gate_and_publish", python_callable=_gate_and_publish)
    t6 = PythonOperator(task_id="cleanup", python_callable=_cleanup, trigger_rule="none_failed")
    t1 >> t2 >> t3 >> t4 >> t5 >> t6
