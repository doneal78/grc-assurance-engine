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
    assert backup.stat().st_mode & 0o777 == 0o600
    assert backup.parent.stat().st_mode & 0o777 == 0o700
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


def test_tarball_cleanup_runs_after_the_function_returns(tmp_path):
    """EXIT cleanup must not read a name that was local to the function."""
    directory = tmp_path / "has space"
    directory.mkdir()
    returned = directory / "after-return.tar.gz"
    exited = directory / "after-exit.tar.gz"
    returned.write_bytes(b"return-path")
    exited.write_bytes(b"exit-path")
    returned_q = shlex.quote(str(returned))
    exited_q = shlex.quote(str(exited))

    after_return = _run(
        "source infra/deploy-app-revision.sh\n"
        "arm_and_return() {\n"
        f"  local tarball={returned_q}\n"
        '  arm_tarball_cleanup "$tarball"\n'
        "}\n"
        "arm_and_return\n"
        'if [[ -z "${CLEANUP_TAR_FILE:-}" ]]; then\n'
        '  echo "cleanup path was lost after return" >&2\n'
        "  exit 2\n"
        "fi\n"
        'if [[ "$CLEANUP_TAR_FILE" != ' + returned_q + " ]]; then\n"
        '  echo "cleanup path changed after return" >&2\n'
        "  exit 3\n"
        "fi\n"
        "exit 0\n"
    )
    assert after_return.returncode == 0, after_return.stderr
    assert "unbound variable" not in after_return.stderr
    assert not returned.exists()

    after_exit = _run(
        "source infra/deploy-app-revision.sh\n"
        "arm_and_exit() {\n"
        f"  local tarball={exited_q}\n"
        '  arm_tarball_cleanup "$tarball"\n'
        "  exit 0\n"
        "}\n"
        "arm_and_exit\n"
    )
    assert after_exit.returncode == 0, after_exit.stderr
    assert "unbound variable" not in after_exit.stderr
    assert not exited.exists()

    missing = _source_deploy("arm_tarball_cleanup")
    assert missing.returncode != 0
    assert "without a path" in missing.stderr


def test_bootstrap_installs_the_sqlite3_cli_and_neither_script_traps_a_local():
    deploy = DEPLOY.read_text(encoding="utf-8")
    bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
    assert 'arm_tarball_cleanup "$tarball"' in deploy
    assert 'arm_tarball_cleanup "$tarball"' in bootstrap
    assert "CLEANUP_TAR_FILE" in bootstrap
    assert 'trap \'rm -f -- "$tarball"\' EXIT' not in deploy
    assert 'trap \'rm -f -- "$tarball"\' EXIT' not in bootstrap
    install_lines = [line.strip() for line in bootstrap.splitlines() if "apt-get install" in line]
    assert any(line.split().count("sqlite3") == 1 for line in install_lines)
    assert "sqlite3 is not installed" in deploy
    assert ".backup" in deploy


def test_deploy_script_is_a_lighter_path_than_bootstrap():
    text = DEPLOY.read_text(encoding="utf-8")
    bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
    assert 'source "${_DEPLOY_SCRIPT_DIR}/lightsail-bootstrap.sh"' in text
    assert "replace_app_tree" in text
    assert ".backup" in text
    assert "/etc/grc-assurance-revision" in text
    assert "DEPLOYED_COMMIT" not in text
    assert "apply_runtime_ownership" in text
    assert 'chown -R "$running_user:$running_user" "$APP_DIR"' not in text
    assert 'chown -R "$running_user:$running_user" "$DATA_DIR"' not in text
    assert "BACKUP_KEEP" in text
    assert "prune_sqlite_backups" in text
    main = text.split("\nmain() {", 1)[1]
    assert main.index("backup_sqlite_online") < main.index("prune_sqlite_backups") < main.index("replace_app_tree")
    assert main.index("apply_runtime_ownership") < main.index('systemctl restart "$UNIT_NAME"')
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
    assert "8dcfea2139ba86134697fe83fb4f64734e3155ce" in text
    assert "does not skip the backup" in text
    assert "unbound variable" in text
    assert "sqlite3" in text
    assert "2026-10-27" in text
    assert "grc-assurance-restore-drill-202610271020" in text
    assert "257a67e4f2e2245b6f15e9775fa6181d78f93e85" in text
    assert "da9329c2aed979fcf6465392b9b4393fa03e7421" in text
    assert "The owner states" in text
    assert "did not SSH" in text
    assert "4af28b7302340baec080c1f34156ef8b35b1f0b2" in text
    assert "2026-10-29" in text
    assert "except for comments" in text
    assert "valid until 2041" in text
    assert "Certbot is not used, by design." in text
    assert "There is no swap" in text
    assert "exited 141" in text
    assert "administrator `/32`" in text
    assert "Lightsail console" in text
    assert "BACKUP_KEEP" in text
    assert "defaults to 14" in text
    assert "does not delete those loose copies" in text
    assert "harden-lightsail-host.sh" in text
    assert "PermitRootLogin no" in text
    assert "Nothing in this repository runs it" in text
    assert "has not been executed" not in text
    assert "still untested" not in text
    assert "not installed yet" not in text


def _mode(path: Path) -> int:
    return path.stat().st_mode & 0o7777


def test_backup_keep_count_reads_the_environment():
    default = _source_deploy("unset BACKUP_KEEP; backup_keep_count")
    assert default.returncode == 0, default.stderr
    assert default.stdout.strip() == "14"

    zero = _source_deploy("backup_keep_count", env={"BACKUP_KEEP": "0"})
    assert zero.returncode == 0, zero.stderr
    assert zero.stdout.strip() == "0"

    padded = _source_deploy("backup_keep_count", env={"BACKUP_KEEP": "014"})
    assert padded.returncode == 0, padded.stderr
    assert padded.stdout.strip() == "14"

    for bad in ("-1", "14.5", "nope", "9999999", "14 "):
        result = _source_deploy("backup_keep_count", env={"BACKUP_KEEP": bad})
        assert result.returncode != 0, bad
        assert "BACKUP_KEEP" in result.stderr


def _backup_name(day: int, sha: str = SHA_A) -> str:
    return f"grc_assurance-202610{day:02d}T010000Z-{sha}.sqlite3"


def test_prune_keeps_the_newest_and_never_deletes_the_backup_just_made(tmp_path):
    backups = tmp_path / "backups"
    backups.mkdir()
    parent_copy = tmp_path / _backup_name(3)
    parent_copy.write_text("loose", encoding="utf-8")
    loose_inside = backups / "grc_assurance-copy.sqlite3"
    loose_inside.write_text("not-the-pattern", encoding="utf-8")
    notes = backups / "notes.txt"
    notes.write_text("keep", encoding="utf-8")
    target = tmp_path / "symlink-target.sqlite3"
    target.write_text("target", encoding="utf-8")
    link = backups / _backup_name(2, SHA_B)
    link.symlink_to(target)
    written = {}
    for day in range(1, 21):
        path = backups / _backup_name(day)
        path.write_text(str(day), encoding="utf-8")
        written[day] = path
    newest = written[20]
    oldest = written[1]

    kept = _source_deploy(
        "prune_sqlite_backups "
        f"{shlex.quote(str(backups))} 14 {shlex.quote(str(newest))}"
    )
    assert kept.returncode == 0, kept.stderr
    names = {path.name for path in backups.iterdir()}
    for day in range(7, 21):
        assert _backup_name(day) in names
    for day in range(1, 7):
        assert _backup_name(day) not in names
    regular = {
        path.name
        for path in backups.iterdir()
        if path.is_symlink() is False and path.name.startswith("grc_assurance-2026")
    }
    assert regular == {_backup_name(day) for day in range(7, 21)}
    assert loose_inside.read_text(encoding="utf-8") == "not-the-pattern"
    assert notes.read_text(encoding="utf-8") == "keep"
    assert parent_copy.read_text(encoding="utf-8") == "loose"
    assert link.is_symlink()
    assert target.read_text(encoding="utf-8") == "target"

    again = _source_deploy(
        "prune_sqlite_backups "
        f"{shlex.quote(str(backups))} 14 {shlex.quote(str(newest))}"
    )
    assert again.returncode == 0, again.stderr
    assert {path.name for path in backups.iterdir()} == names

    for day in range(1, 7):
        written[day].write_text(str(day), encoding="utf-8")
    preserved = _source_deploy(
        "prune_sqlite_backups "
        f"{shlex.quote(str(backups))} 1 {shlex.quote(str(oldest))}"
    )
    assert preserved.returncode == 0, preserved.stderr
    assert oldest.read_text(encoding="utf-8") == "1"
    assert newest.read_text(encoding="utf-8") == "20"
    assert not written[10].exists()

    only_new = _source_deploy(
        "prune_sqlite_backups "
        f"{shlex.quote(str(backups))} 0 {shlex.quote(str(newest))}"
    )
    assert only_new.returncode == 0, only_new.stderr
    assert newest.read_text(encoding="utf-8") == "20"
    assert not oldest.exists()
    assert loose_inside.exists()
    assert parent_copy.exists()
    assert link.is_symlink()
    assert target.read_text(encoding="utf-8") == "target"


def test_prune_refuses_paths_that_are_not_the_backup_directory(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    live = data / "grc_assurance.sqlite3"
    live.write_text("live", encoding="utf-8")
    stray = data / _backup_name(1)
    stray.write_text("stray", encoding="utf-8")
    refused = _source_deploy(
        "prune_sqlite_backups "
        f"{shlex.quote(str(data))} 1 {shlex.quote(str(stray))}"
    )
    assert refused.returncode != 0
    assert "not backups" in refused.stderr
    assert live.read_text(encoding="utf-8") == "live"
    assert stray.read_text(encoding="utf-8") == "stray"

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    victim = elsewhere / "victim"
    victim.write_text("victim", encoding="utf-8")
    linked = tmp_path / "backups"
    linked.symlink_to(elsewhere, target_is_directory=True)
    refused_link = _source_deploy(f"prune_sqlite_backups {shlex.quote(str(linked))} 0")
    assert refused_link.returncode != 0
    assert victim.read_text(encoding="utf-8") == "victim"
    assert linked.is_symlink()

    real_backups = tmp_path / "real" / "backups"
    real_backups.mkdir(parents=True)
    sample = real_backups / _backup_name(4)
    sample.write_text("sample", encoding="utf-8")
    bad = _source_deploy(
        "prune_sqlite_backups "
        f"{shlex.quote(str(real_backups))} nope {shlex.quote(str(sample))}"
    )
    assert bad.returncode != 0
    assert sample.read_text(encoding="utf-8") == "sample"


def test_runtime_ownership_is_idempotent_and_limits_writes(tmp_path):
    user = subprocess.check_output(["id", "-un"], text=True).strip()
    group = subprocess.check_output(["id", "-gn"], text=True).strip()
    app = tmp_path / "grc-assurance-engine"
    (app / "app").mkdir(parents=True)
    source = app / "app" / "demo.py"
    source.write_text("print('ok')\n", encoding="utf-8")
    source.chmod(0o777)
    venv_bin = app / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    gunicorn = venv_bin / "gunicorn"
    gunicorn.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    gunicorn.chmod(0o777)
    real_python = tmp_path / "python-real"
    real_python.write_text("#!/bin/sh\n", encoding="utf-8")
    real_python.chmod(0o700)
    (venv_bin / "python").symlink_to(real_python)
    instance = app / "instance"
    instance.mkdir()
    secret = instance / "sandbox_secret"
    secret.write_text("secret-value", encoding="utf-8")
    secret.chmod(0o644)
    data = tmp_path / "data"
    data.mkdir()
    database = data / "grc_assurance.sqlite3"
    database.write_text("db", encoding="utf-8")
    wal = data / "grc_assurance.sqlite3-wal"
    wal.write_text("wal", encoding="utf-8")
    loose = data / "loose-copy.sqlite3"
    loose.write_text("loose", encoding="utf-8")
    loose.chmod(0o644)
    backups = data / "backups"
    backups.mkdir()
    backup = backups / f"grc_assurance-20261029T000000Z-{SHA_A}.sqlite3"
    backup.write_text("backup", encoding="utf-8")
    backup.chmod(0o644)
    log = tmp_path / "chown.log"
    result = _run(
        "source infra/lightsail-bootstrap.sh\n"
        "chown() { printf '%s\\n' \"$*\" >> "
        + shlex.quote(str(log))
        + "; }\n"
        "apply_runtime_ownership "
        f"{shlex.quote(str(app))} {shlex.quote(str(data))} {shlex.quote(user)}\n"
        "apply_runtime_ownership "
        f"{shlex.quote(str(app))} {shlex.quote(str(data))} {shlex.quote(user)}\n"
    )
    assert result.returncode == 0, result.stderr
    assert _mode(source) == 0o644
    assert _mode(gunicorn) == 0o755
    assert _mode(app) == 0o755
    assert _mode(real_python) == 0o700
    assert (venv_bin / "python").is_symlink()
    assert secret.read_text(encoding="utf-8") == "secret-value"
    assert _mode(secret) == 0o600
    assert _mode(instance) == 0o750
    assert _mode(data) == 0o1770
    assert _mode(database) == 0o600
    assert database.read_text(encoding="utf-8") == "db"
    assert _mode(wal) == 0o600
    assert wal.read_text(encoding="utf-8") == "wal"
    assert _mode(backups) == 0o700
    assert _mode(backup) == 0o600
    assert backup.read_text(encoding="utf-8") == "backup"
    assert loose.read_text(encoding="utf-8") == "loose"
    assert _mode(loose) == 0o644
    logged = log.read_text(encoding="utf-8")
    assert f"root:root -- {source}" in logged
    assert f"root:root -- {gunicorn}" in logged
    assert f"root:{group} -- {data}" in logged
    assert f"{user}:{group} -- {database}" in logged
    assert f"{user}:{group} -- {wal}" in logged
    assert f"{user}:{group} -- {instance}" in logged
    assert f"root:root -- {backup}" in logged
    assert "loose-copy.sqlite3" not in logged
    assert "python-real" not in logged


def test_runtime_ownership_refuses_unsafe_paths_before_changing_modes(tmp_path):
    user = subprocess.check_output(["id", "-un"], text=True).strip()
    app = tmp_path / "grc-assurance-engine"
    app.mkdir()
    marker = app / "keep.py"
    marker.write_text("keep", encoding="utf-8")
    marker.chmod(0o777)
    inside = app / "data"
    refused_inside = _run(
        "source infra/lightsail-bootstrap.sh\n"
        "chown() { return 0; }\n"
        "apply_runtime_ownership "
        f"{shlex.quote(str(app))} {shlex.quote(str(inside))} {shlex.quote(user)}"
    )
    assert refused_inside.returncode != 0
    assert "inside the app tree" in refused_inside.stderr
    assert _mode(marker) == 0o777

    refused_root = _run(
        "source infra/lightsail-bootstrap.sh\n"
        "apply_runtime_ownership "
        f"{shlex.quote(str(app))} {shlex.quote(str(tmp_path / 'data'))} root"
    )
    assert refused_root.returncode != 0
    assert "root" in refused_root.stderr.lower()
    assert _mode(marker) == 0o777

    link = app / "instance"
    link.symlink_to(tmp_path, target_is_directory=True)
    refused_link = _run(
        "source infra/lightsail-bootstrap.sh\n"
        "chown() { return 0; }\n"
        "apply_runtime_ownership "
        f"{shlex.quote(str(app))} {shlex.quote(str(tmp_path / 'safe-data'))} {shlex.quote(user)}"
    )
    assert refused_link.returncode != 0
    assert "symlink" in refused_link.stderr.lower()
    assert _mode(marker) == 0o777
    assert link.is_symlink()
