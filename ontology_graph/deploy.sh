#!/usr/bin/env bash
# Starts everything the LIC demo needs in one go (MinIO, Qdrant, Airflow, GraphDB, PostgreSQL, webhook, UI). Run on the EC2 box:
#   bash ontology_graph/deploy.sh [up|status|down] [--pull]
#   up      (default) build and start everything, re-run the idempotent MinIO bucket/event setup, then verify
#   status  show the state of the services this demo uses
#   down    stop only the LIC services (MinIO, Qdrant and Airflow keep running; they are shared)
#   --pull  git pull --ff-only first
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

COMPOSE=(docker compose -f rag_ingestion/docker-compose.yml -f ontology_graph/docker-compose.yml)
INFRA=(minio qdrant airflow-webserver airflow-scheduler)
LIC=(graphdb policy-postgres lic-webhook lic-ui)
ENV_FILE="rag_ingestion/.env"

ACTION="up"
PULL=0
for arg in "$@"; do
  case "$arg" in
    up|status|down) ACTION="$arg" ;;
    --pull) PULL=1 ;;
    *) echo "Unknown argument: $arg (use: up | status | down | --pull)" >&2; exit 2 ;;
  esac
done

log() { printf '\n==> %s\n' "$*"; }

# wait_for "<what>" <timeout_seconds> <command...>: retries the command every 3s until it succeeds.
wait_for() {
  local what="$1" timeout="$2"; shift 2
  local waited=0
  until "$@" >/dev/null 2>&1; do
    if [ "$waited" -ge "$timeout" ]; then
      echo "    TIMED OUT waiting for: $what" >&2
      return 1
    fi
    sleep 3; waited=$((waited + 3))
  done
  echo "    ready: $what"
}

container_of() { "${COMPOSE[@]}" ps -a -q "$1" | head -n1; }
is_healthy() { [ "$(docker inspect -f '{{.State.Health.Status}}' "$(container_of "$1")" 2>/dev/null)" = "healthy" ]; }
has_exited() { [ "$(docker inspect -f '{{.State.Status}}' "$(container_of "$1")" 2>/dev/null)" = "exited" ]; }
exit_code_is_zero() { [ "$(docker inspect -f '{{.State.ExitCode}}' "$(container_of "$1")" 2>/dev/null)" = "0" ]; }
dag_loaded() {
  local listing
  listing="$("${COMPOSE[@]}" exec -T airflow-scheduler airflow dags list 2>/dev/null)" || return 1
  grep -q "lic_policy_ingestion" <<<"$listing"
}

show_status() {
  "${COMPOSE[@]}" ps -a "${INFRA[@]}" "${LIC[@]}" lic-minio-init
}

show_urls() {
  cat <<'EOF'

Where to look
  Policy Data Query Agent   http://<ec2-host>:8503
  Airflow UI                http://<ec2-host>:8080
  MinIO console             http://<ec2-host>:9001   (upload PDFs to the "licdocuments" bucket)
  GraphDB Workbench         http://localhost:7200    (ssh -L 7200:localhost:7200 ubuntu@<ec2-host>)
EOF
}

case "$ACTION" in
  status)
    show_status
    show_urls
    exit 0
    ;;
  down)
    log "Stopping LIC services (shared MinIO / Qdrant / Airflow stay up)"
    "${COMPOSE[@]}" stop "${LIC[@]}"
    exit 0
    ;;
esac

if [ "$PULL" -eq 1 ]; then
  log "Pulling latest code"
  git pull --ff-only
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE. It holds the keys and passwords the stack needs." >&2
  exit 1
fi
if ! grep -Eq '^LIC_POSTGRES_PASSWORD=.+' "$ENV_FILE"; then
  echo "LIC_POSTGRES_PASSWORD is not set in $ENV_FILE. Add a line like LIC_POSTGRES_PASSWORD=<choose one> and re-run." >&2
  exit 1
fi

log "Building and starting shared infra, Airflow and LIC services"
"${COMPOSE[@]}" up -d --build "${INFRA[@]}" "${LIC[@]}"

log "Waiting for the webhook to be healthy"
wait_for "lic-webhook healthy" 90 is_healthy lic-webhook

log "Running the MinIO bucket/event setup (idempotent)"
"${COMPOSE[@]}" up -d --force-recreate --no-deps lic-minio-init
wait_for "lic-minio-init finished" 120 has_exited lic-minio-init
if exit_code_is_zero lic-minio-init; then
  echo "    MinIO setup OK"
else
  echo "    MinIO setup FAILED; see: ${COMPOSE[*]} logs lic-minio-init" >&2
  exit 1
fi

log "Waiting for Airflow to load the lic_policy_ingestion DAG"
wait_for "lic_policy_ingestion DAG registered" 120 dag_loaded || echo "    DAG not visible yet; check: ${COMPOSE[*]} exec airflow-scheduler airflow dags list"

log "Status"
show_status
show_urls
