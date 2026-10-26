"""Offline checks for the app-revision deploy script and the manual workflow."""

import io
import os
import shlex
import shutil
import sqlite3
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "infra" / "deploy-app-revision.sh"
BOOTSTRAP = ROOT / "infra" / "lightsail-bootstrap.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-lightsail.yml"
DEPLOYMENT_DOC = ROOT / "docs" / "deployment.md"
SHA_A = "a" * 40
SHA_B = "b" * 40
NGINX_SITE = "server { server_name grc-assurance.davidoneal.dev; }\n"


def _run(script, env=None):
    merged = os.environ.copy()
    merged.pop("GRC_REVISION", None)
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


def _source_deploy(call, env=None):
    return _run(f"source infra/deploy-app-revision.sh; {call}", env=env)


def _tarball(path: Path, files: dict[str, str], prefix: str = "repo-sha") -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name, content in files.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name=f"{prefix}/{name}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


def _app_and_database(tmp_path: Path):
    app = tmp_path / "grc-assurance-engine"
    app.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    database = data / "grc_assurance.sqlite3"
    database.write_bytes(b"")
    backup = data / "backups" / f"grc_assurance-20261026T211500Z-{SHA_A}.sqlite3"
    return app, database, backup


def test_deploy_script_has_valid_bash_syntax():
    result = subprocess.run(
        ["bash", "-n", str(DEPLOY)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_require_revision_accepts_a_full_sha_and_refuses_branches():
    padded = _source_deploy(
        f"require_revision {shlex.quote('  ' + SHA_A.upper() + chr(10))}"
    )
    assert padded.returncode == 0, padded.stderr
    assert padded.stdout.strip() == SHA_A

    for rejected in ("main", "3218061", "g" * 40, "a" * 39, "a" * 41, "../etc/passwd", "a" * 20 + " " + "b" * 20, ""):
        result = _source_deploy(f"require_revision {shlex.quote(rejected)}")
        assert result.returncode != 0, rejected
        if rejected.strip():
            assert rejected.strip().lower() not in result.stdout.lower()
        assert "branch" in result.stderr.lower() or "sha" in result.stderr.lower()


def test_parse_deploy_args_requires_a_sha_and_defaults_nginx_off():
    from_flag = _source_deploy(
        "parse_deploy_args --update-nginx --revision "
        + shlex.quote(SHA_A.upper())
        + "; printf '%s %s\\n' \"$DEPLOY_REVISION\" \"$DEPLOY_UPDATE_NGINX\""
    )
    assert from_flag.returncode == 0, from_flag.stderr
    assert from_flag.stdout.strip() == f"{SHA_A} 1"

    from_env = _source_deploy(
        "parse_deploy_args; printf '%s %s\\n' \"$DEPLOY_REVISION\" \"$DEPLOY_UPDATE_NGINX\"",
        env={"GRC_REVISION": SHA_A},
    )
    assert from_env.returncode == 0, from_env.stderr
    assert from_env.stdout.strip() == f"{SHA_A} 0"

    override = _source_deploy(
        f"parse_deploy_args --revision {SHA_B}; printf '%s\\n' \"$DEPLOY_REVISION\"",
        env={"GRC_REVISION": SHA_A},
    )
    assert override.returncode == 0, override.stderr
    assert override.stdout.strip() == SHA_B

    help_result = _source_deploy("parse_deploy_args --help; printf '%s\\n' \"$DEPLOY_SHOW_HELP\"")
    assert help_result.returncode == 0, help_result.stderr
    assert help_result.stdout.strip() == "1"

    for call in (
        "parse_deploy_args",
        "parse_deploy_args --revision",
        f"parse_deploy_args --revision {SHA_A} --revision {SHA_B}",
        f"parse_deploy_args --revision {SHA_A} --force",
        "parse_deploy_args --revision main",
        f"parse_deploy_args {SHA_A}",
        "parse_deploy_args --revision --update-nginx",
    ):
        result = _source_deploy(call, env={"GRC_REVISION": "main"})
        assert result.returncode != 0, call
        assert SHA_A not in result.stdout


def test_parse_deploy_args_does_not_read_the_pin_file(tmp_path):
    pin = tmp_path / "grc-assurance-revision"
    pin.write_text(SHA_B + "\n", encoding="utf-8")
    result = _source_deploy(
        f"PIN_FILE={shlex.quote(str(pin))} parse_deploy_args; printf '%s\\n' \"$DEPLOY_REVISION\""
    )
    assert result.returncode != 0
    assert SHA_B not in result.stdout
    assert pin.read_text(encoding="utf-8") == SHA_B + "\n"


def test_service_account_name_refuses_root_and_shell_metacharacters():
    for name in ("ubuntu", "grc-assurance"):
        result = _source_deploy(f"assert_service_account_name {shlex.quote(name)}")
        assert result.returncode == 0, result.stderr
    for name in ("root", "", "ubuntu;id", "../ubuntu", "Ubuntu", "grc assurance"):
        result = _source_deploy(f"assert_service_account_name {shlex.quote(name)}")
        assert result.returncode != 0


def test_auth_env_refuses_enabled_gate_without_printing_a_password(tmp_path):
    missing = tmp_path / "absent.env"
    assert _source_deploy(
        f"auth_env_is_consistent {shlex.quote(str(missing))}"
    ).returncode == 0

    closed = tmp_path / "closed.env"
    closed.write_text("REQUIRE_AUTH=false\n", encoding="utf-8")
    assert _source_deploy(
        f"auth_env_is_consistent {shlex.quote(str(closed))}"
    ).returncode == 0

    commented = tmp_path / "comment.env"
    commented.write_text("# REQUIRE_AUTH=true\n", encoding="utf-8")
    assert _source_deploy(
        f"auth_env_is_consistent {shlex.quote(str(commented))}"
    ).returncode == 0

    ready = tmp_path / "ready.env"
    ready.write_text(
        "REQUIRE_AUTH=true\nDEMO_USERNAME=demo\nDEMO_PASSWORD=synthetic-demo-password\n",
        encoding="utf-8",
    )
    ready_result = _source_deploy(f"auth_env_is_consistent {shlex.quote(str(ready))}")
    assert ready_result.returncode == 0, ready_result.stderr
    assert "synthetic-demo-password" not in ready_result.stdout
    assert "synthetic-demo-password" not in ready_result.stderr

    for body in (
        "REQUIRE_AUTH=true\nDEMO_USERNAME=demo\n",
        "REQUIRE_AUTH=true\nDEMO_USERNAME=demo\nDEMO_PASSWORD=\n",
        'REQUIRE_AUTH=true\nDEMO_USERNAME=demo\nDEMO_PASSWORD=""\n',
    ):
        env_file = tmp_path / "broken.env"
        env_file.write_text(body, encoding="utf-8")
        result = _source_deploy(f"auth_env_is_consistent {shlex.quote(str(env_file))}")
        assert result.returncode != 0
        assert "synthetic" not in result.stderr
        assert "PASSWORD" in result.stderr


def test_safe_paths_keep_the_database_outside_the_app_tree(tmp_path):
    app, database, backup = _app_and_database(tmp_path)
    allowed = _source_deploy(
        "assert_safe_deploy_paths "
        f"{shlex.quote(str(app))} {shlex.quote(str(database))} {shlex.quote(str(backup))}"
    )
    assert allowed.returncode == 0, allowed.stderr

    inside = app / "instance" / "grc_assurance.sqlite3"
    inside.parent.mkdir()
    inside.write_bytes(b"do-not-use")
    refused_db = _source_deploy(
        "assert_safe_deploy_paths "
        f"{shlex.quote(str(app))} {shlex.quote(str(inside))} {shlex.quote(str(backup))}"
    )
    assert refused_db.returncode != 0
    assert "app tree" in refused_db.stderr.lower()
    assert inside.read_bytes() == b"do-not-use"

    wrong_name = tmp_path / "other-name"
    wrong_name.mkdir()
    refused_name = _source_deploy(
        "assert_safe_deploy_paths "
        f"{shlex.quote(str(wrong_name))} {shlex.quote(str(database))} {shlex.quote(str(backup))}"
    )
    assert refused_name.returncode != 0
    assert "name is not grc-assurance-engine" in refused_name.stderr

    live = _source_deploy(
        "assert_safe_deploy_paths "
        f"{shlex.quote(str(app))} {shlex.quote(str(database))} {shlex.quote(str(database))}"
    )
    assert live.returncode != 0
    assert "live database" in live.stderr.lower()
    assert database.read_bytes() == b""

    relative = _source_deploy(
        "assert_safe_deploy_paths "
        f"{shlex.quote(str(app))} {shlex.quote(str(database))} backups/copy.sqlite3"
    )
    assert relative.returncode != 0

    dotted = str(database.parent / "backups") + "/../grc_assurance.sqlite3"
    refused_dot = _source_deploy(
        "assert_safe_deploy_paths "
        f"{shlex.quote(str(app))} {shlex.quote(str(database))} {shlex.quote(dotted)}"
    )
    assert refused_dot.returncode != 0
    assert "segments" in refused_dot.stderr.lower()

    spaced = str(backup) + " copy"
    refused_space = _source_deploy(
        "assert_safe_deploy_paths "
        f"{shlex.quote(str(app))} {shlex.quote(str(database))} {shlex.quote(spaced)}"
    )
    assert refused_space.returncode != 0

    (app / "stolen").mkdir()
    (database.parent / "backups").symlink_to(app, target_is_directory=True)
    stolen = database.parent / "backups" / "x.sqlite3"
    refused_link = _source_deploy(
        "assert_safe_deploy_paths "
        f"{shlex.quote(str(app))} {shlex.quote(str(database))} {shlex.quote(str(stolen))}"
    )
    assert refused_link.returncode != 0
    assert "app tree" in refused_link.stderr.lower()
    assert not (app / "x.sqlite3").exists()
    assert database.read_bytes() == b""


def test_safe_paths_refuse_an_app_directory_outside_the_allowed_prefixes(tmp_path):
    allowed_tmp = tmp_path / "allowed-temp"
    allowed_tmp.mkdir()
    fixture_root = ROOT / ".deploy-refusal-fixture"
    outside = fixture_root / "grc-assurance-engine"
    fixture_root.mkdir()
    outside.mkdir()
    marker = outside / "keep.py"
    marker.write_text("keep", encoding="utf-8")
    database = tmp_path / "data" / "grc_assurance.sqlite3"
    database.parent.mkdir()
    database.write_bytes(b"keep-register")
    backup = database.parent / "backups" / "copy.sqlite3"
    try:
        refused = _source_deploy(
            "assert_safe_deploy_paths "
            f"{shlex.quote(str(outside))} {shlex.quote(str(database))} {shlex.quote(str(backup))}",
            env={"TMPDIR": str(allowed_tmp)},
        )
        assert refused.returncode != 0
        assert "outside" in refused.stderr.lower()
        assert marker.read_text(encoding="utf-8") == "keep"
        assert database.read_bytes() == b"keep-register"
    finally:
        if fixture_root.is_dir() and fixture_root.parent == ROOT and fixture_root.name == ".deploy-refusal-fixture":
            shutil.rmtree(fixture_root)


def test_backup_destination_shape_and_online_backup_keeps_the_source(tmp_path):
    shaped = _source_deploy(
        f"backup_destination /var/lib/grc-assurance/ {SHA_A} 20261026T211500Z"
    )
    assert shaped.returncode == 0, shaped.stderr
    assert shaped.stdout.strip() == (
        f"/var/lib/grc-assurance/backups/grc_assurance-20261026T211500Z-{SHA_A}.sqlite3"
    )
    bad_stamp = _source_deploy(
        f"backup_destination /var/lib/grc-assurance {SHA_A} yesterday"
    )
    assert bad_stamp.returncode != 0
    bad_revision = _source_deploy(
        "backup_destination /var/lib/grc-assurance main 20261026T211500Z"
    )
    assert bad_revision.returncode != 0
    assert "archive/main" not in bad_revision.stdout

    app, database, backup = _app_and_database(tmp_path)
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE saved (id INTEGER)")
    connection.execute("INSERT INTO saved VALUES (7)")
    connection.commit()
    connection.close()
    backup.parent.mkdir()
    copied = _source_deploy(
        "backup_sqlite_online "
        f"{shlex.quote(str(app))} {shlex.quote(str(database))} {shlex.quote(str(backup))}"
    )
    assert copied.returncode == 0, copied.stderr
    assert backup.is_file()
    copy = sqlite3.connect(backup)
    assert copy.execute("SELECT id FROM saved").fetchone() == (7,)
    copy.close()
    original = sqlite3.connect(database)
    assert original.execute("SELECT id FROM saved").fetchone() == (7,)
    original.close()

    again = _source_deploy(
        "backup_sqlite_online "
        f"{shlex.quote(str(app))} {shlex.quote(str(database))} {shlex.quote(str(backup))}"
    )
    assert again.returncode != 0
    assert "already exists" in again.stderr.lower()
    original = sqlite3.connect(database)
    assert original.execute("SELECT id FROM saved").fetchone() == (7,)
    original.close()


def test_preflight_paths_require_an_existing_tree_venv_and_database(tmp_path):
    app = tmp_path / "grc-assurance-engine"
    database = tmp_path / "data" / "grc_assurance.sqlite3"
    missing = _source_deploy(
        f"preflight_paths {shlex.quote(str(app))} {shlex.quote(str(database))}"
    )
    assert missing.returncode != 0

    app.mkdir()
    no_venv = _source_deploy(
        f"preflight_paths {shlex.quote(str(app))} {shlex.quote(str(database))}"
    )
    assert no_venv.returncode != 0
    assert "virtualenv" in no_venv.stderr.lower()

    pip = app / ".venv" / "bin" / "pip"
    pip.parent.mkdir(parents=True)
    pip.write_text("#!/bin/sh\n", encoding="utf-8")
    pip.chmod(0o755)
    no_db = _source_deploy(
        f"preflight_paths {shlex.quote(str(app))} {shlex.quote(str(database))}"
    )
    assert no_db.returncode != 0
    assert "does not create or delete" in no_db.stderr

    database.parent.mkdir()
    database.write_bytes(b"keep")
    ready = _source_deploy(
        f"preflight_paths {shlex.quote(str(app))} {shlex.quote(str(database))}"
    )
    assert ready.returncode == 0, ready.stderr
    assert database.read_bytes() == b"keep"


def test_health_response_requires_status_ok_and_database_reachable():
    ok = '{"status": "ok", "service": "grc-assurance-engine", "database": "reachable"}'
    result = _source_deploy(f"health_response_acceptable {shlex.quote(ok)}")
    assert result.returncode == 0, result.stderr

    extra = '{"database":"reachable","status":"ok","rule_set":"illustrative"}'
    assert _source_deploy(f"health_response_acceptable {shlex.quote(extra)}").returncode == 0

    unreachable = '{"status":"ok","database":"unreachable"}'
    unreachable_result = _source_deploy(
        f"health_response_acceptable {shlex.quote(unreachable)}"
    )
    assert unreachable_result.returncode == 3

    unavailable = '{"status":"unavailable","database":"reachable"}'
    assert _source_deploy(
        f"health_response_acceptable {shlex.quote(unavailable)}"
    ).returncode == 1

    for body in (
        "",
        "not json",
        '["status","ok"]',
        'not json "status":"ok" "database":"reachable"',
        '{"status":"ok"}',
    ):
        assert _source_deploy(
            f"health_response_acceptable {shlex.quote(body)}"
        ).returncode != 0


def test_release_tarball_member_and_nginx_destination(tmp_path):
    archive = tmp_path / "app.tar.gz"
    _tarball(archive, {
        "requirements.txt": "flask\n",
        "infra/nginx-site.conf": NGINX_SITE,
        "app/nested/requirements.txt": "nope\n",
    })
    requirements = _source_deploy(
        f"release_tarball_member {shlex.quote(str(archive))} requirements.txt"
    )
    assert requirements.returncode == 0, requirements.stderr
    assert requirements.stdout.strip() == "repo-sha/requirements.txt"

    github_name = f"grc-assurance-engine-{SHA_A}"
    github_archive = tmp_path / "github.tar.gz"
    _tarball(github_archive, {"requirements.txt": "flask\n", "infra/nginx-site.conf": NGINX_SITE}, prefix=github_name)
    github_member = _source_deploy(
        f"release_tarball_member {shlex.quote(str(github_archive))} requirements.txt"
    )
    assert github_member.returncode == 0, github_member.stderr
    assert github_member.stdout.strip() == f"{github_name}/requirements.txt"

    extracted = tmp_path / "nginx.conf"
    nginx = _source_deploy(
        "extract_tarball_member "
        f"{shlex.quote(str(archive))} infra/nginx-site.conf {shlex.quote(str(extracted))}"
    )
    assert nginx.returncode == 0, nginx.stderr
    assert extracted.read_text(encoding="utf-8") == NGINX_SITE
    assert _source_deploy(
        f"assert_nginx_site_source {shlex.quote(str(extracted))}"
    ).returncode == 0

    wrong = tmp_path / "other.conf"
    wrong.write_text("server { server_name _; }\n", encoding="utf-8")
    refused_source = _source_deploy(f"assert_nginx_site_source {shlex.quote(str(wrong))}")
    assert refused_source.returncode != 0

    allowed_dest = _source_deploy(
        "assert_nginx_site_destination /etc/nginx/sites-available/grc-assurance-engine"
    )
    assert allowed_dest.returncode == 0, allowed_dest.stderr
    for dest in (
        "/etc/nginx/sites-enabled/grc-assurance-engine",
        "/tmp/grc-assurance-engine",
        "/etc/nginx/sites-available/other",
    ):
        refused_dest = _source_deploy(f"assert_nginx_site_destination {shlex.quote(dest)}")
        assert refused_dest.returncode != 0

    empty = tmp_path / "empty.tar.gz"
    _tarball(empty, {"README.md": "no requirements\n"})
    missing = _source_deploy(
        f"release_tarball_member {shlex.quote(str(empty))} requirements.txt"
    )
    assert missing.returncode != 0

    doubled = tmp_path / "two.tar.gz"
    with tarfile.open(doubled, "w:gz") as handle:
        for prefix in ("one", "two"):
            data = b"flask\n"
            info = tarfile.TarInfo(name=f"{prefix}/requirements.txt")
            info.size = len(data)
            handle.addfile(info, io.BytesIO(data))
    two = _source_deploy(f"release_tarball_member {shlex.quote(str(doubled))} requirements.txt")
    assert two.returncode != 0

    url = _source_deploy(f"tarball_url_for_revision {SHA_A.upper()}")
    assert url.returncode == 0, url.stderr
    assert url.stdout.strip() == (
        "https://github.com/doneal78/grc-assurance-engine/archive/" + SHA_A + ".tar.gz"
    )
    refused_url = _source_deploy("tarball_url_for_revision main")
    assert refused_url.returncode != 0
    assert "archive/main" not in refused_url.stdout


def test_record_deployed_revision_writes_the_bootstrap_pin_path(tmp_path):
    assert _source_deploy("assert_bootstrap_paths").returncode == 0
    pin = tmp_path / "grc-assurance-revision"
    recorded = _source_deploy(
        f"record_deployed_revision {shlex.quote(SHA_A.upper())} {shlex.quote(str(pin))}"
    )
    assert recorded.returncode == 0, recorded.stderr
    assert pin.read_text(encoding="utf-8") == SHA_A + "\n"

    pin.write_text("keep\n", encoding="utf-8")
    refused = _source_deploy(
        f"record_deployed_revision main {shlex.quote(str(pin))}"
    )
    assert refused.returncode != 0
    assert pin.read_text(encoding="utf-8") == "keep\n"

    target = tmp_path / "target"
    target.write_text("keep\n", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(target)
    through_link = _source_deploy(
        f"record_deployed_revision {SHA_A} {shlex.quote(str(link))}"
    )
    assert through_link.returncode != 0
    assert "symlink" in through_link.stderr.lower()
    assert target.read_text(encoding="utf-8") == "keep\n"
    assert link.is_symlink()


def test_deploy_script_is_a_lighter_path_than_bootstrap():
    text = DEPLOY.read_text(encoding="utf-8")
    bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
    assert 'source "${_DEPLOY_SCRIPT_DIR}/lightsail-bootstrap.sh"' in text
    assert "replace_app_tree" in text
    assert ".backup" in text
    assert "/etc/grc-assurance-revision" in text
    assert "DEPLOYED_COMMIT" not in text
    assert 'chown -R "$running_user:$running_user" "$APP_DIR"' in text
    assert 'chown -R "$running_user:$running_user" "$DATA_DIR"' not in text
    assert "rm -rf" not in text
    assert "apt-get" not in text
    assert "useradd" not in text
    assert "daemon-reload" not in text
    assert "/etc/systemd/system/grc-assurance-engine.service" not in text
    assert "--update-nginx" in text
    assert "http://127.0.0.1:8000/health" in text
    assert "PIN_FILE=/etc/grc-assurance-revision" in bootstrap
    assert "deploy-app-revision.sh" in bootstrap


def test_deploy_workflow_is_manual_and_fails_closed_without_secrets():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "pull_request" not in text
    for line in text.splitlines():
        stripped = line.strip()
        assert not stripped.startswith("push:")
        assert stripped != "pull_request:"
    assert "secrets.LIGHTSAIL_SSH_KEY" in text
    assert "secrets.LIGHTSAIL_HOST" in text
    assert "secrets.LIGHTSAIL_KNOWN_HOSTS" in text
    assert "Missing repository secret LIGHTSAIL_SSH_KEY" in text
    assert "BEGIN OPENSSH PRIVATE KEY" not in text
    assert "BEGIN RSA PRIVATE KEY" not in text
    assert "require_revision" in text
    assert "sudo --non-interactive" in text
    assert "update_nginx" in text


def test_deployment_doc_describes_the_script_and_the_remaining_gaps():
    text = DEPLOYMENT_DOC.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "no automated deployment pipeline" not in lowered
    assert "infra/deploy-app-revision.sh" in text
    assert "workflow_dispatch" in text
    assert "LIGHTSAIL_SSH_KEY" in text
    assert "LIGHTSAIL_HOST" in text
    assert "LIGHTSAIL_KNOWN_HOSTS" in text
    assert "/etc/grc-assurance-revision" in text
    assert "REQUIRE_AUTH" in text
    assert "snapshot" in lowered
    assert "highly available" in lowered or "no second host" in lowered
    assert "--update-nginx" in text
    assert "lightsail-bootstrap.sh" in text
