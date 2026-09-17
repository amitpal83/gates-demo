# Instance role, deliberately minimal: the only permission granted is AWS's
# managed SSM Core policy, which gives Session Manager shell access (no SSH
# keys, no security-group CIDR whitelisting needed for operational access).
# No S3, no other AWS API permissions -- MinIO is self-hosted on the box and
# the app talks to it directly, so the instance never needs to call AWS APIs
# to do its job. No wildcard IAM permissions anywhere in this stack.

data "aws_iam_policy_document" "ec2_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "rag_ingestion_ec2" {
  name               = "rag-ingestion-ec2-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_trust.json
}

resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.rag_ingestion_ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "rag_ingestion" {
  name = "rag-ingestion-ec2-profile"
  role = aws_iam_role.rag_ingestion_ec2.name
}
