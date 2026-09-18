#!/bin/bash
# Rendered by main.tf's templatefile() and run as root via cloud-init on first boot.
set -eu

exec > >(tee /var/log/user-data.log | logger -t user-data) 2>&1

echo "=== rag_ingestion user-data: starting $(date -u) ==="

apt-get update -y
apt-get install -y docker.io git curl
systemctl enable --now docker
usermod -aG docker ubuntu

mkdir -p /usr/local/lib/docker/cli-plugins
curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64" \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# Nitro instance types often expose the attached EBS volume as /dev/nvme1n1, not /dev/xvdf.
if [ -e /dev/nvme1n1 ]; then
  DEV=/dev/nvme1n1
else
  DEV=/dev/xvdf
fi

if [ -b "$DEV" ]; then
  if ! blkid "$DEV" >/dev/null 2>&1; then
    echo "Formatting $DEV as ext4 (no filesystem detected)"
    mkfs.ext4 "$DEV"
  else
    echo "$DEV already has a filesystem, skipping mkfs"
  fi

  mkdir -p /data

  if ! grep -qF "$DEV" /etc/fstab; then
    echo "$DEV /data ext4 defaults,nofail 0 2" >> /etc/fstab
  fi

  mount /data || mount -a
else
  echo "WARNING: expected data volume device not found at $DEV -- skipping mount. Check block device naming manually (lsblk)."
fi

if [ ! -d /opt/gates_ai_lld ]; then
  git clone --branch "${repo_ref}" "${repo_url}" /opt/gates_ai_lld
else
  echo "/opt/gates_ai_lld already exists, skipping clone"
fi

# Root-owned, 600 -- holds live API keys and generated passwords.
mkdir -p /opt/gates_ai_lld/rag_ingestion
cat > /opt/gates_ai_lld/rag_ingestion/.env <<EOF
OPENAI_API_KEY=${openai_api_key}
LLAMA_CLOUD_API_KEY=${llama_cloud_api_key}
LANGFUSE_PUBLIC_KEY=${langfuse_public_key}
LANGFUSE_SECRET_KEY=${langfuse_secret_key}
MINIO_ROOT_USER=${minio_root_user}
MINIO_ROOT_PASSWORD=${minio_root_password}
MINIO_BUCKET=gates-rag-ingestion
AIRFLOW_POSTGRES_PASSWORD=${airflow_postgres_password}
AIRFLOW_API_USERNAME=${airflow_api_username}
AIRFLOW_API_PASSWORD=${airflow_api_password}
AIRFLOW_FERNET_KEY=${airflow_fernet_key}
AIRFLOW_WEBSERVER_SECRET_KEY=${airflow_webserver_secret_key}
RAG_WEBHOOK_SHARED_SECRET=${rag_webhook_shared_secret}
GATES_ENV=production
EOF
chmod 600 /opt/gates_ai_lld/rag_ingestion/.env
chown root:root /opt/gates_ai_lld/rag_ingestion/.env

# Best-effort -- if the compose file/image isn't ready at boot, re-run this same command by hand.
cd /opt/gates_ai_lld
docker compose -f rag_ingestion/docker-compose.yml up -d || \
  echo "WARNING: docker compose up failed -- see /var/log/user-data.log and re-run manually."

echo "=== rag_ingestion user-data: finished $(date -u) ==="
