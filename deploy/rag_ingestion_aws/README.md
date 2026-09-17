# RAG Ingestion AWS deployment (Terraform)

This provisions a single EC2 instance to run the `rag_ingestion/`
docker-compose stack (MinIO, Qdrant, Airflow + its own Postgres, a
one-shot `rag-webhook` service, and the Streamlit ingestion UI) --
security group, IAM instance role, an attached data EBS volume, an
Elastic IP, and a `cloud-init` script that installs Docker, clones this
repo, writes the stack's `.env`, and brings the compose stack up.

This is **fully additive**: it does not touch `litellm/`'s own manual EC2
setup (see `litellm/README.md`), and it does not touch `agents/`,
`streamlit_app.py`, the root `requirements.txt`, or `gates_ai_common/`.
The only thing it depends on from elsewhere in the repo is
`rag_ingestion/docker-compose.yml`, which another workstream owns --
Terraform here does not build or define that stack, only deploys it.

## Prerequisites

- AWS credentials configured locally (`aws configure`, or environment
  variables) with permission to create EC2 instances, security groups,
  EBS volumes, Elastic IPs, and IAM roles/instance profiles.
- Terraform >= 1.7.
- An existing EC2 key pair in the target region (create one in the EC2
  console or via `aws ec2 create-key-pair` if you don't have one).
- Your own IP (or whatever CIDR you want to allow) for `ssh_allowed_cidr`
  and `ui_allowed_cidr`.
- In hand: an `OPENAI_API_KEY`, a LlamaParse API key from
  [cloud.llamaindex.ai](https://cloud.llamaindex.ai) (`llama_cloud_api_key`),
  and optionally Langfuse keys.

## Setup

    cd deploy/rag_ingestion_aws
    cp terraform.tfvars.example terraform.tfvars

Edit `terraform.tfvars`: fill in `key_pair_name`, `ssh_allowed_cidr`,
`ui_allowed_cidr`, and the external API keys, then generate the secrets
this stack owns:

    openssl rand -hex 24   # minio_root_password
    openssl rand -hex 24   # airflow_postgres_password
    openssl rand -hex 24   # airflow_api_password
    openssl rand -hex 24   # airflow_webserver_secret_key
    openssl rand -hex 24   # rag_webhook_shared_secret

    # Airflow needs a REAL Fernet key, not an arbitrary hex string:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # -> airflow_fernet_key

Then:

    terraform init
    terraform plan
    terraform apply

## After apply

    terraform output

Gives you the public IP, an SSH command, and the Streamlit/Airflow/MinIO
console URLs. SSH in and confirm the compose stack came up:

    ssh -i <path-to-your-key.pem> ubuntu@<instance_public_ip>
    cd /opt/gates_ai_lld
    docker compose -f rag_ingestion/docker-compose.yml ps

The `user_data.sh.tpl` cloud-init script attempts `docker compose ... up
-d` automatically on first boot, but this is light automation, not a
guaranteed zero-touch deploy -- if `rag_ingestion/docker-compose.yml` (or
an image it needs to build) wasn't ready in this repo at boot time, that
step fails harmlessly and you just re-run the same command by hand over
SSH. Check `/var/log/user-data.log` on the box if anything looks off.

Once it's up, from your own browser:

- Streamlit: `http://<instance_public_ip>:8501`
- Airflow: `http://<instance_public_ip>:8080`
- MinIO console: `http://<instance_public_ip>:9001`

(Qdrant and the internal `rag-webhook` service are not reachable from
outside the box by design -- see the security group notes below.)

## MinIO is exposed to the internet by design

The security group opens MinIO's API (9000) and console (9001) to
`0.0.0.0/0` -- **on purpose**, per an explicit request so PDFs can be
uploaded directly to MinIO's browser console or API from anywhere,
without an SSH tunnel or VPN. This mirrors this repo's existing
`litellm/docker-compose.yml`, which exposes its proxy port publicly for
the same reason: convenience for a POC/exploration deployment, not a
hardened production posture.

This is **not hardened**. There is no IP allowlisting, no TLS, and MinIO
sits behind nothing but its own root credentials. A strong,
randomly-generated `minio_root_password` is the only thing standing
between the internet and this bucket -- treat that value as sensitive,
never reuse it elsewhere, and don't leave this instance running longer
than the exploration needs it. If you ever want this closer to
production, the two changes that matter most are: put MinIO behind
something with TLS/auth in front of it (e.g. an ALB + Cognito, or a
reverse proxy with basic auth over HTTPS), and narrow the security-group
source from `0.0.0.0/0` to specific CIDRs.

Qdrant (6333/6334) and the `rag-webhook` service intentionally have **no**
security-group rule at all -- they're reachable only on the Docker
Compose internal network (Qdrant has no external consumer; `rag-webhook`
is only ever called by MinIO's own webhook notification inside that
network), so no port needs to be, or should be, opened for them.

## Cost estimate

Rough us-east-1 on-demand pricing, `t3.xlarge` (default):

- Compute (t3.xlarge, ~730 hrs/mo): ~$121/mo
- Root EBS (30 GB gp3): ~$2.40/mo
- Data EBS (100 GB gp3): ~$8/mo
- Elastic IP (attached to a running instance, no charge while attached;
  budget ~$3.60/mo if it's ever left unattached): ~$3.60/mo
- Data transfer: a few dollars, workload-dependent

**Total: roughly $135-140/month.**

Cheaper fallback with `t3.large` (2 vCPU / 8 GB RAM, lighter use only):
roughly **$75-80/month**. To switch, change `instance_type` in
`terraform.tfvars` and run `terraform apply` again -- this replaces the
instance (a new instance ID, same attached data volume and Elastic IP),
so expect a few minutes of downtime and re-running
`docker compose ... up -d` on the new box if `user_data` doesn't manage to
finish before you SSH in.

## Update workflow

To pick up new code (either the compose file itself or the app it runs):

    ssh -i <path-to-your-key.pem> ubuntu@<instance_public_ip>
    cd /opt/gates_ai_lld
    git pull
    docker compose -f rag_ingestion/docker-compose.yml up -d --build

## Teardown

    terraform destroy

**WARNING:** this deletes the data EBS volume along with the instance --
that means all MinIO objects, Qdrant vectors, and Airflow/Postgres state
are gone, permanently, unless you snapshot first. To snapshot before
destroying:

    terraform output data_volume_id
    aws ec2 create-snapshot --volume-id <data_volume_id> --description "rag-ingestion pre-destroy snapshot"

## Future improvements (not built here, deliberately)

- **Remote state**: this uses local Terraform state only, no S3 backend,
  no DynamoDB lock table -- a deliberate choice for a small-team/POC-leaning
  setup. Add an S3 backend (+ lock table, or S3-native locking on newer
  Terraform) if more than one person starts running `terraform apply`
  against this.
- **Secrets management**: `terraform.tfvars` holds live secrets in a local,
  gitignored file. AWS Secrets Manager or SSM Parameter Store (pulled into
  `rag_ingestion/.env` by `user_data.sh.tpl` via the AWS CLI/SDK, using the
  instance role) would avoid secrets ever touching a local file or
  Terraform state at all.
- **Hardening MinIO's public exposure** -- see the callout above.
