#!/usr/bin/env bash
set -Eeuo pipefail
exec >> /var/log/grc-assurance-bootstrap.log 2>&1
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y ca-certificates curl nginx python3-venv python3-pip

install -d -o ubuntu -g ubuntu /opt/grc-assurance-engine
curl -fsSL https://api.github.com/repos/doneal78/grc-assurance-engine/tarball/main -o /tmp/grc-assurance-engine.tar.gz
tar -xzf /tmp/grc-assurance-engine.tar.gz --strip-components=1 -C /opt/grc-assurance-engine
python3 -m venv /opt/grc-assurance-engine/.venv
/opt/grc-assurance-engine/.venv/bin/pip install --upgrade pip
/opt/grc-assurance-engine/.venv/bin/pip install -r /opt/grc-assurance-engine/requirements.txt

install -d -o ubuntu -g ubuntu -m 0750 /var/lib/grc-assurance
if [[ ! -e /etc/grc-assurance-engine.env ]]; then
    install -o root -g root -m 0600 /dev/null /etc/grc-assurance-engine.env
fi

cat > /etc/systemd/system/grc-assurance-engine.service <<'UNIT'
[Unit]
Description=GRC Assurance Engine demo web application
After=network-online.target
Wants=network-online.target

[Service]
User=ubuntu
Group=ubuntu
WorkingDirectory=/opt/grc-assurance-engine
Environment=REQUIRE_AUTH=false
Environment=DATABASE_PATH=/var/lib/grc-assurance/grc_assurance.sqlite3
EnvironmentFile=/etc/grc-assurance-engine.env
ExecStart=/opt/grc-assurance-engine/.venv/bin/gunicorn --workers 2 --bind 127.0.0.1:8000 --access-logfile - run:app
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT

# Write the closed setup placeholder only on first install. On a re-run,
# keep whatever site config is already live so the demo is not taken offline.
SITE=/etc/nginx/sites-available/grc-assurance-engine
if [[ ! -e "$SITE" ]]; then
    cat > "$SITE" <<'NGINX'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name grc-assurance.davidoneal.dev;
    location / {
        add_header Retry-After 60 always;
        return 503 "Demo setup in progress. Please try again shortly.\n";
    }
}
NGINX
fi
rm -f /etc/nginx/sites-enabled/default
ln -sfn "$SITE" /etc/nginx/sites-enabled/grc-assurance-engine
nginx -t
systemctl enable nginx
systemctl reload-or-restart nginx
systemctl daemon-reload
systemctl enable grc-assurance-engine
# On first boot the demo credentials are not set yet, so the app is expected
# to refuse to start (fail closed) while Nginx serves the placeholder.
systemctl restart grc-assurance-engine || true
touch /var/lib/grc-assurance/bootstrap-complete
