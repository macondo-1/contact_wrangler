provider "aws" {
  region = var.aws_region
}

# Every account (including a brand-new free-tier one) already has a
# default VPC + subnets in every region -- reusing them keeps this to
# "one instance, one security group" instead of a full custom
# VPC/subnet/route-table/internet-gateway stack that would be pure
# overhead for a single-box portfolio deployment.
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
  owners      = ["099720109477"] # Canonical's official AMI owner ID

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# Generated at apply time, not hardcoded -- it only ever lands in
# Terraform state (gitignored) and the instance's own user-data /
# .env file, never in the repo. This is a demo app seeded entirely with
# synthetic data, but there's no reason to hardcode a real password
# anyway.
resource "random_password" "postgres" {
  length  = 24
  special = false # goes straight into a shell heredoc in user_data -- keep it shell-safe
}

resource "aws_security_group" "app" {
  name        = "contact-wrangler-app"
  description = "Contact Wrangler demo instance -- SSH restricted, app port public"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.allowed_ssh_cidr]
  }

  ingress {
    description = "Contact Wrangler API"
    from_port   = 8001
    to_port     = 8001
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"] # deliberately public -- this port being reachable is the point
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "app" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  key_name               = var.key_name
  subnet_id              = data.aws_subnets.default.ids[0]
  vpc_security_group_ids = [aws_security_group.app.id]

  user_data = templatefile("${path.module}/user_data.sh.tpl", {
    postgres_password = random_password.postgres.result
    repo_url          = var.repo_url
  })
  user_data_replace_on_change = true

  tags = {
    Name = "contact-wrangler-demo"
  }
}
