#!/usr/bin/env bash
# Install or update the demo app on the Lightsail host.
#
# Installs the commit in GRC_REVISION, or, on a re-run, the SHA recorded in
# /etc/grc-assurance-revision. Refuses a branch name, including main.
# Replaces files under /opt/grc-assurance-engine that are not in that
# tarball, and keeps .venv and instance/. Does not delete
# /var/lib/grc-assurance or its SQLite file. Creates the local account
# grc-assurance when it is missing and runs the service as that account.
# Does not replace an existing Nginx site file.
#
# Run as root. The functions above main can be sourced by tests.
set -Eeuo pipefail

PIN_FILE=/etc/grc-assurance-revision
APP_DIR=/opt/grc-assurance-engine
DATA_DIR=/var/lib/grc-assurance
SERVICE_USER=grc-assurance

resolve_revision() {
  local pin_file=${1:-}
  local revision=${GRC_REVISION:-}
  if [[ -z "$revision" && -n "$pin_file" && -f "$pin_file" ]]; then
    revision=$(tr -d '[:space:]' < "$pin_file")
  fi
  if [[ ! "$revision" =~ ^[0-9a-fA-F]{40}$ ]]; then
    echo "GRC_REVISION must be a full 40-character commit SHA. This script does not install a branch name." >&2
    return 1
  fi
  printf '%s\n' "${revision,,}"
}

replace_app_tree() {
  local app=$1
  local tarball=$2
  local resolved tmp_root
  if [[ ! -d "$app" ]]; then
    echo "App directory does not exist." >&2
    return 1
  fi
  if [[ ! -f "$tarball" ]]; then
    echo "Release tarball does not exist." >&2
    return 1
  fi
  resolved=$(readlink -f -- "$app")
  tmp_root=${TMPDIR:-/tmp}
  tmp_root=${tmp_root%/}
  if [[ "$(basename -- "$resolved")" != "grc-assurance-engine" ]]; then
    echo "Refusing to replace an app directory whose name is not grc-assurance-engine." >&2
    return 1
  fi
  case "$resolved" in
    /opt/grc-assurance-engine) ;;
    "$tmp_root"/*|/var/tmp/*) ;;
    *)
      echo "Refusing to replace an app directory outside /opt/grc-assurance-engine or the temp directory." >&2
      return 1
      ;;
  esac
  _replace_app_tree_apply "$resolved" "$tarball"
}

_replace_app_tree_apply() {
  (
    set -Eeuo pipefail
    app=$1
    tarball=$2
    staging=$(mktemp -d)
    keep=$(mktemp -d)
    cleanup() {
      if [[ -d "$keep/.venv" ]]; then
        rm -rf -- "$app/.venv"
        mv -- "$keep/.venv" "$app/.venv"
      fi
      if [[ -d "$keep/instance" ]]; then
        rm -rf -- "$app/instance"
        mv -- "$keep/instance" "$app/instance"
      fi
      rm -rf -- "$staging" "$keep"
    }
    trap cleanup EXIT
    tar -xzf "$tarball" --strip-components=1 -C "$staging" --no-same-owner
    if [[ ! -f "$staging/requirements.txt" ]]; then
      echo "Tarball has no requirements.txt; refusing to replace the app tree." >&2
      exit 1
    fi
    if [[ -d "$app/.venv" ]]; then
      mv -- "$app/.venv" "$keep/.venv"
    fi
    if [[ -d "$app/instance" ]]; then
      mv -- "$app/instance" "$keep/instance"
    fi
    find "$app" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
    cp -a "$staging"/. "$app"/
  )
}

ensure_service_user() {
  if id "$SERVICE_USER" >/dev/null 2>&1; then
    return 0
  fi
  useradd \
    --system \
    --user-group \
    --home-dir /nonexistent \
    --no-create-home \
    --shell /usr/sbin/nologin \
    "$SERVICE_USER"
}

main() {
  local revision tarball
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "Run this bootstrap as root." >&2
    exit 1
  fi
  if ! revision=$(resolve_revision "$PIN_FILE"); then
    exit 1
  fi
  exec >> /var/log/grc-assurance-bootstrap.log 2>&1
  echo "bootstrap start $(date -u +%Y-%m-%dT%H:%M:%SZ) revision=${revision}"
  export DEBIAN_FRONTEND=noninteractive
  umask 022

  apt-get update
  apt-get install -y ca-certificates curl nginx python3-venv python3-pip
  ensure_service_user

  tarball=$(mktemp)
  trap 'rm -f -- "$tarball"' EXIT
  curl -fsSL "https://github.com/doneal78/grc-assurance-engine/archive/${revision}.tar.gz" -o "$tarball"
  install -d -o root -g root -m 0755 "$APP_DIR"
  replace_app_tree "$APP_DIR" "$tarball"
  rm -f -- "$tarball"
  python3 -m venv "$APP_DIR/.venv"
  "$APP_DIR/.venv/bin/pip" install --upgrade pip
  "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"
  chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"
  install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$DATA_DIR"
  chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR"
  install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$APP_DIR/instance"

  if [[ ! -e /etc/grc-assurance-engine.env ]]; then
    install -o root -g root -m 0600 /dev/null /etc/grc-assurance-engine.env
  fi
  printf '%s\n' "$revision" > "$PIN_FILE"
  chown root:root "$PIN_FILE"
  chmod 644 "$PIN_FILE"

  cat > /etc/systemd/system/grc-assurance-engine.service <<UNIT
[Unit]
Description=GRC Assurance Engine demo web application
After=network-online.target
Wants=network-online.target

[Service]
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${APP_DIR}
Environment=REQUIRE_AUTH=false
Environment=DATABASE_PATH=${DATA_DIR}/grc_assurance.sqlite3
EnvironmentFile=/etc/grc-assurance-engine.env
ExecStart=${APP_DIR}/.venv/bin/gunicorn --workers 2 --bind 127.0.0.1:8000 --access-logfile - run:app
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT

  # Write the closed setup placeholder only on first install. On a re-run,
  # keep whatever site config is already live so the demo is not taken offline.
  # This script does not publish infra/nginx-site.conf.
  local site=/etc/nginx/sites-available/grc-assurance-engine
  if [[ ! -e "$site" ]]; then
    cat > "$site" <<'NGINX'
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
  ln -sfn "$site" /etc/nginx/sites-enabled/grc-assurance-engine
  nginx -t
  systemctl enable nginx
  systemctl reload-or-restart nginx
  systemctl daemon-reload
  systemctl enable grc-assurance-engine
  systemctl restart grc-assurance-engine
  touch "$DATA_DIR/bootstrap-complete"
  echo "bootstrap finished ${revision}"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
