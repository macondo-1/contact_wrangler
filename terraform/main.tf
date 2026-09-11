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
    # Public by default -- that's the point of deploying this at all,
    # rather than only ever running it locally. Set
    # restrict_app_to_ssh_cidr = true to lock it down to your own IP
    # instead, e.g. while you're just confirming it works before deciding
    # whether to leave it visible to anyone else.
    cidr_blocks = var.restrict_app_to_ssh_cidr ? [var.allowed_ssh_cidr] : ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "app" {
  ami           = data.aws_ami.ubuntu.id
  instance_type = var.instance_type
  key_name      = var.key_name
  # data.aws_subnets.default.ids is not guaranteed to come back in a
  # stable order across separate calls -- sort() first so the same
  # subnet gets picked every time, rather than risking a spurious forced
  # replacement (subnet_id can't be changed in place) if AWS ever returns
  # the list in a different order on some later plan/apply.
  subnet_id              = sort(data.aws_subnets.default.ids)[0]
  vpc_security_group_ids = [aws_security_group.app.id]

  # The AMI's default root volume is ~8GiB -- genuinely tight once Docker
  # image layers/build cache and a fully-seeded Postgres database
  # (~500k rows once scripts/seed.py has run) are both on it.
  root_block_device {
    volume_size = 20
    volume_type = "gp3"
  }

  user_data = templatefile("${path.module}/user_data.sh.tpl", {
    postgres_password = random_password.postgres.result
    repo_url          = var.repo_url
  })
  # Forces destroy-and-recreate on any user_data change (e.g. editing
  # user_data.sh.tpl, or bumping repo_url) -- user_data only ever runs at
  # first boot, so there's no other way to apply a changed script to an
  # existing instance. Be aware this means Postgres's data (which lives
  # only in a docker-compose named volume on THIS instance's own root
  # volume, nowhere else) is destroyed along with it -- there's no
  # separate persistent data store to preserve across a replacement.
  # Fine for this project (synthetic, re-seedable data), but worth
  # knowing before assuming any `apply` is safe to run against a
  # long-lived instance.
  user_data_replace_on_change = true

  tags = {
    Name = "contact-wrangler-demo"
  }
}
