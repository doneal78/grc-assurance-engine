"""Bootstrap revision pin, stale-tree cleanup, and the repo Nginx limits."""

import io
import os
import shlex
import shutil
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "infra" / "lightsail-bootstrap.sh"
NGINX = ROOT / "infra" / "nginx-site.conf"
SHA_A = "a" * 40
SHA_B = "b" * 40


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


def _source(call, env=None):
    return _run(f"source infra/lightsail-bootstrap.sh; {call}", env=env)


def _tarball(path: Path, files: dict[str, str]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name, content in files.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name=f"repo-sha/{name}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


def test_bootstrap_script_has_valid_bash_syntax():
    result = subprocess.run(
        ["bash", "-n", str(BOOTSTRAP)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_bootstrap_unit_uses_the_dedicated_account_and_leaves_auth_off():
    text = BOOTSTRAP.read_text(encoding="utf-8")
    assert "User=${SERVICE_USER}" in text or "User=grc-assurance" in text
    assert "SERVICE_USER=grc-assurance" in text
    assert "Environment=REQUIRE_AUTH=false" in text
    assert "DATABASE_PATH=${DATA_DIR}/grc_assurance.sqlite3" in text
    assert "User=ubuntu" not in text
    assert "/var/lib/grc-assurance" in text


def test_resolve_revision_requires_a_full_sha_and_prefers_the_environment(tmp_path):
    pin = tmp_path / "installed-revision"
    pin.write_text(SHA_B + "\n", encoding="utf-8")
    quoted = shlex.quote(str(pin))

    from_env = _source(f"resolve_revision {quoted}", env={"GRC_REVISION": SHA_A.upper()})
    assert from_env.returncode == 0, from_env.stderr
    assert from_env.stdout.strip() == SHA_A

    from_pin = _source(f"resolve_revision {quoted}")
    assert from_pin.returncode == 0, from_pin.stderr
    assert from_pin.stdout.strip() == SHA_B

    padded = tmp_path / "padded-revision"
    padded.write_text("  " + SHA_A + "\n", encoding="utf-8")
    padded_result = _source(f"resolve_revision {shlex.quote(str(padded))}")
    assert padded_result.returncode == 0
    assert padded_result.stdout.strip() == SHA_A

    for rejected in ("main", "3218061", "g" * 40):
        result = _source(f"resolve_revision {quoted}", env={"GRC_REVISION": rejected})
        assert result.returncode != 0
        assert SHA_B not in result.stdout
        assert "branch" in result.stderr.lower() or "SHA" in result.stderr

    missing = _source(f"resolve_revision {shlex.quote(str(tmp_path / 'absent'))}")
    assert missing.returncode != 0


def test_replace_app_tree_removes_stale_files_and_keeps_runtime_data(tmp_path):
    app = tmp_path / "grc-assurance-engine"
    (app / "oldpkg").mkdir(parents=True)
    (app / "oldpkg" / "stale.py").write_text("old", encoding="utf-8")
    (app / "requirements.txt").write_text("old\n", encoding="utf-8")
    (app / ".venv").mkdir()
    (app / ".venv" / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
    (app / "instance").mkdir()
    (app / "instance" / "local.sqlite3").write_bytes(b"keep-instance")
    outside = tmp_path / "data" / "grc_assurance.sqlite3"
    outside.parent.mkdir()
    outside.write_bytes(b"keep-register")

    tarball = tmp_path / "app.tar.gz"
    _tarball(tarball, {
        "requirements.txt": "flask\n",
        "app/new.py": "new\n",
        ".gitignore": "instance/\n",
    })
    result = _source(
        "replace_app_tree "
        f"{shlex.quote(str(app))} {shlex.quote(str(tarball))}"
    )
    assert result.returncode == 0, result.stderr
    assert not (app / "oldpkg").exists()
    assert (app / "app" / "new.py").read_text(encoding="utf-8") == "new\n"
    assert (app / "requirements.txt").read_text(encoding="utf-8") == "flask\n"
    assert (app / ".gitignore").read_text(encoding="utf-8") == "instance/\n"
    assert (app / ".venv" / "pyvenv.cfg").read_text(encoding="utf-8") == "home = /usr\n"
    assert (app / "instance" / "local.sqlite3").read_bytes() == b"keep-instance"
    assert outside.read_bytes() == b"keep-register"


def test_replace_app_tree_installs_into_an_empty_directory(tmp_path):
    app = tmp_path / "grc-assurance-engine"
    app.mkdir()
    tarball = tmp_path / "app.tar.gz"
    _tarball(tarball, {"requirements.txt": "flask\n", "run.py": "print('ok')\n"})
    result = _source(
        "replace_app_tree "
        f"{shlex.quote(str(app))} {shlex.quote(str(tarball))}"
    )
    assert result.returncode == 0, result.stderr
    assert (app / "run.py").read_text(encoding="utf-8") == "print('ok')\n"
    assert not (app / ".venv").exists()
    assert not (app / "instance").exists()


def test_replace_app_tree_refuses_a_bad_tarball_without_deleting_files(tmp_path):
    app = tmp_path / "grc-assurance-engine"
    app.mkdir()
    (app / "keep.py").write_text("keep", encoding="utf-8")
    (app / ".venv").mkdir()
    (app / ".venv" / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
    tarball = tmp_path / "bad.tar.gz"
    _tarball(tarball, {"README.md": "no requirements\n"})
    result = _source(
        "replace_app_tree "
        f"{shlex.quote(str(app))} {shlex.quote(str(tarball))}"
    )
    assert result.returncode != 0
    assert (app / "keep.py").read_text(encoding="utf-8") == "keep"
    assert (app / ".venv" / "pyvenv.cfg").is_file()

    garbage = tmp_path / "garbage.tar.gz"
    garbage.write_bytes(b"not a tarball")
    failed = _source(
        "replace_app_tree "
        f"{shlex.quote(str(app))} {shlex.quote(str(garbage))}"
    )
    assert failed.returncode != 0
    assert (app / "keep.py").read_text(encoding="utf-8") == "keep"
    assert (app / ".venv" / "pyvenv.cfg").is_file()


def test_replace_app_tree_refuses_an_unexpected_path(tmp_path):
    app = tmp_path / "other-name"
    app.mkdir()
    (app / "keep.py").write_text("keep", encoding="utf-8")
    tarball = tmp_path / "app.tar.gz"
    _tarball(tarball, {"requirements.txt": "flask\n"})
    result = _source(
        "replace_app_tree "
        f"{shlex.quote(str(app))} {shlex.quote(str(tarball))}"
    )
    assert result.returncode != 0
    assert "name is not grc-assurance-engine" in result.stderr
    assert (app / "keep.py").read_text(encoding="utf-8") == "keep"
    assert not (app / "requirements.txt").exists()

    # Correct directory name, but the resolved path is outside the prefixes
    # the script allows. The call site is a symlink under tmp_path. TMPDIR is
    # narrowed so a checkout that lives under /tmp is still refused. This does
    # not depend on a fixed host directory such as /workspace.
    allowed = tmp_path / "allowed-temp"
    allowed.mkdir()
    fixture_root = ROOT / ".replace-refusal-fixture"
    outside = fixture_root / "grc-assurance-engine"
    fixture_root.mkdir()
    outside.mkdir()
    marker = outside / "keep.py"
    marker.write_text("keep", encoding="utf-8")
    link = tmp_path / "grc-assurance-engine"
    link.symlink_to(outside, target_is_directory=True)
    try:
        refused = _source(
            "replace_app_tree "
            f"{shlex.quote(str(link))} {shlex.quote(str(tarball))}",
            env={"TMPDIR": str(allowed)},
        )
        assert refused.returncode != 0
        assert "outside" in refused.stderr.lower()
        assert marker.read_text(encoding="utf-8") == "keep"
        assert not (outside / "requirements.txt").exists()
        assert link.is_symlink()
    finally:
        if fixture_root.is_dir() and fixture_root.parent == ROOT and fixture_root.name == ".replace-refusal-fixture":
            shutil.rmtree(fixture_root)


def test_nginx_limits_api_like_try_and_leaves_the_site_limit():
    text = NGINX.read_text(encoding="utf-8")
    assert "zone=try_per_visitor:10m rate=20r/m" in text
    assert "zone=api_per_visitor:10m rate=20r/m" in text
    assert "zone=api_total:1m rate=5r/s" in text
    assert "zone=site_per_visitor:10m rate=120r/m" in text
    assert "location /api/" in text
    assert "limit_req zone=api_per_visitor burst=10 nodelay;" in text
    assert "location /api/" in text
    api_block = text.split("location /api/", 1)[1].split("location /", 1)[0]
    assert "zone=site_per_visitor" not in api_block
    assert "live host" in text.lower() or "repository file does not change the live host" in text
