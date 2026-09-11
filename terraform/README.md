# Terraform — AWS EC2 deployment

Provisions a single EC2 instance that clones this repo, builds the Docker
image, and runs the same `docker compose up --build` the local Setup
instructions describe — proving the Dockerized app works on real hosting,
not just on a laptop. Deliberately minimal (one instance, one security
group, the account's default VPC) rather than a production-shaped
multi-AZ/load-balanced setup: the point of Phase 8 is demonstrating real
Terraform practice, not building infrastructure this project doesn't need.

## Prerequisites

1. **An AWS account** with billing enabled. Historically, new accounts
   got 12 months of free-tier EC2 hours that `t3.micro` (the default
   here) fits inside, but AWS's free-tier terms have changed before and
   may not be identical by the time you sign up — check the Free Tier
   page in your own account rather than assuming this is free. Either
   way, `t3.micro` on-demand pricing is small (roughly $0.01/hour) if it
   turns out not to be free, and `terraform destroy` (below) stops the
   meter entirely.
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

## Security notes worth actually reading

- **The app has no authentication on any endpoint** (out of scope for
  this MVP entirely) — anyone who finds `app_url` can read *and write*
  data through it, not just view it. Port 8001 is public by default
  because a viewable demo is the point of deploying this at all, but
  don't leave one running unattended for long. Set
  `-var="restrict_app_to_ssh_cidr=true"` to lock the app port down to
  your own IP too (same restriction as SSH), e.g. while you're just
  confirming the deployment works before deciding whether to show it to
  anyone else.
- **The generated Postgres password is recoverable two ways**, not just
  via the (already-gitignored) local state file: it's also embedded in
  the instance's EC2 user-data, retrievable by anyone with
  `ec2:DescribeInstanceAttribute` on your AWS account (`aws ec2
  describe-instance-attribute --attribute userData ...`, or via the
  console). Irrelevant if you're the only one with access to your own
  AWS account, but worth knowing if you ever grant anyone else even
  read-only access to it.
- **Any `apply` that changes `user_data.sh.tpl` (or `repo_url`,
  `postgres_password`'s inputs, etc.) destroys and recreates the whole
  instance**, including Postgres's data — it lives only in a
  docker-compose volume on that one instance's own root disk, nowhere
  else. Fine here (synthetic, re-seedable data), but don't assume a
  routine `apply` is always safe against a long-lived instance holding
  anything you'd actually mind losing.

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
