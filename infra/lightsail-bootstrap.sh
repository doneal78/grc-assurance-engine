#!/usr/bin/env bash
# Install or update the demo app on the Lightsail host.
#
# Installs the commit in GRC_REVISION, or, on a re-run, the SHA recorded in
# /etc/grc-assurance-revision. Refuses a branch name, including main.
# Replaces files under /opt/grc-assurance-engine that are not in that
# tarball, and keeps .venv and instance/. Does not delete
# /var/lib/grc-assurance or its SQLite file. Creates the local account
# grc-assurance when it is missing and runs the service as that account.
# The app tree and the virtualenv stay root-owned and not writable by that
# account. The account can write the data directory and instance/ only.
# That ownership is safe to repeat. Does not replace an existing Nginx site
# file.
#
# Routine updates of a host that already has the unit, the virtualenv, and
# the data directory should use infra/deploy-app-revision.sh. This bootstrap
# also apt-get installs packages, including the sqlite3 CLI used for online
# backups, creates the service account, and rewrites the systemd unit. It
# does not back up SQLite or check /health.
#
# Run as root. The functions above main can be sourced by tests.
set -Eeuo pipefail

PIN_FILE=/etc/grc-assurance-revision
APP_DIR=/opt/grc-assurance-engine
DATA_DIR=/var/lib/grc-assurance
SERVICE_USER=grc-assurance

# Print the canonical app path, or fail. Callers may use a temp directory
# whose basename is grc-assurance-engine. They may not use an arbitrary path.
assert_replaceable_app_dir() {
  local app=$1
  local resolved tmp_root
  if [[ ! -d "$app" ]]; then
    echo "App directory does not exist." >&2
    return 1
  fi
  resolved=$(readlink -f -- "$app")
  tmp_root=${TMPDIR:-/tmp}
  tmp_root=${tmp_root%/}
  if [[ "$(basename -- "$resolved")" != "grc-assurance-engine" ]]; then
    echo "Refusing an app directory whose name is not grc-assurance-engine." >&2
    return 1
  fi
  case "$resolved" in
    /opt/grc-assurance-engine) ;;
    "$tmp_root"/*|/var/tmp/*) ;;
    *)
      echo "Refusing an app directory outside /opt/grc-assurance-engine or the temp directory." >&2
      return 1
      ;;
  esac
  printf '%s\n' "$resolved"
}

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
  local resolved
  if [[ ! -f "$tarball" ]]; then
    echo "Release tarball does not exist." >&2
    return 1
  fi
  if ! resolved=$(assert_replaceable_app_dir "$app"); then
    return 1
  fi
  _replace_app_tree_apply "$resolved" "$tarball"
}

_replace_app_tree_apply() {
  (
    set -Eeuo pipefail
    app=$1
    tarball=$2
    staging=$(mktemp -d)
    keep=$(mktemp -d)
    # Invoked by the EXIT trap below. Shellcheck does not treat that as a call.
    # shellcheck disable=SC2317
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

# Root owns the app tree and the virtualenv. The service account can write
# only the data directory (SQLite and its sidecars) and the instance
# directory. Safe to run again: it does not delete the database, backups,
# or loose copies that sit beside the database.
apply_runtime_ownership() {
  local app=$1
  local data=$2
  local user=$3
  local group resolved resolved_data parent base path link db sidecar backups
  if [[ -z "$app" || -z "$data" || -z "$user" ]]; then
    echo "Refusing to set ownership without an app directory, a data directory, and a service account." >&2
    return 1
  fi
  if [[ "$user" == "root" ]]; then
    echo "Refusing to give the service write paths to root." >&2
    return 1
  fi
  if ! id "$user" >/dev/null 2>&1; then
    echo "Service account ${user} does not exist." >&2
    return 1
  fi
  group=$(id -gn -- "$user")
  if [[ -z "$group" || "$group" == "root" ]]; then
    echo "Refusing service account ${user} whose group is root or empty." >&2
    return 1
  fi
  if ! resolved=$(assert_replaceable_app_dir "$app"); then
    return 1
  fi
  case "$data" in
    /*) ;;
    *)
      echo "Data directory must be absolute." >&2
      return 1
      ;;
  esac
  if [[ -L "$data" ]]; then
    echo "Refusing a symlink as the data directory." >&2
    return 1
  fi
  if [[ -d "$data" ]]; then
    resolved_data=$(readlink -f -- "$data")
  else
    parent=$(dirname -- "$data")
    base=$(basename -- "$data")
    if [[ ! -d "$parent" || -L "$parent" ]]; then
      echo "Data directory parent does not exist." >&2
      return 1
    fi
    resolved_data=$(readlink -f -- "$parent")/$base
  fi
  case "$resolved_data" in
    "$resolved"|"$resolved"/*)
      echo "Refusing a data directory inside the app tree." >&2
      return 1
      ;;
  esac
  if [[ -L "$resolved/instance" || -L "$resolved/.venv" || -L "$resolved/.venv/bin" ]]; then
    echo "Refusing to set ownership while instance or .venv is a symlink." >&2
    return 1
  fi
  if [[ -d "$resolved/instance" ]]; then
    link=$(find -P "$resolved/instance" -mindepth 1 -type l -print -quit)
    if [[ -n "$link" ]]; then
      echo "Refusing to set ownership while instance contains a symlink." >&2
      return 1
    fi
  fi
  db="$resolved_data/grc_assurance.sqlite3"
  if [[ -L "$db" || -L "${db}-wal" || -L "${db}-shm" || -L "${db}-journal" ]]; then
    echo "Refusing a symlink as the SQLite database or one of its sidecars." >&2
    return 1
  fi
  backups="$resolved_data/backups"
  if [[ -L "$backups" ]]; then
    echo "Refusing a symlink as the backup directory." >&2
    return 1
  fi

  while IFS= read -r -d '' path; do
    chown -h root:root -- "$path"
    if [[ -L "$path" ]]; then
      continue
    fi
    if [[ -d "$path" ]]; then
      chmod 0755 "$path"
    elif [[ -f "$path" ]]; then
      chmod 0644 "$path"
    fi
  done < <(find -P "$resolved" -path "$resolved/instance" -prune -o -print0)
  if [[ -d "$resolved/.venv/bin" ]]; then
    while IFS= read -r -d '' path; do
      [[ -L "$path" ]] && continue
      [[ -f "$path" ]] || continue
      chmod 0755 "$path"
    done < <(find -P "$resolved/.venv/bin" -mindepth 1 -maxdepth 1 -type f -print0)
  fi

  mkdir -p -- "$resolved/instance"
  chown "$user:$group" -- "$resolved/instance"
  chmod 0750 "$resolved/instance"
  while IFS= read -r -d '' path; do
    [[ -L "$path" ]] && continue
    chown "$user:$group" -- "$path"
    if [[ -d "$path" ]]; then
      chmod 0750 "$path"
    elif [[ -f "$path" ]]; then
      chmod 0600 "$path"
    fi
  done < <(find -P "$resolved/instance" -mindepth 1 -print0)

  mkdir -p -- "$resolved_data"
  if [[ -L "$resolved_data" ]]; then
    echo "Refusing a symlink as the data directory." >&2
    return 1
  fi
  resolved_data=$(readlink -f -- "$resolved_data")
  case "$resolved_data" in
    "$resolved"|"$resolved"/*)
      echo "Refusing a data directory inside the app tree." >&2
      return 1
      ;;
  esac
  # Root owns the directory. The service group can create files. The sticky
  # bit stops that account from unlinking the root-owned backups directory.
  chown "root:$group" -- "$resolved_data"
  chmod 1770 "$resolved_data"
  db="$resolved_data/grc_assurance.sqlite3"
  if [[ -f "$db" ]]; then
    chown "$user:$group" -- "$db"
    chmod 0600 "$db"
  fi
  for sidecar in "${db}-wal" "${db}-shm" "${db}-journal"; do
    if [[ -f "$sidecar" ]]; then
      chown "$user:$group" -- "$sidecar"
      chmod 0600 "$sidecar"
    fi
  done
  backups="$resolved_data/backups"
  mkdir -p -- "$backups"
  chown root:root -- "$backups"
  chmod 0700 "$backups"
  while IFS= read -r -d '' path; do
    [[ -L "$path" ]] && continue
    [[ -f "$path" ]] || continue
    chown root:root -- "$path"
    chmod 0600 "$path"
  done < <(find -P "$backups" -mindepth 1 -maxdepth 1 -type f -print0)
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

# Path of a downloaded tarball removed on EXIT. This is not a function local.
# main returns before the shell exits, and the EXIT trap then runs under
# set -u. A local name such as tarball is already gone by then.
CLEANUP_TAR_FILE=""

cleanup_downloaded_tarball() {
  if [[ -n "${CLEANUP_TAR_FILE:-}" ]]; then
    rm -f -- "$CLEANUP_TAR_FILE"
    CLEANUP_TAR_FILE=""
  fi
}

arm_tarball_cleanup() {
  local path=${1-}
  if [[ -z "$path" ]]; then
    echo "Refusing to arm tarball cleanup without a path." >&2
    return 1
  fi
  CLEANUP_TAR_FILE=$path
  trap cleanup_downloaded_tarball EXIT
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
  apt-get install -y ca-certificates curl nginx python3-venv python3-pip sqlite3
  ensure_service_user

  tarball=$(mktemp)
  arm_tarball_cleanup "$tarball"
  curl -fsSL "https://github.com/doneal78/grc-assurance-engine/archive/${revision}.tar.gz" -o "$tarball"
  install -d -o root -g root -m 0755 "$APP_DIR"
  replace_app_tree "$APP_DIR" "$tarball"
  rm -f -- "$tarball"
  python3 -m venv "$APP_DIR/.venv"
  "$APP_DIR/.venv/bin/pip" install --upgrade pip
  "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"
  apply_runtime_ownership "$APP_DIR" "$DATA_DIR" "$SERVICE_USER"

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
