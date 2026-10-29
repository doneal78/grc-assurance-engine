"""Offline checks for the optional Lightsail host-hardening script."""

import os
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARDEN = ROOT / "infra" / "harden-lightsail-host.sh"
BOOTSTRAP = ROOT / "infra" / "lightsail-bootstrap.sh"
DEPLOY = ROOT / "infra" / "deploy-app-revision.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-lightsail.yml"
ATTRIBUTES = ROOT / ".gitattributes"
ADMIN = "203.0.113.10/32"


def _run(script, env=None):
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        ["bash", "-c", script],
        cwd=ROOT,
        env=merged,
        text=True,
        capture_output=True,
        check=False,
    )


def _source(call, env=None):
    return _run(f"source infra/harden-lightsail-host.sh; {call}", env=env)


def test_harden_script_has_valid_bash_syntax_and_lf_endings():
    result = subprocess.run(
        ["bash", "-n", str(HARDEN)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    for path in (ROOT / "infra").glob("*.sh"):
        data = path.read_bytes()
        assert b"\r" not in data, path.name
    attributes = ATTRIBUTES.read_text(encoding="utf-8")
    assert "*.sh text eol=lf" in attributes


def test_admin_cidr_is_required_and_must_be_one_ipv4_host():
    missing = _source("require_admin_cidr")
    assert missing.returncode != 0
    assert "without it" in missing.stderr.lower() or "/32" in missing.stderr

    accepted = _source(f"require_admin_cidr {shlex.quote(ADMIN)}")
    assert accepted.returncode == 0, accepted.stderr
    assert accepted.stdout.strip() == ADMIN

    for rejected in (
        "",
        "203.0.113.10",
        "203.0.113.10/24",
        "203.0.113.10/0",
        "0.0.0.0/0",
        "203.0.113.10/32/32",
        "999.1.2.3/32",
        "01.2.3.4/32",
        "203.0.113.10/32 ",
        "grc-assurance.davidoneal.dev/32",
        "2001:db8::1/128",
        "203.0.113.10/32;id",
    ):
        result = _source(f"require_admin_cidr {shlex.quote(rejected)}")
        assert result.returncode != 0, rejected
        assert "ufw " not in result.stdout


def test_parse_harden_args_refuses_to_plan_without_the_admin_host():
    dry_missing = _source("parse_harden_args --dry-run")
    assert dry_missing.returncode != 0

    bare = _source("parse_harden_args")
    assert bare.returncode != 0

    dry = _source(
        "parse_harden_args --dry-run "
        + shlex.quote(ADMIN)
        + '; printf "%s %s\\n" "$HARDEN_DRY_RUN" "$HARDEN_CIDR"'
    )
    assert dry.returncode == 0, dry.stderr
    assert dry.stdout.strip() == f"1 {ADMIN}"

    apply = _source(
        "parse_harden_args "
        + shlex.quote(ADMIN)
        + '; printf "%s %s\\n" "$HARDEN_DRY_RUN" "$HARDEN_CIDR"'
    )
    assert apply.returncode == 0, apply.stderr
    assert apply.stdout.strip() == f"0 {ADMIN}"

    two = _source(f"parse_harden_args {ADMIN} 198.51.100.4/32")
    assert two.returncode != 0

    help_result = _source('parse_harden_args --help; printf "%s\\n" "$HARDEN_SHOW_HELP"')
    assert help_result.returncode == 0, help_result.stderr
    assert help_result.stdout.strip() == "1"


def test_cloudflare_ranges_reject_the_world_and_shell_metacharacters():
    good = _source(
        "printf '%s\\n' '173.245.48.0/20' '2606:4700::/32' '# comment' | read_cloudflare_ranges"
    )
    assert good.returncode == 0, good.stderr
    assert good.stdout.splitlines() == ["173.245.48.0/20", "2606:4700::/32"]

    for line in ("0.0.0.0/0", "::/0", "173.245.48.0/20; ufw allow 22", "999.1.1.1/20", "not-a-range"):
        result = _source(
            f"printf '%s\\n' {shlex.quote(line)} | read_cloudflare_ranges"
        )
        assert result.returncode != 0, line
        assert line not in result.stdout or ";" in line and line not in result.stdout


def test_dry_run_lists_the_plan_and_does_not_apply_it(tmp_path):
    log = tmp_path / "called.log"
    log_q = shlex.quote(str(log))
    script = f"""
source infra/harden-lightsail-host.sh
fetch_cloudflare_ranges() {{ printf '%s\\n' '173.245.48.0/20' '2606:4700::/32'; }}
ufw() {{ printf '%s\\n' "ufw $*" >> {log_q}; }}
apply_swap() {{ printf '%s\\n' swap >> {log_q}; }}
apply_sshd_no_root() {{ printf '%s\\n' sshd >> {log_q}; }}
main --dry-run {shlex.quote(ADMIN)}
"""
    result = _run(script)
    assert result.returncode == 0, result.stderr
    assert "Dry run only. No changes were made." in result.stdout
    assert "ufw default deny incoming" in result.stdout
    assert f"ufw allow from {ADMIN} to any port 22 proto tcp" in result.stdout
    assert "ufw allow from 173.245.48.0/20 to any port 80 proto tcp" in result.stdout
    assert "ufw allow from 173.245.48.0/20 to any port 443 proto tcp" in result.stdout
    assert "ufw allow from 2606:4700::/32 to any port 443 proto tcp" in result.stdout
    assert "PermitRootLogin no" in result.stdout
    assert "1 GiB" in result.stdout
    assert "SWAP_SIZE=1G" not in result.stdout or "1G" in result.stdout
    assert "https://www.cloudflare.com/ips-v4" in result.stdout
    assert "https://www.cloudflare.com/ips-v6" in result.stdout
    assert "Re-run the script to refresh" in result.stdout
    assert "Rollback:" in result.stdout
    assert "ufw disable" in result.stdout
    assert not log.exists()


def test_apply_without_root_and_without_a_cidr_changes_nothing(tmp_path):
    log = tmp_path / "called.log"
    log_q = shlex.quote(str(log))
    no_root = _run(
        f"""
source infra/harden-lightsail-host.sh
fetch_cloudflare_ranges() {{ printf '%s\\n' '173.245.48.0/20'; }}
ufw() {{ printf '%s\\n' "ufw $*" >> {log_q}; }}
apply_swap() {{ printf '%s\\n' swap >> {log_q}; }}
apply_sshd_no_root() {{ printf '%s\\n' sshd >> {log_q}; }}
main {shlex.quote(ADMIN)}
"""
    )
    assert no_root.returncode != 0
    assert "No changes were made." in no_root.stderr
    assert "ufw default deny incoming" in no_root.stdout
    assert not log.exists()

    no_cidr = _run(
        f"""
source infra/harden-lightsail-host.sh
fetch_cloudflare_ranges() {{ printf '%s\\n' fetched >> {log_q}; exit 1; }}
ufw() {{ printf '%s\\n' ufw >> {log_q}; }}
main --dry-run
"""
    )
    assert no_cidr.returncode != 0
    assert not log.exists()


def test_hardening_is_not_invoked_by_bootstrap_deploy_or_actions():
    assert "harden-lightsail-host.sh" not in BOOTSTRAP.read_text(encoding="utf-8")
    assert "harden-lightsail-host.sh" not in DEPLOY.read_text(encoding="utf-8")
    assert "harden-lightsail-host.sh" not in WORKFLOW.read_text(encoding="utf-8")
    text = HARDEN.read_text(encoding="utf-8")
    assert "PermitRootLogin no" in text
    assert "default deny incoming" in text
    assert "SWAP_SIZE=1G" in text
    assert "Nothing in this repository" in text or "not lightsail-bootstrap.sh" in text
