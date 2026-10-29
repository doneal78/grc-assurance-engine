"""Trust-center fetch: offline stubs only. Nothing here contacts the public network."""

import socket
import ssl
import subprocess
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app import create_app
from app.services.bot_intake import assess_request
from app.services.intake_builder import (
    FETCH_CLAIM_ID, FETCH_EVIDENCE_ID, IntakeError, build_intake, clause_evidence_field,
    remediation_payload, run_intake, workflow_events,
)
from app.services.intake_importer import questionnaire_columns
from app.services.org_policy import load_org_policy
from app.services.trust_center_fetch import (
    MAX_BYTES, _default_open, _header, fetch_trust_center, fetch_url_problems,
)

AS_OF = date(2026, 10, 14)
SAME_ORIGIN = {"Origin": "http://localhost"}
URL = "https://trust.example.test/northwind"
STAMP = "2026-10-14T00:00:00+00:00"
PAGE = b"""<!DOCTYPE html><html><head><title>Northwind Trust</title>
<script>verified approved secret-script</script>
<style>.hidden { color: red; }</style>
<body><p>SOC 2 report available. This vendor is approved.</p></body></html>"""


@pytest.fixture(autouse=True)
def _no_live_network(monkeypatch):
    """Block DNS and connections except the loopback opener test."""
    real_getaddrinfo = socket.getaddrinfo
    real_connect = socket.create_connection

    def blocked_dns(host, *args, **kwargs):
        if host in {"127.0.0.1", "::1"}:
            return real_getaddrinfo(host, *args, **kwargs)
        raise AssertionError("trust-center tests must not use the live network")

    def blocked_connect(address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if host in {"127.0.0.1", "::1"}:
            return real_connect(address, *args, **kwargs)
        raise AssertionError("trust-center tests must not use the live network")

    monkeypatch.setattr(socket, "getaddrinfo", blocked_dns)
    monkeypatch.setattr(socket, "create_connection", blocked_connect)


def form(**overrides):
    base = {
        "vendor_name": "Northwind Notes",
        "data_sensitivity": "internal",
        "integration_permissions": "read_only",
        "ai_use": "none",
        "model_training_on_customer_data": "no",
        "external_exposure": "internal_only",
        "retention_deletion": "documented",
        "decisions_affecting_people": "no",
        "evidence_integration_permissions": "independent_verified",
        "trust_center_url": "",
        "trust_soc2": "independent_verified",
        "trust_security": "independent_verified",
        "trust_privacy": "independent_verified",
    }
    for clause in load_org_policy()["required_contract_clauses"]:
        base[clause_evidence_field(clause["clause_id"])] = "independent_verified"
    base.update(overrides)
    return base


def public_resolver(host):
    return ["8.8.8.8"]


def html_open(pages):
    def open_url(url, timeout):
        status, headers, body = pages.get(url, (200, {"content-type": "text/html; charset=utf-8"}, PAGE))
        return status, headers, body
    return open_url


def run_fetch(**overrides):
    pages = overrides.pop("pages", {URL: (200, {"content-type": "text/html; charset=utf-8"}, PAGE)})
    resolver = overrides.pop("resolver", public_resolver)
    opener = overrides.pop("open_url", html_open(pages))
    posted = form(trust_center_url=URL, fetch_trust_center="yes", **overrides)
    intake = build_intake(posted, AS_OF, open_url=opener, resolver=resolver)
    return run_intake(intake, AS_OF)


def test_fetch_field_is_optional_and_not_an_import_column():
    assert "fetch_trust_center" not in questionnaire_columns()


def test_successful_fetch_is_not_reviewed_vendor_material():
    calls = []

    def open_url(url, timeout):
        calls.append((url, timeout))
        return 200, {"content-type": "text/html; charset=utf-8"}, PAGE

    result = run_fetch(open_url=open_url)
    fetch = result["trust_center"]["fetch"]
    artifact = result["trust_center"]["artifact"]
    assert calls == [(URL, 8)]
    assert result["trust_center"]["fetched"] is True
    assert result["trust_center"]["collection"] == "http_get"
    assert result["trust_center"]["url"] == URL
    assert fetch["outcome"] == "retrieved"
    assert fetch["fetched_at"] == STAMP
    assert fetch["http_status"] == 200
    assert fetch["source"] == "vendor"
    assert fetch["evidence_status"] == "not_reviewed"
    assert fetch["evidence_id"] == FETCH_EVIDENCE_ID
    assert "Northwind Trust" in fetch["summary"]
    assert "SOC 2 report available" in fetch["excerpt"]
    assert "secret-script" not in fetch["excerpt"]
    assert "approved" in fetch["excerpt"]
    assert artifact["evidence_status"] == "not_reviewed"
    assert artifact["claim_id"] == FETCH_CLAIM_ID
    item = artifact["evidence"][0]
    assert item["status"] == "not_reviewed"
    assert item["source"] == "vendor"
    assert item["artifact_type"] == "vendor_statement"
    assert item["trust_center_url"] == URL
    assert item["fetched_at"] == STAMP
    assert "approved" in item["excerpt"]
    assert item["status"] != "verified"
    assert "fetch_claim" not in result["trust_center"]
    assert "fetch_evidence" not in result["trust_center"]
    assert FETCH_TOPIC_ABSENT(result)
    assert result["risk"]["review_path"] == "standard_review"


def FETCH_TOPIC_ABSENT(result):
    return all(claim["topic"] != "trust_center_page" for claim in result["claims"])


def test_fetched_page_does_not_change_the_score_or_approve():
    baseline = run_intake(build_intake(form(trust_center_url=URL), AS_OF), AS_OF)
    fetched = run_fetch()
    assert [claim["evidence_status"] for claim in fetched["claims"]] == [
        claim["evidence_status"] for claim in baseline["claims"]
    ]
    assert fetched["risk"]["evidence_confidence"] == baseline["risk"]["evidence_confidence"]
    assert fetched["risk"]["residual"] == baseline["risk"]["residual"]
    assert fetched["risk"]["inherent"] == baseline["risk"]["inherent"]
    assert {item["control_id"] for item in fetched["mappings"]} == {
        item["control_id"] for item in baseline["mappings"]
    }
    assert remediation_payload(fetched) is None
    package_claims = {claim["topic"] for claim in fetched["claims"]}
    assert "trust_center_page" not in package_claims
    assert fetched["trust_center"]["artifact"]["evidence_status"] == "not_reviewed"


def test_fetch_with_no_other_evidence_does_not_verify_a_claim():
    result = run_fetch(
        evidence_integration_permissions="none",
        trust_soc2="none",
        trust_security="none",
        trust_privacy="none",
        **{clause_evidence_field("CC-001"): "none"},
    )
    assert {claim["evidence_status"] for claim in result["claims"]} == {"missing"}
    assert result["trust_center"]["fetch"]["evidence_status"] == "not_reviewed"
    assert result["risk"]["policy_outcome"]["status"] == "not_prohibited"
    assert all(pointer["evidence_ids"] == [] for pointer in result["trust_center"]["pointers"])


@pytest.mark.parametrize("status", [404, 500])
def test_http_error_is_an_evidence_gap(status):
    result = run_fetch(pages={URL: (status, {"content-type": "text/html"}, b"missing")})
    fetch = result["trust_center"]["fetch"]
    assert result["trust_center"]["fetched"] is False
    assert result["trust_center"]["collection"] == "fetch_failed"
    assert fetch["outcome"] == "failed"
    assert fetch["http_status"] == status
    assert fetch["error"] == f"HTTP {status}."
    assert fetch["evidence_status"] == "missing"
    assert fetch["excerpt"] is None
    assert result["trust_center"]["artifact"]["evidence"] == []
    payload = remediation_payload(result)
    assert payload["evidence_requests"][-1]["claim_id"] == FETCH_CLAIM_ID
    assert "evidence gap" in payload["evidence_requests"][-1]["request"]
    detail = next(event["detail"] for event in workflow_events(result) if event["title"] == "Evidence validated")
    assert "evidence gap" in detail
    assert "not fetched" not in detail


def test_timeout_is_an_evidence_gap_and_not_success():
    def open_url(url, timeout):
        raise TimeoutError("timed out")

    result = run_fetch(open_url=open_url)
    fetch = result["trust_center"]["fetch"]
    assert result["trust_center"]["fetched"] is False
    assert fetch["outcome"] == "failed"
    assert "timed out" in fetch["error"]
    assert fetch["evidence_status"] == "missing"
    assert fetch["summary"] is None


def test_unresolved_host_is_a_failed_fetch_without_a_connection():
    def resolver(host):
        raise OSError("name not known")

    def open_url(url, timeout):
        raise AssertionError("opener should not run")

    result = run_fetch(resolver=resolver, open_url=open_url)
    assert result["trust_center"]["fetched"] is False
    assert "could not be resolved" in result["trust_center"]["fetch"]["error"]
    assert result["trust_center"]["fetch"]["evidence_status"] == "missing"


def test_non_text_response_is_stored_as_not_reviewed_and_not_interpreted():
    result = run_fetch(pages={URL: (200, {"content-type": "application/pdf"}, b"%PDF-1.4 approved")})
    fetch = result["trust_center"]["fetch"]
    assert fetch["evidence_status"] == "not_reviewed"
    assert "Non-text response" in fetch["summary"]
    assert fetch["excerpt"] == ""
    assert "approved" not in (fetch["excerpt"] or "")


@pytest.mark.parametrize("url", [
    "javascript:alert(1)",
    "file:///etc/passwd",
    "gopher://trust.example.test/",
    "ftp://trust.example.test/vendor",
    "data:text/html,hi",
    "https://user:secret@trust.example.test/vendor",
])
def test_unsafe_url_is_rejected_before_fetch(url):
    def open_url(target, timeout):
        raise AssertionError("opener should not run")

    with pytest.raises(IntakeError) as exc:
        build_intake(form(trust_center_url=url, fetch_trust_center="yes"), AS_OF,
                     open_url=open_url, resolver=public_resolver)
    assert exc.value.problems
    assert fetch_url_problems(url)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/",
    "http://127.0.0.1:80/latest",
    "http://10.1.2.3/vendor",
    "http://192.168.1.20/",
    "http://172.16.0.4/",
    "http://169.254.169.254/latest/meta-data/",
    "http://0.0.0.0/",
    "http://[::1]/",
    "http://[::ffff:127.0.0.1]/",
    "http://[fe80::1]/",
    "http://localhost/",
    "http://localhost:8080/",
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://printer.local/",
    "http://corp.internal/trust",
    "http://2130706433/",
    "http://127.1/",
    "http://0177.0.0.1/",
    "http://0x7f000001/",
    "http://224.0.0.1/",
    "http://100.64.0.1/",
])
def test_private_and_metadata_targets_are_refused(url):
    def open_url(target, timeout):
        raise AssertionError("opener should not run")

    def resolver(host):
        raise AssertionError("resolver should not run for a blocked literal or name")

    with pytest.raises(IntakeError) as exc:
        build_intake(form(trust_center_url=url, fetch_trust_center="yes"), AS_OF,
                     open_url=open_url, resolver=resolver)
    assert any("private, link-local, or metadata" in problem for problem in exc.value.problems)


def test_dns_to_a_private_address_is_refused_without_connecting():
    def resolver(host):
        assert host == "trust.example.test"
        return ["10.0.0.8", "169.254.169.254"]

    def open_url(url, timeout):
        raise AssertionError("opener should not run")

    with pytest.raises(IntakeError) as exc:
        build_intake(form(trust_center_url=URL, fetch_trust_center="yes"), AS_OF,
                     open_url=open_url, resolver=resolver)
    assert any("private, link-local, or metadata" in problem for problem in exc.value.problems)


def test_redirect_to_a_metadata_address_is_a_failed_fetch():
    calls = []

    def open_url(url, timeout):
        calls.append(url)
        if url == URL:
            return 302, {"location": "http://169.254.169.254/latest/meta-data/"}, b""
        raise AssertionError("redirect target should not be opened")

    result = run_fetch(open_url=open_url)
    assert calls == [URL]
    assert result["trust_center"]["fetched"] is False
    assert "redirect was refused" in result["trust_center"]["fetch"]["error"]
    assert result["trust_center"]["fetch"]["evidence_status"] == "missing"


def test_redirect_to_a_public_page_stores_the_final_url():
    final = "https://cdn.example.test/northwind"

    def open_url(url, timeout):
        if url == URL:
            return 302, {"Location": final}, b""
        return 200, {"content-type": "text/plain"}, b"Published security overview."

    result = run_fetch(open_url=open_url)
    fetch = result["trust_center"]["fetch"]
    assert result["trust_center"]["fetched"] is True
    assert fetch["final_url"] == final
    assert fetch["evidence_status"] == "not_reviewed"
    assert "security overview" in fetch["excerpt"]


def test_too_many_redirects_fail():
    def open_url(url, timeout):
        step = url.rsplit("/", 1)[-1]
        nxt = "0" if step == "northwind" else str(int(step) + 1)
        return 302, {"location": f"https://trust.example.test/{nxt}"}, b""

    result = run_fetch(open_url=open_url)
    assert result["trust_center"]["fetched"] is False
    assert "too many redirects" in result["trust_center"]["fetch"]["error"]


def test_paste_citation_still_skips_the_network():
    def open_url(url, timeout):
        raise AssertionError("paste path must not fetch")

    posted = form(trust_center_url=URL)
    result = run_intake(build_intake(posted, AS_OF, open_url=open_url, resolver=public_resolver), AS_OF)
    assert result["trust_center"]["fetched"] is False
    assert result["trust_center"]["collection"] == "pasted_metadata"
    assert result["trust_center"]["fetch"]["outcome"] == "not_requested"
    assert result["trust_center"]["artifact"] is None
    detail = next(event["detail"] for event in workflow_events(result) if event["title"] == "Evidence validated")
    assert "not fetched" in detail
    explicit = run_intake(build_intake(
        form(trust_center_url=URL, fetch_trust_center="no"), AS_OF, open_url=open_url), AS_OF)
    assert explicit["trust_center"]["fetched"] is False


def test_private_url_can_still_be_stored_when_fetch_is_not_requested():
    def open_url(url, timeout):
        raise AssertionError("paste path must not fetch")

    result = run_intake(build_intake(
        form(trust_center_url="http://127.0.0.1/trust", fetch_trust_center="no"),
        AS_OF, open_url=open_url), AS_OF)
    assert result["trust_center"]["url"] == "http://127.0.0.1/trust"
    assert result["trust_center"]["fetched"] is False


def test_fetch_yes_requires_a_url_and_rejects_unknown_choices():
    with pytest.raises(IntakeError) as missing:
        build_intake(form(fetch_trust_center="yes"), AS_OF)
    assert any("URL is required" in problem for problem in missing.value.problems)

    with pytest.raises(IntakeError) as bad:
        build_intake(form(fetch_trust_center="maybe"), AS_OF)
    assert any("choose yes or no" in problem for problem in bad.value.problems)


class _LocalPage(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/go":
            self.send_response(302)
            self.send_header("Location", "/landed")
            self.end_headers()
            return
        body = b"<title>Local</title><p>Hello review</p>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return


def test_default_opener_reads_loopback_and_does_not_follow_redirects():
    """The real HTTP opener, pointed only at 127.0.0.1. Not a public fetch."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _LocalPage)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, headers, body = _default_open(f"http://127.0.0.1:{port}/page", 2)
        assert status == 200
        assert b"Hello review" in body
        status, headers, body = _default_open(f"http://127.0.0.1:{port}/go", 2)
        assert status == 302
        assert _header(headers, "location") == "/landed"
        assert b"Hello review" not in body
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_public_ip_literal_is_allowed_and_a_public_name_needs_a_resolver():
    assert fetch_url_problems("https://8.8.8.8/trust") == []
    assert fetch_url_problems("https://trust.example.test/northwind") == []

    def open_url(url, timeout):
        return 200, {"content-type": "text/plain"}, b"literal page"

    fetched = fetch_trust_center("https://8.8.8.8/trust", open_url=open_url, clock=AS_OF_CLOCK())
    assert fetched["ok"] is True
    assert fetched["summary"] == "literal page"


def AS_OF_CLOCK():
    from datetime import datetime, time, timezone
    return datetime.combine(AS_OF, time.min, tzinfo=timezone.utc)


def test_bot_assess_uses_the_same_fetch_result():
    document = assess_request(
        {"contract_version": "1.0.0", "as_of": AS_OF.isoformat(),
         "form": form(trust_center_url=URL, fetch_trust_center="yes")},
        open_url=html_open({URL: (200, {"content-type": "text/html"}, PAGE)}),
        resolver=public_resolver,
    )
    assert document["automatic_approval"] is None
    assert document["human_review_required"] is True
    assert document["trust_center"]["fetched"] is True
    assert document["trust_center"]["fetch"]["evidence_status"] == "not_reviewed"
    assert "Northwind Trust" in document["trust_center"]["fetch"]["summary"]
    assert all(claim["evidence_status"] != "not_reviewed" or claim["topic"] != "trust_center_page"
               for claim in document["claims"])
    assert "trust_center_page" not in {claim["topic"] for claim in document["claims"]}

    pasted = assess_request(
        {"contract_version": "1.0.0", "as_of": AS_OF.isoformat(), "form": form(trust_center_url=URL)},
    )
    assert pasted["trust_center"]["fetched"] is False
    assert pasted["trust_center"]["fetch"]["outcome"] == "not_requested"


def test_public_form_shows_the_fetch_and_keeps_paste(monkeypatch, tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "fetch.sqlite3"), "REQUIRE_AUTH": False})
    client = app.test_client()

    def fake(url, **kwargs):
        return {
            "ok": True,
            "refused": False,
            "requested_url": url,
            "final_url": url,
            "http_status": 200,
            "fetched_at": STAMP,
            "content_type": "text/html",
            "summary": "Northwind Trust. SOC 2 report available.",
            "excerpt": "SOC 2 report available. This vendor is approved.",
            "byte_length": 64,
            "error": None,
        }

    monkeypatch.setattr("app.services.intake_builder.fetch_trust_center", fake)
    page = client.get("/try/")
    assert b"fetch_trust_center" in page.data
    assert b"does not open the page" in page.data
    posted = form(trust_center_url=URL, fetch_trust_center="yes")
    response = client.post("/try/assess", data=posted, headers=SAME_ORIGIN)
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Northwind Trust" in body
    assert "Not Reviewed" in body
    assert "This page is not verified evidence." in body
    assert "SOC 2 report available" in body
    pasted = client.post("/try/assess", data=form(trust_center_url=URL, fetch_trust_center="no"),
                         headers=SAME_ORIGIN)
    assert pasted.status_code == 200
    assert b"Fetched: no" in pasted.data


PIN_URL = "http://trust.example.test:8080/northwind"
BLOCKED_RESOLUTIONS = [
    "10.1.2.3",
    "172.16.0.4",
    "192.168.1.20",
    "127.0.0.1",
    "169.254.169.254",
    "0.0.0.0",
    "::1",
    "fe80::1",
    "fc00::1",
    "::ffff:127.0.0.1",
    "::ffff:10.0.0.1",
    "::ffff:169.254.169.254",
    "::ffff:0.0.0.0",
    "224.0.0.1",
    "ff02::1",
    "100.64.0.1",
    "240.0.0.1",
    "192.0.2.1",
]


class _ScriptedPage(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.seen.append({"host": self.headers.get("Host"), "path": self.path})
        status, headers, body = self.server.script.pop(0)
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, fmt, *args):
        return


def _start_page(script, *, certfile=None, keyfile=None):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ScriptedPage)
    server.script = list(script)
    server.seen = []
    if certfile is not None:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile, keyfile)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stop_page(server, thread):
    server.shutdown()
    thread.join(timeout=2)
    server.server_close()


def _script_dns(monkeypatch, plans):
    """Replace getaddrinfo. ``plans[host]`` is a queue of answers, each a list of IPs."""
    previous = socket.getaddrinfo
    queued = {host: [list(answer) if isinstance(answer, (list, tuple)) else [answer]
                     for answer in answers]
              for host, answers in plans.items()}

    def getaddrinfo(host, port, *args, **kwargs):
        if host in {"127.0.0.1", "::1"}:
            return previous(host, port, *args, **kwargs)
        if host not in queued or not queued[host]:
            raise AssertionError(f"unexpected DNS lookup for {host}")
        ips = queued[host].pop(0)
        return [
            (
                socket.AF_INET6 if ":" in ip else socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (ip, 0 if port is None else port),
            )
            for ip in ips
        ]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    return queued


def _redirect_pins(monkeypatch, allowed, local_port):
    """Record socket.connect targets. Dial only loopback, and only for an allowed pin."""
    recorded = []
    original = socket.socket.connect

    def connect(self, address):
        recorded.append(address)
        host = address[0]
        if host in allowed:
            return original(self, ("127.0.0.1", local_port))
        if host in {"127.0.0.1", "::1"}:
            return original(self, address)
        raise AssertionError(f"blocked connect to {address!r}")

    monkeypatch.setattr(socket.socket, "connect", connect)
    return recorded


def _issue_cert(directory, hostname):
    directory.mkdir(parents=True, exist_ok=True)
    ca_key = directory / "ca.key"
    ca_crt = directory / "ca.crt"
    leaf_key = directory / "leaf.key"
    leaf_csr = directory / "leaf.csr"
    leaf_crt = directory / "leaf.crt"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
         "-keyout", str(ca_key), "-out", str(ca_crt), "-days", "2",
         "-subj", "/CN=GRC Test CA",
         "-addext", "basicConstraints=critical,CA:TRUE",
         "-addext", "keyUsage=critical,keyCertSign,cRLSign"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["openssl", "req", "-newkey", "rsa:2048", "-nodes",
         "-keyout", str(leaf_key), "-out", str(leaf_csr),
         "-subj", f"/CN={hostname}",
         "-addext", f"subjectAltName=DNS:{hostname}",
         "-addext", "basicConstraints=CA:FALSE",
         "-addext", "keyUsage=digitalSignature,keyEncipherment",
         "-addext", "extendedKeyUsage=serverAuth"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["openssl", "x509", "-req", "-in", str(leaf_csr),
         "-CA", str(ca_crt), "-CAkey", str(ca_key), "-CAcreateserial",
         "-out", str(leaf_crt), "-days", "2", "-copy_extensions", "copy"],
        check=True, capture_output=True,
    )
    return ca_crt, leaf_crt, leaf_key


def _trust_test_ca(monkeypatch, ca_crt):
    real_context = ssl.create_default_context

    def context(*args, **kwargs):
        ctx = real_context(cafile=str(ca_crt))
        # Python 3.14 turns this on inside create_default_context. Force it
        # here so a certificate that would fail that default fails on 3.12 too.
        if hasattr(ssl, "VERIFY_X509_STRICT"):
            ctx.verify_flags |= ssl.VERIFY_X509_STRICT
        return ctx

    monkeypatch.setattr(ssl, "create_default_context", context)


def _record_sni(monkeypatch):
    names = []
    real_wrap = ssl.SSLContext.wrap_socket

    def wrap(self, sock, *args, server_hostname=None, **kwargs):
        if server_hostname is not None:
            names.append(server_hostname)
            assert self.check_hostname is True
            assert self.verify_mode == ssl.CERT_REQUIRED
        return real_wrap(self, sock, *args, server_hostname=server_hostname, **kwargs)

    monkeypatch.setattr(ssl.SSLContext, "wrap_socket", wrap)
    return names


def test_pinned_happy_path_keeps_the_host_header_and_the_timeout(monkeypatch):
    script = [(200, {"Content-Type": "text/html; charset=utf-8"}, PAGE)]
    server, thread = _start_page(script)
    plans = _script_dns(monkeypatch, {"trust.example.test": [["8.8.8.8"]]})
    connected = _redirect_pins(monkeypatch, {"8.8.8.8"}, server.server_address[1])
    try:
        result = fetch_trust_center(PIN_URL, clock=AS_OF_CLOCK())
    finally:
        _stop_page(server, thread)
    assert plans["trust.example.test"] == []
    assert connected == [("8.8.8.8", 8080)]
    assert server.seen == [{"host": "trust.example.test:8080", "path": "/northwind"}]
    assert result["ok"] is True
    assert result["refused"] is False
    assert result["http_status"] == 200
    assert result["final_url"] == PIN_URL
    assert "Northwind Trust" in result["summary"]
    assert "SOC 2 report available" in result["excerpt"]
    assert result["fetched_at"] == STAMP


def test_dns_rebinding_second_private_answer_is_not_connected(monkeypatch):
    """The check sees a public address. A later lookup would be private. The socket stays on the first."""
    script = [(200, {"Content-Type": "text/plain"}, b"Pinned public page")]
    server, thread = _start_page(script)
    plans = _script_dns(monkeypatch, {
        "trust.example.test": [["8.8.8.8"], ["169.254.169.254"]],
    })
    connected = _redirect_pins(monkeypatch, {"8.8.8.8"}, server.server_address[1])
    try:
        result = fetch_trust_center(PIN_URL, clock=AS_OF_CLOCK())
    finally:
        _stop_page(server, thread)
    assert result["ok"] is True
    assert result["summary"] == "Pinned public page"
    assert connected == [("8.8.8.8", 8080)]
    assert plans["trust.example.test"] == [["169.254.169.254"]]
    assert all(address[0] != "169.254.169.254" for address in connected)


def test_same_host_redirect_rebinds_to_a_private_address_and_is_blocked(monkeypatch):
    script = [(302, {"Location": "/next"}, b"")]
    server, thread = _start_page(script)
    plans = _script_dns(monkeypatch, {
        "trust.example.test": [["8.8.8.8"], ["10.0.0.9"]],
    })
    connected = _redirect_pins(monkeypatch, {"8.8.8.8"}, server.server_address[1])
    try:
        result = fetch_trust_center(PIN_URL, clock=AS_OF_CLOCK())
    finally:
        _stop_page(server, thread)
    assert plans["trust.example.test"] == []
    assert [address[0] for address in connected] == ["8.8.8.8"]
    assert result["ok"] is False
    assert result["refused"] is False
    assert "redirect was refused" in result["error"]
    assert "private, link-local, or metadata" in result["error"]


def test_redirect_to_a_private_host_is_blocked(monkeypatch):
    script = [(302, {"Location": "http://inside.example.test/latest"}, b"")]
    server, thread = _start_page(script)
    plans = _script_dns(monkeypatch, {
        "trust.example.test": [["8.8.8.8"]],
        "inside.example.test": [["169.254.169.254"]],
    })
    connected = _redirect_pins(monkeypatch, {"8.8.8.8"}, server.server_address[1])
    try:
        result = fetch_trust_center(PIN_URL, clock=AS_OF_CLOCK())
    finally:
        _stop_page(server, thread)
    assert plans["inside.example.test"] == []
    assert [address[0] for address in connected] == ["8.8.8.8"]
    assert result["ok"] is False
    assert result["refused"] is False
    assert "redirect was refused" in result["error"]
    assert server.seen == [{"host": "trust.example.test:8080", "path": "/northwind"}]


@pytest.mark.parametrize("address", BLOCKED_RESOLUTIONS)
def test_resolved_private_loopback_metadata_and_mapped_addresses_are_blocked(address, monkeypatch):
    attempted = []

    def connect(self, target):
        attempted.append(target)
        raise AssertionError(f"connected to {target!r}")

    monkeypatch.setattr(socket.socket, "connect", connect)

    def resolver(host):
        assert host == "trust.example.test"
        return [address]

    result = fetch_trust_center(URL, resolver=resolver, clock=AS_OF_CLOCK())
    assert attempted == []
    assert result["ok"] is False
    assert result["refused"] is True
    assert "private, link-local, or metadata" in result["error"]


def test_mixed_public_and_private_answers_do_not_connect(monkeypatch):
    attempted = []

    def connect(self, target):
        attempted.append(target)
        raise AssertionError(target)

    monkeypatch.setattr(socket.socket, "connect", connect)
    result = fetch_trust_center(
        URL,
        resolver=lambda host: ["8.8.8.8", "::ffff:169.254.169.254"],
        clock=AS_OF_CLOCK(),
    )
    assert attempted == []
    assert result["refused"] is True
    assert result["ok"] is False


def test_ipv4_mapped_public_address_is_pinned_as_ipv4(monkeypatch):
    script = [(200, {"Content-Type": "text/plain"}, b"Mapped public pin")]
    server, thread = _start_page(script)
    _script_dns(monkeypatch, {"trust.example.test": [["::ffff:8.8.8.8"]]})
    connected = _redirect_pins(monkeypatch, {"8.8.8.8"}, server.server_address[1])
    try:
        result = fetch_trust_center(PIN_URL, clock=AS_OF_CLOCK())
    finally:
        _stop_page(server, thread)
    assert connected == [("8.8.8.8", 8080)]
    assert result["ok"] is True
    assert result["summary"] == "Mapped public pin"
    assert server.seen[0]["host"] == "trust.example.test:8080"


def test_connection_failure_tries_the_next_pinned_address_only(monkeypatch):
    script = [(200, {"Content-Type": "text/plain"}, b"Second pin")]
    server, thread = _start_page(script)
    _script_dns(monkeypatch, {"trust.example.test": [["8.8.8.8", "1.1.1.1"]]})
    recorded = []
    original = socket.socket.connect

    def connect(self, address):
        recorded.append(address[0])
        if address[0] == "8.8.8.8":
            raise ConnectionRefusedError("refused")
        if address[0] == "1.1.1.1":
            return original(self, ("127.0.0.1", server.server_address[1]))
        raise AssertionError(address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    try:
        result = fetch_trust_center(PIN_URL, clock=AS_OF_CLOCK())
    finally:
        _stop_page(server, thread)
    assert recorded == ["8.8.8.8", "1.1.1.1"]
    assert result["ok"] is True
    assert result["summary"] == "Second pin"


def test_timeout_does_not_move_on_to_another_pinned_address(monkeypatch):
    _script_dns(monkeypatch, {"trust.example.test": [["8.8.8.8", "1.1.1.1"]]})
    recorded = []

    def connect(self, address):
        recorded.append(address[0])
        raise TimeoutError("timed out")

    monkeypatch.setattr(socket.socket, "connect", connect)
    result = fetch_trust_center(PIN_URL, clock=AS_OF_CLOCK())
    assert recorded == ["8.8.8.8"]
    assert result["ok"] is False
    assert "timed out" in result["error"]


def test_opener_does_not_resolve_a_hostname_without_a_pin(monkeypatch):
    def getaddrinfo(*args, **kwargs):
        raise AssertionError("name lookup")

    def connect(self, address):
        raise AssertionError(address)

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(socket.socket, "connect", connect)
    with pytest.raises(OSError, match="no pinned address"):
        _default_open("http://trust.example.test/northwind", 1)


def test_pinned_read_keeps_the_size_cap(monkeypatch):
    script = [(200, {"Content-Type": "text/plain"}, b"A" * (MAX_BYTES + 25))]
    server, thread = _start_page(script)
    _script_dns(monkeypatch, {"trust.example.test": [["8.8.8.8"]]})
    _redirect_pins(monkeypatch, {"8.8.8.8"}, server.server_address[1])
    try:
        result = fetch_trust_center(PIN_URL, clock=AS_OF_CLOCK())
    finally:
        _stop_page(server, thread)
    assert result["ok"] is True
    assert result["byte_length"] == MAX_BYTES
    assert "truncated" in result["summary"]


def test_tls_verifies_the_certificate_against_the_original_hostname(monkeypatch, tmp_path):
    ca_crt, leaf_crt, leaf_key = _issue_cert(tmp_path / "match", "trust.example.test")
    body = b"Certificate matched the original name"
    server, thread = _start_page(
        [(200, {"Content-Type": "text/plain"}, body)],
        certfile=leaf_crt, keyfile=leaf_key,
    )
    plans = _script_dns(monkeypatch, {
        "trust.example.test": [["8.8.8.8"], ["169.254.169.254"]],
    })
    connected = _redirect_pins(monkeypatch, {"8.8.8.8"}, server.server_address[1])
    _trust_test_ca(monkeypatch, ca_crt)
    sni = _record_sni(monkeypatch)
    try:
        result = fetch_trust_center("https://trust.example.test/northwind", clock=AS_OF_CLOCK())
    finally:
        _stop_page(server, thread)
    assert result["ok"] is True
    assert result["summary"] == body.decode()
    assert connected == [("8.8.8.8", 443)]
    assert sni == ["trust.example.test"]
    assert plans["trust.example.test"] == [["169.254.169.254"]]
    assert server.seen[0]["host"] == "trust.example.test"


def test_tls_rejects_a_certificate_for_a_different_hostname(monkeypatch, tmp_path):
    ca_crt, leaf_crt, leaf_key = _issue_cert(tmp_path / "wrong", "wrong.example.test")
    server, thread = _start_page(
        [(200, {"Content-Type": "text/plain"}, b"should-not-be-stored")],
        certfile=leaf_crt, keyfile=leaf_key,
    )
    _script_dns(monkeypatch, {"trust.example.test": [["8.8.8.8", "1.1.1.1"]]})
    connected = _redirect_pins(monkeypatch, {"8.8.8.8", "1.1.1.1"}, server.server_address[1])
    _trust_test_ca(monkeypatch, ca_crt)
    sni = _record_sni(monkeypatch)
    try:
        result = fetch_trust_center("https://trust.example.test/northwind", clock=AS_OF_CLOCK())
    finally:
        _stop_page(server, thread)
    assert result["ok"] is False
    assert result["refused"] is False
    assert result["excerpt"] is None
    assert "should-not-be-stored" not in (result["summary"] or "")
    assert "should-not-be-stored" not in (result["error"] or "")
    lowered = result["error"].lower()
    assert "certificate" in lowered or "hostname" in lowered
    assert sni == ["trust.example.test"]
    assert [address[0] for address in connected] == ["8.8.8.8"]
