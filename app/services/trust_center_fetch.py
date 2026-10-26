"""Fetch one public trust-center URL for human review.

The standard library performs the GET. Nothing in this module scores a
vendor or marks a page verified. A caller supplies ``open_url`` and
``resolver`` in tests so pytest does not use the live network.

The address check is intentionally small. It allows only http and https,
rejects private, loopback, link-local, and metadata targets, and checks
each redirect the same way. It does not pin DNS, so a name that changes
address after the check is a known limit of this portfolio prototype.
Environment proxies are not used.
"""

import ipaddress
import re
import socket
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

MAX_BYTES = 65536
EXCERPT_CHARS = 600
SUMMARY_CHARS = 240
TIMEOUT_SECONDS = 8
MAX_REDIRECTS = 3
USER_AGENT = "GRCAssuranceEngine/portfolio (trust-center review fetch)"

REFUSAL = (
    "Trust center URL cannot be fetched: the host is a private, link-local, or metadata address."
)
REDIRECTS = {301, 302, 303, 307, 308}

_BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.google.internal",
}
_BLOCKED_SUFFIXES = (".localhost", ".local", ".localdomain", ".internal")
_TEXT_TYPES = {
    "application/json",
    "application/xml",
    "application/xhtml+xml",
    "application/problem+json",
}


class _Extractor(HTMLParser):
    """Visible text and the title, skipping script and style."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self._parts = []
        self._title = []
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self._skip += 1
        elif tag == "title" and self._skip == 0:
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self._title.append(data)
        else:
            self._parts.append(data)

    def text(self):
        return _clean(" ".join(self._parts))

    def title(self):
        return _clean(" ".join(self._title))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface a redirect to the caller instead of following it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


def fetch_url_problems(url):
    """Return syntax and address problems. An empty list means the URL may be fetched.

    Name resolution is separate. This function does not contact the network.
    """
    text = (url or "").strip()
    if not text:
        return ["Trust center URL is required."]
    if not text.isprintable() or any(character.isspace() for character in text) or "\\" in text:
        return ["Trust center URL contains unsupported characters."]
    parsed = urlparse(text)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ["Trust center URL must start with http:// or https:// and include a host."]
    if parsed.username or parsed.password or "@" in parsed.netloc:
        return ["Trust center URL must not include a username or password."]
    try:
        host = parsed.hostname
    except ValueError:
        return ["Trust center URL has an invalid host."]
    if not host or "%" in host:
        return ["Trust center URL has an invalid host."]
    host = host.rstrip(".").lower()
    if host in _BLOCKED_HOSTS or host.endswith(_BLOCKED_SUFFIXES):
        return [REFUSAL]
    if host.isdigit() or re.fullmatch(r"0x[0-9a-f]+", host):
        return [REFUSAL]
    numeric = _numeric_host(host)
    if numeric is not None:
        return numeric
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return []
    if not _public_ip(ip):
        return [REFUSAL]
    return []


def fetch_trust_center(url, *, open_url=None, resolver=None, clock=None,
                       timeout=TIMEOUT_SECONDS, max_bytes=MAX_BYTES, max_redirects=MAX_REDIRECTS):
    """GET one URL and return a review record. HTTP failures stay in the record.

    ``refused`` is true only when the URL itself must not be requested.
    A later redirect to a blocked address is a failed fetch, not a refusal
    of the caller's original URL. ``open_url(url, timeout)`` returns
    ``(status, headers, body)``. ``resolver(host)`` returns IP strings.
    """
    stamp = _stamp(clock)
    opener = open_url or _default_open
    lookup = resolver or _system_resolver
    gate = _screen(url, lookup)
    if gate["action"] == "refuse":
        return _result(url, stamp, ok=False, refused=True, error=gate["error"])
    if gate["action"] == "fail":
        return _result(url, stamp, ok=False, refused=False, error=gate["error"])

    current = url
    seen = set()
    for hop in range(max_redirects + 1):
        if current in seen:
            return _result(url, stamp, ok=False, refused=False,
                           error="The trust center URL redirected in a loop.")
        seen.add(current)
        if hop:
            again = _screen(current, lookup)
            if again["action"] != "allow":
                detail = again["error"]
                return _result(url, stamp, ok=False, refused=False,
                               error=f"The trust center redirect was refused. {detail}")
        try:
            opened = opener(current, timeout)
        except TimeoutError:
            return _result(url, stamp, ok=False, refused=False,
                           error="The trust center request timed out.")
        except (urllib.error.URLError, OSError) as exc:
            return _result(url, stamp, ok=False, refused=False,
                           error=f"The trust center request failed ({_short(exc)}).")
        status, headers, body = _opened(opened)
        if status in REDIRECTS:
            location = _header(headers, "location")
            if not location:
                return _result(url, stamp, ok=False, refused=False, http_status=status,
                               error=f"HTTP {status} redirect had no location.")
            current = urljoin(current, location.strip())
            continue
        if status < 200 or status >= 300:
            return _result(url, stamp, ok=False, refused=False, http_status=status,
                           error=f"HTTP {status}.")
        summary, excerpt, content_type, size = _summarize(body or b"", headers, max_bytes)
        return _result(url, stamp, ok=True, refused=False, http_status=status,
                       final_url=current, content_type=content_type, summary=summary,
                       excerpt=excerpt, byte_length=size)
    return _result(url, stamp, ok=False, refused=False,
                   error="The trust center URL had too many redirects.")


def _screen(url, resolver):
    problems = fetch_url_problems(url)
    if problems:
        return {"action": "refuse", "error": problems[0]}
    host = urlparse(url).hostname.rstrip(".").lower()
    try:
        ipaddress.ip_address(host)
        return {"action": "allow"}
    except ValueError:
        pass
    try:
        addresses = list(resolver(host))
    except OSError:
        return {"action": "fail", "error": "The trust center host could not be resolved."}
    if not addresses:
        return {"action": "fail", "error": "The trust center host could not be resolved."}
    for address in addresses:
        try:
            ip = ipaddress.ip_address(str(address).split("%", 1)[0])
        except ValueError:
            return {"action": "refuse", "error": REFUSAL}
        if not _public_ip(ip):
            return {"action": "refuse", "error": "Trust center URL resolves to a private, link-local, or metadata address."}
    return {"action": "allow"}


def _numeric_host(host):
    labels = host.split(".")
    if not labels or not all(label.isdigit() for label in labels):
        return None
    if len(labels) != 4 or any(len(label) > 1 and label.startswith("0") for label in labels):
        return [REFUSAL]
    try:
        ip = ipaddress.IPv4Address(host)
    except ValueError:
        return [REFUSAL]
    if not _public_ip(ip):
        return [REFUSAL]
    return []


def _public_ip(ip):
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if (ip.is_multicast or ip.is_reserved or ip.is_unspecified or ip.is_loopback
            or ip.is_link_local or ip.is_private or not ip.is_global):
        return False
    return True


def _system_resolver(host):
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos if info[4]]


def _default_open(url, timeout):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html, text/plain, application/json;q=0.8, */*;q=0.1",
            "Accept-Encoding": "identity",
        },
        method="GET",
    )
    opener = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, response.headers, response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        body = exc.read(MAX_BYTES + 1) if exc.fp is not None else b""
        return exc.code, exc.headers, body


def _opened(value):
    status, headers, body = value[0], value[1], value[2]
    return int(status), headers or {}, body or b""


def _header(headers, name):
    if not headers:
        return None
    try:
        pairs = headers.items()
    except AttributeError:
        return None
    wanted = name.lower()
    for key, value in pairs:
        if str(key).lower() == wanted and value:
            return str(value)
    return None


def _summarize(body, headers, max_bytes):
    content_type = _header(headers, "content-type") or ""
    raw = body[:max_bytes]
    truncated = len(body) > max_bytes
    if not _is_text(content_type, raw):
        kind = content_type.split(";", 1)[0].strip() or "unknown type"
        summary = f"Non-text response ({kind}, {len(raw)} bytes). The bytes were not stored as a control document."
        if truncated:
            summary += " The download was truncated."
        return summary, "", content_type or None, len(raw)
    text = _decode(raw, content_type)
    base = content_type.split(";", 1)[0].strip().lower()
    if "html" in base or text.lstrip()[:1] == "<":
        parser = _Extractor()
        try:
            parser.feed(text)
            parser.close()
            visible = parser.text()
            title = parser.title()
        except Exception:
            visible = _clean(text)
            title = ""
    else:
        visible = _clean(text)
        title = ""
    excerpt = visible[:EXCERPT_CHARS]
    if title and visible:
        summary = _clean(f"{title}. {visible}")
    else:
        summary = title or visible
    summary = summary[:SUMMARY_CHARS]
    if not summary:
        summary = "The response had no readable text."
    if truncated:
        note = " The download was truncated."
        summary = summary[: max(0, SUMMARY_CHARS - len(note))] + note
    return summary, excerpt, content_type or None, len(raw)


def _is_text(content_type, body):
    if b"\x00" in body[:1024]:
        return False
    base = content_type.split(";", 1)[0].strip().lower()
    if not base:
        return True
    if base.startswith("text/") or base in _TEXT_TYPES:
        return True
    return base.endswith("+json") or base.endswith("+xml")


def _decode(body, content_type):
    charset = "utf-8"
    lowered = content_type.lower()
    if "charset=" in lowered:
        charset = lowered.split("charset=", 1)[1].split(";", 1)[0].strip().strip('"').strip("'") or "utf-8"
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def _clean(value):
    collapsed = " ".join((value or "").split())
    return "".join(character for character in collapsed if character.isprintable())


def _stamp(clock):
    moment = clock if isinstance(clock, datetime) else datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.isoformat()


def _short(exc):
    reason = getattr(exc, "reason", None)
    text = " ".join(str(reason if reason is not None else exc).split())
    return (text or exc.__class__.__name__)[:240]


def _result(url, stamp, *, ok, refused, error=None, http_status=None, final_url=None,
            content_type=None, summary=None, excerpt=None, byte_length=None):
    return {
        "ok": ok,
        "refused": refused,
        "requested_url": url,
        "final_url": final_url,
        "http_status": http_status,
        "fetched_at": stamp,
        "content_type": content_type,
        "summary": summary,
        "excerpt": excerpt,
        "byte_length": byte_length,
        "error": error,
    }
