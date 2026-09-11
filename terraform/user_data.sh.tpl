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

# Idempotent: user-data has no built-in retry, so if anything below this
# point failed on a prior boot attempt (a transient apt/network hiccup),
# a plain `git clone` into an already-existing directory would itself
# fail and abort the whole script again -- wipe any partial attempt first.
rm -rf /opt/contact_wrangler
git clone ${repo_url} /opt/contact_wrangler
cd /opt/contact_wrangler

# Same shape as .env.example, just with a real generated password instead
# of the local-dev placeholder -- docker-compose.yml reads these exact
# names. Delimiter is quoted ('ENVEOF', not ENVEOF) so the heredoc body
# is written out completely literally -- with an unquoted delimiter, bash
# would additionally run its own parameter/command substitution over
# this text, which would silently mangle the password if it ever
# contained a "$" or backtick.
cat > .env <<'ENVEOF'
POSTGRES_USER=contact_wrangler
POSTGRES_PASSWORD=${postgres_password}
POSTGRES_DB=contact_wrangler
DATABASE_URL=postgresql+psycopg://contact_wrangler:${postgres_password}@postgres:5432/contact_wrangler
ENVEOF
chmod 600 .env

# Same command as the local Docker workflow (README's Setup section) --
# migrations run automatically via entrypoint.sh before uvicorn starts.
docker compose up --build -d

# `docker compose up -d` returning only confirms the containers started,
# not that they stayed up -- poll the real health endpoint before
# declaring success, so a crash/OOM shortly after start (a real risk on
# a memory-tight t3.micro) is reported as a genuine failure instead of a
# false "ready" marker that `cloud-init status --wait` would otherwise
# report as a clean success.
ready=false
for _ in $(seq 1 30); do
  if curl -sf http://localhost:8001/health > /dev/null; then
    ready=true
    break
  fi
  sleep 2
done

if [ "$ready" = true ]; then
  echo "contact-wrangler user_data finished" > /var/log/contact-wrangler-ready
else
  echo "contact-wrangler app never became healthy -- dumping compose logs:" >&2
  docker compose logs >&2
  exit 1
fi
