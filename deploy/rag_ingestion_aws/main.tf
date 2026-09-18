# Uses the account's default VPC -- a single-box stack doesn't need a custom one.
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

  # Public on purpose so PDFs can be uploaded from anywhere -- keep minio_root_password strong.
  ingress {
    description = "MinIO API (deliberately public)"
    from_port   = 9000
    to_port     = 9000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "MinIO console (deliberately public)"
    from_port   = 9001
    to_port     = 9001
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # No rule for Qdrant/rag-webhook -- both are internal-only on the compose network.

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
