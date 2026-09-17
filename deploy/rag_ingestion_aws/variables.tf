variable "aws_region" {
  description = "AWS region to provision the RAG ingestion stack in."
  type        = string
  default     = "us-east-1"
}

variable "instance_type" {
  description = <<-EOT
    EC2 instance type for the single box running the whole rag_ingestion
    docker-compose stack. Defaults to t3.xlarge (4 vCPU / 16 GB RAM):
    Airflow alone runs a webserver + scheduler + its own dedicated Postgres,
    Qdrant keeps its HNSW index resident in memory, MinIO and the rag-webhook
    service add more on top, and the Streamlit UI stacks on the same box --
    that combination wants real headroom, not a burstable micro/small
    instance. t3.large (2 vCPU / 8 GB RAM) is a cheaper fallback if this is
    only for light, occasional use, but expect Airflow + Qdrant to compete
    for memory under any real ingestion load at that size.
  EOT
  type        = string
  default     = "t3.xlarge"
}

variable "root_volume_size_gb" {
  description = "Size (GB) of the root EBS volume (OS, Docker images, container layers)."
  type        = number
  default     = 30
}

variable "data_volume_size_gb" {
  description = "Size (GB) of the separate data EBS volume mounted at /data (MinIO objects, Qdrant vectors, Airflow/Postgres data)."
  type        = number
  default     = 100
}

variable "key_pair_name" {
  description = "Name of an EXISTING EC2 key pair to attach to the instance. Terraform does not create or manage key material -- create the key pair yourself (or reuse one) and pass its name here."
  type        = string
}

variable "ssh_allowed_cidr" {
  description = "CIDR blocks allowed to reach port 22 (SSH). Keep this as narrow as possible (e.g. your own IP as a /32)."
  type        = list(string)
}

variable "ui_allowed_cidr" {
  description = "CIDR blocks allowed to reach the Streamlit UI (8501) and the Airflow webserver (8080). Keep this as narrow as practical."
  type        = list(string)
}

variable "repo_url" {
  description = "Git URL this instance clones at boot to get the rag_ingestion/ docker-compose stack. Defaults to this project's own origin remote; override if you're deploying from a fork."
  type        = string
  default     = "https://github.com/amitpal83/gates-demo.git"
}

variable "repo_ref" {
  description = "Git branch/tag/ref to check out on the instance."
  type        = string
  default     = "main"
}

variable "openai_api_key" {
  description = "OpenAI API key used by the rag_ingestion pipeline (embeddings, LLM calls)."
  type        = string
  sensitive   = true
}

variable "llama_cloud_api_key" {
  description = "LlamaCloud API key for LlamaParse (PDF parsing). Get one at https://cloud.llamaindex.ai."
  type        = string
  sensitive   = true
}

variable "langfuse_public_key" {
  description = "Optional Langfuse public key for tracing. Leave blank to skip Langfuse."
  type        = string
  sensitive   = true
  default     = ""
}

variable "langfuse_secret_key" {
  description = "Optional Langfuse secret key for tracing. Leave blank to skip Langfuse."
  type        = string
  sensitive   = true
  default     = ""
}

variable "minio_root_user" {
  description = "MinIO root (admin) username."
  type        = string
  sensitive   = true
  default     = "minioadmin"
}

variable "minio_root_password" {
  description = "MinIO root (admin) password. MinIO's API (9000) and console (9001) are deliberately exposed to the internet (see README/main.tf), so this MUST be a strong, randomly generated value -- e.g. `openssl rand -hex 24`."
  type        = string
  sensitive   = true
}

variable "airflow_postgres_password" {
  description = "Password for Airflow's dedicated Postgres instance. Generate with `openssl rand -hex 24`."
  type        = string
  sensitive   = true
}

variable "airflow_api_username" {
  description = "Airflow webserver admin username."
  type        = string
  sensitive   = true
  default     = "admin"
}

variable "airflow_api_password" {
  description = "Airflow webserver admin password. Generate with `openssl rand -hex 24`."
  type        = string
  sensitive   = true
}

variable "airflow_fernet_key" {
  description = "Airflow Fernet key used to encrypt connection/variable secrets at rest. Must be a real Fernet key, NOT an arbitrary random hex string -- generate with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
  type        = string
  sensitive   = true
}

variable "airflow_webserver_secret_key" {
  description = "Airflow webserver Flask secret key (session signing). Generate with `openssl rand -hex 24`."
  type        = string
  sensitive   = true
}

variable "rag_webhook_shared_secret" {
  description = "Shared secret used to authenticate MinIO's webhook notification calls into the internal rag-webhook service. Generate with `openssl rand -hex 24`."
  type        = string
  sensitive   = true
}
