output "public_ip" {
  description = "Public IP of the instance"
  value       = aws_instance.app.public_ip
}

output "app_url" {
  description = "Where the app should be reachable once user_data finishes (takes a minute or two after apply -- Docker install + image build + migrations all run on first boot)"
  value       = "http://${aws_instance.app.public_ip}:8001"
}

output "ssh_command" {
  description = "SSH in to check on the instance (e.g. `cloud-init status --wait` to confirm user_data finished, or `docker compose logs` in /opt/contact_wrangler)"
  value       = "ssh -i <path-to-your-private-key> ubuntu@${aws_instance.app.public_ip}"
}

# Note on state and secrets: terraform.tfstate holds the generated
# Postgres password in plaintext (Terraform state always contains
# resource attribute values, including this one) -- it's already
# gitignored below the repo root, but treat the whole terraform/
# directory's state files as sensitive, not just "not committed".
