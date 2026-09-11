#!/bin/bash
# Runs once, on first boot, as root (EC2 user-data). Logs go to
# /var/log/cloud-init-output.log -- check there first if the app never
# comes up.
set -euo pipefail

apt-get update -y
apt-get install -y ca-certificates curl gnupg git

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

git clone ${repo_url} /opt/contact_wrangler
cd /opt/contact_wrangler

# Same shape as .env.example, just with a real generated password instead
# of the local-dev placeholder -- docker-compose.yml reads these exact
# names.
cat > .env <<ENVEOF
POSTGRES_USER=contact_wrangler
POSTGRES_PASSWORD=${postgres_password}
POSTGRES_DB=contact_wrangler
DATABASE_URL=postgresql+psycopg://contact_wrangler:${postgres_password}@postgres:5432/contact_wrangler
ENVEOF
chmod 600 .env

# Same command as the local Docker workflow (README's Setup section) --
# migrations run automatically via entrypoint.sh before uvicorn starts.
docker compose up --build -d

echo "contact-wrangler user_data finished" > /var/log/contact-wrangler-ready
