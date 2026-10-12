FROM apache/airflow:2.9.0
USER root
RUN apt-get update -y &&     apt-get install -y curl gnupg ca-certificates libgomp1 &&     curl -fsSL https://packages.clickhouse.com/rpm/lts/repodata/repomd.xml.key | gpg --dearmor -o /usr/share/keyrings/clickhouse.gpg &&     echo "deb [signed-by=/usr/share/keyrings/clickhouse.gpg] https://packages.clickhouse.com/deb stable main" | tee /etc/apt/sources.list.d/clickhouse.list &&     echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" | tee /etc/apt/sources.list.d/google-cloud-sdk.list &&     curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg &&     apt-get update -y &&     apt-get install -y clickhouse-client google-cloud-cli &&     apt-get clean &&     rm -rf /var/lib/apt/lists/* &&     rm -rf /home/airflow/.config &&     mkdir -p /home/airflow/.config/gcloud/configurations &&     chown -R airflow:root /home/airflow/.config
# requirements-lock.txt: phiên bản cố định lấy từ worker (requirements.txt cũ không ghi phiên bản, build lại có thể đổi phiên bản)
COPY requirements-lock.txt /tmp/requirements-lock.txt
USER airflow
RUN pip install --no-cache-dir "apache-airflow==2.9.0" -r /tmp/requirements-lock.txt
