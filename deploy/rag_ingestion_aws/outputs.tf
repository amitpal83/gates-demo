output "instance_public_ip" {
  description = "Public (Elastic) IP of the rag_ingestion EC2 instance."
  value       = aws_eip.rag_ingestion.public_ip
}

output "ssh_command" {
  description = "SSH command to reach the instance (swap in the path to your key_pair_name .pem file)."
  value       = "ssh -i <path-to-${var.key_pair_name}.pem> ubuntu@${aws_eip.rag_ingestion.public_ip}"
}

output "streamlit_url" {
  description = "URL for the Streamlit UI."
  value       = "http://${aws_eip.rag_ingestion.public_ip}:8501"
}

output "airflow_url" {
  description = "URL for the Airflow webserver."
  value       = "http://${aws_eip.rag_ingestion.public_ip}:8080"
}

output "minio_console_url" {
  description = "URL for the MinIO console."
  value       = "http://${aws_eip.rag_ingestion.public_ip}:9001"
}

output "data_volume_id" {
  description = "EBS volume ID of the /data volume (MinIO/Qdrant/Airflow data) -- useful for snapshotting before `terraform destroy`."
  value       = aws_ebs_volume.data.id
}
