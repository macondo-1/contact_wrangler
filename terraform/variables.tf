variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "us-east-1"
}

variable "instance_type" {
  description = <<-EOT
    EC2 instance type. t3.micro has historically been AWS's free-tier
    default (check your own account's Free Tier page -- terms have
    changed before) and enough to prove the app runs, but is tight on RAM
    (1GB) once Postgres, the app container, and the seed script's ~500k
    rows are all in play at once -- bump to t3.small if seeding struggles
    or the app OOMs under any real load.
  EOT
  type        = string
  default     = "t3.micro"
}

variable "allowed_ssh_cidr" {
  description = <<-EOT
    CIDR allowed to SSH in on port 22, e.g. "1.2.3.4/32" (your own
    current IP). Required, no default -- never leave this as 0.0.0.0/0
    (open to the entire internet); find your IP with `curl ifconfig.me`
    and pass it as -var (or in a .tfvars file, which is gitignored).
  EOT
  type        = string

  validation {
    condition     = var.allowed_ssh_cidr != "0.0.0.0/0"
    error_message = "allowed_ssh_cidr must not be 0.0.0.0/0 -- that opens SSH to the entire internet. Use your own IP (curl ifconfig.me) with a /32 suffix."
  }
}

variable "restrict_app_to_ssh_cidr" {
  description = <<-EOT
    If true, port 8001 (the app itself) is restricted to allowed_ssh_cidr
    instead of the whole internet -- use this while you're just confirming
    the deployment works for yourself. The default (false) leaves it public,
    since a demoable, recruiter-viewable instance is the actual point of
    deploying this at all -- but the app has NO authentication on any
    endpoint (this MVP's scope never included it), so a fully public
    instance is writable by anyone who finds it, not just viewable. Don't
    leave one running unattended for long either way.
  EOT
  type        = bool
  default     = false
}

variable "key_name" {
  description = <<-EOT
    Name of an existing EC2 key pair for SSH access. Terraform doesn't
    create or manage the private key for you -- create one first via the
    AWS console (EC2 -> Key Pairs -> Create key pair) or
    `aws ec2 create-key-pair --key-name <name> --query 'KeyMaterial' --output text > <name>.pem`,
    then pass its name here.
  EOT
  type        = string
}

variable "repo_url" {
  description = "Git URL the instance clones on boot to get the app's code"
  type        = string
  default     = "https://github.com/macondo-1/contact_wrangler.git"
}
