#!/usr/bin/env bash
# Optional hardening for the Lightsail demo host. Nothing in this repository
# runs it: not lightsail-bootstrap.sh, not deploy-app-revision.sh, not
# systemd, and not GitHub Actions. An administrator runs it by hand as root.
#
# Usage:
#   harden-lightsail-host.sh --dry-run <admin-ipv4>/32
#   harden-lightsail-host.sh <admin-ipv4>/32
#
# The script refuses to run without one IPv4 /32. That address is the only
# source allowed to open SSH. Incoming policy is deny. Ports 80 and 443 are
# allowed only from Cloudflare ranges fetched at run time from:
#   https://www.cloudflare.com/ips-v4
#   https://www.cloudflare.com/ips-v6
# Cloudflare changes those ranges. This script does not store a copy and
# does not schedule a refresh. Re-run it to fetch the current list. A failed
# fetch makes no firewall change.
#
# Dry-run prints the planned changes and does not apply them. It still
# requires the /32, and it still fetches the ranges so the plan lists them.
#
# Also creates a 1 GiB /swapfile (mode 0600) and sets PermitRootLogin no.
#
# Rollback, from the Lightsail console if a wrong /32 has locked out SSH:
#   ufw disable
#   rm -f /etc/ssh/sshd_config.d/99-grc-no-root-login.conf
#   sshd -t && systemctl reload ssh
#   swapoff /swapfile || true
#   rm -f /swapfile
#   Remove the /swapfile line from /etc/fstab.
# The Lightsail networking firewall is separate and this script does not
# change it. See docs/deployment.md.
set -Eeuo pipefail

CLOUDFLARE_IPV4_URL=https://www.cloudflare.com/ips-v4
CLOUDFLARE_IPV6_URL=https://www.cloudflare.com/ips-v6
SWAP_FILE=/swapfile
SWAP_SIZE=1G
SSHD_DROPIN=/etc/ssh/sshd_config.d/99-grc-no-root-login.conf

usage() {
  cat <<EOF
Usage: harden-lightsail-host.sh [--dry-run] <admin-ipv4>/32

Optional. Not run by bootstrap, deploy, systemd, or GitHub Actions.
Refuses to run without one IPv4 /32. That address is the only SSH source.
Ports 80 and 443 are allowed only from Cloudflare ranges fetched from
${CLOUDFLARE_IPV4_URL} and ${CLOUDFLARE_IPV6_URL}. Re-run to refresh.
There is no schedule. --dry-run prints the plan and changes nothing.

Also plans a 1 GiB ${SWAP_FILE} (mode 0600) and PermitRootLogin no.

Rollback: ufw disable; remove ${SSHD_DROPIN} and reload ssh; swapoff and
delete ${SWAP_FILE}; remove its /etc/fstab line. A wrong /32 can lock out
new SSH. Use the Lightsail console and run: ufw disable
EOF
}

require_admin_cidr() {
  local cidr=${1-}
  local octet
  if [[ -z "$cidr" ]]; then
    echo "An administrator IPv4 /32 is required. Example: harden-lightsail-host.sh --dry-run 203.0.113.10/32" >&2
    echo "Refusing to run without it. This script does not open SSH to the world." >&2
    return 1
  fi
  if [[ ! "$cidr" =~ ^([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})/32$ ]]; then
    echo "SSH must be limited to one IPv4 /32. Refusing ${cidr}." >&2
    return 1
  fi
  for octet in "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}" "${BASH_REMATCH[3]}" "${BASH_REMATCH[4]}"; do
    if [[ "$octet" =~ ^0[0-9] || "$octet" -gt 255 ]]; then
      echo "SSH must be limited to one IPv4 /32. Refusing ${cidr}." >&2
      return 1
    fi
  done
  printf '%s\n' "$cidr"
}

valid_cloudflare_range() {
  local line=$1
  local octet prefix addr o1 o2 o3 o4
  if [[ "$line" == "0.0.0.0/0" || "$line" == "::/0" ]]; then
    return 1
  fi
  if [[ "$line" =~ ^([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})/([0-9]{1,2})$ ]]; then
    # Copy the match before the next =~ . That operator clears BASH_REMATCH.
    o1=${BASH_REMATCH[1]}
    o2=${BASH_REMATCH[2]}
    o3=${BASH_REMATCH[3]}
    o4=${BASH_REMATCH[4]}
    prefix=${BASH_REMATCH[5]}
    if [[ "$prefix" =~ ^0[0-9] || "$prefix" -gt 32 ]]; then
      return 1
    fi
    for octet in "$o1" "$o2" "$o3" "$o4"; do
      if [[ "$octet" =~ ^0[0-9] || "$octet" -gt 255 ]]; then
        return 1
      fi
    done
    return 0
  fi
  if [[ "$line" =~ ^([0-9a-fA-F:]+)/([0-9]{1,3})$ ]]; then
    addr=${BASH_REMATCH[1]}
    prefix=${BASH_REMATCH[2]}
    if [[ "$addr" != *:* || "$addr" == *::*::* ]]; then
      return 1
    fi
    if [[ "$prefix" =~ ^0[0-9] || "$prefix" -gt 128 ]]; then
      return 1
    fi
    return 0
  fi
  return 1
}

read_cloudflare_ranges() {
  local line count=0
  while IFS= read -r line || [[ -n "${line-}" ]]; do
    line=${line%$'\r'}
    [[ -z "$line" || "$line" == \#* ]] && continue
    if ! valid_cloudflare_range "$line"; then
      echo "Refusing Cloudflare range line." >&2
      return 1
    fi
    printf '%s\n' "$line"
    count=$((count + 1))
  done
  if [[ "$count" -eq 0 ]]; then
    echo "Cloudflare range list was empty." >&2
    return 1
  fi
}

fetch_cloudflare_ranges() {
  local v4 v6 combined
  if ! command -v curl >/dev/null 2>&1; then
    echo "curl is required to fetch Cloudflare IP ranges. No firewall change was made." >&2
    return 1
  fi
  if ! v4=$(curl -fsSL --retry 3 --retry-delay 2 --max-time 30 "$CLOUDFLARE_IPV4_URL"); then
    echo "Could not fetch ${CLOUDFLARE_IPV4_URL}. No firewall change was made." >&2
    return 1
  fi
  if ! v6=$(curl -fsSL --retry 3 --retry-delay 2 --max-time 30 "$CLOUDFLARE_IPV6_URL"); then
    echo "Could not fetch ${CLOUDFLARE_IPV6_URL}. No firewall change was made." >&2
    return 1
  fi
  combined=$(printf '%s\n%s\n' "$v4" "$v6")
  if ! printf '%s\n' "$combined" | read_cloudflare_ranges; then
    echo "Cloudflare range list was rejected. No firewall change was made." >&2
    return 1
  fi
}

parse_harden_args() {
  HARDEN_DRY_RUN=0
  HARDEN_CIDR=""
  HARDEN_SHOW_HELP=0
  local arg
  while [[ $# -gt 0 ]]; do
    arg=$1
    case "$arg" in
      -h|--help)
        HARDEN_SHOW_HELP=1
        return 0
        ;;
      --dry-run)
        HARDEN_DRY_RUN=1
        shift
        ;;
      --)
        shift
        break
        ;;
      -*)
        echo "Unknown argument: ${arg}" >&2
        return 1
        ;;
      *)
        if [[ -n "$HARDEN_CIDR" ]]; then
          echo "Only one administrator IPv4 /32 is accepted." >&2
          return 1
        fi
        HARDEN_CIDR=$arg
        shift
        ;;
    esac
  done
  if [[ $# -gt 0 ]]; then
    echo "Only one administrator IPv4 /32 is accepted." >&2
    return 1
  fi
  if ! HARDEN_CIDR=$(require_admin_cidr "$HARDEN_CIDR"); then
    return 1
  fi
}

print_planned_changes() {
  local cidr=$1
  shift
  local range
  cat <<EOF
Planned changes:
- install the ufw package only if it is missing (apply only; dry-run does not install it)
- ufw --force reset
- ufw default deny incoming
- ufw default allow outgoing
- ufw allow from ${cidr} to any port 22 proto tcp
- allow ports 80 and 443 only from these Cloudflare ranges:
EOF
  for range in "$@"; do
    printf '  ufw allow from %s to any port 80 proto tcp\n' "$range"
    printf '  ufw allow from %s to any port 443 proto tcp\n' "$range"
  done
  cat <<EOF
- ufw --force enable
- 1 GiB swapfile at ${SWAP_FILE} (fallocate -l ${SWAP_SIZE}), mode 0600, mkswap, swapon, one /etc/fstab line
- write ${SSHD_DROPIN} with PermitRootLogin no, run sshd -t, reload ssh only if the effective value is no
Refresh note: ranges are fetched when this script runs, from
  ${CLOUDFLARE_IPV4_URL}
  ${CLOUDFLARE_IPV6_URL}
Re-run the script to refresh. It does not schedule a refresh.
Rollback: ufw disable; remove ${SSHD_DROPIN} and reload ssh; swapoff ${SWAP_FILE}, delete it, and remove its /etc/fstab line.
A wrong /32 locks out new SSH. The Lightsail console can run: ufw disable
EOF
}

apply_ufw() {
  local cidr=$1
  shift
  local range
  if ! command -v ufw >/dev/null 2>&1; then
    if ! command -v apt-get >/dev/null 2>&1; then
      echo "ufw is not installed and apt-get is not available. No firewall change was made." >&2
      return 1
    fi
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y ufw
  fi
  echo "Resetting ufw. Current SSH sessions can stay up. New SSH is allowed only from ${cidr}. If that address is wrong, open the Lightsail console and run: ufw disable"
  if ! ufw --force reset \
    || ! ufw default deny incoming \
    || ! ufw default allow outgoing \
    || ! ufw allow from "$cidr" to any port 22 proto tcp comment 'grc-admin-ssh'; then
    ufw disable || true
    echo "ufw setup failed before Cloudflare rules. Ran ufw disable so SSH is not left on a partial policy. The Lightsail firewall is unchanged." >&2
    return 1
  fi
  for range in "$@"; do
    if ! ufw allow from "$range" to any port 80 proto tcp comment 'grc-cloudflare-http' \
      || ! ufw allow from "$range" to any port 443 proto tcp comment 'grc-cloudflare-https'; then
      ufw disable || true
      echo "ufw setup failed while adding Cloudflare ranges. Ran ufw disable. The Lightsail firewall is unchanged." >&2
      return 1
    fi
  done
  if ! ufw --force enable; then
    ufw disable || true
    echo "ufw enable failed. Ran ufw disable. The Lightsail firewall is unchanged." >&2
    return 1
  fi
}

apply_swap() {
  local active=0 kind
  if [[ -L "$SWAP_FILE" ]]; then
    echo "Refusing a symlink at ${SWAP_FILE}." >&2
    return 1
  fi
  if [[ -e "$SWAP_FILE" && ! -f "$SWAP_FILE" ]]; then
    echo "Refusing ${SWAP_FILE} because it is not a regular file." >&2
    return 1
  fi
  if swapon --show=NAME --noheadings | grep -Fxq -- "$SWAP_FILE"; then
    active=1
  fi
  if [[ "$active" -eq 0 ]]; then
    if [[ -e "$SWAP_FILE" ]]; then
      kind=$(blkid -o value -s TYPE -- "$SWAP_FILE" 2>/dev/null || true)
      if [[ "$kind" != "swap" ]]; then
        echo "Refusing to overwrite ${SWAP_FILE}. It is not an existing swap signature." >&2
        return 1
      fi
      chmod 0600 "$SWAP_FILE"
      swapon -- "$SWAP_FILE"
    else
      if ! fallocate -l "$SWAP_SIZE" "$SWAP_FILE"; then
        dd if=/dev/zero of="$SWAP_FILE" bs=1M count=1024 status=none
      fi
      chmod 0600 "$SWAP_FILE"
      mkswap "$SWAP_FILE"
      swapon -- "$SWAP_FILE"
    fi
  fi
  chmod 0600 "$SWAP_FILE"
  if [[ ! -f /etc/fstab || -L /etc/fstab ]]; then
    echo "Refusing to edit /etc/fstab." >&2
    return 1
  fi
  if ! grep -Eq '^[[:space:]]*/swapfile[[:space:]]' /etc/fstab; then
    printf '%s\n' '/swapfile none swap sw 0 0' >> /etc/fstab
  fi
}

apply_sshd_no_root() {
  local config=/etc/ssh/sshd_config
  local dir effective
  if [[ ! -f "$config" || -L "$config" ]]; then
    echo "Refusing to change sshd because ${config} is missing or a symlink." >&2
    return 1
  fi
  if ! grep -Eq '^[[:space:]]*Include[[:space:]]+/etc/ssh/sshd_config\.d/\*\.conf[[:space:]]*$' "$config"; then
    echo "Refusing to add a drop-in because ${config} does not include /etc/ssh/sshd_config.d/*.conf on its own line." >&2
    return 1
  fi
  dir=$(dirname -- "$SSHD_DROPIN")
  if [[ ! -d "$dir" || -L "$dir" ]]; then
    echo "Refusing to write ${SSHD_DROPIN} because ${dir} is missing or a symlink." >&2
    return 1
  fi
  if [[ -L "$SSHD_DROPIN" ]]; then
    echo "Refusing to write sshd config through a symlink." >&2
    return 1
  fi
  printf '%s\n' '# Managed by infra/harden-lightsail-host.sh. Rollback: remove this file and reload ssh.' 'PermitRootLogin no' > "$SSHD_DROPIN"
  chmod 0644 "$SSHD_DROPIN"
  if ! sshd -t; then
    rm -f -- "$SSHD_DROPIN"
    echo "sshd -t failed. Removed ${SSHD_DROPIN} and did not reload ssh." >&2
    return 1
  fi
  effective=$(sshd -T | awk '$1 == "permitrootlogin" { print $2; exit }')
  if [[ "$effective" != "no" ]]; then
    rm -f -- "$SSHD_DROPIN"
    echo "Effective PermitRootLogin is '${effective:-unknown}', not no. sshd keeps the first value it sees, so this drop-in did not win. Removed it and did not reload ssh." >&2
    return 1
  fi
  if ! systemctl reload ssh; then
    if ! systemctl reload sshd; then
      echo "sshd config is valid and PermitRootLogin no is effective, and the reload failed. Existing sessions were left as they were." >&2
      return 1
    fi
  fi
}

main() {
  local ranges_text range
  local -a ranges=()
  if ! parse_harden_args "$@"; then
    exit 1
  fi
  if [[ "$HARDEN_SHOW_HELP" -eq 1 ]]; then
    usage
    exit 0
  fi
  if ! ranges_text=$(fetch_cloudflare_ranges); then
    exit 1
  fi
  while IFS= read -r range || [[ -n "${range-}" ]]; do
    [[ -z "$range" ]] && continue
    ranges+=("$range")
  done <<< "$ranges_text"
  if [[ "${#ranges[@]}" -eq 0 ]]; then
    echo "Cloudflare range list was empty. No firewall change was made." >&2
    exit 1
  fi
  print_planned_changes "$HARDEN_CIDR" "${ranges[@]}"
  if [[ "$HARDEN_DRY_RUN" -eq 1 ]]; then
    echo "Dry run only. No changes were made."
    exit 0
  fi
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "Run this script as root to apply the plan above. No changes were made." >&2
    exit 1
  fi
  apply_ufw "$HARDEN_CIDR" "${ranges[@]}"
  apply_swap
  apply_sshd_no_root
  echo "Host hardening applied. SSH is limited to ${HARDEN_CIDR}. Rollback steps are in the header comment and docs/deployment.md."
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
