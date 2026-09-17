# Uses the account's default VPC/subnet rather than provisioning a custom
# VPC. This is a single-instance, no-isolation-requirement stack (one box
# running the whole rag_ingestion compose stack) -- a custom VPC would add
# complexity (subnets, route tables, NAT/IGW wiring) and cost for no benefit
# here. Revisit if this ever needs to sit behind a private network.
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }
}

resource "aws_security_group" "rag_ingestion" {
  name        = "rag-ingestion-sg"
  description = "Security group for the rag_ingestion EC2 host"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = var.ssh_allowed_cidr
  }

  ingress {
    description = "Streamlit UI"
    from_port   = 8501
    to_port     = 8501
    protocol    = "tcp"
    cidr_blocks = var.ui_allowed_cidr
  }

  ingress {
    description = "Airflow webserver"
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = var.ui_allowed_cidr
  }

  # Deliberately public per explicit request so PDFs can be uploaded
  # directly via the MinIO console/API from anywhere. This is an
  # unhardened, POC-style exposure -- same spirit as this repo's
  # litellm/docker-compose.yml exposing its proxy port publicly for
  # exploration. A strong minio_root_password is essential since this port
  # is reachable from the internet; revisit before any real production use.
  ingress {
    description = "MinIO API (deliberately public -- see comment above)"
    from_port   = 9000
    to_port     = 9000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Deliberately public per explicit request so PDFs can be uploaded
  # directly via the MinIO console/API from anywhere. This is an
  # unhardened, POC-style exposure -- same spirit as this repo's
  # litellm/docker-compose.yml exposing its proxy port publicly for
  # exploration. A strong minio_root_password is essential since this port
  # is reachable from the internet; revisit before any real production use.
  ingress {
    description = "MinIO console (deliberately public -- see comment above)"
    from_port   = 9001
    to_port     = 9001
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # No rule for Qdrant (6333/6334) and no rule for the rag-webhook service:
  # both are internal-only on the Docker Compose network. Qdrant has no
  # external consumer and rag-webhook is reached only by MinIO's own webhook
  # notification inside the compose network -- neither is ever reachable
  # from outside the box, so no security-group entry is needed or correct
  # for them. This is intentional; do not "fix" this apparent gap by adding
  # ingress rules for those ports.

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "rag-ingestion-sg"
  }
}

resource "aws_instance" "rag_ingestion" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  key_name               = var.key_pair_name
  subnet_id              = data.aws_subnets.default.ids[0]
  vpc_security_group_ids = [aws_security_group.rag_ingestion.id]
  iam_instance_profile   = aws_iam_instance_profile.rag_ingestion.name

  root_block_device {
    volume_size = var.root_volume_size_gb
    volume_type = "gp3"
  }

  user_data = templatefile("${path.module}/user_data.sh.tpl", {
    repo_url                     = var.repo_url
    repo_ref                     = var.repo_ref
    openai_api_key               = var.openai_api_key
    llama_cloud_api_key          = var.llama_cloud_api_key
    langfuse_public_key          = var.langfuse_public_key
    langfuse_secret_key          = var.langfuse_secret_key
    minio_root_user              = var.minio_root_user
    minio_root_password          = var.minio_root_password
    airflow_postgres_password    = var.airflow_postgres_password
    airflow_api_username         = var.airflow_api_username
    airflow_api_password         = var.airflow_api_password
    airflow_fernet_key           = var.airflow_fernet_key
    airflow_webserver_secret_key = var.airflow_webserver_secret_key
    rag_webhook_shared_secret    = var.rag_webhook_shared_secret
  })

  tags = {
    Name = "gates-ai-server"
  }
}

resource "aws_ebs_volume" "data" {
  availability_zone = aws_instance.rag_ingestion.availability_zone
  size              = var.data_volume_size_gb
  type              = "gp3"

  tags = {
    Name = "rag-ingestion-data"
  }
}

resource "aws_volume_attachment" "data" {
  device_name = "/dev/sdf"
  volume_id   = aws_ebs_volume.data.id
  instance_id = aws_instance.rag_ingestion.id
}

resource "aws_eip" "rag_ingestion" {
  instance = aws_instance.rag_ingestion.id
  domain   = "vpc"

  tags = {
    Name = "rag-ingestion-eip"
  }
}
