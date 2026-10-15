#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
DEPLOY_HOST=${DEPLOY_HOST:-ubuntu@54.37.204.161}
DEPLOY_KEY=${DEPLOY_KEY:-$HOME/.ssh/qoc_vps_ed25519}
rsync -az -e "ssh -i $DEPLOY_KEY -o BatchMode=yes" --exclude .DS_Store server.py audit.py admin.py countries.py diagnostics.py static deploy "$DEPLOY_HOST:/tmp/cruze-deploy/"
ssh -i "$DEPLOY_KEY" -o BatchMode=yes "$DEPLOY_HOST" 'bash -se' <<'REMOTE'
sudo install -d -m 755 /srv/cruze
sudo rsync -a --chown=root:root --chmod=D755,F644 /tmp/cruze-deploy/ /srv/cruze/
if [ ! -x /srv/cruze/.venv/bin/python ]; then
  sudo python3 -m venv /srv/cruze/.venv
fi
sudo /srv/cruze/.venv/bin/pip install --require-hashes -r /srv/cruze/deploy/requirements.txt
cd /srv/cruze
sudo /srv/cruze/.venv/bin/python deploy/update-country.py
sudo install -m 644 /srv/cruze/deploy/cruze.service /etc/systemd/system/cruze.service
sudo systemctl daemon-reload
sudo systemctl enable cruze
sudo systemctl restart cruze
for attempt in 1 2 3 4 5; do
  if curl --head --fail --silent http://127.0.0.1:8774/ >/dev/null; then break; fi
  sleep 1
done
curl --head --fail --silent http://127.0.0.1:8774/ >/dev/null
sudo install -d -m 755 /etc/caddy/sites
stamp=$(date +%Y%m%d-%H%M%S)
sudo cp /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.before-cruze-$stamp"
sudo install -m 644 /srv/cruze/deploy/cruze.caddy /etc/caddy/sites/cruze.caddy
if ! sudo grep -Fxq 'import /etc/caddy/sites/cruze.caddy' /etc/caddy/Caddyfile; then
  printf '\nimport /etc/caddy/sites/cruze.caddy\n' | sudo tee -a /etc/caddy/Caddyfile >/dev/null
fi
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemctl reload caddy
sudo systemctl is-active cruze caddy
REMOTE
