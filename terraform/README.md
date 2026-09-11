# Terraform — AWS EC2 deployment

Provisions a single EC2 instance that clones this repo, builds the Docker
image, and runs the same `docker compose up --build` the local Setup
instructions describe — proving the Dockerized app works on real hosting,
not just on a laptop. Deliberately minimal (one instance, one security
group, the account's default VPC) rather than a production-shaped
multi-AZ/load-balanced setup: the point of Phase 8 is demonstrating real
Terraform practice, not building infrastructure this project doesn't need.

## Prerequisites

1. **An AWS account** with billing enabled (a new account gets 12 months
   of free-tier EC2 hours, which `t3.micro` — the default here — fits
   inside).
2. **An IAM user or role with EC2/VPC permissions**, and its credentials
   configured locally so the AWS provider can find them —
   `aws configure` (access key + secret + default region), or an
   `AWS_PROFILE` env var pointing at one already configured. Never commit
   credentials to this repo; `aws configure` stores them outside it
   (`~/.aws/credentials`).
3. **An EC2 key pair**, for SSH access to the instance. Create one via the
   AWS console (EC2 → Key Pairs → Create key pair, download the `.pem`)
   or:
   ```bash
   aws ec2 create-key-pair --key-name contact-wrangler --query 'KeyMaterial' --output text > contact-wrangler.pem
   chmod 400 contact-wrangler.pem
   ```
4. **Your current public IP**, to restrict SSH access to just you:
   ```bash
   curl ifconfig.me
   ```

## Usage

```bash
cd terraform
terraform init
terraform plan \
  -var="allowed_ssh_cidr=<your-ip>/32" \
  -var="key_name=<your-key-pair-name>"
terraform apply \
  -var="allowed_ssh_cidr=<your-ip>/32" \
  -var="key_name=<your-key-pair-name>"
```

(Or put those in a `terraform.tfvars` file — already gitignored — so you
don't have to repeat `-var` flags on every command.)

`terraform apply` prints `app_url` when it finishes provisioning the
instance itself, but the app isn't reachable *immediately* — `user_data`
still has to install Docker, clone the repo, and build the image on first
boot, which realistically takes a couple of minutes. Check progress via:

```bash
ssh -i <your-key>.pem ubuntu@<public_ip>
cloud-init status --wait   # blocks until user_data finishes
cd /opt/contact_wrangler && docker compose logs -f
```

Once it's up, `<app_url>` behaves exactly like the local stack — seed it
the same way, over SSH:

```bash
cd /opt/contact_wrangler
docker compose exec app uv run python scripts/seed.py
```

## Tearing it down

This instance costs money for every hour it runs past the free tier (and
even inside the free tier, forgetting about it is how people end up
surprised by a bill later). When you're done demonstrating it works:

```bash
terraform destroy \
  -var="allowed_ssh_cidr=<your-ip>/32" \
  -var="key_name=<your-key-pair-name>"
```

## What's deliberately not here

- **No remote state backend** (S3 + DynamoDB lock table) — this is a
  single-maintainer deployment, not a team-shared one, so the setup cost
  of bootstrapping a remote backend isn't worth it here. State stays
  local (`terraform.tfstate`, gitignored — it holds the generated
  Postgres password in plaintext, since Terraform state always contains
  full resource attribute values).
- **No custom VPC** — reuses the account's default VPC/subnet, which
  every account already has in every region.
- **No HTTPS/TLS** — the app is served plain HTTP on port 8001, matching
  local Docker exactly. Not fixed here, since fronting it with a real
  domain + cert (e.g. via a load balancer or Caddy/nginx sidecar) is a
  separate concern from proving Terraform can provision the instance.
