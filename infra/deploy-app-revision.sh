#!/usr/bin/env bash
# Install one pinned commit on an already bootstrapped Lightsail host.
#
# Requires a full 40-character SHA. Refuses a branch name, a short SHA, and
# a re-run that would silently reuse /etc/grc-assurance-revision. Backs up
# the SQLite file with the sqlite3 CLI .backup command (the online backup
# API) before replacing code. Reuses replace_app_tree from
# lightsail-bootstrap.sh, so .venv and instance/ are kept and
# /var/lib/grc-assurance is not deleted. Reinstalls Python dependencies into
# the existing virtualenv, restarts grc-assurance-engine, and records the
# SHA in /etc/grc-assurance-revision only after local /health returns
# "status":"ok" and "database":"reachable".
#
# Does not install OS packages, create the service account, or rewrite the systemd unit.
# Leaves Nginx unchanged unless --update-nginx is set. That flag installs
# infra/nginx-site.conf from the same SHA, runs nginx -t, and reloads.
#
# First install, package setup, and the service-user switch stay in
# infra/lightsail-bootstrap.sh. Run this script as root. The functions above
# main can be sourced by tests.
set -Eeuo pipefail

_DEPLOY_SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=lightsail-bootstrap.sh
source "${_DEPLOY_SCRIPT_DIR}/lightsail-bootstrap.sh"

# Same pin file lightsail-bootstrap.sh writes. Do not add a second revision file.
DEPLOY_LOG=/var/log/grc-assurance-deploy.log
DEPLOY_LOCK=/var/lock/grc-assurance-deploy.lock
ENV_FILE=/etc/grc-assurance-engine.env
NGINX_SITE=/etc/nginx/sites-available/grc-assurance-engine
HEALTH_URL=http://127.0.0.1:8000/health
UNIT_NAME=grc-assurance-engine
DATABASE_FILE="${DATA_DIR}/grc_assurance.sqlite3"
GITHUB_ARCHIVE_PREFIX=https://github.com/doneal78/grc-assurance-engine/archive

require_revision() {
  local revision=${1-}
  revision=${revision#"${revision%%[![:space:]]*}"}
  revision=${revision%"${revision##*[![:space:]]}"}
  if [[ -z "$revision" ]]; then
    echo "A full 40-character commit SHA is required. This script does not install a branch name." >&2
    return 1
  fi
  if [[ ! "$revision" =~ ^[0-9a-fA-F]{40}$ ]]; then
    echo "Revision must be a full 40-character commit SHA. This script does not install a branch name or a short SHA." >&2
    return 1
  fi
  printf '%s\n' "${revision,,}"
}

parse_deploy_args() {
  DEPLOY_REVISION=""
  DEPLOY_UPDATE_NGINX=0
  DEPLOY_SHOW_HELP=0
  local arg saw_revision=0
  for arg in "$@"; do
    if [[ "$arg" == "-h" || "$arg" == "--help" ]]; then
      DEPLOY_SHOW_HELP=1
      return 0
    fi
  done
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --revision)
        if [[ $# -lt 2 ]]; then
          echo "--revision requires a full 40-character commit SHA." >&2
          return 1
        fi
        if [[ "$saw_revision" -eq 1 ]]; then
          echo "--revision was provided more than once." >&2
          return 1
        fi
        saw_revision=1
        DEPLOY_REVISION=$2
        shift 2
        ;;
      --update-nginx)
        DEPLOY_UPDATE_NGINX=1
        shift
        ;;
      *)
        echo "Unknown argument: $1" >&2
        return 1
        ;;
    esac
  done
  if [[ "$saw_revision" -eq 0 ]]; then
    if [[ -n "${GRC_REVISION:-}" ]]; then
      DEPLOY_REVISION=$GRC_REVISION
    else
      echo "A full 40-character commit SHA is required. Pass --revision or set GRC_REVISION. This script does not read ${PIN_FILE} and does not install a branch name." >&2
      return 1
    fi
  fi
  if ! DEPLOY_REVISION=$(require_revision "$DEPLOY_REVISION"); then
    return 1
  fi
}

assert_bootstrap_paths() {
  if [[ "$PIN_FILE" != "/etc/grc-assurance-revision" ]]; then
    echo "Refusing to record a revision in ${PIN_FILE}. The bootstrap pin file is /etc/grc-assurance-revision." >&2
    return 1
  fi
  if [[ "$APP_DIR" != "/opt/grc-assurance-engine" ]]; then
    echo "Refusing app directory ${APP_DIR}." >&2
    return 1
  fi
  if [[ "$DATA_DIR" != "/var/lib/grc-assurance" ]]; then
    echo "Refusing data directory ${DATA_DIR}." >&2
    return 1
  fi
}

assert_service_account_name() {
  local name=${1-}
  if [[ -z "$name" || "$name" == "root" ]]; then
    echo "Refusing to deploy while the unit runs as root or has no User=." >&2
    return 1
  fi
  if [[ ! "$name" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]]; then
    echo "Refusing unexpected service account name." >&2
    return 1
  fi
}

auth_env_is_consistent() {
  local file=$1
  local line value require=0 user="" pass=""
  if [[ ! -f "$file" ]]; then
    return 0
  fi
  while IFS= read -r line || [[ -n "$line" ]]; do
    case "$line" in
      ''|\#*) continue ;;
    esac
    case "$line" in
      REQUIRE_AUTH=true|REQUIRE_AUTH=true[[:space:]]*)
        require=1
        ;;
      DEMO_USERNAME=*)
        value=${line#DEMO_USERNAME=}
        if [[ -n "$value" && "$value" != '""' && "$value" != "''" ]]; then
          user=set
        else
          user=""
        fi
        ;;
      DEMO_PASSWORD=*)
        value=${line#DEMO_PASSWORD=}
        if [[ -n "$value" && "$value" != '""' && "$value" != "''" ]]; then
          pass=set
        else
          pass=""
        fi
        ;;
    esac
  done < "$file"
  if [[ "$require" -eq 1 && ( -z "$user" || -z "$pass" ) ]]; then
    echo "REQUIRE_AUTH=true in ${file}, and DEMO_USERNAME or DEMO_PASSWORD is empty. Refusing to restart. The values were not printed." >&2
    return 1
  fi
}

preflight_paths() {
  local app=$1
  local database=$2
  if [[ ! -d "$app" ]]; then
    echo "App directory does not exist. Run infra/lightsail-bootstrap.sh for the first install." >&2
    return 1
  fi
  if [[ ! -x "$app/.venv/bin/pip" ]]; then
    echo "Existing virtualenv is missing at ${app}/.venv. This script does not create it. Run infra/lightsail-bootstrap.sh for the first install." >&2
    return 1
  fi
  if [[ ! -f "$database" ]]; then
    echo "SQLite database does not exist. This script does not create or delete it." >&2
    return 1
  fi
}

assert_nginx_site_destination() {
  local dest=$1
  if [[ "$dest" == "$NGINX_SITE" ]]; then
    return 0
  fi
  echo "Refusing to write an Nginx site file outside ${NGINX_SITE}." >&2
  return 1
}

assert_nginx_site_source() {
  local src=$1
  if [[ ! -f "$src" ]]; then
    echo "Nginx source file does not exist." >&2
    return 1
  fi
  if ! grep -q "server_name grc-assurance.davidoneal.dev;" "$src"; then
    echo "Refusing Nginx file that does not name grc-assurance.davidoneal.dev." >&2
    return 1
  fi
}

# Print the one archive member whose path is <one-directory>/${suffix}.
release_tarball_member() {
  local tarball=$1
  local suffix=$2
  local entry rest
  local -a entries=()
  if [[ ! -f "$tarball" ]]; then
    echo "Release tarball does not exist." >&2
    return 1
  fi
  if ! tar -tzf "$tarball" >/dev/null; then
    echo "Release tarball is not readable." >&2
    return 1
  fi
  while IFS= read -r entry; do
    [[ -z "$entry" ]] && continue
    entry=${entry#./}
    case "$entry" in
      "$suffix"|*/"$suffix")
        rest=${entry%/"$suffix"}
        case "$rest" in
          ""|*/*) ;;
          *) entries+=("$entry") ;;
        esac
        ;;
    esac
  done < <(tar -tzf "$tarball")
  if [[ "${#entries[@]}" -ne 1 ]]; then
    echo "Expected one top-level ${suffix} in the release tarball, found ${#entries[@]}." >&2
    return 1
  fi
  entry=${entries[0]}
  case "$entry" in
    /*|*..*|*[![:alnum:]/_.-]*)
      echo "Refusing tarball member ${entry}." >&2
      return 1
      ;;
  esac
  printf '%s\n' "$entry"
}

extract_tarball_member() {
  local tarball=$1
  local suffix=$2
  local dest=$3
  local entry listing mode
  if ! entry=$(release_tarball_member "$tarball" "$suffix"); then
    return 1
  fi
  if ! listing=$(tar -tvzf "$tarball" -- "$entry"); then
    echo "Could not list tarball member ${entry}." >&2
    return 1
  fi
  mode=${listing%% *}
  case "$mode" in
    -*) ;;
    *)
      echo "Refusing tarball member ${entry} that is not a regular file." >&2
      return 1
      ;;
  esac
  if ! tar -xOzf "$tarball" -- "$entry" > "$dest"; then
    echo "Could not extract ${entry}." >&2
    return 1
  fi
}

tarball_url_for_revision() {
  local revision
  if ! revision=$(require_revision "$1"); then
    return 1
  fi
  printf '%s\n' "${GITHUB_ARCHIVE_PREFIX}/${revision}.tar.gz"
}

backup_destination() {
  local data_dir=${1-}
  local revision stamp=${3-}
  data_dir=${data_dir%/}
  if [[ -z "$data_dir" || "$data_dir" != /* ]]; then
    echo "Backup data directory must be absolute." >&2
    return 1
  fi
  if ! revision=$(require_revision "${2-}"); then
    return 1
  fi
  if [[ -z "$stamp" ]]; then
    stamp=$(date -u +%Y%m%dT%H%M%SZ)
  fi
  if [[ ! "$stamp" =~ ^[0-9]{8}T[0-9]{6}Z$ ]]; then
    echo "Backup timestamp must be UTC YYYYmmddTHHMMSSZ." >&2
    return 1
  fi
  printf '%s\n' "${data_dir}/backups/grc_assurance-${stamp}-${revision}.sqlite3"
}

assert_resolved_backup_target() {
  local app=$1
  local database=$2
  local backup=$3
  local resolved_app resolved_db resolved_backup data_dir
  resolved_app=$(readlink -f -- "$app")
  resolved_db=$(readlink -f -- "$database")
  resolved_backup=$(readlink -f -- "$backup")
  if [[ "$resolved_backup" == "$resolved_db" ]]; then
    echo "Refusing to back up onto the live database path." >&2
    return 1
  fi
  case "$resolved_backup" in
    "$resolved_app"|"$resolved_app"/*)
      echo "Refusing to write a backup inside the app tree." >&2
      return 1
      ;;
  esac
  data_dir=$(dirname -- "$resolved_db")
  case "$resolved_backup" in
    "$data_dir"/backups/*) ;;
    *)
      echo "Refusing backup path outside ${data_dir}/backups." >&2
      return 1
      ;;
  esac
}

assert_safe_deploy_paths() {
  local app=$1
  local database=$2
  local backup=$3
  local resolved_app resolved_db data_dir tmp_root
  if [[ ! -d "$app" ]]; then
    echo "App directory does not exist." >&2
    return 1
  fi
  resolved_app=$(readlink -f -- "$app")
  if [[ "$(basename -- "$resolved_app")" != "grc-assurance-engine" ]]; then
    echo "Refusing to deploy into an app directory whose name is not grc-assurance-engine." >&2
    return 1
  fi
  tmp_root=${TMPDIR:-/tmp}
  tmp_root=${tmp_root%/}
  case "$resolved_app" in
    /opt/grc-assurance-engine) ;;
    "$tmp_root"/*|/var/tmp/*) ;;
    *)
      echo "Refusing to deploy into an app directory outside /opt/grc-assurance-engine or the temp directory." >&2
      return 1
      ;;
  esac
  case "$database" in
    /*) ;;
    *)
      echo "Database path must be absolute." >&2
      return 1
      ;;
  esac
  if [[ ! -f "$database" ]]; then
    echo "SQLite database does not exist. This script does not create or delete it." >&2
    return 1
  fi
  resolved_db=$(readlink -f -- "$database")
  case "$resolved_db" in
    "$resolved_app"|"$resolved_app"/*)
      echo "Refusing to use a database inside the app tree." >&2
      return 1
      ;;
  esac
  case "$backup" in
    /*) ;;
    *)
      echo "Backup path must be absolute." >&2
      return 1
      ;;
  esac
  if [[ ! "$backup" =~ ^[A-Za-z0-9_./-]+$ ]]; then
    echo "Refusing backup path with unexpected characters." >&2
    return 1
  fi
  case "/$backup/" in
    */../*|*/./*)
      echo "Refusing backup path with . or .. segments." >&2
      return 1
      ;;
  esac
  if [[ "$backup" == "$resolved_db" || "$backup" == "$database" ]]; then
    echo "Refusing to back up onto the live database path." >&2
    return 1
  fi
  data_dir=$(dirname -- "$resolved_db")
  case "$backup" in
    "$data_dir"/backups/*) ;;
    *)
      echo "Refusing backup path outside ${data_dir}/backups." >&2
      return 1
      ;;
  esac
  case "$backup" in
    "$resolved_app"|"$resolved_app"/*)
      echo "Refusing to write a backup inside the app tree." >&2
      return 1
      ;;
  esac
  if [[ -d "$(dirname -- "$backup")" ]]; then
    assert_resolved_backup_target "$app" "$database" "$backup"
  fi
}

backup_sqlite_online() {
  local app=$1
  local database=$2
  local dest=$3
  local dest_dir
  assert_safe_deploy_paths "$app" "$database" "$dest"
  dest_dir=$(dirname -- "$dest")
  mkdir -p -- "$dest_dir"
  chmod 700 "$dest_dir"
  assert_resolved_backup_target "$app" "$database" "$dest"
  if [[ -e "$dest" ]]; then
    echo "Backup destination already exists." >&2
    return 1
  fi
  if ! command -v sqlite3 >/dev/null 2>&1; then
    echo "sqlite3 is not installed. This script does not install OS packages. Install the sqlite3 package and re-run. The app tree was not changed." >&2
    return 1
  fi
  # .backup uses SQLite's online backup API. It is not a file copy.
  if ! sqlite3 "$database" ".timeout 5000" ".backup ${dest}"; then
    rm -f -- "$dest"
    echo "SQLite online backup failed. The app tree was not changed." >&2
    return 1
  fi
  chmod 600 "$dest"
}

health_response_acceptable() {
  python3 -c '
import json
import sys
raw = sys.stdin.read()
try:
    data = json.loads(raw)
except json.JSONDecodeError:
    raise SystemExit(2)
if not isinstance(data, dict):
    raise SystemExit(2)
if data.get("status") != "ok":
    raise SystemExit(1)
if data.get("database") != "reachable":
    raise SystemExit(3)
' <<<"${1-}"
}

record_deployed_revision() {
  local revision pin=${2:-$PIN_FILE} dir
  if ! revision=$(require_revision "$1"); then
    return 1
  fi
  if [[ -L "$pin" ]]; then
    echo "Refusing to write the revision through a symlink at ${pin}." >&2
    return 1
  fi
  dir=$(dirname -- "$pin")
  if [[ ! -d "$dir" ]]; then
    echo "Pin directory does not exist: ${dir}" >&2
    return 1
  fi
  printf '%s\n' "$revision" > "$pin"
  if [[ "$(id -u)" -eq 0 ]]; then
    chown root:root "$pin"
    chmod 644 "$pin"
  fi
}

usage() {
  cat <<EOF
Usage: deploy-app-revision.sh --revision <40-character SHA> [--update-nginx]

Install one commit on a host that already has the ${UNIT_NAME} unit,
${APP_DIR}/.venv, and ${DATABASE_FILE}. A branch name or a short SHA is
refused. ${PIN_FILE} is not used as the revision to install.

The SQLite file is backed up with sqlite3 .backup before the app tree
changes. .venv and instance/ stay. ${DATA_DIR} is not deleted. Dependencies
are reinstalled into the existing virtualenv. The unit is restarted as
whatever User= it already has. This script does not create that account
and does not rewrite the unit.

The SHA is written to ${PIN_FILE} only after ${HEALTH_URL} returns
"status":"ok" and "database":"reachable". Nginx is left alone unless
--update-nginx is set.

First install: infra/lightsail-bootstrap.sh
EOF
}

main() {
  local revision update_nginx tarball backup dest_dir running_user previous url
  if ! parse_deploy_args "$@"; then
    exit 1
  fi
  if [[ "${DEPLOY_SHOW_HELP:-0}" -eq 1 ]]; then
    usage
    exit 0
  fi
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "Run this deploy as root." >&2
    exit 1
  fi
  if ! command -v flock >/dev/null 2>&1; then
    echo "flock is not installed. Refusing to deploy without a lock." >&2
    exit 1
  fi
  mkdir -p -- "$(dirname -- "$DEPLOY_LOCK")"
  exec 9>"$DEPLOY_LOCK"
  if ! flock -n 9; then
    echo "Another deploy is running (lock ${DEPLOY_LOCK})." >&2
    exit 1
  fi

  revision=$DEPLOY_REVISION
  update_nginx=$DEPLOY_UPDATE_NGINX
  touch "$DEPLOY_LOG"
  chown root:root "$DEPLOY_LOG"
  chmod 640 "$DEPLOY_LOG"
  if command -v stdbuf >/dev/null 2>&1; then
    exec > >(stdbuf -oL tee -a "$DEPLOY_LOG") 2>&1
  else
    exec > >(tee -a "$DEPLOY_LOG") 2>&1
  fi

  echo "deploy start $(date -u +%Y-%m-%dT%H:%M:%SZ) revision=${revision} update_nginx=${update_nginx}"
  assert_bootstrap_paths
  preflight_paths "$APP_DIR" "$DATABASE_FILE"
  auth_env_is_consistent "$ENV_FILE"
  if ! command -v curl >/dev/null 2>&1 || ! command -v python3 >/dev/null 2>&1 || ! command -v sqlite3 >/dev/null 2>&1; then
    echo "curl, python3, and sqlite3 are required. This script does not install OS packages." >&2
    exit 1
  fi
  if ! command -v systemctl >/dev/null 2>&1; then
    echo "systemctl is not available." >&2
    exit 1
  fi
  if ! systemctl cat "${UNIT_NAME}.service" >/dev/null 2>&1; then
    echo "systemd unit ${UNIT_NAME} is not installed. Run infra/lightsail-bootstrap.sh for the first install." >&2
    exit 1
  fi
  running_user=$(systemctl show -p User --value "${UNIT_NAME}.service")
  assert_service_account_name "$running_user"
  if ! id "$running_user" >/dev/null 2>&1; then
    echo "Service account ${running_user} does not exist. This script does not create accounts." >&2
    exit 1
  fi

  previous="<none>"
  if [[ -f "$PIN_FILE" && ! -L "$PIN_FILE" ]]; then
    previous=$(tr -d '[:space:]' < "$PIN_FILE" || true)
  fi
  echo "previous pin=${previous:-<empty>} target=${revision}"

  umask 022
  tarball=$(mktemp)
  # The EXIT trap reads CLEANUP_TAR_FILE, not this function-local name.
  arm_tarball_cleanup "$tarball"
  if ! url=$(tarball_url_for_revision "$revision"); then
    exit 1
  fi
  if ! curl -fsSL --retry 3 --retry-delay 2 "$url" -o "$tarball"; then
    echo "Download failed. The app tree was not changed." >&2
    exit 1
  fi
  if ! release_tarball_member "$tarball" "requirements.txt" >/dev/null; then
    echo "The release tarball has no single top-level requirements.txt. The app tree was not changed." >&2
    exit 1
  fi

  dest_dir=$(dirname -- "$(readlink -f -- "$DATABASE_FILE")")
  if ! backup=$(backup_destination "$dest_dir" "$revision"); then
    exit 1
  fi
  echo "sqlite backup ${backup}"
  if ! backup_sqlite_online "$APP_DIR" "$DATABASE_FILE" "$backup"; then
    echo "SQLite backup failed. The app tree was not changed." >&2
    exit 1
  fi
  if ! replace_app_tree "$APP_DIR" "$tarball"; then
    echo "Replacing the app tree failed. ${PIN_FILE} was not updated. Database backup: ${backup}." >&2
    exit 1
  fi
  if ! "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"; then
    echo "pip install failed. The unit was not restarted and ${PIN_FILE} was not updated. The app tree may already be ${revision}. Database backup: ${backup}." >&2
    exit 1
  fi
  if ! chown -R "$running_user:$running_user" "$APP_DIR"; then
    echo "Could not give the app tree to ${running_user}. The unit was not restarted and ${PIN_FILE} was not updated. Database backup: ${backup}." >&2
    exit 1
  fi
  if ! systemctl restart "$UNIT_NAME"; then
    echo "Restart failed. ${PIN_FILE} was not updated. The app tree may already be ${revision}. Database backup: ${backup}." >&2
    exit 1
  fi
  if ! wait_for_local_health; then
    echo "Health check failed. ${PIN_FILE} was not updated. The app tree may already be ${revision}. Re-run this script with the previous SHA to roll the code back. The database file was not deleted. Backup: ${backup}." >&2
    systemctl status "$UNIT_NAME" --no-pager -l || true
    journalctl -u "$UNIT_NAME" -n 40 --no-pager || true
    exit 1
  fi
  if ! record_deployed_revision "$revision" "$PIN_FILE"; then
    echo "Health passed, and ${PIN_FILE} was not updated. Database backup: ${backup}." >&2
    exit 1
  fi
  echo "recorded ${revision} in ${PIN_FILE}"

  if [[ "$update_nginx" -eq 1 ]]; then
    if ! install_nginx_from_tarball "$tarball"; then
      echo "App revision ${revision} passed health and was recorded. Nginx was not switched." >&2
      exit 1
    fi
    echo "deploy finished ${revision} nginx=updated"
  else
    echo "deploy finished ${revision} nginx=unchanged"
  fi
}

wait_for_local_health() {
  local attempts=20
  local i=0 body=""
  while [[ "$i" -lt "$attempts" ]]; do
    i=$((i + 1))
    body=$(curl -sS --max-time 3 "$HEALTH_URL" 2>/dev/null || true)
    if health_response_acceptable "$body"; then
      printf '%s\n' "$body"
      return 0
    fi
    sleep 1
  done
  echo "Local health check failed at ${HEALTH_URL}. Last body: ${body:-<empty>}" >&2
  return 1
}

install_nginx_from_tarball() {
  local tarball=$1
  local extracted backup
  extracted=$(mktemp)
  if ! extract_tarball_member "$tarball" "infra/nginx-site.conf" "$extracted"; then
    rm -f -- "$extracted"
    return 1
  fi
  if ! assert_nginx_site_source "$extracted"; then
    rm -f -- "$extracted"
    return 1
  fi
  if ! assert_nginx_site_destination "$NGINX_SITE"; then
    rm -f -- "$extracted"
    return 1
  fi
  if [[ ! -f "$NGINX_SITE" ]]; then
    rm -f -- "$extracted"
    echo "Refusing to create ${NGINX_SITE}. Bootstrap writes a placeholder only when that file is missing, and this script does not. Nginx was not changed." >&2
    return 1
  fi
  backup=$(mktemp)
  cp -a -- "$NGINX_SITE" "$backup"
  install -o root -g root -m 644 "$extracted" "$NGINX_SITE"
  rm -f -- "$extracted"
  if ! nginx -t; then
    cp -a -- "$backup" "$NGINX_SITE"
    rm -f -- "$backup"
    echo "nginx -t failed. Restored the previous site file and did not reload Nginx." >&2
    return 1
  fi
  if ! systemctl reload nginx; then
    cp -a -- "$backup" "$NGINX_SITE"
    rm -f -- "$backup"
    nginx -t && systemctl reload nginx || true
    echo "Nginx reload failed. Attempted to restore the previous site file." >&2
    return 1
  fi
  rm -f -- "$backup"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
